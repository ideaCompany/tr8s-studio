"""
Recognising what the machine is playing, from the notes it sends.

The TR-8S will not say which pattern is selected and will not say which of the
eight variations is running. It does not act on a Program Change either, so it
cannot even be asked to move somewhere known. The one thing it does do is send
a note every time an instrument sounds, and a clock that gives a step position.

That is enough. A variation is a set of `(step, instrument)` pairs, and so is a
few bars of listening. Comparing the two identifies the pattern the way a
person would -- by recognising it.

Two details decide whether this works at all.

**Rotation.** Without a Start message the step counter's phase is arbitrary, so
the heard bar sits at an unknown offset. Every comparison is done at all
sixteen rotations and the best is kept.

**Symmetry.** Scoring "what fraction of what I heard does this explain" lets a
sparse variation explain a sparse hearing perfectly: a five-hit intro scored
1.0 against almost anything. F1 over the two sets counts what was expected and
not heard as well, which is what makes an intro distinguishable from a peak.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

STEPS = 16


def fingerprint(tracks: dict) -> frozenset:
    """The set of (step, instrument) a variation sounds."""
    return frozenset((i, inst) for inst, steps in (tracks or {}).items()
                     for i, c in enumerate(steps or "") if c != ".")


def heard_set(hits) -> frozenset:
    """Turn monitor hits into the same shape. Repeats collapse: a note on the
    same step every bar is one piece of evidence, not eight."""
    return frozenset((step, inst) for _, step, inst in hits)


def score(heard: frozenset, expected: frozenset) -> float:
    """Best F1 over every rotation, 0..1."""
    if not heard or not expected:
        return 0.0
    best = 0.0
    for shift in range(STEPS):
        rot = {((s + shift) % STEPS, i) for s, i in heard}
        best = max(best, 2 * len(rot & expected) / (len(rot) + len(expected)))
    return best


@dataclass
class Match:
    slot: int
    variation: str
    score: float
    margin: float
    name: str = ""

    def as_dict(self) -> dict:
        return {"slot": self.slot, "variation": self.variation,
                "score": round(self.score, 3), "margin": round(self.margin, 3),
                "name": self.name}


class Index:
    """
    Every pattern's variations, as fingerprints.

    Building it costs one read per pattern -- about a minute for all 128 -- and
    then identification is pure arithmetic with no further reads. That is the
    whole point: the alternative is polling the machine, which is what made the
    UI lurch.
    """

    def __init__(self):
        self.entries: dict[int, dict] = {}

    def add(self, slot: int, name: str, variations: dict):
        prints = {v: fingerprint(t) for v, t in (variations or {}).items()}
        prints = {v: f for v, f in prints.items() if f}
        # An empty pattern is recorded too, with no prints. It can never be
        # recognised by ear (there is nothing to hear), but knowing it is
        # empty is what lets the studio follow the machine onto it while
        # playing and, on the next stop, report exactly what was built there.
        self.entries[int(slot)] = {"name": name, "prints": prints}

    def __len__(self):
        return len(self.entries)

    def identify(self, heard: frozenset, min_hits: int = 4,
                 min_score: float = 0.6, min_margin: float = 0.12,
                 only: int | None = None) -> Match | None:
        """
        The pattern and variation that best explain what was heard.

        `only` restricts the search to a single slot, for confirming what is
        already on screen rather than searching everything.

        Returns None when nothing scores well enough, or when the best two
        candidates are too close to separate. Variations of one pattern share
        most of their steps, so a narrow win means "cannot tell".
        """
        if len(heard) < min_hits:
            return None
        ranked = []
        for slot, e in self.entries.items():
            if only is not None and slot != only:
                continue
            for v, print_ in e["prints"].items():
                ranked.append((score(heard, print_), slot, v, e["name"]))
        if not ranked:
            return None
        ranked.sort(key=lambda r: -r[0])
        best = ranked[0]
        # the runner-up that is a *different* answer, not the same pattern's
        # neighbouring variation scoring identically
        runner = 0.0
        for r in ranked[1:]:
            if (r[1], r[2]) != (best[1], best[2]):
                runner = r[0]
                break
        margin = best[0] - runner
        if best[0] < min_score:
            return None
        # A narrow win means "cannot tell" -- unless the winner explains what
        # was heard (almost) exactly. Variations of one generated track are
        # close relatives (D scored 1.00 against H's 0.90 on a real track and
        # was refused for a 0.10 margin, so the readout stayed dead), and a
        # perfect match is not a coin flip whatever the runner-up scores.
        exact = best[0] >= 0.95
        strong = best[0] >= 0.8 and margin >= 0.04
        if not (exact or strong or margin >= min_margin):
            return None
        return Match(slot=best[1], variation=best[2], score=best[0],
                     margin=margin, name=best[3])

    # ------------------------------------------------------------ on disk

    def to_json(self) -> str:
        return json.dumps({
            str(slot): {"name": e["name"],
                        "prints": {v: sorted([s, i] for s, i in f)
                                   for v, f in e["prints"].items()}}
            for slot, e in self.entries.items()})

    @classmethod
    def from_json(cls, text: str) -> "Index":
        ix = cls()
        for slot, e in json.loads(text).items():
            ix.entries[int(slot)] = {
                "name": e.get("name", ""),
                "prints": {v: frozenset((s, i) for s, i in pairs)
                           for v, pairs in (e.get("prints") or {}).items()},
            }
        return ix

    def save(self, path):
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json())

    @classmethod
    def load(cls, path) -> "Index":
        from pathlib import Path
        p = Path(path)
        if not p.is_file():
            return cls()
        try:
            return cls.from_json(p.read_text())
        except (ValueError, OSError):
            return cls()
