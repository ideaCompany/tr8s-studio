"""
Tests for the on-disk track library.

The library files are real exports, so these also serve as a check that the
export format has not drifted away from what pattern.import accepts.
"""

import json

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import tools
from tr8s.tools import ToolError, _library_dir


@pytest.fixture
def wired():
    d, t = make_device(patterns={0: load_fixture_pattern()},
                       kits={0: load_fixture_kit(), 89: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def library_files():
    d = _library_dir()
    return sorted(d.glob("*.json")) if d.is_dir() else []


def test_the_library_directory_is_found():
    assert _library_dir().name == "library"


def test_every_library_file_is_valid_json_with_the_expected_shape():
    files = library_files()
    if not files:
        pytest.skip("no library on this checkout")
    for f in files:
        doc = json.loads(f.read_text())
        assert doc.get("name"), f
        assert doc.get("variations"), f
        assert isinstance(doc.get("tempo"), (int, float)), f


def test_every_library_track_carries_its_provenance():
    """A pattern you cannot rebuild or vary is only a recording."""
    for f in library_files():
        meta = json.loads(f.read_text()).get("_meta") or {}
        assert meta.get("style") and meta.get("key"), f


def test_list_reports_what_is_there():
    r = tools.call("library.list", {})
    if not library_files():
        pytest.skip("no library on this checkout")
    assert r["tracks"]
    for t in r["tracks"]:
        assert t["name"] and t["style"] and t["key"]


def test_load_writes_the_pattern(wired):
    files = library_files()
    if not files:
        pytest.skip("no library on this checkout")
    name = files[0].stem
    doc = json.loads(files[0].read_text())

    r = tools.call("library.load", {"name": name, "slot": 0})
    assert r["loaded"] == name
    got = tools.call("pattern.get", {"slot": 0})
    assert got["name"] == doc["name"]
    for v, entry in doc["variations"].items():
        for inst, steps in entry["tracks"].items():
            assert got["variations"][v][inst] == steps, f"{v}/{inst}"


def test_load_says_what_it_replaced(wired):
    """Overwriting silently is the one thing this must not do."""
    files = library_files()
    if not files:
        pytest.skip("no library on this checkout")
    before = tools.call("pattern.get", {"slot": 0})["name"]
    r = tools.call("library.load", {"name": files[0].stem, "slot": 0})
    assert r["replaced"] == before


def test_load_states_the_panel_steps_the_melodies_need(wired):
    files = library_files()
    if not files:
        pytest.skip("no library on this checkout")
    r = tools.call("library.load", {"name": files[0].stem, "slot": 0})
    joined = " ".join(r["panel_setup"])
    assert "MOTION" in joined and "CTRL" in joined


def test_an_unknown_name_lists_the_real_ones(wired):
    if not library_files():
        pytest.skip("no library on this checkout")
    with pytest.raises(ToolError) as e:
        tools.call("library.load", {"name": "nonexistent", "slot": 0})
    assert "have" in str(e.value)


def test_names_are_case_insensitive(wired):
    files = library_files()
    if not files:
        pytest.skip("no library on this checkout")
    r = tools.call("library.load", {"name": files[0].stem.upper(), "slot": 0})
    assert r["loaded"]


def test_the_library_directory_is_the_repo_one():
    from tr8s.tools._core import _library_dir
    d = _library_dir()
    assert d.name == "library" and (d / "acidtrax.json").is_file(), d
