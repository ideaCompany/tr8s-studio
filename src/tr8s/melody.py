"""
Layer 2 — melodies. Turns note names into per-step tune motion.

Two mechanisms, documented in docs/PROTOCOL.md:

  COARSE (preferred)  byte +2 of the step record, stored as semitones + 24.
                      Exactly 1 unit per semitone over -24..+24 -- four
                      octaves, no calibration, no tuning error.
                      Requires a SAMPLE tone with Coarse Tune on its CTRL knob.

  FINE (fallback)     byte +0, offset-binary, ~24.3 units per semitone, so the
                      whole range is only ~10 semitones. Works on any tone.

Both need MOTION [ON] lit on the panel, which software cannot set.

A caution when READING motion back: byte +0 is always Tune, so fine motion is
unambiguously pitch. Byte +2 is whatever is assigned to that instrument's CTRL
knob -- Coarse Tune, or pan, or a send -- and that assignment is NOT stored in
the kit blob, so nothing here can verify it. Reading CTRL as semitones is only
valid when the caller knows Coarse Tune is assigned.
"""

from __future__ import annotations

import math

from .pattern import MASK_CTRL, MASK_TUNE, STEPS, Pattern

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_PITCH = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
          "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10,
          "BB": 10, "B": 11}

COARSE_OFFSET = 24
COARSE_MIN, COARSE_MAX = -24, 24
FINE_UNITS_PER_SEMITONE = 24.3      # measured acoustically; +/- 0.1 semitone
FINE_MIN, FINE_MAX = -128, 127

REST = {".", "-", "_", ""}


class MelodyError(ValueError):
    pass


def note_to_midi(name: str) -> int | None:
    """'C#3' -> MIDI number. A rest ('.', '-', '_') returns None."""
    s = str(name).strip().upper()
    if s in REST:
        return None
    i = 0
    while i < len(s) and (s[i].isalpha() or s[i] == "#"):
        i += 1
    pitch, octave = s[:i], s[i:]
    if pitch not in _PITCH or not octave.lstrip("-").isdigit():
        raise MelodyError(f"bad note {name!r}; expected e.g. C3, F#2, A#4 or . for a rest")
    return (int(octave) + 1) * 12 + _PITCH[pitch]


def midi_to_note(m: int) -> str:
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def hz_to_note(freq: float) -> tuple[str, int]:
    """Frequency -> (note name, cents off). Used to read a sample's real root."""
    m = 12 * math.log2(freq / 440.0) + 69
    i = int(round(m))
    return midi_to_note(i), round((m - i) * 100)


def parse(notes) -> list[int | None]:
    toks = notes.split() if isinstance(notes, str) else list(notes)
    if len(toks) > STEPS:
        raise MelodyError(f"{len(toks)} notes; a variation holds {STEPS} steps")
    return [note_to_midi(tk) for tk in toks]


def coarse_range(root: str) -> tuple[str, str]:
    m = note_to_midi(root)
    return midi_to_note(m + COARSE_MIN), midi_to_note(m + COARSE_MAX)


def fine_range(root: str) -> tuple[str, str]:
    m = note_to_midi(root)
    span = int(FINE_MAX / FINE_UNITS_PER_SEMITONE)
    return midi_to_note(m - span), midi_to_note(m + span)


def write(pattern: Pattern, variation, inst: str, notes, root: str,
          mode: str = "coarse", velocity: int = 104,
          strict: bool = False) -> list[str]:
    """
    Write a melody. Returns a list of warnings; unreachable notes are clamped
    rather than silently transposed, and each one is reported.

    `root` is the note the instrument sounds at tune 0 -- its natural pitch.
    Get it from the tone catalogue rather than guessing: an incorrect root
    transposes the whole line.
    """
    if mode not in ("coarse", "fine"):
        raise MelodyError("mode must be 'coarse' or 'fine'")
    midis = parse(notes)
    root_midi = note_to_midi(root)
    if root_midi is None:
        raise MelodyError("root must be a real note, not a rest")

    pattern.clear_motion(variation, inst)
    for s in range(STEPS):
        pattern.set_steps(variation, inst,
                          pattern.get_steps(variation, inst))  # keep other steps
    # clear this instrument's steps; the melody defines them
    pattern.set_steps(variation, inst, "." * STEPS)

    warnings: list[str] = []
    for step, midi in enumerate(midis):
        if midi is None:
            continue
        semis = midi - root_midi
        if mode == "coarse":
            if not COARSE_MIN <= semis <= COARSE_MAX:
                msg = (f"step {step+1} {midi_to_note(midi)}: {semis:+d} semitones "
                       f"from {root} is outside Coarse Tune's "
                       f"{COARSE_MIN}..{COARSE_MAX}")
                if strict:
                    raise MelodyError(msg)
                warnings.append(msg)
                semis = max(COARSE_MIN, min(COARSE_MAX, semis))
            ctrl = semis + COARSE_OFFSET
            pattern.set_motion(variation, inst, step, ctrl=ctrl)
        else:
            units = int(round(semis * FINE_UNITS_PER_SEMITONE))
            if not FINE_MIN <= units <= FINE_MAX:
                reach = FINE_MAX / FINE_UNITS_PER_SEMITONE
                msg = (f"step {step+1} {midi_to_note(midi)}: {semis:+d} semitones "
                       f"from {root} exceeds fine tune's +/-{reach:.1f} semitones")
                if strict:
                    raise MelodyError(msg)
                warnings.append(msg)
                units = max(FINE_MIN, min(FINE_MAX, units))
            pattern.set_motion(variation, inst, step, tune=units)
        # sound the step
        cur = list(pattern.get_steps(variation, inst))
        cur[step] = "X" if velocity >= 112 else "x" if velocity >= 90 else "o"
        pattern.set_steps(variation, inst, "".join(cur))
    return warnings


def read(pattern: Pattern, variation, inst: str, root: str,
         mode: str = "coarse") -> str:
    root_midi = note_to_midi(root)
    steps = pattern.get_steps(variation, inst)
    out = []
    for s in range(STEPS):
        if steps[s] == ".":
            out.append(".")
            continue
        m = pattern.get_motion(variation, inst, s)
        if mode == "coarse":
            semis = (m["ctrl"] - COARSE_OFFSET) if m["ctrl"] is not None else 0
        else:
            semis = round((m["tune"] or 0) / FINE_UNITS_PER_SEMITONE)
        out.append(midi_to_note(root_midi + semis))
    return " ".join(out)
