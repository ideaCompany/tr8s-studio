"""
Tests for the DSP and the measurement interpreter, on synthetic signals.

No hardware and no audio device: every input here is generated, so the
numbers are known in advance and a regression is unambiguous.
"""

import math
import struct
import wave

import pytest

from tr8s import audio
from tr8s.analysis import interpret


def tone(freq, seconds=0.3, rate=6000, amp=0.5, harmonic=0.0):
    n = int(seconds * rate)
    return [amp * math.sin(2 * math.pi * freq * i / rate)
            + harmonic * math.sin(4 * math.pi * freq * i / rate)
            for i in range(n)]


def decaying(freq, tau=0.05, seconds=0.5, rate=6000):
    n = int(seconds * rate)
    return [math.sin(2 * math.pi * freq * i / rate) * math.exp(-i / (tau * rate))
            for i in range(n)]


def saw(freq, seconds=0.3, rate=6000, amp=0.5):
    n = int(seconds * rate)
    return [(2 * ((freq * i / rate) % 1) - 1) * amp for i in range(n)]


# ---------------------------------------------------------------------- pitch

@pytest.mark.parametrize("f0", [55.0, 82.4, 110.0, 220.0, 440.0, 880.0])
def test_yin_is_accurate(f0):
    est = audio.yin(tone(f0, harmonic=0.2), 6000)
    assert est is not None, f"no pitch detected for {f0} Hz"
    assert abs(est - f0) / f0 < 0.01, f"{est} vs {f0}"


def test_yin_returns_none_for_noise_and_silence():
    import random
    random.seed(7)
    noise = [random.uniform(-1, 1) for _ in range(2000)]
    # noise may occasionally yield a low-confidence guess; silence must not
    assert audio.yin([0.0] * 2000, 6000) is None
    est = audio.yin(noise, 6000)
    assert est is None or 30 <= est <= 2000


def test_note_naming():
    assert audio.note_of(440.0)[0] == "A4"
    assert audio.note_of(65.41)[0] == "C2"
    assert audio.note_of(None) == (None, None)
    name, cents = audio.note_of(440.0 * 2 ** (1 / 24))    # a quarter-tone sharp
    assert name in ("A4", "A#4") and abs(cents) > 30


# ------------------------------------------------------------------ envelope

def test_decay_is_measured_and_sustain_detected():
    fast = audio.measure(decaying(200, tau=0.02), 6000)
    slow = audio.measure(decaying(200, tau=0.10), 6000)
    held = audio.measure(tone(200, seconds=0.5), 6000)
    assert fast.decay_ms and slow.decay_ms
    assert fast.decay_ms < slow.decay_ms, "a faster decay must measure shorter"
    assert held.sustained and held.decay_ms is None


def test_silence_is_flagged():
    m = audio.measure([0.0] * 3000, 6000)
    assert m.silent and m.peak < 0.002


# ---------------------------------------------------------------- brightness

def test_centroid_orders_by_brightness():
    sine = audio.centroid(tone(200), 6000)
    buzz = audio.centroid(saw(200), 6000)
    assert sine and buzz and buzz > sine * 2, "a saw must read brighter than a sine"


# -------------------------------------------------------------------- wav io

def test_float_wav_roundtrip(tmp_path):
    """arecord writes IEEE-float WAVs, which Python's `wave` cannot read."""
    path = tmp_path / "t.wav"
    frames = [(0.25, -0.25)] * 100
    data = b"".join(struct.pack("<ff", a, b) for a, b in frames)
    with open(path, "wb") as f:
        fmt = struct.pack("<HHIIHH", 3, 2, 48000, 48000 * 8, 8, 32)
        f.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data))
                + b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
                + b"data" + struct.pack("<I", len(data)) + data)
    with pytest.raises(wave.Error):
        wave.open(str(path))              # the stdlib really cannot
    ch, rate, samples = audio.read_wav(path)
    assert (ch, rate, len(samples)) == (2, 48000, 200)
    mono = audio.mono(samples, ch)
    assert len(mono) == 100 and abs(mono[0]) < 1e-6      # +0.25 and -0.25 cancel


def test_mono_decimation_reduces_length():
    ch, rate = 2, 6000
    import array
    a = array.array("f", [0.1] * 800)
    assert len(audio.mono(a, ch)) == 400
    assert len(audio.mono(a, ch, 8)) == 50


# -------------------------------------------------------------- interpretation

def rows(**series):
    """Build probe rows from parallel lists."""
    n = len(next(iter(series.values())))
    out = []
    for i in range(n):
        r = {"value": i * 32, "peak": 0.2, "silent": False}
        for k, v in series.items():
            r[k] = v[i]
        out.append(r)
    return out


def test_interpret_detects_tuning():
    r = interpret(rows(hz=[100, 120, 140, 170, 200, 240]))
    assert "tuning" in r["verdict"]
    assert r["confidence"] == "high"
    assert r["signals"]["pitch_semitones"] > 1.5


def test_interpret_detects_envelope_length():
    r = interpret(rows(hz=[200] * 6, decay_ms=[20, 60, 120, 200, 300, 420]))
    assert "envelope" in r["verdict"]


def test_interpret_detects_brightness():
    r = interpret(rows(hz=[200] * 6, centroid=[300, 500, 900, 1400, 2000, 2600]))
    assert "filter" in r["verdict"] or "colour" in r["verdict"]


def test_interpret_detects_level():
    r = [{"value": v, "peak": p, "silent": False}
         for v, p in zip(range(0, 256, 42), [0.02, 0.06, 0.12, 0.2, 0.3, 0.42])]
    assert "level" in interpret(r)["verdict"] or "gain" in interpret(r)["verdict"]


def test_interpret_reports_no_effect_when_nothing_moves():
    r = interpret(rows(hz=[200] * 6, centroid=[800] * 6, decay_ms=[100] * 6))
    assert "no audible effect" in r["verdict"]


def test_interpret_is_honest_about_silence():
    r = interpret([{"value": v, "silent": True} for v in range(0, 256, 32)])
    assert r["confidence"] == "low"
    assert "silent" in r["verdict"]


def test_interpret_never_claims_high_confidence_without_pitch():
    """Only an unambiguous pitch shift earns high confidence."""
    for r in (rows(hz=[200] * 6, decay_ms=[20, 60, 120, 200, 300, 420]),
              rows(hz=[200] * 6, centroid=[300, 900, 1500, 2000, 2400, 2600])):
        assert interpret(r)["confidence"] != "high"


# ------------------------------------------------------------ probe reporting

from tr8s.analysis import KNOWN_KIT_OFFSETS, SAMPLE_REGION, probe_report


def test_known_offsets_are_excluded_from_probing():
    unknown = [o for o in range(52) if o not in KNOWN_KIT_OFFSETS]
    # the identified fields must never be swept
    for known in (0, 1, 2, 3, 4, 6, 7, 8, 11):
        assert known not in unknown
    assert 5 in unknown and 12 in unknown
    assert len(unknown) == 52 - len(KNOWN_KIT_OFFSETS)


def test_level_is_marked_read_only_in_the_known_map():
    assert "read-only" in KNOWN_KIT_OFFSETS[4]


def _entry(verdict, confidence, **signals):
    base = {"pitch_semitones": 0.0, "level_spread": 0.0,
            "brightness_spread": 0.0, "decay_spread": 0.0, "silent_values": 0}
    base.update(signals)
    return {"interpretation": {"verdict": verdict, "confidence": confidence,
                               "signals": base}}


def test_report_orders_confident_findings_first():
    report = {
        "20": _entry("unclear", "low"),
        "5": _entry("tuning (pitch tracks the value)", "high", pitch_semitones=7.2),
        "12": _entry("level or gain", "medium", level_spread=0.9),
    }
    lines = probe_report(report).splitlines()
    body = [l for l in lines if l.startswith("| `+")]
    assert body[0].startswith("| `+5`"), "high confidence must come first"
    assert body[1].startswith("| `+12`")
    assert body[2].startswith("| `+20`")


def test_report_flags_the_sample_region_caveat():
    report = {"37": {**_entry("mostly silent", "low"),
                     "caveat": "inside the sample envelope/gain region: ..."}}
    text = probe_report(report)
    assert "¹" in text
    assert "not evidence the byte does nothing" in text


def test_report_omits_the_footnote_when_nothing_is_caveated():
    text = probe_report({"12": _entry("level or gain", "medium")})
    assert "¹" not in text


def test_sample_region_covers_the_envelope_bytes():
    for off in (29, 30, 33, 35, 37, 40):
        assert off in SAMPLE_REGION
    assert 12 not in SAMPLE_REGION


def test_default_probe_tone_is_suitable():
    """
    The probe tone must be able to reveal what a sweep is looking for: a single
    oscillator (unambiguous pitch), sustained (so envelope changes show), and
    harmonically rich (so a filter moves the centroid).
    """
    from tr8s.analysis import DEFAULT_PROBE_TONE
    from tr8s.tones import Catalog
    cat = Catalog.load()
    t = cat.get(DEFAULT_PROBE_TONE)
    if t is None:
        pytest.skip("catalogue not built on this machine")
    assert t.type == 2, "must be a sample tone so every parameter applies"
    assert t.sustained, "a decaying tone hides envelope changes"
    assert (t.centroid or 0) > 500, "needs harmonics for a filter to show"
    assert t.hz and 40 < t.hz < 400, "pitch must sit where the detector is solid"


# ------------------------------------------------------ monotonicity checks

from tr8s.analysis import _rank_corr


def test_rank_correlation_finds_a_trend():
    xs = list(range(8))
    assert _rank_corr(xs, [v * 2 for v in xs]) > 0.99
    assert _rank_corr(xs, [-v for v in xs]) < -0.99


def test_rank_correlation_ignores_missing_values():
    xs = [0, 1, 2, 3, 4, 5]
    ys = [0, None, 2, None, 4, 5]
    assert _rank_corr(xs, ys) > 0.99


def test_rank_correlation_is_zero_without_a_trend():
    assert abs(_rank_corr([0, 1, 2, 3, 4, 5], [5, 5, 5, 5, 5, 5])) < 0.01
    assert abs(_rank_corr(list(range(6)), [3, 1, 4, 1, 5, 2])) < 0.7


def test_a_step_change_is_not_reported_as_tuning():
    """
    Real case: three kit offsets whose pitch stepped once at the bottom of the
    range and then sat flat. Range alone called that "tuning, high confidence".
    """
    hz = [78.0, 78.0, 65.4, 65.4, 65.4, 65.4, 65.4, 65.4]
    r = interpret(rows(hz=hz))
    assert "tuning" not in r["verdict"]
    assert "selects" in r["verdict"]
    assert r["confidence"] != "high"


def test_pitch_that_vanishes_in_the_middle_is_not_tuning():
    """An unpitched middle means the sample broke, not that it was tuned."""
    hz = [65.4, 44.5, None, None, None, 39.2, 60.2, 65.3]
    r = interpret(rows(hz=hz))
    assert "tuning" not in r["verdict"]


def test_a_real_tuning_sweep_still_reads_as_tuning():
    r = interpret(rows(hz=[100, 120, 140, 170, 200, 240, 280, 330]))
    assert r["verdict"].startswith("tuning")
    assert r["confidence"] == "high"
    assert r["signals"]["pitch_trend"] > 0.9


def test_a_downward_tuning_sweep_also_reads_as_tuning():
    r = interpret(rows(hz=[330, 280, 240, 200, 170, 140, 120, 100]))
    assert r["verdict"].startswith("tuning")


def test_a_non_monotonic_level_is_not_called_gain():
    r = [{"value": v * 32, "peak": p, "silent": False, "hz": 200}
         for v, p in enumerate([0.1, 0.9, 0.2, 0.8, 0.15, 0.95, 0.3, 0.85])]
    assert "level" not in interpret(r)["verdict"]


def test_signals_always_report_the_trends():
    r = interpret(rows(hz=[200] * 6))
    for k in ("pitch_trend", "level_trend", "brightness_trend", "decay_trend",
              "pitched_fraction"):
        assert k in r["signals"]


from tr8s.analysis import _step_dominance


def test_step_dominance_spots_a_switch():
    """Two values high, the rest low: all the change is in one jump."""
    xs = list(range(8))
    assert _step_dominance(xs, [78, 78, 65, 65, 65, 65, 65, 65]) > 0.95


def test_step_dominance_is_low_for_a_real_sweep():
    xs = list(range(8))
    assert _step_dominance(xs, [100, 120, 140, 170, 200, 240, 280, 330]) < 0.3


def test_step_dominance_handles_flat_and_short_input():
    assert _step_dominance([0, 1, 2], [5, 5, 5]) == 0.0
    assert _step_dominance([0, 1], [1, 9]) == 0.0


def test_a_monotonic_step_is_still_not_tuning():
    """
    The real +5 sweep: pitch falls monotonically, so rank correlation alone
    passes it, but the whole 3-semitone change happens between two adjacent
    values and the rest of the range is flat.
    """
    hz = [77.98, 77.97, 65.4, 65.41, 65.41, 65.38, 65.32, 65.31]
    r = interpret(rows(hz=hz))
    assert r["signals"]["pitch_trend"] < -0.8, "it really is monotonic"
    assert r["signals"]["pitch_step_dominance"] > 0.9
    assert "tuning" not in r["verdict"]
