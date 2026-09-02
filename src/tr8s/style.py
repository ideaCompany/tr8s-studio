"""
Layer 2 — the groove engine.

Patterns used to be typed out as literal step strings. That works once and
then stops working: "same but darker and more hypnotic" has no handle to turn.
This module knows how techno and its neighbours are actually built, and
generates from `(style, energy, role, seed)`.

Two ideas do most of the work.

**Energy** (0..1) is not a density knob applied uniformly. Adding energy to
techno means specific things in a specific order: the open hat arrives, then
the hats subdivide from 8ths to 16ths, then the ride, then ghost notes fill the
gaps. Layers enter in the order a producer would add them.

**Role** is where the bar sits in an arrangement. `intro` strips to the pulse,
`break` takes the kick away, `fill` rewrites the last four steps, `drop` is the
bar of near-silence before everything returns. A-H become an arrangement
instead of eight unrelated loops.

Everything is seeded, so "the same but sparser" really is the same pattern with
less in it, rather than a new roll of the dice.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

STEPS = 16
ACCENT, NORMAL, GHOST, REST = "X", "x", "o", "."
ROLES = ("intro", "main", "break", "fill", "drop")


# --------------------------------------------------------------- rhythm tools

OFFBEAT_8 = (2, 6, 10, 14)          # the "and" of each beat
DOWNBEATS = (0, 4, 8, 12)
BACKBEAT = (4, 12)                  # 2 and 4


def euclid(pulses: int, steps: int = STEPS, rotate: int = 0) -> list[int]:
    """
    Spread `pulses` as evenly as possible over `steps` — a Euclidean rhythm.

    This is why hypnotic techno works: 5 or 7 hits across 16 never lines up
    with the four-to-the-floor underneath, so the loop keeps seeming to move
    while nothing actually changes.
    """
    if pulses <= 0:
        return []
    pulses = min(pulses, steps)
    hits = [i for i in range(steps)
            if (i * pulses) % steps < pulses]
    return sorted(((i + rotate) % steps) for i in hits)


def place(indices, char: str = NORMAL, base: str | None = None) -> str:
    """Write `char` at each index of a 16-step string."""
    row = list(base or REST * STEPS)
    for i in indices:
        row[i % STEPS] = char
    return "".join(row)


def merge(*rows: str) -> str:
    """Overlay rows; a louder hit wins, so ghosts never erase accents."""
    rank = {REST: 0, GHOST: 1, NORMAL: 2, ACCENT: 3}
    out = [REST] * STEPS
    for row in rows:
        if not row:
            continue
        for i, c in enumerate(row.ljust(STEPS, REST)[:STEPS]):
            if rank[c] > rank[out[i]]:
                out[i] = c
    return "".join(out)


def thin(row: str, keep: float, rng: random.Random,
         protect=(0, 4, 8, 12)) -> str:
    """
    Drop hits at random, keeping the downbeats. Used to take energy out of a
    part without changing its character.
    """
    out = list(row)
    for i, c in enumerate(out):
        if c == REST or i in protect:
            continue
        if rng.random() > keep:
            out[i] = REST
    return "".join(out)


def humanise(row: str, rng: random.Random, amount: float = 0.25,
             protect=DOWNBEATS) -> str:
    """
    Demote a few hits to ghosts. Machine-perfect velocity sounds dead.

    `protect` must cover whatever carries the groove. Left to itself this
    happily flattens the offbeat hats, which are the one thing in a techno
    pattern that must not be softened.
    """
    out = list(row)
    for i, c in enumerate(out):
        if c == NORMAL and i not in protect and rng.random() < amount:
            out[i] = GHOST
    return "".join(out)





# ---------------------------------------------------------------- the styles

@dataclass
class Style:
    name: str
    bpm: tuple[int, int]
    summary: str
    build: object = field(repr=False)
    kit_hint: str = ""

    def tempo(self, rng: random.Random) -> float:
        lo, hi = self.bpm
        return float(rng.randrange(lo, hi + 1))


def _hats(rng, energy, style="straight"):
    """
    Closed hats, subdividing as energy rises. The order matters: 8ths first,
    then offbeat accents, then 16ths. Going straight to 16ths reads as busy
    rather than as energetic.
    """
    if energy < 0.25:
        return place(OFFBEAT_8, NORMAL)
    if energy < 0.5:
        row = place(range(0, STEPS, 2), GHOST)
        return merge(row, place(OFFBEAT_8, NORMAL))
    row = place(range(STEPS), GHOST)
    row = merge(row, place(OFFBEAT_8, NORMAL))
    if energy > 0.8:
        row = merge(row, place(DOWNBEATS, NORMAL))
    return humanise(row, rng, 0.15, protect=DOWNBEATS + OFFBEAT_8)


def _techno(rng, energy, role):
    t = {}
    t["BD"] = place(DOWNBEATS, ACCENT)
    if energy > 0.75:                       # the 16th pickup into the next bar
        t["BD"] = merge(t["BD"], place([15], GHOST))
    t["CH"] = _hats(rng, energy)
    if energy > 0.2:
        t["OH"] = place(OFFBEAT_8, NORMAL if energy < 0.7 else ACCENT)
    if energy > 0.35:
        t["HC"] = place(BACKBEAT, ACCENT if energy > 0.6 else NORMAL)
    if energy > 0.45:
        t["RS"] = thin(place(euclid(5, rotate=2), GHOST), 0.8, rng, protect=())
    if energy > 0.7:
        t["RC"] = place(range(0, STEPS, 2), GHOST)
    if energy > 0.55:
        t["MT"] = place(euclid(3, rotate=5), GHOST)
    return t


def _hypnotic(rng, energy, role):
    """
    Minimal, and built on odd cycles against the four. Almost nothing is on the
    grid you expect, which is the whole point — it should feel like it is
    turning without ever landing.
    """
    t = {}
    t["BD"] = place(DOWNBEATS, ACCENT)
    t["CH"] = place(euclid(7, rotate=1), GHOST if energy < 0.6 else NORMAL)
    t["RS"] = place(euclid(5, rotate=3), GHOST)
    if energy > 0.4:
        t["HC"] = place(euclid(3, rotate=7), GHOST)
    if energy > 0.6:
        t["OH"] = place([6, 14], NORMAL)
    if energy > 0.75:
        t["MT"] = place(euclid(11, rotate=2), GHOST)
    return t


def _dub(rng, energy, role):
    """
    Space is the instrument. The kick is soft, the offbeat is a chord stab
    (written by the melody layer, not here), and everything else stays out of
    the way.
    """
    t = {}
    t["BD"] = place(DOWNBEATS, NORMAL if energy < 0.6 else ACCENT)
    t["CH"] = place(OFFBEAT_8, GHOST)
    if energy > 0.35:
        t["RS"] = place(euclid(3, rotate=6), GHOST)
    if energy > 0.55:
        t["OH"] = place([6, 14], GHOST)
    if energy > 0.7:
        t["HC"] = place([12], GHOST)
    return t


def _acid(rng, energy, role):
    t = {}
    t["BD"] = place(DOWNBEATS, ACCENT)
    t["CH"] = _hats(rng, max(energy, 0.5))
    t["OH"] = place(OFFBEAT_8, NORMAL)
    if energy > 0.5:
        t["HC"] = place(BACKBEAT, NORMAL)
    if energy > 0.65:
        t["RS"] = place(euclid(7, rotate=1), GHOST)
    return t


def _hard(rng, energy, role):
    """
    Faster, and the kick stops leaving room. At the top the offbeats fill in
    until the pulse reads as eighths — the rolling kick.
    """
    t = {}
    bd = place(DOWNBEATS, ACCENT)
    if energy > 0.55:
        bd = merge(bd, place(OFFBEAT_8, GHOST))
    if energy > 0.85:
        bd = merge(bd, place(OFFBEAT_8, NORMAL), place([15], NORMAL))
    t["BD"] = bd
    t["CH"] = merge(place(range(STEPS), GHOST), place(OFFBEAT_8, ACCENT))
    if energy > 0.4:
        t["HC"] = place(BACKBEAT, ACCENT)
    if energy > 0.6:
        t["CC"] = place([0], NORMAL)
    if energy > 0.7:
        t["HT"] = place(euclid(5, rotate=9), GHOST)
    return t


def _broken(rng, energy, role):
    """Techno with the floor pulled out — the kick syncopates."""
    t = {}
    t["BD"] = merge(place([0], ACCENT), place([6, 10], NORMAL),
                    place([11] if energy > 0.6 else [], GHOST))
    t["SD"] = place(BACKBEAT, ACCENT)
    if energy > 0.3:
        t["CH"] = _hats(rng, energy)
    if energy > 0.5:
        t["RS"] = place(euclid(7, rotate=2), GHOST)
    if energy > 0.7:
        t["OH"] = place([6, 14], NORMAL)
    return t


def _dnb(rng, energy, role):
    """The two-step: kick on 1 and the 11, snare on 2 and 4, everything fast."""
    t = {}
    t["BD"] = merge(place([0], ACCENT), place([10], NORMAL))
    if energy > 0.6:
        t["BD"] = merge(t["BD"], place([6], GHOST))
    t["SD"] = place(BACKBEAT, ACCENT)
    if energy > 0.4:
        t["SD"] = merge(t["SD"], place([7, 14], GHOST))
    t["CH"] = merge(place(range(0, STEPS, 2), GHOST),
                    place(OFFBEAT_8, NORMAL))
    if energy > 0.55:
        t["RC"] = place(range(0, STEPS, 2), GHOST)
    if energy > 0.75:
        t["RS"] = place(euclid(5, rotate=3), GHOST)
    return t


def _lofi(rng, energy, role):
    """Soft, swung, behind the beat. Shuffle comes from the header, not here."""
    t = {}
    t["BD"] = place(DOWNBEATS, NORMAL)
    t["OH"] = place(OFFBEAT_8, GHOST)
    t["HC"] = place(BACKBEAT, NORMAL)
    if energy > 0.4:
        t["CH"] = place(range(STEPS), GHOST)
    if energy > 0.6:
        t["RS"] = place(euclid(3, rotate=5), GHOST)
    return t


def _house(rng, energy, role):
    t = {}
    t["BD"] = place(DOWNBEATS, ACCENT)
    t["OH"] = place(OFFBEAT_8, NORMAL)
    t["HC"] = place(BACKBEAT, ACCENT)
    if energy > 0.3:
        t["CH"] = _hats(rng, energy)
    if energy > 0.6:
        t["RS"] = place(euclid(5, rotate=1), GHOST)
    if energy > 0.75:
        t["MT"] = place(euclid(3, rotate=2), GHOST)
    return t


STYLES: dict[str, Style] = {
    "techno": Style("techno", (130, 140),
                    "driving peak-time techno: four to the floor, offbeat open "
                    "hat, clap on 2 and 4", _techno,
                    "punchy kick, bright hats, short clap"),
    "hypnotic": Style("hypnotic", (128, 134),
                      "minimal hypnotic techno built on 5- and 7-step cycles "
                      "against the four — sparse, endlessly turning", _hypnotic,
                      "dry short percussion, restrained kick"),
    "dub": Style("dub", (118, 128),
                 "dub techno: soft kick, offbeat chord stabs, and a lot of "
                 "space", _dub,
                 "soft kick, long reverberant stab, muted percussion"),
    "acid": Style("acid", (130, 142),
                  "acid techno: relentless hats under a 303 line", _acid,
                  "tight kick, bright 16th hats, a saw or square for the line"),
    "hard": Style("hard", (145, 160),
                  "hard techno: rolling kick, hats on every 16th, no space",
                  _hard, "distorted kick, aggressive metallic percussion"),
    "broken": Style("broken", (128, 138),
                    "broken techno: the kick syncopates and the floor drops "
                    "out", _broken, "weighty kick, snappy snare"),
    "dnb": Style("dnb", (168, 176),
                 "drum and bass two-step at 174", _dnb,
                 "tight kick, cracking snare, fast ride"),
    "lofi": Style("lofi", (110, 122),
                  "lo-fi house: soft, swung, behind the beat", _lofi,
                  "dusty kick, soft clap, quiet shaker"),
    "house": Style("house", (120, 128),
                   "house: four to the floor with the open hat carrying the "
                   "swing", _house, "round kick, open hat with body"),
}


# ------------------------------------------------------------------- roles

def _apply_role(tracks: dict, role: str, rng: random.Random,
                energy: float) -> dict:
    """
    Shape a generated bar for where it sits in an arrangement.

    These are the moves that make eight variations sound like one track rather
    than eight loops.
    """
    if role == "main":
        return tracks
    t = dict(tracks)

    if role == "intro":
        # the pulse and one colour; everything else waits
        keep = [k for k in ("BD", "CH", "RS") if k in t]
        t = {k: t[k] for k in keep}
        if "CH" in t:
            t["CH"] = thin(t["CH"], 0.5, rng, protect=())
        return t

    if role == "break":
        # the kick leaves. That is the whole event -- do not replace it
        t.pop("BD", None)
        for k in ("HC", "SD"):
            if k in t:
                t[k] = thin(t[k], 0.5, rng, protect=())
        if "OH" in t:
            t["OH"] = place(OFFBEAT_8, NORMAL)
        return t

    if role == "fill":
        # rewrite the last four steps; the bar has to announce the change
        tail = rng.choice([
            {"MT": place([12, 13, 14, 15], NORMAL)},
            {"SD": place([12, 14, 15], NORMAL)},
            {"HT": place([12, 13], NORMAL), "MT": place([14, 15], NORMAL)},
            {"SD": place([12, 13, 14, 15], GHOST), "CC": place([15], NORMAL)},
        ])
        for inst, row in tail.items():
            t[inst] = merge(t.get(inst, ""), row)
        if "BD" in t:                       # keep the floor under the fill
            t["BD"] = merge(t["BD"], place(DOWNBEATS, ACCENT))
        return t

    if role == "drop":
        # near silence, then everything at once. Only the downbeat survives
        out = {"BD": place([0], ACCENT)}
        if "CC" in t or energy > 0.5:
            out["CC"] = place([0], ACCENT)
        return out

    return t


# ------------------------------------------------------------------ the API

def generate(style: str = "techno", energy: float = 0.6, role: str = "main",
             seed: int | None = None) -> dict:
    """
    Build one 16-step bar.

    Returns `{"tracks": {...}, "tempo": float, "style": ..., "seed": int}`.
    The seed is always reported, so a pattern you liked can be asked for again.
    """
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; have {', '.join(STYLES)}")
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; have {', '.join(ROLES)}")
    energy = max(0.0, min(1.0, float(energy)))

    if seed is None:
        seed = random.randrange(1 << 30)
    rng = random.Random(seed)
    st = STYLES[style]

    tracks = st.build(rng, energy, role)
    tracks = _apply_role(tracks, role, rng, energy)
    tracks = {k: v for k, v in tracks.items() if v and set(v) != {REST}}

    return {"style": style, "role": role, "energy": energy, "seed": seed,
            "tempo": st.tempo(rng), "tracks": tracks}


def arrangement(style: str = "techno", seed: int | None = None,
                energy: float = 0.6) -> dict:
    """
    Eight variations that work as one track: A-H as intro through peak.

    The energy curve is the shape of a techno track, not a ramp — the break
    sits lower than the intro so the return lands.
    """
    if seed is None:
        seed = random.randrange(1 << 30)
    plan = [
        ("A", "intro", 0.30), ("B", "main", 0.55), ("C", "main", 0.70),
        ("D", "fill", 0.75), ("E", "break", 0.25), ("F", "drop", 0.40),
        ("G", "main", 0.90), ("H", "fill", 0.95),
    ]
    out = {}
    for i, (v, role, level) in enumerate(plan):
        # scale the curve by the requested energy, keeping its shape
        e = max(0.05, min(1.0, level * (0.5 + energy)))
        out[v] = generate(style, energy=e, role=role, seed=seed + i)
    return {"style": style, "seed": seed, "variations": out,
            "tempo": out["B"]["tempo"]}


def describe() -> list[dict]:
    return [{"name": s.name, "bpm": list(s.bpm), "summary": s.summary,
             "kit_hint": s.kit_hint} for s in STYLES.values()]
