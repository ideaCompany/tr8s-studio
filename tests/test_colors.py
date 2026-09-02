"""
Tests for the per-instrument fader colour.

The offset was identified statistically rather than by watching the panel, so
these pin down what the evidence actually supports: eleven bytes, one per
instrument in TRACKS order, small palette, and a factory default that groups
by instrument category.
"""

import pathlib

import pytest

from fake import load_fixture_kit, make_device
from tr8s import tools
from tr8s.kit import COLOR_BASE, COLOR_COUNT, COLOUR_NAMES, TRACKS, Kit, KitError
from tr8s.tools import ToolError

BACKUPS = pathlib.Path.home() / ".local/share/tr8s/backups/kits"


@pytest.fixture
def wired():
    d, t = make_device(kits={0: load_fixture_kit(), 61: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def test_there_is_one_colour_byte_per_instrument():
    assert COLOR_BASE + len(TRACKS) <= 1312
    k = Kit.from_bytes(load_fixture_kit())
    assert set(k.colors()) == set(TRACKS)


def test_colours_map_to_the_bytes_in_track_order():
    k = Kit.from_bytes(load_fixture_kit())
    for i, inst in enumerate(TRACKS):
        assert k.color(inst) == k.raw[COLOR_BASE + i]


def test_setting_a_colour_touches_only_that_byte():
    k = Kit.from_bytes(load_fixture_kit())
    before = bytes(k.raw)
    k.set_color("HC", 9)
    differ = [i for i in range(len(before)) if before[i] != k.raw[i]]
    assert differ == [COLOR_BASE + TRACKS.index("HC")]
    assert k.color("HC") == 9


def test_a_colour_outside_the_palette_is_refused():
    k = Kit.from_bytes(load_fixture_kit())
    for bad in (-1, COLOR_COUNT, 255):
        with pytest.raises(KitError):
            k.set_color("BD", bad)


def test_every_palette_index_has_a_name():
    assert len(COLOUR_NAMES) == COLOR_COUNT


def test_describe_reports_the_colour_and_its_name():
    d = Kit.from_bytes(load_fixture_kit()).describe()
    bd = d["instruments"]["BD"]
    assert 0 <= bd["color"] < COLOR_COUNT
    assert bd["color_name"] == COLOUR_NAMES[bd["color"]]


# ------------------------------------------------- evidence from real kits

def real_kits():
    if not BACKUPS.is_dir():
        return []
    return [Kit.from_bytes(p.read_bytes()) for p in sorted(BACKUPS.glob("*.bin"))]


def test_real_kits_keep_the_colours_inside_the_palette():
    kits = real_kits()
    if not kits:
        pytest.skip("no kit backups on this machine")
    for k in kits:
        for inst in TRACKS:
            assert 0 <= k.color(inst) < COLOR_COUNT, f"{k.name}/{inst}"


def test_the_factory_default_groups_by_instrument_category():
    """
    This is the evidence the identification rests on: the default is not
    arbitrary, it colours kicks, snares, toms, claps and hats as groups.
    """
    kits = real_kits()
    if not kits:
        pytest.skip("no kit backups on this machine")
    from collections import Counter
    default = Counter(tuple(k.colors()[i] for i in TRACKS) for k in kits)
    scheme, _ = default.most_common(1)[0]
    by = dict(zip(TRACKS, scheme))
    assert by["LT"] == by["MT"] == by["HT"], "the toms should share a colour"
    assert by["CH"] == by["OH"], "the hats should share a colour"
    assert by["BD"] != by["SD"], "kick and snare should differ"


def test_colours_actually_vary_between_kits():
    """A field that never changes would not be worth reading."""
    kits = real_kits()
    if not kits:
        pytest.skip("no kit backups on this machine")
    seen = {tuple(k.colors()[i] for i in TRACKS) for k in kits}
    assert len(seen) > 1


# -------------------------------------------------------------- the tool

def test_set_color_writes_and_reports(wired):
    r = tools.call("kit.set_color", {"slot": 0, "colors": {"BD": 5, "SD": 9}})
    assert r["changed"]["BD"][1] == 5
    k = tools.call("kit.get", {"slot": 0})["instruments"]
    assert k["BD"]["color"] == 5 and k["SD"]["color"] == 9


def test_set_color_rejects_an_unknown_instrument(wired):
    with pytest.raises(ToolError, match="unknown instrument"):
        tools.call("kit.set_color", {"slot": 0, "colors": {"XX": 1}})


def test_set_color_rejects_an_out_of_range_index(wired):
    with pytest.raises(ToolError):
        tools.call("kit.set_color", {"slot": 0, "colors": {"BD": 99}})


def test_set_color_admits_the_palette_is_unconfirmed(wired):
    r = tools.call("kit.set_color", {"slot": 0, "colors": {"BD": 2}})
    assert "not by watching the panel" in r["note"]
