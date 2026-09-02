"""
Measured relationships between kit bytes and what you hear.

Everything here came off the machine rather than out of a spec. Each table
names the tone it was measured on, because a curve measured on one sound is
evidence about that sound and only suggestive about the rest.

## TUNE

Swept byte `+2` on tone 465 (OSC Saw Low, a sustained saw with an unambiguous
pitch), measuring the fundamental at seventeen points:

    byte      0    32    64    96   128   160   192   224   255
    semis -11.99 -8.99 -6.00 -2.99  0.00 +3.03 +6.03 +9.10 +11.99

Dead straight, and symmetric about 128. `semitones = 24 * value / 255 - 12`
reproduces every measured point to within 0.07 of a semitone, so the parameter
is exactly **one octave either way**, linear in the byte.

Note this is *not* the same scale as the per-step motion tune byte in a
pattern, which covers a much narrower range — see `melody.FINE_UNITS_PER_SEMITONE`.
Two different fields, two different scalings; do not reuse one constant for the
other.

## DECAY

Swept byte `+3` of a kit instrument record on tone 1 (808 Bass1), measuring the
time for the level to fall by 20 dB:

    byte    16   32   48   64   96  128  160  192  224
    ms      60   80  110  140  235  295  400  610  745

Monotonic and smooth across that range, so interpolating between the points is
reasonable. The two endpoints are not part of the curve:

  **255** does not decay at all — the tone sustains.

  **0** also does not decay, and is the *loudest* value measured (peak 0.61
  against 0.25–0.46 across the rest of the range). A value that is both louder
  and longer than its neighbours is not the bottom of an envelope curve; the
  likely reading is that 0 means "no envelope, play the sample", but that is a
  hypothesis and is not asserted here. Either way it is not a short decay, and
  code that wants a short decay must not reach for it.
"""

from __future__ import annotations

TUNE_TONE = 465
TUNE_CENTRE = 128
TUNE_SEMITONE_RANGE = 12.0          # each way; 24 semitones end to end
TUNE_MEASURED = [(0, -11.99), (32, -8.99), (64, -6.00), (96, -2.99),
                 (128, 0.00), (160, 3.03), (192, 6.03), (224, 9.10),
                 (255, 11.99)]

DECAY_TONE = 1
DECAY_CURVE = [(16, 60), (32, 80), (48, 110), (64, 140), (96, 235),
               (128, 295), (160, 400), (192, 610), (224, 745)]

DECAY_MIN_BYTE = DECAY_CURVE[0][0]
DECAY_MAX_BYTE = DECAY_CURVE[-1][0]
DECAY_MIN_MS = DECAY_CURVE[0][1]
DECAY_MAX_MS = DECAY_CURVE[-1][1]

SUSTAIN_BYTES = (0, 255)


def decay_ms_for_byte(value: int) -> float | None:
    """
    Milliseconds for a decay byte, or None where the tone does not decay.

    Outside the measured range the nearest measured value is returned rather
    than an extrapolation — there is no evidence for what happens beyond it.
    """
    if value in SUSTAIN_BYTES:
        return None
    if value <= DECAY_MIN_BYTE:
        return float(DECAY_MIN_MS)
    if value >= DECAY_MAX_BYTE:
        return float(DECAY_MAX_MS)
    for (a, am), (b, bm) in zip(DECAY_CURVE, DECAY_CURVE[1:]):
        if a <= value <= b:
            f = (value - a) / (b - a)
            return am + f * (bm - am)
    return None


def decay_byte_for_ms(ms: float) -> int:
    """
    The decay byte that gives roughly `ms`, clamped to the measured range.

    Never returns 0: that value is louder and longer than its neighbours, so
    asking for the shortest decay and getting 0 would do the opposite of what
    was asked.
    """
    ms = float(ms)
    if ms <= DECAY_MIN_MS:
        return DECAY_MIN_BYTE
    if ms >= DECAY_MAX_MS:
        return DECAY_MAX_BYTE
    for (a, am), (b, bm) in zip(DECAY_CURVE, DECAY_CURVE[1:]):
        if am <= ms <= bm:
            f = (ms - am) / (bm - am)
            return int(round(a + f * (b - a)))
    return DECAY_MAX_BYTE


def describe_decay() -> dict:
    return {
        "measured_on_tone": DECAY_TONE,
        "curve": [{"byte": b, "ms": m} for b, m in DECAY_CURVE],
        "range_ms": [DECAY_MIN_MS, DECAY_MAX_MS],
        "sustain_bytes": list(SUSTAIN_BYTES),
        "caveat": "measured on one tone; treat as the shape of the curve "
                  "rather than exact milliseconds for every sound. Byte 0 is "
                  "an outlier: louder and non-decaying.",
    }


# --------------------------------------------------------------------- tune

def tune_semitones_for_byte(value: int) -> float:
    """Semitones away from the tone's natural pitch, for a kit TUNE byte."""
    v = max(0, min(255, int(value)))
    return 24.0 * v / 255.0 - TUNE_SEMITONE_RANGE


def tune_byte_for_semitones(semitones: float) -> tuple[int, float]:
    """
    The TUNE byte nearest to `semitones`, and what it actually gives.

    Returns both, because the byte is a whole number and the request usually
    is not: asking for +7 gets you +6.98, and the caller should be able to say
    so rather than claim an exactness the hardware does not have.
    """
    s = max(-TUNE_SEMITONE_RANGE, min(TUNE_SEMITONE_RANGE, float(semitones)))
    v = int(round((s + TUNE_SEMITONE_RANGE) * 255.0 / 24.0))
    v = max(0, min(255, v))
    return v, tune_semitones_for_byte(v)


def tune_reaches(semitones: float) -> bool:
    return abs(float(semitones)) <= TUNE_SEMITONE_RANGE


def describe_tune() -> dict:
    return {
        "measured_on_tone": TUNE_TONE,
        "model": "semitones = 24 * byte / 255 - 12",
        "range_semitones": [-TUNE_SEMITONE_RANGE, TUNE_SEMITONE_RANGE],
        "centre_byte": TUNE_CENTRE,
        "points": [{"byte": b, "semitones": s} for b, s in TUNE_MEASURED],
        "caveat": "measured on one sustained sample tone. An ACB tone may not "
                  "follow the same law, and a sample with a short body may "
                  "change character as well as pitch.",
    }
