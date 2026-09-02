"""
Tests for the measured decay curve and the fixer built on it.

The curve is real data taken off the machine, so these check that the code
respects its limits: no extrapolating past what was measured, and never
returning byte 0, which measured louder and longer than its neighbours.
"""

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import tools
from tr8s.tools import ToolError
from tr8s.calibration import (DECAY_CURVE, DECAY_MAX_BYTE, DECAY_MAX_MS,
                              DECAY_MIN_BYTE, DECAY_MIN_MS, SUSTAIN_BYTES,
                              decay_byte_for_ms, decay_ms_for_byte,
                              describe_decay)


def test_the_curve_is_monotonic():
    """If it were not, interpolating between points would be meaningless."""
    bytes_ = [b for b, _ in DECAY_CURVE]
    ms = [m for _, m in DECAY_CURVE]
    assert bytes_ == sorted(bytes_)
    assert ms == sorted(ms)


def test_every_measured_point_round_trips():
    for b, ms in DECAY_CURVE:
        assert decay_ms_for_byte(b) == pytest.approx(ms)
        assert decay_byte_for_ms(ms) == pytest.approx(b, abs=1)


def test_interpolation_lands_between_the_points():
    ms = decay_ms_for_byte(40)          # between 32 (80ms) and 48 (110ms)
    assert 80 < ms < 110


def test_the_sustain_values_report_no_decay():
    for v in SUSTAIN_BYTES:
        assert decay_ms_for_byte(v) is None


def test_nothing_is_extrapolated_past_what_was_measured():
    """There is no evidence for what happens beyond the swept range."""
    assert decay_ms_for_byte(230) == DECAY_MAX_MS
    assert decay_byte_for_ms(10_000) == DECAY_MAX_BYTE
    assert decay_byte_for_ms(1) == DECAY_MIN_BYTE


def test_asking_for_the_shortest_decay_never_returns_zero():
    """
    Byte 0 measured LOUDER and non-decaying — the opposite of a short decay.
    Handing it back for "as short as possible" would do the reverse of the ask.
    """
    for ms in (0, 1, 5, 20, 59):
        b = decay_byte_for_ms(ms)
        assert b not in SUSTAIN_BYTES
        assert b == DECAY_MIN_BYTE


def test_the_description_carries_its_caveat():
    d = describe_decay()
    assert d["measured_on_tone"]
    assert "one tone" in d["caveat"]
    assert "outlier" in d["caveat"]


# ------------------------------------------------------------------- kit.fix

@pytest.fixture
def wired():
    d, t = make_device(patterns={0: load_fixture_pattern()},
                       kits={0: load_fixture_kit(), 89: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def test_fix_shortens_a_smearing_decay(wired):
    d, t = wired
    tools.call("pattern.clear_variation", {"slot": 0, "variation": "A"})
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "OH",
                                     "steps": "x.x.x.x.x.x.x.x."})
    p = tools.call("pattern.get", {"slot": 0})
    tools.call("kit.set_instrument", {"slot": p["kit"], "instrument": "OH",
                                      "decay": 224})       # 745 ms, far too long
    r = tools.call("kit.fix", {"slot": 0, "variation": "A"})
    oh = [c for c in r["changes"] if c["instrument"] == "OH"]
    if oh:                       # only if the tone is measured on this machine
        assert oh[0]["to"] < oh[0]["from"]
        assert r["applied"] is True


def test_fix_can_be_previewed_without_writing(wired):
    d, t = wired
    before = len([1 for k, _ in t.sent if k == "kit"])
    r = tools.call("kit.fix", {"slot": 0, "variation": "A", "apply": False})
    assert r["applied"] is False
    assert len([1 for k, _ in t.sent if k == "kit"]) == before


def test_fix_reports_what_it_cannot_fix(wired):
    """Level belongs to the faders, so a collision is advice, never a change."""
    r = tools.call("kit.fix", {"slot": 0, "variation": "A"})
    for a in r["advice"]:
        assert a["why_not_fixable"]


def test_fix_says_so_when_there_is_nothing_to_do(wired):
    tools.call("pattern.clear_variation", {"slot": 0, "variation": "H"})
    r = tools.call("kit.fix", {"slot": 0, "variation": "H"})
    assert r["changes"] == []
    assert "note" in r


def test_the_calibration_tool_exposes_the_caveat(wired):
    d = tools.call("calibration.describe", {})
    assert d["decay"]["curve"]
    assert "one tone" in d["decay"]["caveat"]


# --------------------------------------------------------------------- tune

from tr8s.calibration import (TUNE_MEASURED, TUNE_SEMITONE_RANGE,
                              describe_tune, tune_byte_for_semitones,
                              tune_reaches, tune_semitones_for_byte)


def test_the_tune_model_matches_every_measured_point():
    for b, measured in TUNE_MEASURED:
        assert tune_semitones_for_byte(b) == pytest.approx(measured, abs=0.06)


def test_tune_is_symmetric_about_the_centre():
    assert tune_semitones_for_byte(0) == pytest.approx(-12, abs=0.05)
    assert tune_semitones_for_byte(255) == pytest.approx(12, abs=0.05)
    assert abs(tune_semitones_for_byte(128)) < 0.1


def test_tune_round_trips_through_the_byte():
    for semis in (-12, -7, -3, 0, 3.5, 7, 12):
        b, actual = tune_byte_for_semitones(semis)
        assert 0 <= b <= 255
        assert actual == pytest.approx(semis, abs=0.1)


def test_tune_reports_what_it_actually_lands_on():
    """The byte is a whole number; claiming exactness would be a lie."""
    b, actual = tune_byte_for_semitones(7)
    assert isinstance(b, int)
    assert actual == pytest.approx(7, abs=0.1)


def test_tune_requests_beyond_an_octave_are_clamped_and_detectable():
    assert not tune_reaches(13)
    assert tune_reaches(12) and tune_reaches(-12)
    b, actual = tune_byte_for_semitones(40)
    assert actual == pytest.approx(TUNE_SEMITONE_RANGE, abs=0.05)


def test_the_tune_scale_is_not_the_motion_tune_scale():
    """
    Two different fields with two different laws. Reusing one constant for the
    other transposes every fine-mode melody.
    """
    from tr8s.melody import FINE_UNITS_PER_SEMITONE
    kit_units_per_semitone = 255.0 / (2 * TUNE_SEMITONE_RANGE)
    assert abs(kit_units_per_semitone - FINE_UNITS_PER_SEMITONE) > 5


def test_tune_description_carries_its_caveat():
    d = describe_tune()
    assert "one" in d["caveat"] and d["points"]
    assert d["range_semitones"] == [-12.0, 12.0]


# ----------------------------------------------------------- kit.tune_to

def test_tune_to_moves_the_instrument_to_the_asked_note(wired):
    r = tools.call("kit.tune_to", {"slot": 0, "instrument": "BD",
                                   "note": "C1", "root": "G1"})
    assert r["semitones"] == pytest.approx(-7, abs=0.1)
    k = tools.call("kit.get", {"slot": 0})
    got = tune_semitones_for_byte(k["instruments"]["BD"]["tune"] + 128)
    assert got == pytest.approx(-7, abs=0.1), "the signed byte was mishandled"


def test_tune_to_refuses_what_it_cannot_reach(wired):
    with pytest.raises(ToolError, match="only reaches"):
        tools.call("kit.tune_to", {"slot": 0, "instrument": "BD",
                                   "note": "C4", "root": "G1"})


def test_tune_to_needs_a_root_it_can_trust(wired):
    """Without knowing what it sounds at now, there is nothing to shift from."""
    with pytest.raises(ToolError, match="root"):
        tools.call("kit.tune_to", {"slot": 0, "instrument": "CH",
                                   "note": "C2"})


def test_tune_to_says_when_it_cannot_land_exactly(wired):
    r = tools.call("kit.tune_to", {"slot": 0, "instrument": "BD",
                                   "note": "C1", "root": "G1"})
    assert abs(r["semitones"] - r["requested_semitones"]) < 0.1
