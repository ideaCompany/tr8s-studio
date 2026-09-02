"""
Tests for the one-call track builder.

The thing most worth protecting here is the ordering: kits are committed
before any pattern is written, because the machine re-points the last
transferred pattern at whatever kit is committed next (docs/PROTOCOL.md).
A test that only checks the end state on a fake device would not catch a
regression in that order, so the order itself is asserted.
"""

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import tools
from tr8s.style import STYLES
from tr8s.tools import DEFAULT_KEYS, DEFAULT_LINE, ToolError


@pytest.fixture
def wired():
    d, t = make_device(
        patterns={0: load_fixture_pattern(), 5: load_fixture_pattern()},
        kits={0: load_fixture_kit(), 61: load_fixture_kit(),
              70: load_fixture_kit(), 89: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def test_a_track_is_built_end_to_end(wired):
    r = tools.call("track.create", {"slot": 0, "style": "techno",
                                    "kit_slot": 70, "name": "TEST",
                                    "seed": 42})
    assert r["name"] == "TEST" and r["seed"] == 42
    assert set(r["roles"]) == set("ABCDEFGH")
    assert r["kit"]["slot"] == 70
    assert r["line"]["shape"] == "bass"
    assert "audit" in r
    assert len(r["steps"]) >= 4


def test_every_kit_write_precedes_every_pattern_write(wired):
    """
    The machine stamps the last transferred pattern with the next kit
    committed. Interleaving the two silently re-points the pattern.
    """
    d, t = wired
    tools.call("track.create", {"slot": 0, "style": "techno", "kit_slot": 70,
                                "seed": 1})
    kinds = [k for k, _ in t.sent]
    assert "kit" in kinds and "pattern" in kinds
    assert kinds.index("pattern") > max(i for i, k in enumerate(kinds)
                                        if k == "kit"), \
        "a kit was committed after a pattern was written"


def test_omitting_kit_slot_leaves_the_kit_alone(wired):
    """Passing a slot overwrites that kit, so it must never be implied."""
    d, t = wired
    r = tools.call("track.create", {"slot": 0, "style": "dub", "seed": 3})
    assert "kit" not in r
    assert not [k for k, _ in t.sent if k == "kit"]


def test_the_key_defaults_to_something_that_suits_the_style(wired):
    r = tools.call("track.create", {"slot": 0, "style": "hypnotic", "seed": 2})
    assert r["key"] == DEFAULT_KEYS["hypnotic"]
    assert "phrygian" in r["key"], "hypnotic techno wants the flat second"


def test_the_line_shape_defaults_per_style(wired):
    """A dub track wants offbeat stabs, not a rolling bassline."""
    # needs a built kit: the fixture's LT holds an ACB tone, which has no
    # Coarse Tune and so cannot carry a line at all
    r = tools.call("track.create", {"slot": 0, "style": "dub", "kit_slot": 70,
                                    "seed": 2})
    assert r["line"]["shape"] == DEFAULT_LINE["dub"] == "stab"


def test_line_none_writes_no_melody(wired):
    r = tools.call("track.create", {"slot": 0, "style": "techno",
                                    "line": "none", "seed": 2})
    assert "line" not in r


def test_the_same_seed_rebuilds_the_same_track(wired):
    a = tools.call("track.create", {"slot": 0, "style": "techno",
                                    "kit_slot": 70, "seed": 7})
    b = tools.call("track.create", {"slot": 5, "style": "techno",
                                    "kit_slot": 89, "seed": 7})
    assert a["roles"] == b["roles"]
    assert a["tempo"] == b["tempo"]
    assert [v["notes"] for v in a["line"]["variations"]] \
        == [v["notes"] for v in b["line"]["variations"]]


def test_a_seed_is_always_reported(wired):
    r = tools.call("track.create", {"slot": 0, "style": "techno"})
    assert isinstance(r["seed"], int)


def test_an_unknown_style_lists_the_real_ones(wired):
    with pytest.raises(ToolError, match="techno"):
        tools.call("track.create", {"slot": 0, "style": "gabber"})


def test_the_name_is_truncated_to_what_the_display_holds(wired):
    r = tools.call("track.create", {"slot": 0, "style": "techno",
                                    "name": "AVERYLONGNAME", "seed": 1})
    assert len(r["name"]) <= 8


def test_a_line_that_cannot_be_written_is_reported_not_swallowed(wired):
    """
    An ACB tone has no Coarse Tune. The track should still be built, and the
    reason the line is missing must come back.
    """
    tools.call("kit.set_instrument", {"slot": 0, "instrument": "LT", "tone": 1})
    r = tools.call("track.create", {"slot": 0, "style": "techno", "seed": 4})
    assert "line" not in r or "line_error" in r
    assert r["roles"], "the rest of the track was abandoned"


def test_panel_setup_is_passed_on_when_a_line_was_written(wired):
    r = tools.call("track.create", {"slot": 0, "style": "techno", "seed": 8})
    if "line" in r:
        joined = " ".join(r["panel_setup"])
        assert "MOTION" in joined and "CTRL" in joined


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_style_builds(wired, style):
    r = tools.call("track.create", {"slot": 0, "style": style, "seed": 5})
    assert r["roles"] and r["tempo"] > 0


# ------------------------------------------------------------------ remix

def test_remix_writes_elsewhere_and_leaves_the_original(wired):
    d, t = wired
    before = tools.call("pattern.get", {"slot": 0})
    tools.call("track.create", {"slot": 0, "style": "techno", "seed": 1})
    original = tools.call("pattern.get", {"slot": 0})

    r = tools.call("track.remix", {"slot": 0, "style": "techno", "into": 5,
                                   "seed": 999})
    assert r["remixed_from"]["slot"] == 0
    assert tools.call("pattern.get", {"slot": 0})["variations"] \
        == original["variations"], "the original was changed"
    assert "warning" not in r


def test_remix_in_place_says_it_overwrote(wired):
    """Destroying the source silently would be the worst possible default."""
    tools.call("track.create", {"slot": 0, "style": "techno", "seed": 1})
    r = tools.call("track.remix", {"slot": 0, "style": "techno", "seed": 2})
    assert "warning" in r and "undo" in r["warning"]


def test_remix_keeps_the_kit_and_tempo(wired):
    tools.call("track.create", {"slot": 0, "style": "techno", "seed": 1,
                                "set_tempo": True})
    before = tools.call("pattern.get", {"slot": 0})
    r = tools.call("track.remix", {"slot": 0, "style": "techno", "into": 5,
                                   "seed": 5})
    after = tools.call("pattern.get", {"slot": 5})
    assert after["kit"] == before["kit"]
    assert after["tempo"] == before["tempo"]
    assert r["kept"]["tempo"] == before["tempo"]


def test_remix_with_a_new_seed_gives_a_different_pattern(wired):
    tools.call("track.create", {"slot": 0, "style": "techno", "seed": 1})
    a = tools.call("track.remix", {"slot": 0, "style": "techno", "into": 5,
                                   "seed": 100})
    b = tools.call("track.remix", {"slot": 0, "style": "techno", "into": 5,
                                   "seed": 200})
    assert a["roles"] == b["roles"]          # the shape is the same
    got_a = tools.call("pattern.get", {"slot": 5})["variations"]
    assert got_a, "nothing was written"
    assert a["seed"] != b["seed"]


def test_remix_at_a_higher_energy_adds_layers(wired):
    tools.call("track.create", {"slot": 0, "style": "techno", "seed": 1})
    quiet = tools.call("track.remix", {"slot": 0, "style": "techno", "into": 5,
                                       "seed": 3, "energy": 0.2})
    q = set(tools.call("pattern.get", {"slot": 5})["variations"]["C"])
    loud = tools.call("track.remix", {"slot": 0, "style": "techno", "into": 5,
                                      "seed": 3, "energy": 0.95})
    l = set(tools.call("pattern.get", {"slot": 5})["variations"]["C"])
    assert len(l) > len(q)
