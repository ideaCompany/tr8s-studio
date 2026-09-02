"""
Layer 2 — assembling a kit from what the tones actually sound like.

Every tone on the machine was played and measured: `root`, `decay_ms`,
`sustained`, `centroid`, `peak`. That turns kit building from a naming exercise
into a selection problem with real criteria. A kick can be chosen for being
short and low rather than for being called "Kick 3", and a bassline tone can be
chosen so its root sits in the key the track is in.

Two things are being avoided, and both are audible mistakes rather than
theoretical ones:

  **Pitch clash.** The kick has a pitch. A bassline a semitone off it beats
  against the low end on every downbeat. Choosing a kick whose root is the
  tonic or the fifth of the key removes the problem at the source.

  **Spectral collision.** Two parts with the same centroid mask each other:
  put a closed hat and a rimshot in the same place and one of them disappears.
  Candidates too close to something already chosen are penalised.

Targets below are calibrated against the measured distribution of this
machine's own tones, not against textbook figures. Measured centroids top out
near 2 kHz because the analysis decimates to 6 kHz, so a target of "3 kHz for a
hat" would match nothing at all.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .melody import NOTE_NAMES, note_to_midi
from .tones import Catalog

TRACKS = ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH", "OH", "CC", "RC"]

SCALES = {
    "minor":       [0, 2, 3, 5, 7, 8, 10],
    "natural minor": [0, 2, 3, 5, 7, 8, 10],
    "phrygian":    [0, 1, 3, 5, 7, 8, 10],
    "dorian":      [0, 2, 3, 5, 7, 9, 10],
    "harmonic minor": [0, 2, 3, 5, 7, 8, 11],
    "major":       [0, 2, 4, 5, 7, 9, 11],
}


@dataclass
class Target:
    """What a track should sound like. `None` means the property is free."""
    cats: tuple
    centroid: tuple | None = None      # (low, high) preferred window
    decay: tuple | None = None         # (low, high) in ms
    sustained: bool | None = None
    type_: int | None = None           # 1 ACB, 2 sample
    weight_peak: float = 0.3           # how much loudness matters


# Baseline: what each track is, before a style has an opinion.
BASE: dict[str, Target] = {
    "BD": Target(("BD",), centroid=(50, 160), decay=(180, 450)),
    "SD": Target(("SD",), centroid=(900, 1700), decay=(60, 200)),
    "LT": Target(("TOM", "PERC1", "PERC2"), centroid=(80, 400), decay=(150, 500)),
    "MT": Target(("TOM", "PERC1", "PERC3"), centroid=(200, 700), decay=(120, 400)),
    "HT": Target(("TOM", "PERC1", "PERC4"), centroid=(300, 900), decay=(100, 350)),
    "RS": Target(("RS", "PERC1"), centroid=(900, 1800), decay=(15, 90)),
    "HC": Target(("HC",), centroid=(1200, 2000), decay=(40, 200)),
    "CH": Target(("CH/OH",), centroid=(1500, 2000), decay=(25, 120)),
    "OH": Target(("CH/OH",), centroid=(1400, 2000), decay=(200, 700)),
    "CC": Target(("CC/RC",), centroid=(1500, 2100), decay=(500, 900)),
    "RC": Target(("CC/RC",), centroid=(1600, 2100), decay=(300, 800)),
}

# Per style, only what differs. Anything absent keeps the baseline.
STYLE_TARGETS: dict[str, dict[str, Target]] = {
    "techno": {},
    "hard": {
        # punchier and dirtier: shorter kick, more high content in it
        "BD": Target(("BD",), centroid=(90, 400), decay=(120, 320)),
        "CH": Target(("CH/OH",), centroid=(1700, 2100), decay=(25, 90)),
        "HC": Target(("HC",), centroid=(1400, 2400), decay=(30, 140)),
    },
    "hypnotic": {
        # everything dry, so nothing smears across the odd cycles
        "BD": Target(("BD",), centroid=(50, 140), decay=(150, 350)),
        "RS": Target(("RS", "PERC1"), centroid=(800, 1600), decay=(15, 60)),
        "CH": Target(("CH/OH",), centroid=(1500, 2000), decay=(25, 70)),
        "OH": Target(("CH/OH",), centroid=(1400, 1900), decay=(150, 400)),
    },
    "dub": {
        # soft and long: the kick is felt, the space is the point
        "BD": Target(("BD",), centroid=(50, 120), decay=(350, 900), weight_peak=0.1),
        "CH": Target(("CH/OH",), centroid=(1400, 1900), decay=(25, 100),
                     weight_peak=0.05),
        "RS": Target(("RS", "PERC1"), centroid=(700, 1500), decay=(20, 120)),
    },
    "acid": {
        "BD": Target(("BD",), centroid=(60, 200), decay=(140, 350)),
        "CH": Target(("CH/OH",), centroid=(1600, 2100), decay=(25, 80)),
    },
    "broken": {
        "BD": Target(("BD",), centroid=(50, 200), decay=(200, 600)),
        "SD": Target(("SD",), centroid=(1000, 1900), decay=(80, 250)),
    },
    "dnb": {
        "BD": Target(("BD",), centroid=(60, 250), decay=(100, 300)),
        "SD": Target(("SD",), centroid=(1100, 2000), decay=(80, 300)),
        "RC": Target(("CC/RC",), centroid=(1700, 2100), decay=(200, 600)),
    },
    "lofi": {
        # dusty means dark: the top is rolled off everywhere
        "BD": Target(("BD",), centroid=(50, 110), decay=(250, 700), weight_peak=0.1),
        "SD": Target(("SD",), centroid=(600, 1300), decay=(60, 200)),
        "CH": Target(("CH/OH",), centroid=(900, 1600), decay=(25, 110)),
        "HC": Target(("HC",), centroid=(900, 1600), decay=(40, 200)),
    },
    "house": {
        "BD": Target(("BD",), centroid=(50, 150), decay=(250, 600)),
        "OH": Target(("CH/OH",), centroid=(1400, 2000), decay=(300, 800)),
    },
}

# A melodic track needs a tone that can hold a note: a sample, sustained, and
# pitched where the part belongs. The register is not optional — the machine
# offers the same oscillator at C2, C3, C4 and C5, and brightness alone cannot
# tell them apart, so a "bass" chosen on centroid lands in the fifth octave
# about as often as not.
BASS_TARGET = Target(("BASS", "SYNTH2", "SYNTH1"), centroid=(60, 900),
                     sustained=True, type_=2)
BASS_ROOT = ("C1", "C3")        # where a bassline's own root has to sit
LEAD_TARGET = Target(("SYNTH1", "SYNTH2", "CHORD", "VOICE"), centroid=(600, 2200),
                     sustained=True, type_=2)
LEAD_ROOT = ("C3", "C5")        # above the bass, or they are the same part


def _window_score(value, window) -> float:
    """1.0 inside the window, falling off outside it rather than cliffing."""
    if value is None or window is None:
        return 0.5
    lo, hi = window
    if lo <= value <= hi:
        return 1.0
    span = max(hi - lo, 1)
    dist = (lo - value) if value < lo else (value - hi)
    return max(0.0, 1.0 - dist / (span * 1.5))


def score(tone, target: Target, taken_centroids=()) -> float:
    if target.type_ is not None and tone.type != target.type_:
        return -1
    if target.sustained is not None and bool(tone.sustained) != target.sustained:
        return -1
    if tone.cat not in target.cats:
        return -1
    if tone.peak is not None and tone.peak < 0.02:
        return -1                       # effectively silent, whatever it is

    s = 2.0 * _window_score(tone.centroid, target.centroid)
    s += 1.5 * _window_score(tone.decay_ms, target.decay)
    s += target.weight_peak * min(1.0, (tone.peak or 0) / 0.5)

    # penalise a tone that would sit on top of something already chosen
    if tone.centroid:
        for other in taken_centroids:
            if other and abs(tone.centroid - other) < 120:
                s -= 0.8
    return s


def _pitch_class(note: str | None):
    if not note:
        return None
    m = note_to_midi(note)
    return None if m is None else m % 12


def scale_pitches(key: str) -> tuple[int, list[int]]:
    """'C minor' -> (0, [0,2,3,5,7,8,10]). Returns pitch classes."""
    parts = str(key).strip().split(None, 1)
    root = parts[0].strip()
    mode = (parts[1] if len(parts) > 1 else "minor").strip().lower()
    if mode not in SCALES:
        raise ValueError(f"unknown mode {mode!r}; have {', '.join(sorted(SCALES))}")
    try:
        midi = note_to_midi(root + "3")
    except Exception:
        midi = None
    if midi is None:
        raise ValueError(
            f"unknown key root {root!r}; expected a note name like C, F#, Bb")
    tonic = midi % 12
    return tonic, [(tonic + i) % 12 for i in SCALES[mode]]


def build(style: str = "techno", key: str = "C minor", seed: int | None = None,
          catalog: Catalog | None = None, melodic: tuple = ("LT", "MT")) -> dict:
    """
    Choose a tone for every track. Returns the plan and the reason for each
    choice, so the decision can be argued with rather than just accepted.

    Nothing is written here — see `tools.kit.auto_build`.
    """
    # `catalog or ...` would be wrong: an empty Catalog is falsy, so passing
    # one would silently fall back to the machine's real catalogue
    cat = Catalog.load() if catalog is None else catalog
    tones = list(cat.tones.values())
    if not tones:
        raise ValueError("the tone catalogue is empty; run `tr8s analyse-tones`")

    if seed is None:
        seed = random.randrange(1 << 30)    # report it, so a kit can be re-made
    rng = random.Random(seed)
    tonic, scale = scale_pitches(key)
    targets = dict(BASE)
    targets.update(STYLE_TARGETS.get(style, {}))

    plan: dict[str, dict] = {}
    taken: list[float] = []
    used: set[int] = set()

    def pick(track, target, extra_bonus=None):
        scored = []
        for t in tones:
            # two instruments on the identical tone is a wasted voice
            if t.id in used:
                continue
            sc = score(t, target, taken)
            if sc < 0:
                continue
            if extra_bonus:
                sc += extra_bonus(t)
            scored.append((sc, t))
        if not scored:
            return None
        scored.sort(key=lambda x: -x[0])
        # choose among the near-best, so two kits in the same style differ
        best = scored[0][0]
        pool = [t for sc, t in scored if sc >= best - 0.25][:6]
        chosen = rng.choice(pool)
        used.add(chosen.id)
        return chosen

    # The kick first: everything else is chosen around it, and its pitch is the
    # one that has to agree with the key.
    def kick_bonus(t):
        pc = _pitch_class(t.root)
        if pc is None:
            return 0.0
        if pc == tonic:
            return 1.2                  # the tonic: the strongest choice
        if pc == (tonic + 7) % 12:
            return 0.8                  # the fifth: also stable under a bassline
        if pc in scale:
            return 0.3
        return -0.6                     # out of key, and audible on every beat

    bd = pick("BD", targets["BD"], kick_bonus)
    if bd:
        plan["BD"] = _entry(bd, _kick_reason(bd, tonic, scale, key))
        taken.append(bd.centroid)

    for track in TRACKS:
        if track in plan or track in melodic:
            continue
        t = pick(track, targets[track])
        if t:
            plan[track] = _entry(t, _reason(t, targets[track]))
            taken.append(t.centroid)

    # melodic tracks last, so they can dodge whatever the drums took
    for i, track in enumerate(melodic):
        target, window = ((BASS_TARGET, BASS_ROOT) if i == 0
                          else (LEAD_TARGET, LEAD_ROOT))
        t = pick(track, target, _register_bonus(window))
        if t is None:
            t = pick(track, target)
        if t:
            plan[track] = _entry(t, _melodic_reason(t, key, window))
            taken.append(t.centroid)

    return {"style": style, "key": key, "seed": seed,
            "tonic": NOTE_NAMES[tonic], "scale": [NOTE_NAMES[p] for p in scale],
            "instruments": plan,
            "melodic_tracks": [m for m in melodic if m in plan]}


def _register_bonus(window):
    """Prefer a tone whose own root sits in the register the part belongs to."""
    lo, hi = note_to_midi(window[0]), note_to_midi(window[1])

    def bonus(t):
        m = None if not t.root else note_to_midi(t.root)
        if m is None:
            return -1.5             # unknown pitch is unusable for a line
        if lo <= m <= hi:
            return 2.5
        return -2.0 * (min(abs(m - lo), abs(m - hi)) / 12.0)
    return bonus


def _entry(t, why: str) -> dict:
    return {"tone": t.id, "name": t.name, "category": t.cat,
            "root": t.root, "decay_ms": t.decay_ms, "sustained": t.sustained,
            "centroid": t.centroid, "why": why}


def _fmt(t):
    bits = []
    if t.centroid:
        bits.append(f"centroid {t.centroid:.0f} Hz")
    if t.sustained:
        bits.append("sustained")
    elif t.decay_ms:
        bits.append(f"decay {t.decay_ms:.0f} ms")
    return ", ".join(bits)


def _reason(t, target: Target) -> str:
    return f"{_fmt(t)} — inside the window this style wants"


def _kick_reason(t, tonic, scale, key) -> str:
    pc = _pitch_class(t.root)
    base = _fmt(t)
    if pc == tonic:
        return f"{base}; its pitch {t.root} is the tonic of {key}, so the " \
               f"bassline cannot beat against it"
    if pc == (tonic + 7) % 12:
        return f"{base}; its pitch {t.root} is the fifth of {key}"
    if pc in scale:
        return f"{base}; its pitch {t.root} is in {key}"
    if pc is None:
        return f"{base}; no measured pitch, so nothing to clash"
    return f"{base}; WARNING its pitch {t.root} is outside {key}"


def _melodic_reason(t, key, window=None) -> str:
    base = (f"{_fmt(t)}; sustained sample tone rooted at {t.root}, so Coarse "
            f"Tune covers {key} across four octaves")
    if window and t.root:
        lo, hi = note_to_midi(window[0]), note_to_midi(window[1])
        if not lo <= note_to_midi(t.root) <= hi:
            return (base + f" — WARNING its root is outside {window[0]}.."
                           f"{window[1]}, so the line will sit in the wrong "
                           f"octave")
    return base
