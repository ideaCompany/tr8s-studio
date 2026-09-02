#!/usr/bin/env python3
"""
Write melodies into TR-8S patterns.

A melody on the TR-8S is per-step TUNE motion. The mechanism, decoded and
measured 2026-08-28:

    tune lane   = 12 + instrument index      (BD=12, SD=13, LT=14 ... RC=22)
    value byte  = 144 + blk*2436 + 4 + lane*64 + step*4 + 0
                  offset-binary: 0x80 == 0, so byte = units + 128
    marker byte = same record + 3, set to 0x80 to mark "motion present here"

A step whose marker is 0 has no motion and plays at the kit's own tune, which
is NOT the same as writing tune 0.

Scale, measured by recording the TR-8S's own USB audio and pitch-tracking it:

    ~24.3 tune units per semitone, linear in pitch (residual < 0.1 st)

which means the whole -128..+127 range covers only about 10.5 semitones. A
melody has to fit inside roughly +/- 5 semitones of the tone's natural pitch.
For anything wider you need Coarse Tune (-24..+24 SEMITONES) assigned to a
CTRL knob, which motion can also record -- not yet decoded here.

IMPORTANT: motion is only played back while the panel's MOTION [ON] button is
lit. A melody written from software is silent until that is on, and software
cannot set it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_write as w   # noqa: E402

HEADER = 144
BLOCK = 2436
UNITS_PER_SEMITONE = 24.3     # fine TUNE: measured, see module docstring

# Coarse Tune, motion-recorded via a CTRL knob. Byte +2 of the step record,
# stored as semitones + 24, so exactly ONE unit per semitone across -24..+24.
# Verified 2026-08-28: +12 st stored 36, -12 st stored 12.
COARSE_OFFSET = 24
COARSE_MIN, COARSE_MAX = -24, 24
MASK_TUNE = 0x80
MASK_CTRL = 0x09
TUNE_MIN, TUNE_MAX = -128, 127

NOTES = {'C': 0, 'C#': 1, 'DB': 1, 'D': 2, 'D#': 3, 'EB': 3, 'E': 4,
         'F': 5, 'F#': 6, 'GB': 6, 'G': 7, 'G#': 8, 'AB': 8,
         'A': 9, 'A#': 10, 'BB': 10, 'B': 11}


def note_to_midi(name):
    """'C#3' -> MIDI number. Returns None for a rest ('.' or '-')."""
    s = name.strip().upper()
    if s in ('.', '-', ''):
        return None
    i = 0
    while i < len(s) and (s[i].isalpha() or s[i] == '#'):
        i += 1
    pitch, octave = s[:i], s[i:]
    if pitch not in NOTES or not octave.lstrip('-').isdigit():
        raise ValueError(f"bad note {name!r}")
    return (int(octave) + 1) * 12 + NOTES[pitch]


def lane_offset(blk, lane, step):
    return HEADER + blk * BLOCK + 4 + lane * 64 + step * 4


def tune_lane(inst):
    return 12 + w.TRACKS.index(inst)


def write_coarse_melody(blob, inst, notes, root, blk=0, velocity=100,
                        strict=False):
    """
    Write a melody using Coarse Tune motion -- semitone steps over four
    octaves, versus the ~10 semitones fine Tune allows.

    Requires, on the instrument: a SAMPLE tone (Coarse Tune does not exist on
    ACB modelled tones), Coarse Tune assigned to its CTRL knob, and the kit's
    CTRL Sel set to User. And MOTION [ON] lit, as ever.
    """
    blob = bytearray(blob)
    if isinstance(notes, str):
        notes = notes.split()
    if len(notes) > 16:
        raise ValueError(f"{len(notes)} notes; a variation holds 16 steps")
    root_midi = note_to_midi(root)
    lane = tune_lane(inst)
    warnings = []

    for step in range(16):
        blob[w.track_offset(blk, inst, step)] = 0
        off = lane_offset(blk, lane, step)
        blob[off + 2] = 0
        blob[off + 3] = 0

    for step, tok in enumerate(notes):
        midi = note_to_midi(tok)
        if midi is None:
            continue
        semis = midi - root_midi
        if semis < COARSE_MIN or semis > COARSE_MAX:
            msg = (f"step {step + 1} {tok}: {semis:+d} semitones from {root} "
                   f"is outside Coarse Tune's {COARSE_MIN}..{COARSE_MAX}")
            if strict:
                raise ValueError(msg)
            warnings.append(msg)
            semis = max(COARSE_MIN, min(COARSE_MAX, semis))
        blob[w.track_offset(blk, inst, step)] = velocity
        off = lane_offset(blk, lane, step)
        blob[off + 2] = (semis + COARSE_OFFSET) & 0xFF
        blob[off + 3] = MASK_CTRL
    return bytes(blob), warnings


def read_coarse_melody(blob, inst, root, blk=0):
    lane = tune_lane(inst)
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    root_midi = note_to_midi(root)
    out = []
    for step in range(16):
        if not blob[w.track_offset(blk, inst, step)]:
            out.append('.')
            continue
        off = lane_offset(blk, lane, step)
        semis = blob[off + 2] - COARSE_OFFSET if blob[off + 3] else 0
        m = root_midi + semis
        out.append(f"{names[m % 12]}{m // 12 - 1}")
    return ' '.join(out)


def write_melody(blob, inst, notes, root, blk=0, velocity=100,
                 units_per_semitone=UNITS_PER_SEMITONE, strict=False):
    """
    Write a melody into a pattern blob.

    notes  -- 16 tokens, space separated or a list: note names or '.' for rest
    root   -- the note this instrument sounds at tune 0 (its natural pitch)

    Returns (blob, warnings). Notes outside the reachable +/- range are
    clamped, and each one is reported -- silently detuning a melody would be
    worse than saying so.
    """
    blob = bytearray(blob)
    if isinstance(notes, str):
        notes = notes.split()
    if len(notes) > 16:
        raise ValueError(f"{len(notes)} notes; a variation holds 16 steps")
    root_midi = note_to_midi(root)
    if root_midi is None:
        raise ValueError("root must be a real note")
    lane = tune_lane(inst)
    warnings = []

    for step in range(16):
        blob[w.track_offset(blk, inst, step)] = 0
        off = lane_offset(blk, lane, step)
        blob[off] = 0
        blob[off + 3] = 0

    for step, tok in enumerate(notes):
        midi = note_to_midi(tok)
        if midi is None:
            continue
        units = int(round((midi - root_midi) * units_per_semitone))
        if units < TUNE_MIN or units > TUNE_MAX:
            reach = (TUNE_MAX / units_per_semitone)
            msg = (f"step {step + 1} {tok}: {(midi - root_midi):+d} semitones "
                   f"from {root} is outside the reachable "
                   f"+/-{reach:.1f} semitones")
            if strict:
                raise ValueError(msg)
            warnings.append(msg)
            units = max(TUNE_MIN, min(TUNE_MAX, units))
        blob[w.track_offset(blk, inst, step)] = velocity
        off = lane_offset(blk, lane, step)
        blob[off] = (units + 128) & 0xFF
        blob[off + 3] = 0x80        # motion present
    return bytes(blob), warnings


def read_melody(blob, inst, root, blk=0, units_per_semitone=UNITS_PER_SEMITONE):
    """Recover a melody from a blob, for round-trip checking."""
    lane = tune_lane(inst)
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    root_midi = note_to_midi(root)
    out = []
    for step in range(16):
        if not blob[w.track_offset(blk, inst, step)]:
            out.append('.')
            continue
        off = lane_offset(blk, lane, step)
        units = blob[off] - 128 if blob[off + 3] else 0
        midi = root_midi + round(units / units_per_semitone)
        out.append(f"{names[midi % 12]}{midi // 12 - 1}")
    return ' '.join(out)


def reachable(root, units_per_semitone=UNITS_PER_SEMITONE):
    """The note range a given root can actually reach."""
    lo = int(TUNE_MIN / units_per_semitone)
    hi = int(TUNE_MAX / units_per_semitone)
    m = note_to_midi(root)
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    f = lambda n: f"{names[n % 12]}{n // 12 - 1}"   # noqa: E731
    return f(m + lo), f(m + hi)
