"""The heard-diff that spots a panel step edit while the machine plays."""
from tr8s.monitor import detect_edits


def row(*steps, vel=100, when=100.0):
    """A 16-step live row with hits (vel, when) at the given step indices."""
    r = [(0, 0.0)] * 16
    for s in steps:
        r[s] = (vel, when)
    return r


def test_a_freshly_heard_step_we_did_not_know_is_an_add():
    known = {"SD": {4, 12}}
    live = {"SD": row(4, 12, 7, when=99.5)}      # 7 is new
    added, removed = detect_edits(known, live, now=100.0)
    assert added == {"SD": {7}}
    assert removed == {}


def test_a_known_step_gone_silent_for_over_a_bar_is_a_remove():
    known = {"CH": {2, 6, 10}}
    # 2 and 6 still sounding; 10 last heard 3s ago -> removed
    live = {"CH": [(0, 0.0)] * 16}
    live["CH"][2] = (100, 99.6)
    live["CH"][6] = (100, 99.6)
    live["CH"][10] = (100, 97.0)
    added, removed = detect_edits(known, live, now=100.0)
    assert removed == {"CH": {10}}
    assert added == {}


def test_a_known_step_never_yet_heard_is_not_a_remove():
    known = {"BD": {0, 8}}
    live = {"BD": row(0, when=99.8)}             # step 8 has when == 0
    added, removed = detect_edits(known, live, now=100.0)
    assert removed == {}                          # not judged until heard once


def test_a_stale_heard_step_is_not_a_fresh_add():
    known = {"SD": {4}}
    live = {"SD": row(4, 9, when=96.0)}          # 9 heard 4s ago -> too old
    added, removed = detect_edits(known, live, now=100.0)
    assert added == {}


def test_nothing_changed_is_silent():
    known = {"SD": {4, 12}, "BD": {0, 8}}
    live = {"SD": row(4, 12, when=99.7), "BD": row(0, 8, when=99.7)}
    added, removed = detect_edits(known, live, now=100.0)
    assert added == {} and removed == {}
