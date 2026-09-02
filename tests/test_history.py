"""
Tests for undo.

The machine has none, so this is entirely our own bookkeeping — which means the
edges matter: a failed snapshot must not block an edit, undo must survive the
device being unreadable, and a new edit has to discard the redo branch.
"""

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import tools
from tr8s.history import HISTORY, History
from tr8s.tools import ToolError


@pytest.fixture
def wired():
    d, t = make_device(patterns={0: load_fixture_pattern()},
                       kits={0: load_fixture_kit(), 61: load_fixture_kit()})
    tools.set_device(d)
    HISTORY.clear()
    yield d, t
    HISTORY.clear()
    tools.set_device(None)


def steps(inst="BD", v="A"):
    return tools.call("pattern.get", {"slot": 0})["variations"][v].get(inst, "")


# --------------------------------------------------------------- capturing

def test_a_mutating_tool_captures_before_it_writes(wired):
    assert len(HISTORY) == 0
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "BD", "steps": "X" * 16})
    assert len(HISTORY) == 1
    assert HISTORY.entries()[0]["kind"] == "pattern"


def test_a_read_only_tool_captures_nothing(wired):
    tools.call("pattern.get", {"slot": 0})
    tools.call("kit.get", {"slot": 0})
    assert len(HISTORY) == 0


def test_a_kit_edit_is_recorded_as_a_kit(wired):
    tools.call("kit.set_instrument", {"slot": 0, "instrument": "BD", "tune": 10})
    assert HISTORY.entries()[0]["kind"] == "kit"


def test_a_failed_snapshot_never_blocks_the_edit(wired):
    d, t = wired

    def boom(*a, **k):
        raise RuntimeError("the device is on fire")
    d.snapshot = boom

    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "SD", "steps": "x" * 16})
    assert steps("SD") == "x" * 16, "the edit was refused because history failed"
    assert len(HISTORY) == 0


# ------------------------------------------------------------------- undo

def test_undo_puts_back_what_was_overwritten(wired):
    before = steps()
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "BD", "steps": "X" * 16})
    assert steps() == "X" * 16
    r = tools.call("history.undo", {})
    assert steps() == before
    assert r["undone"][0]["kind"] == "pattern"


def test_undo_steps_back_through_several_edits(wired):
    original = steps()
    for ch in "xoX":
        tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                         "instrument": "BD", "steps": ch * 16})
    tools.call("history.undo", {"steps": 3})
    assert steps() == original


def test_undo_stops_cleanly_when_it_runs_out(wired):
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "BD", "steps": "X" * 16})
    r = tools.call("history.undo", {"steps": 10})
    assert len(r["undone"]) == 1, "it invented history it did not have"
    assert r["remaining"] == 0


def test_undo_with_nothing_to_undo_says_so(wired):
    with pytest.raises(ToolError, match="nothing to undo"):
        tools.call("history.undo", {})


# ------------------------------------------------------------------- redo

def test_redo_reapplies_the_undone_edit(wired):
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "BD", "steps": "X" * 16})
    tools.call("history.undo", {})
    tools.call("history.redo", {})
    assert steps() == "X" * 16


def test_a_new_edit_discards_the_redo_branch(wired):
    """Otherwise redo would re-apply an edit from a timeline that no longer is."""
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "BD", "steps": "X" * 16})
    tools.call("history.undo", {})
    assert HISTORY.redo_entries()
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "SD", "steps": "o" * 16})
    assert HISTORY.redo_entries() == []
    with pytest.raises(ToolError, match="nothing to redo"):
        tools.call("history.redo", {})


# ------------------------------------------------------------- bookkeeping

def test_history_is_bounded():
    h = History(limit=3)

    class FakeDev:
        def snapshot(self, kind, slot):
            return b"\x00" * 8
    d = FakeDev()
    for i in range(10):
        h.capture(d, "pattern", i, f"edit {i}")
    assert len(h) == 3


def test_an_empty_slot_is_not_recorded():
    h = History()

    class FakeDev:
        def snapshot(self, kind, slot):
            return None
    assert h.capture(FakeDev(), "pattern", 0, "x") is False
    assert len(h) == 0


def test_history_list_reports_depth_and_the_panel_caveat(wired):
    tools.call("pattern.set_steps", {"slot": 0, "variation": "A",
                                     "instrument": "BD", "steps": "X" * 16})
    r = tools.call("history.list", {})
    assert r["depth"] == 1
    assert "panel" in r["note"], "the limit of what undo knows must be stated"


def test_snapshots_come_from_the_cache_not_the_wire(wired):
    """A SysEx read before every step edit would make editing feel broken."""
    d, t = wired
    tools.call("pattern.get", {"slot": 0})       # warms the cache

    reads = []
    real = t.read_blob
    t.read_blob = lambda *a, **k: (reads.append(a), real(*a, **k))[1]
    d.snapshot("pattern", 0)
    assert reads == [], "undo paid for a device read it did not need"
