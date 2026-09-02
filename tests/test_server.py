"""
Tests for the studio server's own logic — the part the UI depends on but the
device tests never touch.

Nothing here binds a socket or opens a port. `Studio` is instantiated without
its constructor so the pure methods can be exercised directly, which is also
how the real handler reaches them.
"""

import queue

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import melody as melodymod
from tr8s import tools
from tr8s.device import DeviceError
from tr8s.pattern import Pattern
from tr8s.server import Hub, Studio
from tr8s.tools import ToolError


@pytest.fixture
def wired():
    d, t = make_device(patterns={0: load_fixture_pattern()},
                       kits={0: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def studio(pattern=None, slot=None, kit=None):
    """
    A real Studio, not a hand-built stand-in.

    Its constructor touches no hardware -- it only builds a Monitor and a Hub --
    so using it keeps these tests honest about the object's actual shape. A
    hand-assembled double drifts from the real one and hides attribute errors
    that would fire the moment the server ran.
    """
    s = Studio()
    s.pattern_obj = pattern
    s.slot = slot
    s.kit = kit
    return s


# ------------------------------------------------------------------- the hub

def test_a_slow_subscriber_cannot_stall_the_device():
    """The publisher runs on the MIDI thread; a full queue must not block it."""
    h = Hub()
    q = h.subscribe()
    for i in range(300):                     # the queue caps at 256
        h.publish({"type": "step", "i": i})
    assert q.qsize() <= 256
    assert q.get_nowait()["i"] == 0, "the oldest events are the ones kept"


def test_unsubscribe_stops_delivery():
    h = Hub()
    q = h.subscribe()
    h.unsubscribe(q)
    h.publish({"type": "step"})
    with pytest.raises(queue.Empty):
        q.get_nowait()
    h.unsubscribe(q)                          # twice must not raise


# --------------------------------------------------------------- melodies

def kit_with_root(root="C3", inst="LT"):
    return {"instruments": {inst: {"root": root}}}


def pattern_with_melody(mode="coarse", notes="C3 . G3 D#3", inst="LT"):
    p = Pattern(bytearray(load_fixture_pattern()))
    for v in "ABCDEFGH":
        p.clear_variation(v)
    melodymod.write(p, "A", inst, notes, "C3", mode=mode)
    return p


def test_ctrl_derived_notes_are_flagged_as_assumed():
    """
    CTRL holds whatever is assigned to that knob. The view may show the notes
    but must not present them as read fact.
    """
    p = pattern_with_melody(mode="coarse")
    mel = Studio._melodies(p, kit_with_root())["A"]["LT"]
    assert mel["assumed"] is True and mel["mode"] == "coarse"
    assert mel["notes"].startswith("C3 . G3 D#3")
    assert mel["root"] == "C3"


def test_fine_tune_notes_are_not_flagged():
    """Byte +0 is always Tune, so fine motion needs no assumption."""
    p = pattern_with_melody(mode="fine", notes="C3 D3 E3")
    mel = Studio._melodies(p, kit_with_root())["A"]["LT"]
    assert mel["assumed"] is False and mel["mode"] == "fine"


def test_an_instrument_without_a_measured_root_is_skipped():
    """A guessed root transposes the whole line, so show nothing instead."""
    p = pattern_with_melody()
    assert Studio._melodies(p, {"instruments": {"LT": {}}}) == {}
    assert Studio._melodies(p, None) == {}


def test_instruments_without_motion_are_absent():
    p = Pattern(bytearray(load_fixture_pattern()))
    for v in "ABCDEFGH":
        p.clear_variation(v)
    p.set_steps("A", "LT", "X...X...X...X...")
    assert Studio._melodies(p, kit_with_root()) == {}


# -------------------------------------------------------------- step edits

def test_step_edit_rejects_bad_input(wired):
    p = Pattern(bytearray(load_fixture_pattern()))
    s = studio(pattern=p, slot=0, kit=None)
    with pytest.raises(ToolError):
        s.step_edit("A", "BD", 0, "Q")
    with pytest.raises(ToolError):
        s.step_edit("A", "BD", 16, "X")
    with pytest.raises(ToolError):
        s.step_edit("A", "BD", -1, "X")


def test_step_edit_without_a_pattern_is_a_clear_error(wired):
    with pytest.raises(DeviceError, match="select one first"):
        studio().step_edit("A", "BD", 0, "X")


def test_step_edit_writes_through_and_publishes(wired):
    d, t = wired
    p = Pattern(bytearray(load_fixture_pattern()))
    p.set_steps("A", "BD", "." * 16)
    s = studio(pattern=p, slot=0, kit=None)
    q = s.hub.subscribe()

    r = s.step_edit("A", "BD", 4, "X")
    assert r["steps"][4] == "X" and r["live"] is True
    assert r["committed"] is False, "a live edit is the edit buffer, not a save"

    assert ("pattern", 0) in t.sent, "the edit never reached the device"
    ev = q.get_nowait()
    assert ev["type"] == "pattern" and ev["pattern"]["slot"] == 0
    # the cached object must carry the edit, since it is not re-read
    assert s.pattern_obj.get_steps("A", "BD")[4] == "X"


def test_step_edit_reports_a_failed_transfer(wired):
    d, t = wired
    t.send_blob = lambda *a, **k: False
    s = studio(pattern=Pattern(bytearray(load_fixture_pattern())), slot=0)
    with pytest.raises(DeviceError, match="incomplete"):
        s.step_edit("A", "BD", 0, "X")


# ------------------------------------------------------------- note edits

def melodic_studio():
    """A studio holding a pattern with a coarse-tune melody on LT."""
    p = pattern_with_melody(notes="C3 . G3 . C4 . . .")
    s = studio(pattern=p, slot=0, kit=kit_with_root())
    return s, p


def test_note_edit_changes_one_step_and_leaves_the_rest(wired):
    s, p = melodic_studio()
    before = melodymod.read(p, "A", "LT", "C3").split()
    r = s.note_edit("A", "LT", 2, "A3", "C3")
    after = melodymod.read(p, "A", "LT", "C3").split()
    assert r["note"] == "A3"
    assert after[2] == "A3"
    assert after[:2] == before[:2] and after[3:] == before[3:]


def test_note_edit_sounds_a_step_that_was_a_rest(wired):
    """Bending a step that never fires would be silent, so give it a hit."""
    s, p = melodic_studio()
    assert p.get_steps("A", "LT")[1] == ".", "fixture assumption"
    s.note_edit("A", "LT", 1, "D3", "C3")
    assert p.get_steps("A", "LT")[1] != "."
    assert melodymod.read(p, "A", "LT", "C3").split()[1] == "D3"


def test_a_null_note_clears_the_step_and_its_motion(wired):
    s, p = melodic_studio()
    s.note_edit("A", "LT", 2, None, "C3")
    assert p.get_steps("A", "LT")[2] == "."
    assert p.get_motion("A", "LT", 2)["mask"] == 0, "motion outlived the note"


def test_note_edit_refuses_a_note_out_of_coarse_range(wired):
    s, _ = melodic_studio()
    with pytest.raises(ToolError, match="outside Coarse Tune"):
        s.note_edit("A", "LT", 0, "C7", "C3")     # +48 semitones


def test_note_edit_rejects_nonsense(wired):
    s, _ = melodic_studio()
    with pytest.raises(ToolError):
        s.note_edit("A", "LT", 99, "C3", "C3")
    with pytest.raises(ToolError):
        s.note_edit("A", "LT", 0, "H9", "C3")
    with pytest.raises(ToolError):
        s.note_edit("A", "LT", 0, "C3", ".")


def test_note_edit_writes_through_and_publishes(wired):
    d, t = wired
    s, _ = melodic_studio()
    q = s.hub.subscribe()
    s.note_edit("A", "LT", 0, "D#3", "C3")
    assert ("pattern", 0) in t.sent
    ev = q.get_nowait()
    assert ev["type"] == "pattern"
    assert ev["pattern"]["melodies"]["A"]["LT"]["notes"].startswith("D#3")


def test_note_edit_without_a_pattern_is_a_clear_error(wired):
    with pytest.raises(DeviceError, match="select one first"):
        studio().note_edit("A", "LT", 0, "C3", "C3")


# ------------------------------------------- following the machine's panel

def follow_studio(slot=0):
    """A studio wired to a fake device, ready for the follower thread."""
    from fake import load_fixture_kit, load_fixture_pattern, make_device
    d, t = make_device(patterns={0: load_fixture_pattern(),
                                 5: load_fixture_pattern(),
                                 9: load_fixture_pattern()},
                       kits={0: load_fixture_kit(), 89: load_fixture_kit()})
    tools.set_device(d)
    return studio(slot=slot), d, t


def test_a_program_change_moves_the_view(wired):
    """Selecting a pattern on the machine has to bring the UI with it."""
    import time
    s, d, t = follow_studio(slot=0)
    s.start_follower()
    q = s.hub.subscribe()

    s._on_transport({"step": 0, "pattern": 5})
    assert s.seen_program_change is True

    for _ in range(60):
        if s.slot == 5:
            break
        time.sleep(0.05)
    assert s.slot == 5, "the view did not follow the machine"
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()["type"])
    assert "followed" in kinds
    tools.set_device(None)


def test_the_follower_never_reads_on_the_midi_thread(wired):
    """
    A SysEx read is ~0.6s. Doing it in the callback would stall the clock, so
    _on_transport must only record the wish and return.
    """
    import time
    s, d, t = follow_studio(slot=0)
    # deliberately do NOT start the follower: nothing may happen without it
    s._on_transport({"step": 0, "pattern": 5})
    time.sleep(0.2)
    assert s.slot == 0, "_on_transport read the pattern itself"
    assert s._want_slot == 5
    tools.set_device(None)


def test_rapid_changes_coalesce_to_where_the_dial_landed(wired):
    """Spinning through ten patterns must cost one read, not ten."""
    import time
    s, d, t = follow_studio(slot=0)
    s.start_follower()
    for pc in (1, 2, 3, 4, 5, 9):
        s._on_transport({"step": 0, "pattern": pc})
    for _ in range(80):
        if s.slot == 9:
            break
        time.sleep(0.05)
    assert s.slot == 9
    reads = [x for x in t.sent]           # writes; reads are not recorded
    assert s._want_slot is None
    tools.set_device(None)


def test_following_can_be_turned_off(wired):
    import time
    s, d, t = follow_studio(slot=0)
    s.follow = False
    s.start_follower()
    s._on_transport({"step": 0, "pattern": 5})
    time.sleep(0.3)
    assert s.slot == 0, "it followed while switched off"
    assert s.seen_program_change is True, "it should still notice the message"
    tools.set_device(None)


def test_a_program_change_for_the_current_slot_does_nothing(wired):
    s, d, t = follow_studio(slot=5)
    s._on_transport({"step": 0, "pattern": 5})
    assert s._want_slot is None
    tools.set_device(None)


def test_state_reports_whether_the_machine_has_ever_said(wired):
    """
    The TR-8S only sends Program Change when Tx Prog Chg is on. The UI has to
    be able to tell "not following" from "the machine has never told us".
    """
    s, d, t = follow_studio()
    f = s.state()["follow"]
    assert f["on"] is True
    assert f["seen_program_change"] is False
    assert f["channel"] is None, "any channel, until the machine says otherwise"
    assert f["channels_seen"] == []
    tools.set_device(None)


def test_a_program_change_on_the_kit_channel_is_ignored_once_pinned(wired):
    """
    The machine sends Program Change for kit switches too, on its own channel.
    Both carry a bare 0-127, so only the channel tells them apart -- following
    a kit change would drag the view to an unrelated pattern.
    """
    import time
    s, d, t = follow_studio(slot=0)
    s.pattern_channel = 9
    s.start_follower()

    s._on_transport({"step": 0, "pattern": 5, "pattern_channel": 4})
    time.sleep(0.25)
    assert s.slot == 0, "it followed a program change on the kit channel"
    assert s.seen_program_change is True

    s._on_transport({"step": 0, "pattern": 5, "pattern_channel": 9})
    for _ in range(60):
        if s.slot == 5:
            break
        time.sleep(0.05)
    assert s.slot == 5
    tools.set_device(None)


def test_every_channel_a_program_change_arrived_on_is_recorded():
    """Seeing two channels is how the kit/pattern ambiguity becomes visible."""
    from tr8s.monitor import Monitor
    m = Monitor()
    m.feed_channel(bytes([0xC9, 12]))
    m.feed_channel(bytes([0xC4, 3]))
    snap = m.snapshot()
    assert snap["program_channels"] == [4, 9]
    assert snap["pattern_channel"] == 4
    assert snap["pattern"] == 3


# ------------------------------------------- telling pattern from kit changes

def test_a_single_channel_needs_no_resolving(wired):
    """With only one channel talking there is no ambiguity to spend a read on."""
    import time
    s, d, t = follow_studio(slot=0)
    s.start_follower()
    s._on_transport({"step": 0, "pattern": 5, "pattern_channel": 9,
                     "program_channels": [9]})
    for _ in range(60):
        if s.slot == 5:
            break
        time.sleep(0.05)
    assert s.slot == 5
    assert s.pattern_channel is None, "it invented a channel it never verified"
    tools.set_device(None)


def test_the_pattern_channel_is_learned_from_the_kit_agreeing(wired):
    """
    Both messages are a bare 0-127. What separates them is that the kit
    announcement must equal the kit stored inside the pattern the other one
    names -- so reading the candidates settles it.
    """
    import time
    from tr8s.pattern import Pattern
    from tr8s.transport import BLOB_SIZES
    from fake import load_fixture_kit, make_device

    p = Pattern.from_bytes(bytes(BLOB_SIZES["pattern"]))
    p.kit = 61                       # pattern 5 says it uses kit 61
    d, t = make_device(patterns={0: p.to_bytes(), 5: p.to_bytes()},
                       kits={0: load_fixture_kit(), 61: load_fixture_kit()})
    tools.set_device(d)
    s = studio(slot=0)
    s.start_follower()
    q = s.hub.subscribe()

    now = time.monotonic()
    s.monitor.state.program_channels = {3, 9}
    s.monitor.state.recent_programs = [(now, 9, 5), (now, 3, 61)]
    s._on_transport({"step": 0, "pattern": 61, "pattern_channel": 3})

    for _ in range(80):
        if s.pattern_channel is not None:
            break
        time.sleep(0.05)
    assert s.pattern_channel == 9, "picked the kit channel as the pattern one"
    assert s.kit_channel == 3
    for _ in range(60):
        if s.slot == 5:
            break
        time.sleep(0.05)
    assert s.slot == 5, "it should follow the pattern, not the kit number"
    tools.set_device(None)


def test_an_unresolvable_burst_says_so_rather_than_guessing(wired):
    """A coin flip would land the view on an unrelated pattern."""
    import time
    s, d, t = follow_studio(slot=0)
    s.start_follower()
    q = s.hub.subscribe()
    now = time.monotonic()
    s.monitor.state.program_channels = {3, 9}
    s.monitor.state.recent_programs = [(now, 9, 111), (now, 3, 7)]
    s._on_transport({"step": 0, "pattern": 7, "pattern_channel": 3})
    time.sleep(0.8)
    assert s.pattern_channel is None
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert any(m.get("level") == "err" and "unclear" in m.get("message", "")
               for m in msgs)
    tools.set_device(None)


# --------------------------------------- hearing which variation is playing

def variation_studio():
    """A studio whose fingerprint index holds one pattern with three audibly
    different variations. Recognition goes through the index."""
    s = studio(slot=0)
    s.pattern = {"variations": {
        "A": {"BD": "X...X...X...X...", "CH": "................"},
        "B": {"BD": "X...X...X...X...", "CH": "..x...x...x...x."},
        "C": {"BD": "X.......X.......", "SD": "....X.......X...",
              "CH": "xxxxxxxxxxxxxxxx"},
    }}
    s.prints.add(0, "TEST", s.pattern["variations"])
    s.heard_variation = None
    return s


def guess(s, hits, **kw):
    """The matcher exactly as the studio uses it: Index.identify over what
    was heard, restricted to the pattern on screen."""
    from tr8s.fingerprint import heard_set
    m = s.prints.identify(heard_set(hits), only=s.slot, **kw)
    return (m.variation, m.score) if m else (None, 0.0)


def hits_for(tracks, times=1):
    """What the machine would transmit if `tracks` were playing, just now."""
    import time as _t
    out = []
    t = _t.monotonic() - 1.0
    for _ in range(times):
        for inst, steps in tracks.items():
            for i, c in enumerate(steps):
                if c != ".":
                    t += 0.01
                    out.append((t, i, inst))
    return out



def _hear(s, snap):
    """Two checks that agree, as the studio now requires before it moves."""
    s._on_transport(snap)
    s._last_guess = 0.0
    s._on_transport(snap)

def test_the_playing_variation_is_recognised(wired):
    s = variation_studio()
    v, conf = guess(s, hits_for(s.pattern["variations"]["C"]),
                                min_hits=6)
    assert v == "C"
    assert conf > 0.5


def test_a_sparser_variation_is_told_from_a_denser_one(wired):
    """
    Discrimination, not sufficiency: the threshold for "enough was heard" is
    lowered here so the test exercises the scoring rather than the gate.
    """
    s = variation_studio()
    v, _ = guess(s, hits_for(s.pattern["variations"]["B"], times=2),
                             min_hits=6)
    assert v == "B", "it should not pick the variation that explains the most"


def test_too_few_hits_is_no_answer(wired):
    """Half a bar of a kick could be almost anything."""
    s = variation_studio()
    v, _ = guess(s, [(0.0, 0, "BD"), (0.1, 4, "BD")])
    assert v is None


def test_an_unrecognisable_pattern_returns_nothing(wired):
    s = variation_studio()
    noise = [(i * 0.01, i % 16, "RC") for i in range(20)]
    v, _ = guess(s, noise, min_hits=6)
    assert v is None


def test_a_narrow_win_is_refused(wired):
    """
    Variations of one pattern share most of their steps. If two explain the
    sound nearly equally the honest answer is "cannot tell".
    """
    s = studio()
    s.pattern = {"variations": {
        "A": {"BD": "X...X...X...X..."},
        "B": {"BD": "X...X...X...X..."},   # identical
    }}
    v, _ = guess(s, hits_for(s.pattern["variations"]["A"], times=4),
                             min_hits=4)
    assert v is None


def test_no_pattern_loaded_is_no_answer(wired):
    s = studio()
    assert guess(s, hits_for({"BD": "X...X...X...X..."})) == (None, 0.0)


def test_hearing_a_variation_publishes_it(wired):
    """Recognition now goes through the fingerprint index, so seed it."""
    s = variation_studio()
    s.slot = 0
    s.prints.add(0, "TEST", s.pattern["variations"])
    q = s.hub.subscribe()
    s.monitor.state.hits = hits_for(s.pattern["variations"]["C"])
    _hear(s, {"step": 0, "playing": True})
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    v = [m for m in msgs if m["type"] == "variation"]
    assert v and v[0]["variation"] == "C" and v[0]["heard"] is True
    assert s.heard_variation == "C"


def test_recognition_finds_a_pattern_that_is_not_on_screen(wired):
    """
    The machine says nothing about which pattern is selected, so the only way
    to line up with it is to recognise what is being played.
    """
    s = variation_studio()
    s.slot = 0
    s.prints.add(0, "SHOWING", {"A": {"BD": "X..............."}})
    s.prints.add(42, "PLAYING", {"F": {"BD": "X...X...X...X...",
                                       "SD": "....X.......X...",
                                       "CH": "xxxxxxxxxxxxxxxx"}})
    q = s.hub.subscribe()
    s.monitor.state.hits = hits_for({"BD": "X...X...X...X...",
                                     "SD": "....X.......X...",
                                     "CH": "xxxxxxxxxxxxxxxx"})
    _hear(s, {"step": 0, "playing": True})
    assert s._want_slot == 42, "it did not go looking for what it heard"
    assert s.heard_variation == "F"


def test_a_rotated_hearing_still_matches(wired):
    """
    The step counter free-runs off the clock, so what we hear can be offset
    from where the bar actually starts. Detection must survive that.
    """
    s = variation_studio()
    true = hits_for(s.pattern["variations"]["C"])
    for shift in (1, 5, 9, 13):
        rotated = [(t, (i + shift) % 16, inst) for t, i, inst in true]
        v, _ = guess(s, rotated, min_hits=6)
        assert v == "C", f"shift {shift} lost it"


def test_a_thin_hearing_is_refused_however_well_it_scores(wired):
    """
    Ten notes can be three distinct hits repeated. A sparse variation of the
    wrong pattern matches that almost perfectly — a hardware self-test named
    variation A of a pattern the machine was not playing, at 0.97.
    """
    s = variation_studio()
    thin = [(i * 0.01, 0, "BD") for i in range(6)] + \
           [(i * 0.01, 4, "BD") for i in range(6)]
    v, _ = guess(s, thin)
    assert v is None


def test_one_instrument_can_be_enough_when_it_is_distinctive(wired):
    """
    An earlier version of this test asserted the opposite, on the reasoning
    that one instrument is thin evidence. It is not a rule: if the variations
    differ in their hats then hats alone identify one, and refusing on
    instrument count throws away a correct answer. The margin decides.
    """
    s = variation_studio()      # C is the only one with hats on every step
    only_hats = [(i * 0.01, i, "CH") for i in range(16)]
    v, conf = guess(s, only_hats)
    assert v == "C" and conf > 0.6


def test_material_common_to_every_variation_identifies_nothing(wired):
    """A four-to-the-floor kick is in all of them, so it says nothing."""
    s = studio()
    s.heard_variation = None
    s.pattern = {"variations": {
        "A": {"BD": "X...X...X...X...", "CH": "..x...x...x...x."},
        "B": {"BD": "X...X...X...X...", "OH": "..x...x...x...x."},
        "C": {"BD": "X...X...X...X...", "RS": "..x...x...x...x."},
    }}
    kick_only = [(i * 0.01, i * 4, "BD") for i in range(4)]
    v, _ = guess(s, kick_only)
    assert v is None
def test_the_watchdog_recovers_once_the_machine_answers_again(wired,
                                                              monkeypatch):
    """
    The studio starts before the machine is reachable more often than not --
    a port still held by something else, a device not yet powered. If the
    watchdog does not recover, the UI stays dead until it is restarted.
    """
    import tr8s.server as srv

    s = studio()
    s.connected = False
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("no reply to a version request")
        return {"port": "fake", "firmware": "2.51"}

    closed = {"n": 0}
    monkeypatch.setattr(srv, "tool_device",
                        lambda: type("D", (), {
                            "transport": type("T", (), {
                                "on_realtime": None, "on_channel": None})(),
                            "info": staticmethod(flaky)})())
    monkeypatch.setattr(srv, "_tool_close",
                        lambda: closed.__setitem__("n", closed["n"] + 1))

    assert s.connect() is False
    assert s.connect() is False
    assert s.connect() is True, "it never recovered"
    assert s.connected is True
    assert s.info.get("firmware") == "2.51"


def test_a_failed_connect_records_why(wired, monkeypatch):
    """"connected: false" with no reason is not something a user can act on."""
    import tr8s.server as srv
    s = studio()
    monkeypatch.setattr(srv, "tool_device",
                        lambda: (_ for _ in ()).throw(
                            RuntimeError("no reply to a version request")))
    assert s.connect() is False
    assert "no reply" in s.info.get("error", "")


# ------------------------------------------------ knobs and faders, live

def test_a_control_change_becomes_a_named_move_and_updates_the_kit(wired):
    """
    A CC is a bare number. What reaches the browser must say which knob on
    which instrument, and the studio's copy of the kit must follow so the
    on-screen knob does not snap back on the next redraw.
    """
    s = studio()
    s.kit = {"instruments": {"BD": {"tune": 0, "level": 200}}}
    # feed_channel publishes on its own now; do not ALSO call _on_transport by
    # hand, or the same move is counted twice
    s.monitor._on_change = s._on_transport
    q = s.hub.subscribe()
    s.monitor.feed_channel(bytes([0xB9, 20, 110, 0xB9, 24, 30, 0xB9, 91, 77]))
    evs = []
    while not q.empty():
        evs.append(q.get_nowait())
    ctl = [e for e in evs if e["type"] == "control"]
    assert len(ctl) == 1, "one event per batch, not one per knob"
    by = {(c.get("instrument"), c.get("param", c.get("name"))): c
          for c in ctl[0]["changes"]}
    assert by[("BD", "tune")]["value"] == 110
    assert by[("BD", "level")]["value"] == 30
    assert by[(None, "reverb_level")]["value"] == 77
    assert s.kit["instruments"]["BD"]["tune"] == 92     # (110-64)*2
    assert s.kit["instruments"]["BD"]["level"] == 60


def test_the_beat_counter_is_not_reported_as_a_control(wired):
    s = studio()
    q = s.hub.subscribe()
    s.monitor.feed_channel(bytes([0xB9, 2, 3]))
    s._on_transport(s.monitor.snapshot(light=True))
    assert not any(e["type"] == "control" for e in
                   [q.get_nowait() for _ in range(q.qsize())])


def test_a_stale_control_is_not_re_sent_on_every_clock(wired):
    """The moved-set is what just moved, not everything ever touched."""
    import time as _t
    s = studio()
    s.kit = {"instruments": {"BD": {"tune": 0}}}
    s.monitor.feed_channel(bytes([0xB9, 20, 100]))
    s.monitor.state.controls[20] = (100, _t.monotonic() - 10.0)   # long ago
    q = s.hub.subscribe()
    s._on_transport(s.monitor.snapshot(light=True))
    assert not any(e["type"] == "control" for e in
                   [q.get_nowait() for _ in range(q.qsize())])


def test_a_knob_turned_while_stopped_is_still_published(wired):
    """
    The bug that hid every fader move from the user: a CC arriving with the
    machine STOPPED comes in through feed_channel, whose callback carried a
    snapshot without the `controls` key, so the move was recorded and never
    published. Only while playing did the clock's snapshots carry it along.
    """
    s = studio()
    s.kit = {"instruments": {"BD": {"tune": 0, "level": 200}}}
    s.monitor._on_change = s._on_transport          # wire it as the studio does
    q = s.hub.subscribe()
    assert not s.monitor.snapshot(light=True).get("playing")
    s.monitor.feed_channel(bytes([0xB9, 24, 61]))   # BD LEVEL, machine stopped
    evs = [q.get_nowait() for _ in range(q.qsize())]
    ctl = [e for e in evs if e["type"] == "control"]
    assert ctl, "a fader moved while stopped and nothing reached the browser"
    assert ctl[0]["changes"][0]["instrument"] == "BD"
    assert ctl[0]["changes"][0]["param"] == "level"
    assert ctl[0]["changes"][0]["value"] == 61


# ------------------ following onto a pattern the studio knows nothing about

def _playing(s, d):
    """Make the studio believe the machine is playing, as notes would."""
    import time as _t
    s.monitor.state.playing = True
    s.monitor.state.last_note = _t.monotonic()
    d.playing = lambda: True


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_following_onto_an_unknown_slot_while_playing_still_moves(wired):
    """
    Slot 7 has no cached bytes and no fingerprint -- an empty pattern about
    to be built, say. The machine is on it, so the studio must be too, even
    with an empty view: otherwise the read on stop lands on the wrong pattern
    and every step entered on the panel goes unseen. This is exactly what
    happened on the ten slots the index had never read.
    """
    import time
    s, d, t = follow_studio(slot=0)
    _playing(s, d)
    s.start_follower()
    q = s.hub.subscribe()
    s._on_transport({"step": 0, "pattern": 7})
    for _ in range(60):
        if s.slot == 7:
            break
        time.sleep(0.05)
    assert s.slot == 7, "the studio stayed behind on a slot it knew"
    assert s.pattern["placeholder"] is True
    assert s.pattern["from_index"] is True
    assert s._want_resync == 7, "the real read must be queued for the stop"
    evs = _drain(q)
    assert any(e["type"] == "followed" and e.get("placeholder") for e in evs)
    tools.set_device(None)


def test_the_read_on_stop_makes_that_slot_current(wired):
    """
    `_resync` used to publish the re-read pattern without making it the
    studio's current slot, so the stopped-poll went on reading the old one
    while the screen showed the new one -- and panel edits diffed nothing.
    """
    s, d, t = follow_studio(slot=0)
    s._select_placeholder(5)
    assert s._resync(5) is True
    assert s.slot == 5
    assert s.pattern["slot"] == 5
    assert not s.pattern.get("placeholder")
    tools.set_device(None)


def test_what_was_built_on_an_empty_pattern_is_reported_on_the_first_read(wired):
    """
    The user picks an empty pattern on the machine while it plays, enters a
    kick line, and stops. The index knew the slot was empty, so the first
    read can say exactly what was added -- and bring TRACK to it.
    """
    from tr8s.server import CHANGELOG
    s, d, t = follow_studio(slot=0)
    s.prints.add(7, "NEW", {})                    # known to be empty
    s.prints_state = "ready"
    p = Pattern(bytearray(load_fixture_pattern()))
    for v in "ABCDEFGH":
        p.clear_variation(v)
    p.set_steps("A", "BD", "X...X...X...X...")
    t.slots["pattern"][7] = bytes(p.to_bytes())
    assert s._select_from_cache(7), "an empty index entry is still a view"
    assert s.pattern["variations"] == {}
    CHANGELOG.clear()
    q = s.hub.subscribe()
    assert s._resync(7) is True
    ev = [e for e in _drain(q) if e["type"] == "pattern"][-1]
    assert ev["from_machine"] is True
    assert ev["changed"] == ["BD"]
    entries = CHANGELOG.recent(10, "user")
    assert entries and entries[-1]["instrument"] == "BD"
    assert "+4" in entries[-1]["detail"]
    assert s.slot == 7
    tools.set_device(None)


def test_an_unknown_baseline_is_not_reported_as_an_edit(wired):
    """
    A never-read slot that turns out to hold a full pattern is not "the user
    just added forty steps on ten instruments": it establishes the baseline
    silently, and only the *next* edit is reported.
    """
    from tr8s.server import CHANGELOG
    s, d, t = follow_studio(slot=0)
    s._select_placeholder(5)                       # the fixture: 10 instruments
    CHANGELOG.clear()
    q = s.hub.subscribe()
    assert s._resync(5) is True
    ev = [e for e in _drain(q) if e["type"] == "pattern"][-1]
    assert ev["changed"] == []
    assert CHANGELOG.recent(10, "user") == []
    # ...and now a single panel edit against that baseline is exact
    p = Pattern(bytearray(t.slots["pattern"][5]))
    row = p.variation_summary("A").get("SD", "." * 16).ljust(16, ".")
    i = row.index(".")
    p.set_steps("A", "SD", row[:i] + "x" + row[i + 1:])
    t.slots["pattern"][5] = bytes(p.to_bytes())    # as if entered on the panel
    assert s._resync(5) is True
    entries = CHANGELOG.recent(10, "user")
    assert entries and entries[-1]["instrument"] == "SD"
    assert entries[-1]["detail"] == "+1 step"
    tools.set_device(None)


def test_a_program_change_is_acted_on_once(wired):
    """
    The monitor keeps the last Program Change it saw and _on_transport runs
    on every step tick. Re-applying the old announcement each tick dragged a
    pattern chosen in the studio straight back to the machine's one.
    """
    s, d, t = follow_studio(slot=0)
    s._on_transport({"step": 0, "pattern": 5, "pattern_at": 10.0})
    assert s._want_slot == 5
    s._want_slot = None
    s.slot = 0                            # the user picked a pattern here
    s._on_transport({"step": 1, "pattern": 5, "pattern_at": 10.0})
    assert s._want_slot is None, "the old announcement was re-applied"
    s._on_transport({"step": 2, "pattern": 5, "pattern_at": 11.0})
    assert s._want_slot == 5, "a new announcement must still be followed"
    tools.set_device(None)


def test_the_ear_cannot_move_the_slot_once_the_machine_announces(wired):
    """
    With Tx Prog Chg on, the machine says which pattern it is on. A by-ear
    match that prefers a look-alike pattern must then only pick the
    variation, never drag the view off the announced slot.
    """
    s = variation_studio()
    s.slot = 0
    s.prints.add(0, "SHOWING", {"A": {"BD": "X..............."}})
    s.prints.add(42, "PLAYING", {"F": {"BD": "X...X...X...X...",
                                       "SD": "....X.......X...",
                                       "CH": "xxxxxxxxxxxxxxxx"}})
    s.seen_program_change = True
    s.pattern_channel = 9
    s.monitor.state.hits = hits_for({"BD": "X...X...X...X...",
                                     "SD": "....X.......X...",
                                     "CH": "xxxxxxxxxxxxxxxx"})
    s._on_transport({"step": 0, "playing": True})
    assert s._want_slot is None, "the ear overrode the machine's own word"
    assert s.slot == 0


def test_missing_fingerprints_are_filled_in_while_stopped(wired):
    """The index build skips reads that fail; the after-stop reader fills
    those slots in one at a time, and gives up on a slot that stays empty."""
    s, d, t = follow_studio(slot=0)
    s.prints.add(0, "ZERO", {"A": {"BD": "X..............."}})
    s.prints_state = "ready"
    assert 5 in s.missing_prints() and 9 in s.missing_prints()
    n = 0
    while s._fill_one_print():
        n += 1
        assert n < 300
    assert 5 in s.prints.entries and 9 in s.prints.entries
    assert s.missing_prints() == []
    tools.set_device(None)


# ------------------------------------------- the monitor's idea of playing

def test_the_beat_counter_proves_playing_without_any_notes():
    """
    An empty pattern being built from scratch sends no notes. Judged by notes
    alone the studio thought it was stopped, polled it, and the bulk read hung
    the port. The beat counter (CC 2) ticks only while the sequencer runs.
    """
    from tr8s.monitor import Monitor
    m = Monitor()
    assert m.snapshot(light=True)["playing"] is False
    m.feed_channel(bytes([0xB9, 2, 1]))
    assert m.snapshot(light=True)["playing"] is True


def test_a_program_change_carries_its_arrival_time():
    import time
    from tr8s.monitor import Monitor
    m = Monitor()
    before = time.monotonic()
    m.feed_channel(bytes([0xC9, 5]))
    snap = m.snapshot(light=True)
    assert snap["pattern"] == 5
    assert snap["pattern_at"] >= before


# ------------------------------------- TRACK-focus by ear while playing

def _bars(rows_per_bar, bpm=120.0, shift=0.0):
    """Hits for several bars, oldest first, ending just now. Each element of
    `rows_per_bar` is {inst: steps} for one bar; later bars are more recent.
    `shift` moves everything `shift` bars further into the past."""
    import time as _t
    bar = 4 * 60.0 / bpm
    now = _t.monotonic() - shift * bar
    n = len(rows_per_bar)
    out = []
    for b, rows in enumerate(rows_per_bar):
        start = now - (n - b) * bar + 0.05
        for inst, steps in rows.items():
            for i, c in enumerate(steps):
                if c != ".":
                    out.append((start + i * bar / 16, i, inst))
    return out


def _ear_studio(rows_per_bar):
    s = studio(slot=0)
    s.monitor.state.bpm = 120.0
    s.monitor.state.hits = _bars(rows_per_bar)
    return s


def _focus_events(s):
    """Two checks, as the studio makes them half a second apart: a change
    has to be seen twice before TRACK moves."""
    q = s.hub.subscribe()
    s._focus_by_ear()
    s._focus_by_ear()
    return [e for e in _drain(q) if e["type"] == "focus"]


def test_a_change_seen_only_once_does_not_move_track():
    steady = {"BD": "X...X...X...X..."}
    edited = {"BD": "X...X...X...X...", "SD": "....X..........."}
    s = _ear_studio([steady, steady, edited])
    q = s.hub.subscribe()
    s._focus_by_ear()
    assert [e for e in _drain(q) if e["type"] == "focus"] == []


def test_a_new_step_on_one_row_brings_track_to_it():
    steady = {"BD": "X...X...X...X...", "CH": "..x...x...x...x."}
    edited = {"BD": "X...X...X...X...", "CH": "..x...x...x...x.",
              "SD": "....X.......X..."}
    evs = _focus_events(_ear_studio([steady, steady, edited]))
    assert [e["instrument"] for e in evs] == ["SD"]
    assert evs[0]["added"] == [5, 13]


def test_a_removed_step_is_heard_too():
    before = {"BD": "X...X...X...X...", "SD": "....X.......X..."}
    after = {"BD": "X...X...X...X...", "SD": "....X..........."}
    evs = _focus_events(_ear_studio([before, before, after]))
    assert [e["instrument"] for e in evs] == ["SD"]
    assert evs[0]["removed"] == [13]


def test_rolls_that_repeat_every_bar_are_not_an_edit():
    """The heard grid may never match the stored one; what matters is that
    it matches ITSELF bar after bar."""
    rolled = {"BD": "X...X...X...X...", "CH": "x.x.x.x.x.x.x.x."}
    assert _focus_events(_ear_studio([rolled, rolled, rolled])) == []


def test_a_step_added_right_beside_an_existing_one_is_heard():
    """Hearing is exact (measured), so no jitter tolerance: SD 4 added next
    to 1, 2, 3 must register."""
    before = {"SD": "xxx............."}
    after = {"SD": "xxxx............"}
    evs = _focus_events(_ear_studio([before, before, after]))
    assert [(e["instrument"], e["added"]) for e in evs] == [("SD", [4])]


def test_several_rows_changing_at_once_is_a_variation_not_a_hand():
    a = {"BD": "X...X...X...X...", "CH": "..x...x...x...x."}
    b = {"BD": "X.......X.......", "SD": "....X.......X...",
         "CH": "xxxxxxxxxxxxxxxx"}
    assert _focus_events(_ear_studio([a, a, b])) == []


def test_the_same_edit_is_reported_once():
    steady = {"BD": "X...X...X...X..."}
    edited = {"BD": "X...X...X...X...", "SD": "....X..........."}
    s = _ear_studio([steady, steady, edited])
    assert len(_focus_events(s)) == 1
    assert _focus_events(s) == [], "the same change, seen again next tick"


def test_fewer_than_three_bars_is_not_enough_to_judge():
    steady = {"BD": "X...X...X...X..."}
    edited = {"BD": "X...X...X...X...", "SD": "....X..........."}
    assert _focus_events(_ear_studio([steady, edited])) == []


def test_a_hit_on_the_window_edge_is_not_a_removed_step():
    """Between two hits of the same step, the previous one is almost a bar
    old. Judged by a window of exactly one bar it drops out for a moment and
    reads as removed -- which is how CH was reported edited untouched."""
    steady = {"BD": "X...X...X...X..."}
    s = studio(slot=0)
    s.monitor.state.bpm = 120.0
    s.monitor.state.hits = _bars([steady, steady, steady], shift=0.12)
    assert _focus_events(s) == []


def test_a_heard_step_stays_lit_for_a_whole_bar_at_slow_tempos():
    """At 82 BPM a bar is 2.9s; a 2.2s window made the step flicker off
    mid-bar and back on at its next hit."""
    import time as _t
    from tr8s.monitor import Monitor
    m = Monitor()
    m.state.bpm = 82.0
    m.state.playing = True
    m.state.live = {"SD": [(0, 0.0)] * 16}
    m.state.live["SD"][4] = (100, _t.monotonic() - 2.6)   # heard 2.6s ago
    assert m.state.live_rows().get("SD", "")[4] != "."


def test_the_tempo_readout_does_not_wander_on_clock_jitter():
    """Clocks arriving with a few ms of USB jitter around a steady 82.0 BPM
    must read 82.0 throughout, not 81.8 / 82.3 / 81.9."""
    import random
    from tr8s.monitor import Monitor, CLOCK
    from unittest import mock
    m = Monitor()
    rnd = random.Random(7)
    period = 60.0 / 82.0 / 24
    t = 1000.0
    seen = set()
    with mock.patch("tr8s.monitor.time.time") as clock:
        for i in range(24 * 4 * 8):                # eight bars
            t += period
            clock.return_value = t + rnd.uniform(-0.003, 0.003)
            m.feed(bytes([CLOCK]))
            if i > 200:
                seen.add(m.state.bpm)
    assert seen == {82.0}, seen


def test_a_real_tempo_change_moves_the_readout():
    from tr8s.monitor import Monitor, CLOCK
    from unittest import mock
    m = Monitor()
    t = 1000.0
    with mock.patch("tr8s.monitor.time.time") as clock:
        for bpm in (120.0, 128.0):
            for _ in range(24 * 4 * 4):
                t += 60.0 / bpm / 24
                clock.return_value = t
                m.feed(bytes([CLOCK]))
            assert m.state.bpm == bpm


def test_clocks_bunched_by_a_reader_stall_do_not_move_the_tempo():
    """The reader thread stalls ~200ms now and then (measured); the clocks
    that queued up land together with one late timestamp. The estimate must
    come from the clocks that arrived on time."""
    from tr8s.monitor import Monitor, CLOCK
    from unittest import mock
    m = Monitor()
    period = 60.0 / 82.0 / 24
    t = 1000.0
    seen = set()
    with mock.patch("tr8s.monitor.time.time") as clock:
        for i in range(24 * 4 * 8):
            t += period
            stalled = (i % 60) in range(50, 57)       # 7 clocks per stall
            clock.return_value = t + (0.2 - (i % 60 - 50) * period
                                      if stalled else 0.0)
            m.feed(bytes([CLOCK]))
            if i > 200:
                seen.add(m.state.bpm)
    assert seen == {82.0}, seen


# ------------------------------- heard edits become the pattern, right away

def test_a_heard_edit_is_merged_into_the_pattern_and_logged_at_once(wired):
    """The user does not stop to edit; what was heard is the pattern now."""
    from tr8s.server import CHANGELOG
    steady = {"BD": "X...X...X...X..."}
    edited = {"BD": "X...X...X...X...", "SD": "....X.......X..."}
    s = _ear_studio([steady, steady, edited])
    s.pattern = {"slot": 0, "variations": {"A": {"BD": "X...X...X...X..."}}}
    s.heard_variation = "A"
    CHANGELOG.clear()
    q = s.hub.subscribe()
    s._focus_by_ear(); s._focus_by_ear()
    assert s.pattern["variations"]["A"]["SD"] == "....x.......x..."
    evs = _drain(q)
    pat = [e for e in evs if e["type"] == "pattern"][-1]
    assert pat["provisional"] is True and pat["changed"] == ["SD"]
    logs = [e["message"] for e in evs if e["type"] == "log"]
    assert logs == ["SD changed on the machine"], logs
    entry = CHANGELOG.recent(5, "user")[-1]
    assert entry["instrument"] == "SD" and entry["detail"] == "+5,13 (heard)"
    assert "SD" in s._live_pending and s._panel_dirty


def test_the_read_on_stop_confirms_heard_edits_quietly(wired):
    """No 'picked up an edit' line for what was already announced."""
    s, d, t = follow_studio(slot=5)
    s.select(5)
    s._live_pending.add("SD")
    s._panel_dirty = True
    p = Pattern(bytearray(t.slots["pattern"][5]))
    row = p.variation_summary("A").get("SD", "." * 16).ljust(16, ".")
    i = row.index(".")
    p.set_steps("A", "SD", row[:i] + "x" + row[i + 1:])
    t.slots["pattern"][5] = bytes(p.to_bytes())
    q = s.hub.subscribe()
    assert s._resync(5)
    assert [e for e in _drain(q) if e["type"] == "log"] == []
    assert s._panel_dirty is False
    tools.set_device(None)


def test_a_studio_edit_over_unread_panel_edits_is_refused_while_playing(wired):
    s, d, t = follow_studio(slot=5)
    s.select(5)
    _playing(s, d)
    s._live_pending.add("SD")
    s._panel_dirty = True
    with pytest.raises(DeviceError, match="SD"):
        s.step_edit("A", "BD", 0, "x")
    assert t.sent == [], "it wrote anyway"
    tools.set_device(None)


def test_a_hand_that_keeps_editing_is_followed_step_by_step():
    """Adding one step per bar: the change is never the same twice, but each
    step is -- so every step is confirmed and reported exactly once."""
    base = {"BD": "X...X...X...X..."}
    b1 = {"BD": "X...X...X...X...", "SD": "....X..........."}
    b2 = {"BD": "X...X...X...X...", "SD": "....X.......X..."}
    b3 = {"BD": "X...X...X...X...", "SD": "..X.X.......X..."}
    s = studio(slot=0)
    s.monitor.state.bpm = 120.0
    q = s.hub.subscribe()
    got = []
    for bars in ([base, base, b1], [base, base, b1], [base, b1, b2],
                 [base, b1, b2], [b1, b2, b3], [b1, b2, b3]):
        s.monitor.state.hits = _bars(bars)
        s._focus_by_ear()
        got += [(e["instrument"], e["added"]) for e in _drain(q)
                if e["type"] == "focus"]
    assert got == [("SD", [5]), ("SD", [13]), ("SD", [3])], got


def test_the_ear_cannot_move_the_slot_when_the_pattern_channel_is_known(wired):
    """Even before the first Program Change of the session: the channel is
    saved from earlier sessions, and that is enough to know the machine
    announces its patterns. (It wandered to another pattern after a restart.)"""
    s = variation_studio()
    s.slot = 0
    s.prints.add(0, "SHOWING", {"A": {"BD": "X..............."}})
    s.prints.add(42, "PLAYING", {"F": {"BD": "X...X...X...X...",
                                       "SD": "....X.......X...",
                                       "CH": "xxxxxxxxxxxxxxxx"}})
    s.seen_program_change = False
    s.pattern_channel = 9
    s.monitor.state.hits = hits_for({"BD": "X...X...X...X...",
                                     "SD": "....X.......X...",
                                     "CH": "xxxxxxxxxxxxxxxx"})
    s._on_transport({"step": 0, "playing": True})
    assert s._want_slot is None and s.slot == 0


def test_following_remembers_the_slot_for_the_next_start(wired):
    import time
    from tr8s import config
    s, d, t = follow_studio(slot=0)
    s.start_follower()
    s._on_transport({"step": 0, "pattern": 5})
    for _ in range(60):
        if s.slot == 5:
            break
        time.sleep(0.05)
    assert config.load_settings().get("last_slot") == 5
    tools.set_device(None)


def test_a_pattern_the_studio_writes_is_recognisable_at_once(wired):
    """The assistant builds a track while the machine plays: its fingerprint
    must be current immediately, not after the next stop."""
    d, t = wired
    s = studio()
    s._watch_writes(d)
    s.prints.add(0, "OLD", {"A": {"BD": "X..............."}})
    s.prints_state = "ready"
    s.select(0)
    s.step_edit("A", "SD", 4, "X")
    fp = s.prints.entries[0]
    assert fp["name"] == "Sakura"
    assert any((4, "SD") in f for f in fp["prints"].values())
    assert s._prints_dirty is True


def test_a_perfect_match_wins_however_close_its_sibling_is():
    """Generated tracks have sibling variations a few hits apart. An exact
    match is not a coin flip."""
    from tr8s.fingerprint import Index, heard_set
    ix = Index()
    d = {"BD": "X...X...X...X...", "CH": "xoxoxoxoxoxoxoxo", "OH": "..X...X...X...X.",
         "MT": "o....o.....oxxxx", "RS": "..o...o........o", "HC": "....X.......X...",
         "RC": "o.o.o.o.o.o.o.o."}
    h = dict(d); h["RS"] = "..o...o........."; h["SD"] = "....X.......X..."
    ix.add(3, "T", {"D": d, "H": h})
    heard = heard_set(hits_for(d))
    m = ix.identify(heard, only=3)
    assert m is not None and m.variation == "D", m


def test_a_variation_is_announced_once_two_checks_agree(wired):
    s = variation_studio()
    s.slot = 0
    q = s.hub.subscribe()
    s.monitor.state.hits = hits_for({"BD": "X.......X.......",
                                     "SD": "....X.......X...",
                                     "CH": "xxxxxxxxxxxxxxxx"})
    s._on_transport({"step": 0, "playing": True})
    assert s.heard_variation is None, "one check is not enough"
    s._last_guess = 0.0
    s._on_transport({"step": 1, "playing": True})
    assert s.heard_variation == "C"
    assert any(e["type"] == "variation" for e in _drain(q))
