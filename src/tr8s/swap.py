"""
Layer 2 — changing an instrument's sound by description.

The catalogue has every tone measured: root pitch, decay, brightness, loudness.
That makes "a darker kick" or "a shorter clap" a query rather than a browse:
start from what the instrument has now, move along one measured axis, stay in
the same category, and return the nearest candidates in order.

This is what the AI reaches for when asked to change a sound, and what the
studio's swap bar steps through with its arrows. Both go through the same
ranking so they agree about what "next" means.
"""

from __future__ import annotations

import math

from .tones import Catalog, Tone

# the vocabulary a musician uses, mapped onto the measured axes. Each entry:
# (axis, direction). Direction +1 means "more of the axis", -1 less.
WORDS = {
    "darker": ("centroid", -1), "dark": ("centroid", -1), "duller": ("centroid", -1),
    "warmer": ("centroid", -1), "muffled": ("centroid", -1),
    "brighter": ("centroid", +1), "bright": ("centroid", +1), "sharper": ("centroid", +1),
    "crisper": ("centroid", +1), "harsher": ("centroid", +1),
    "shorter": ("decay_ms", -1), "short": ("decay_ms", -1), "tighter": ("decay_ms", -1),
    "snappier": ("decay_ms", -1), "punchier": ("decay_ms", -1), "drier": ("decay_ms", -1),
    "longer": ("decay_ms", +1), "long": ("decay_ms", +1), "boomier": ("decay_ms", +1),
    "roomier": ("decay_ms", +1), "sustained": ("decay_ms", +1),
    "lower": ("hz", -1), "deeper": ("hz", -1), "heavier": ("hz", -1),
    "higher": ("hz", +1), "thinner": ("hz", +1),
    "louder": ("peak", +1), "quieter": ("peak", -1), "softer": ("peak", -1),
}

# how far "a bit" / "much" moves, as a multiple of the reference value
AMOUNT = {"slightly": 0.15, "a bit": 0.25, "a little": 0.25, "somewhat": 0.35,
          "much": 0.8, "a lot": 0.8, "way": 1.2, "very": 0.8}


def _axis_value(t: Tone, axis: str):
    v = getattr(t, axis, None)
    if axis == "decay_ms" and t.sustained:
        return 10_000.0          # effectively infinite for ordering
    return float(v) if v is not None else None


def _distance(a: Tone, b: Tone, weights: dict) -> float:
    """
    How different two tones sound, from their measurements. Log-scaled where
    perception is: a 50 Hz change matters at 60 Hz and not at 2 kHz.
    """
    d = 0.0
    for axis, w in weights.items():
        va, vb = _axis_value(a, axis), _axis_value(b, axis)
        if va is None or vb is None:
            d += w * 0.5
            continue
        if axis in ("centroid", "hz", "decay_ms"):
            d += w * abs(math.log((va + 1) / (vb + 1)))
        else:
            d += w * abs(va - vb)
    return d


DEFAULT_WEIGHTS = {"centroid": 1.0, "decay_ms": 1.0, "hz": 0.6, "peak": 0.4}


def neighbours(cat: Catalog, tone_id: int, limit: int = 12,
               same_category: bool = True) -> list[Tone]:
    """Tones most like this one, nearest first. Excludes itself."""
    cur = cat.get(tone_id)
    if cur is None:
        return []
    pool = [t for t in cat.tones.values() if t.id != tone_id]
    if same_category:
        pool = [t for t in pool if t.cat == cur.cat] or pool
    pool.sort(key=lambda t: _distance(cur, t, DEFAULT_WEIGHTS))
    return pool[:limit]


def parse(description: str) -> list[tuple[str, int, float]]:
    """
    'a bit darker and much shorter' -> [('centroid', -1, 0.25),
                                        ('decay_ms', -1, 0.8)]
    Unknown words are ignored; an empty result means nothing was understood.
    """
    text = " " + description.lower().replace(",", " ") + " "
    out = []
    for word, (axis, sign) in WORDS.items():
        if f" {word} " in text:
            amount = 0.5
            for phrase, a in AMOUNT.items():
                if f" {phrase} {word} " in text:
                    amount = a
            out.append((axis, sign, amount))
    return out


def by_description(cat: Catalog, tone_id: int, description: str,
                   limit: int = 8, same_category: bool = True) -> dict:
    """
    Candidates that move from the current tone in the described direction.

    The target is the current value shifted by the amount on each named axis;
    candidates are ranked by distance to that target, but only ones that
    actually moved the right way on every named axis qualify -- "darker" must
    not return something brighter just because it is otherwise similar.
    """
    cur = cat.get(tone_id)
    if cur is None:
        return {"error": f"tone {tone_id} is not in the catalogue"}
    moves = parse(description)
    if not moves:
        return {"error": f"nothing in {description!r} names a direction I "
                         f"know: try darker/brighter, shorter/longer, "
                         f"lower/higher, louder/quieter",
                "understood": []}

    target = {}
    for axis, sign, amount in moves:
        v = _axis_value(cur, axis)
        if v is None:
            continue
        if axis in ("centroid", "hz", "decay_ms"):
            target[axis] = v * (1 + sign * amount) if sign > 0 else v / (1 + amount)
        else:
            target[axis] = v + sign * amount * 0.5

    pool = [t for t in cat.tones.values() if t.id != tone_id]
    if same_category:
        pool = [t for t in pool if t.cat == cur.cat] or pool

    def moved_right_way(t):
        for axis, sign, _ in moves:
            a, b = _axis_value(cur, axis), _axis_value(t, axis)
            if a is None or b is None:
                return False
            if sign > 0 and b <= a:
                return False
            if sign < 0 and b >= a:
                return False
        return True

    qualified = [t for t in pool if moved_right_way(t)]

    class _T:                           # a stand-in tone at the target
        pass
    tgt = _T()
    for axis in DEFAULT_WEIGHTS:
        setattr(tgt, axis, target.get(axis, _axis_value(cur, axis)))
    tgt.sustained = False
    qualified.sort(key=lambda t: _distance(t, tgt, DEFAULT_WEIGHTS))

    return {
        "from": _brief(cur),
        "understood": [{"axis": a, "direction": "more" if s > 0 else "less",
                        "amount": amt} for a, s, amt in moves],
        "candidates": [_brief(t) for t in qualified[:limit]],
        "note": (None if qualified else
                 f"nothing in {cur.cat} moves that way from '{cur.name}'; "
                 f"try same_category=false or a smaller step"),
    }


def _brief(t: Tone) -> dict:
    return {"tone": t.id, "name": t.name, "category": t.cat, "root": t.root,
            "decay_ms": None if t.sustained else t.decay_ms,
            "sustained": t.sustained, "centroid": t.centroid,
            "melodic": t.type == 2}
