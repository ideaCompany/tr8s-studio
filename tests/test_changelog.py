"""The tagged change log: sources, coalescing, persistence."""

import pathlib
import tempfile

from tr8s.changelog import Change, ChangeLog


def fresh():
    return ChangeLog()


def test_the_three_sources_are_recorded_distinctly():
    L = fresh()
    L.add("user", "knob", "MT", "DECAY +11")
    L.add("studio", "tone", "BD", "Zap Kick")
    L.add("ai", "steps", "SD", "+2 steps")
    sources = [e["source"] for e in L.recent()]
    assert set(sources) == {"user", "studio", "ai"}


def test_a_knob_sweep_coalesces_to_one_entry_with_the_final_value():
    L = fresh()
    for v in range(20):
        L.add("user", "knob", "MT", f"DECAY {v}", coalesce_key="MT.decay")
    assert len(L) == 1
    # one line, showing the net move from where it started to where it settled
    detail = L.recent()[0]["detail"]
    assert "DECAY 0" in detail and "19" in detail and "\u2192" in detail


def test_a_different_control_does_not_coalesce():
    L = fresh()
    L.add("user", "knob", "MT", "DECAY 1", coalesce_key="MT.decay")
    L.add("user", "knob", "MT", "TUNE 5", coalesce_key="MT.tune")
    assert len(L) == 2


def test_disabling_stops_recording():
    L = fresh()
    L.enabled = False
    assert L.add("user", "knob", "MT", "x") is None
    assert len(L) == 0


def test_recent_can_filter_by_source():
    L = fresh()
    L.add("user", "knob", "MT", "x")
    L.add("ai", "tone", "BD", "y")
    assert [e["source"] for e in L.recent(source="ai")] == ["ai"]


def test_it_persists_and_reloads_within_a_session():
    d = pathlib.Path(tempfile.mkdtemp()) / "log.jsonl"
    L = fresh(); L.bind(d)
    L.add("user", "steps", "SD", "+2 steps", slot=127)
    L2 = fresh(); L2.bind(d)
    assert len(L2) == 1
    assert L2.recent()[0]["instrument"] == "SD"


def test_a_coalesced_sweep_is_flushed_to_disk_once_settled():
    d = pathlib.Path(tempfile.mkdtemp()) / "log.jsonl"
    L = fresh(); L.bind(d)
    for v in range(10):
        L.add("user", "knob", "MT", f"DECAY {v}", coalesce_key="MT.decay")
    L.add("user", "tone", "BD", "z")            # distinct -> flush
    L2 = fresh(); L2.bind(d)
    mt = [e for e in L2.recent() if e["instrument"] == "MT"]
    assert mt and "DECAY 0" in mt[0]["detail"] and "9" in mt[0]["detail"]


def test_clear_empties_memory_and_disk():
    d = pathlib.Path(tempfile.mkdtemp()) / "log.jsonl"
    L = fresh(); L.bind(d)
    L.add("user", "knob", "MT", "x")
    L.clear()
    assert len(L) == 0 and d.read_text() == ""


def test_the_line_reads_as_a_human_sentence():
    c = Change(source="user", action="knob", instrument="MT", detail="DECAY +11")
    assert c.line() == "[USER] knob MT: DECAY +11"


def test_a_knob_sweep_logs_one_net_gesture():
    """A hundred CCs of one turn collapse to a single start->end line."""
    from tr8s.changelog import ChangeLog
    cl = ChangeLog(); cl.enabled = True
    for v in (20, 25, 31, 38, 45):
        cl.add("user", "knob", instrument="BD",
                detail=f"DECAY {v:+d}", coalesce_key="BD.decay")
    rows = cl.recent(10)
    assert len(rows) == 1
    assert "+20" in rows[0]["detail"] and "+45" in rows[0]["detail"]
    assert "→" in rows[0]["detail"]        # shows the net move, not just the end


def test_interleaved_controls_still_coalesce():
    """The machine streams CTRL and LEVEL motion together while playing;
    alternating keys must each fold into their own line, and a value that
    does not change adds nothing."""
    from tr8s.changelog import ChangeLog
    log = ChangeLog(path=None) if "path" in ChangeLog.__init__.__code__.co_varnames else ChangeLog()
    log.clear()
    for i in range(20):
        log.add("user", "knob", instrument="BD", detail="CTRL 122",
                coalesce_key="BD.ctrl")
        log.add("user", "fader", instrument="BD", detail="LEVEL 255",
                coalesce_key="BD.level")
    assert len(log) == 2, log.as_text()
    log.add("user", "knob", instrument="BD", detail="CTRL 40", coalesce_key="BD.ctrl")
    assert len(log) == 2
    knob = [e for e in log.recent(5) if e["action"] == "knob"][0]
    assert "122" in knob["detail"] and "40" in knob["detail"], knob
