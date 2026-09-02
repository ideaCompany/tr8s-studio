"""
The Control Change map, from the MIDI Implementation Chart.

Every panel knob and fader is a named CC. These pin the table so a typo in a
number moves the wrong knob on screen rather than silently.
"""

import pytest

from tr8s.ccmap import (BEAT_CC, INSTRUMENT_CC, MASTER_CC, PARAMS, cc_for,
                        describe, from_kit_value, label, to_kit_value)
from tr8s.kit import TRACKS


def test_every_instrument_has_all_four_controls():
    assert set(INSTRUMENT_CC) == set(TRACKS)
    for inst, ccs in INSTRUMENT_CC.items():
        assert len(ccs) == len(PARAMS) == 4, inst


def test_no_cc_number_is_used_twice():
    """Two controls on one CC would move together on screen."""
    seen = [cc for ccs in INSTRUMENT_CC.values() for cc in ccs]
    seen += list(MASTER_CC)
    assert len(seen) == len(set(seen))
    assert BEAT_CC not in seen, "the beat counter is not a control"


def test_the_chart_values_are_reproduced():
    """Spot checks against the printed chart, one from each region."""
    assert cc_for("BD", "tune") == 20
    assert cc_for("BD", "ctrl") == 96
    assert cc_for("CH", "level") == 63
    assert cc_for("OH", "tune") == 80       # the OH..RC block jumps to 80
    assert cc_for("RC", "ctrl") == 110
    assert MASTER_CC[91] == "reverb_level"
    assert MASTER_CC[71] == "accent"


def test_describe_and_label():
    assert describe(20) == ("BD", "tune")
    assert describe(16) == (None, "delay_level")
    assert describe(99) is None
    assert label(20) == "BD TUNE"
    assert label(2) == "beat"
    assert label(99) == "CC 99"


def test_cc_to_kit_and_back_is_consistent():
    """7-bit on the wire, 8-bit in the kit; tune is signed, centred at 64."""
    assert to_kit_value("tune", 64) == 0
    assert to_kit_value("tune", 0) == -128
    assert to_kit_value("tune", 127) == 126
    assert to_kit_value("level", 0) == 0
    assert to_kit_value("level", 127) == 255
    for v in (0, 1, 33, 64, 100, 127):
        for p in ("tune", "decay", "level"):
            back = from_kit_value(p, to_kit_value(p, v))
            assert abs(back - v) <= 1, (p, v, back)


def test_out_of_range_cc_is_clamped_not_raised():
    assert to_kit_value("level", 999) == to_kit_value("level", 127)
    assert to_kit_value("tune", -5) == to_kit_value("tune", 0)
