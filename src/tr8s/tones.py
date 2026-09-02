"""
Layer 2 — the tone catalogue.

Names are not enough to choose a sound: "Deep SH Bass" says nothing about what
note it sounds at, how loud it is, or how long it rings. `tone_analysis` fills
in those numbers by triggering each tone and measuring the TR-8S's own audio;
this module reads that catalogue and answers questions against it.

The most important field is `root` -- the note a tone actually sounds at.
Coarse Tune is relative to it, so writing a melody without it transposes the
whole line by an unknown amount.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import config
from .melody import note_to_midi

CATEGORIES = ["IMPORT", "BD", "SD", "TOM", "RS", "HC", "CH/OH", "CC/RC",
              "PERC1", "PERC2", "PERC3", "PERC4", "PERC5", "FX/HIT", "VOICE",
              "SYNTH1", "SYNTH2", "BASS", "SCALED", "CHORD", "OTHERS"]
MELODIC_CATEGORIES = {"SYNTH1", "SYNTH2", "BASS", "SCALED", "CHORD"}

TYPE_ACB = 1
TYPE_SAMPLE = 2


@dataclass
class Tone:
    id: int
    name: str
    cat: str
    type: int
    root: str | None = None
    hz: float | None = None
    cents: int | None = None
    peak: float | None = None
    rms: float | None = None
    decay_ms: int | None = None
    sustained: bool = False
    centroid: int | None = None

    @property
    def melodic(self) -> bool:
        """Only sample tones have Coarse Tune, so only they can play melodies."""
        return self.type == TYPE_SAMPLE

    @property
    def root_midi(self) -> int | None:
        return note_to_midi(self.root) if self.root else None


class Catalog:
    def __init__(self, tones: dict[int, Tone]):
        self.tones = tones

    @classmethod
    def load(cls, path=None) -> "Catalog":
        p = path or config.tone_catalog_path()
        try:
            raw = json.load(open(p))
        except FileNotFoundError:
            return cls({})
        out = {}
        for key, v in raw.items():
            known = {k: v[k] for k in Tone.__dataclass_fields__ if k in v}
            known.setdefault("id", int(key))
            out[int(key)] = Tone(**known)
        return cls(out)

    def __len__(self):
        return len(self.tones)

    def put(self, tone: "Tone", path=None):
        """
        Replace one entry and persist. An import writes a new tone record
        onto the machine, and the catalogue -- which is what names tones
        everywhere in the studio -- must stop calling that id by the name of
        whatever the factory sweep found there.
        """
        import json
        from . import config
        self.tones[tone.id] = tone
        p = path or config.tone_catalog_path()
        try:
            data = json.loads(p.read_text()) if p.is_file() else {}
        except (ValueError, OSError):
            data = {}
        data[str(tone.id)] = {k: v for k, v in tone.__dict__.items() if k != "id"}
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data))
        except OSError:
            pass                       # in-memory update still holds

    def get(self, tone_id: int) -> Tone | None:
        return self.tones.get(tone_id)

    def search(self, category: str | None = None, melodic: bool | None = None,
               root: str | None = None, near_hz: float | None = None,
               max_decay_ms: int | None = None, min_decay_ms: int | None = None,
               brighter_than: int | None = None, darker_than: int | None = None,
               name_contains: str | None = None, limit: int = 25) -> list[Tone]:
        """Filter the catalogue. All criteria are optional and combine with AND."""
        res = list(self.tones.values())
        if category:
            cats = {c.strip().upper() for c in category.split(",")}
            res = [t for t in res if t.cat.upper() in cats]
        if melodic is not None:
            res = [t for t in res if t.melodic == melodic]
        if root:
            rm = note_to_midi(root)
            res = [t for t in res if t.root_midi is not None
                   and t.root_midi % 12 == rm % 12]
        if max_decay_ms is not None:
            res = [t for t in res
                   if not t.sustained and (t.decay_ms or 0) <= max_decay_ms]
        if min_decay_ms is not None:
            res = [t for t in res
                   if t.sustained or (t.decay_ms or 0) >= min_decay_ms]
        if brighter_than is not None:
            res = [t for t in res if (t.centroid or 0) > brighter_than]
        if darker_than is not None:
            res = [t for t in res if 0 < (t.centroid or 0) < darker_than]
        if name_contains:
            n = name_contains.lower()
            res = [t for t in res if n in t.name.lower()]
        if near_hz is not None:
            res = [t for t in res if t.hz]
            res.sort(key=lambda t: abs((t.hz or 0) - near_hz))
        else:
            res.sort(key=lambda t: t.id)
        return res[:limit]

    def suggest_root(self, tone_id: int) -> str | None:
        t = self.get(tone_id)
        return t.root if t else None

    def balance_hint(self, tone_ids: list[int]) -> dict:
        """
        Rough loudness spread across a set of tones, so a kit can be balanced.
        Level itself is fader-controlled and cannot be set from software, so
        this is advisory -- it tells you which instrument will dominate.
        """
        rows = [(i, self.get(i)) for i in tone_ids]
        known = [(i, t) for i, t in rows if t and t.peak]
        if not known:
            return {"known": 0}
        peaks = {i: t.peak for i, t in known}
        loudest = max(peaks, key=peaks.get)
        quietest = min(peaks, key=peaks.get)
        return {
            "known": len(known),
            "peaks": peaks,
            "loudest": loudest,
            "quietest": quietest,
            "spread_db": round(20 * (
                __import__("math").log10(peaks[loudest] / peaks[quietest])
            ), 1) if peaks[quietest] > 0 else None,
        }
