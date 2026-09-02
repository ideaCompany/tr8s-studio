"""
Layer 2 — basslines, acid lines and stabs, in key.

The melody layer can put any note anywhere. That is the right primitive and the
wrong interface: nothing stops a line that is out of key, and "give me a
bassline" should not require naming sixteen notes.

This generates lines that belong to a scale and to a style. Three shapes cover
most of the genre:

  **bass**  the offbeat pulse between the kicks. Techno's bassline is mostly
            one note; what makes it move is where it lands, not how far it
            travels. Wandering is a mistake here, so the generator stays on the
            tonic and pays for every departure.

  **acid**  the 303 line. Sixteenths, heavily rested, with octave jumps and
            accents — the accents are what the ear hears as the melody, so
            they are placed deliberately rather than sprinkled.

  **stab**  dub techno's offbeat chord. One note per offbeat, moving slowly,
            usually only between the tonic and one other degree.

Everything is returned as note names, so it goes straight into
`melody.write()`, and everything is seeded.
"""

from __future__ import annotations

import random

from .kitbuild import scale_pitches
from .melody import COARSE_MAX, COARSE_MIN, NOTE_NAMES, midi_to_note, note_to_midi

STEPS = 16
REST = "."

# where each shape prefers to put notes
OFFBEATS = (2, 6, 10, 14)
EIGHTHS = tuple(range(0, 16, 2))
DOWNBEATS = (0, 4, 8, 12)

SHAPES = ("bass", "acid", "stab", "arp")


def _degrees(scale: list[int], tonic: int) -> dict:
    """Pitch classes of the degrees worth naming, when the scale has them."""
    out = {"root": tonic}
    for name, semis in (("second", 1), ("third", 3), ("fourth", 5),
                        ("fifth", 7), ("sixth", 8), ("seventh", 10)):
        pc = (tonic + semis) % 12
        if pc in scale:
            out[name] = pc
    return out


def _nearest(pc: int, around_midi: int) -> int:
    """
    The MIDI note of pitch class `pc` closest to `around_midi`, breaking a tie
    upward — a tritone away is equally near in both directions, and dropping is
    the choice that puts a bassline under the speaker.
    """
    base = (around_midi // 12) * 12 + pc
    return min((base + 12, base, base - 12),
               key=lambda m: (abs(m - around_midi), -m))


def _reachable(midi: int, root_midi: int) -> bool:
    return COARSE_MIN <= midi - root_midi <= COARSE_MAX


def bassline(key: str = "C minor", energy: float = 0.6, seed: int | None = None,
             root: str = "C2", octave_offset: int = 0) -> dict:
    """
    The offbeat pulse. Mostly tonic — movement is the exception, not the rule.
    """
    rng, tonic, scale, seed = _setup(seed, key)
    deg = _degrees(scale, tonic)
    base = note_to_midi(root) + 12 * octave_offset
    home = _nearest(tonic, base)
    floor = note_to_midi(root) - 12

    # density: at low energy only the offbeats, rising to eighths and then to
    # the odd sixteenth pickup
    slots = list(OFFBEATS)
    if energy > 0.45:
        slots = list(EIGHTHS)
    if energy > 0.8:
        slots += [7, 15]

    notes = [REST] * STEPS
    for i in sorted(set(slots)):
        # the last offbeat of the bar is where a techno bassline moves, if it
        # moves at all -- that is the turnaround the ear waits for
        turnaround = i >= 12
        move = rng.random() < (0.12 + 0.25 * energy) * (2.2 if turnaround else 1)
        if not move:
            notes[i] = midi_to_note(home)
            continue
        choices = [deg.get("fifth"), deg.get("seventh"), deg.get("third"),
                   deg.get("second")]
        choices = [c for c in choices if c is not None]
        pc = rng.choice(choices) if choices else tonic
        m = _nearest(pc, home)
        if rng.random() < 0.25 * energy:
            m -= 12                     # drop an octave for weight
        # a bassline more than an octave below the tone's own root is under
        # the speaker. Raise by octaves rather than clamping, which would move
        # the note out of key.
        while m < floor:
            m += 12
        notes[i] = midi_to_note(m)

    return _finish(notes, key, seed, root, "bass", energy)


def acid(key: str = "C minor", energy: float = 0.7, seed: int | None = None,
         root: str = "C2") -> dict:
    """
    A 303 line: sixteenths, mostly rests, octave jumps, accents that carry the
    tune. Returns `accents` alongside the notes so the caller can write them
    louder — that is where the squelch comes from.
    """
    rng, tonic, scale, seed = _setup(seed, key)
    base = note_to_midi(root)
    home = _nearest(tonic, base)
    floor = base - 12               # same register rule as the bassline
    in_key = sorted(scale)

    density = 0.35 + 0.45 * energy
    notes = [REST] * STEPS
    accents = []
    last = home
    for i in range(STEPS):
        if i not in DOWNBEATS and rng.random() > density:
            continue
        if i in DOWNBEATS and rng.random() > 0.55 + 0.4 * energy:
            continue

        r = rng.random()
        if i in DOWNBEATS and r < 0.6:
            m = home                            # the root anchors the bar
        elif r < 0.22:
            m = home + 12                       # the octave jump, the signature
        elif r < 0.5:
            m = home                            # the line lives on the root
        else:
            pc = rng.choice(in_key)
            m = _nearest(pc, last)
        # keep it in the low register where a 303 lives, without dropping
        # under the speaker
        while m - home > 14:
            m -= 12
        while m - home < -12 or m < floor:
            m += 12
        notes[i] = midi_to_note(m)
        last = m
        # accents on the root and on the octave jumps: the shape the ear reads
        if m in (home, home + 12) and rng.random() < 0.55:
            accents.append(i)

    if all(n == REST for n in notes):           # never hand back silence
        notes[0] = midi_to_note(home)
        accents = [0]

    out = _finish(notes, key, seed, root, "acid", energy)
    out["accents"] = accents
    return out


def stab(key: str = "C minor", energy: float = 0.4, seed: int | None = None,
         root: str = "C3") -> dict:
    """Dub techno's offbeat chord: slow, and only two or three notes a bar."""
    rng, tonic, scale, seed = _setup(seed, key)
    deg = _degrees(scale, tonic)
    base = note_to_midi(root)
    home = _nearest(tonic, base)

    slots = [2, 10] if energy < 0.5 else list(OFFBEATS)
    other = deg.get("third") or deg.get("fifth") or tonic
    notes = [REST] * STEPS
    for n, i in enumerate(slots):
        pc = tonic if (n % 2 == 0 or rng.random() < 0.5) else other
        notes[i] = midi_to_note(_nearest(pc, home))
    return _finish(notes, key, seed, root, "stab", energy)


def arp(key: str = "C minor", energy: float = 0.6, seed: int | None = None,
        root: str = "C3", direction: str = "up") -> dict:
    """A running triad — hypnotic techno's other melodic device."""
    rng, tonic, scale, seed = _setup(seed, key)
    deg = _degrees(scale, tonic)
    third = deg.get("third") or deg.get("second") or tonic
    fifth = deg.get("fifth") or deg.get("fourth") or tonic
    base = note_to_midi(root)
    home = _nearest(tonic, base)

    chord = [home, _nearest(third, home), _nearest(fifth, home), home + 12]
    for i in range(1, len(chord)):                  # force it to ascend
        while chord[i] <= chord[i - 1]:
            chord[i] += 12
    if direction == "down":
        chord.reverse()
    elif direction == "updown":
        chord = chord + chord[-2:0:-1]

    every = 2 if energy > 0.5 else 4
    notes = [REST] * STEPS
    for n, i in enumerate(range(0, STEPS, every)):
        notes[i] = midi_to_note(chord[n % len(chord)])
    return _finish(notes, key, seed, root, "arp", energy)


# ------------------------------------------------------------------ shared

def _setup(seed, key):
    if seed is None:
        seed = random.randrange(1 << 30)
    tonic, scale = scale_pitches(key)
    return random.Random(seed), tonic, scale, seed


def _finish(notes, key, seed, root, shape, energy) -> dict:
    root_midi = note_to_midi(root)
    warnings = []
    out = []
    for i, n in enumerate(notes):
        if n == REST:
            out.append(REST)
            continue
        m = note_to_midi(n)
        if not _reachable(m, root_midi):
            # clamp by octaves rather than to the limit, so it stays in key
            while m - root_midi > COARSE_MAX:
                m -= 12
            while m - root_midi < COARSE_MIN:
                m += 12
            warnings.append(f"step {i + 1}: {n} was out of Coarse Tune's reach "
                            f"from {root}; moved to {midi_to_note(m)}")
        out.append(midi_to_note(m))
    return {"notes": " ".join(out), "key": key, "root": root, "shape": shape,
            "energy": energy, "seed": seed, "warnings": warnings}


def generate(shape: str = "bass", **kw) -> dict:
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape!r}; have {', '.join(SHAPES)}")
    return {"bass": bassline, "acid": acid, "stab": stab, "arp": arp}[shape](**kw)
