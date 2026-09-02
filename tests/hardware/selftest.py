#!/usr/bin/env python3
"""
Exercise the whole stack against a real TR-8S and report what breaks.

Not part of the pytest suite: it needs the machine, it takes a couple of
minutes, and it makes sound. Run it deliberately:

    PYTHONPATH=src .venv/bin/python tests/hardware/selftest.py

Everything it writes goes to a scratch slot, and the original contents are put
back at the end -- including if a check raises. Each check reports pass, fail,
or skipped-with-a-reason; a check that cannot run is never counted as a pass.
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tr8s import tools                                    # noqa: E402
from tr8s.device import slot_to_panel                     # noqa: E402
from tr8s.monitor import INST_NOTES                       # noqa: E402
from tr8s.pattern import Pattern                          # noqa: E402
from tr8s.server import Studio                            # noqa: E402

SCRATCH_PATTERN = 127          # 8-16
RESULTS = []


def check(name):
    def deco(fn):
        def run(*a, **kw):
            t0 = time.time()
            try:
                out = fn(*a, **kw)
            except SkipCheck as e:
                RESULTS.append(("skip", name, str(e), time.time() - t0))
                print(f"  SKIP  {name}: {e}", flush=True)
                return None
            except Exception as e:
                RESULTS.append(("fail", name, f"{type(e).__name__}: {e}",
                                time.time() - t0))
                print(f"  FAIL  {name}: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
                return None
            RESULTS.append(("pass", name, out or "", time.time() - t0))
            print(f"  ok    {name}" + (f" — {out}" if out else ""), flush=True)
            return out
        run.__name__ = fn.__name__
        return run
    return deco


class SkipCheck(Exception):
    pass


# ------------------------------------------------------------------ the wire

@check("the device answers")
def t_info(d):
    i = tools.call("device.info", {})
    assert i.get("firmware"), i
    return f"firmware {i['firmware']}"


@check("a pattern round-trips byte for byte")
def t_roundtrip(d):
    original = d.transport.read_blob("pattern", SCRATCH_PATTERN)
    assert original, "could not read the scratch slot"
    p = Pattern.from_bytes(original)
    p.set_steps("A", "RC", "X.x.o...X.x.o...")
    blob = p.to_bytes()
    assert d.transport.send_blob("pattern", SCRATCH_PATTERN, blob)
    time.sleep(0.4)
    back = d.transport.read_blob("pattern", SCRATCH_PATTERN)
    bad = [i for i in range(len(blob)) if blob[i] != back[i]]
    assert not bad, f"{len(bad)} bytes differ, first at {bad[:4]}"
    return f"{len(blob)} bytes"


@check("a kit commit does not re-point the last pattern")
def t_kit_reference(d):
    """The machine stamps it; the library is supposed to put it back."""
    tools.call("pattern.set_header", {"slot": SCRATCH_PATTERN, "kit": 10})
    before = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})["kit"]
    assert before == 10, f"the header did not take: {before}"
    k = d.read_kit(100)
    d.write_kit(100, k)
    after = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})["kit"]
    assert after == 10, f"kit reference was changed to {after} by a kit commit"
    return "repaired"


# --------------------------------------------------------------- calibration

@check("the TUNE curve matches the machine")
def t_tune(d):
    """Tune an instrument to a named note and check it lands where predicted."""
    from tr8s.calibration import tune_semitones_for_byte
    kit = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})["kit"]
    k = d.read_kit(kit)
    was = k.get("BD", "tune")
    try:
        info = d.tone_info(k.get("BD", "tone"))
        if not info or not info.root:
            raise SkipCheck("BD's tone has no measured root")
        r = tools.call("kit.tune_to", {"slot": kit, "instrument": "BD",
                                       "note": info.root})
        assert abs(r["semitones"]) < 0.1, r
        back = d.read_kit(kit).get("BD", "tune")
        got = tune_semitones_for_byte(back + 128)
        assert abs(got) < 0.1, f"read back {got:+.2f} semitones, wanted 0"
        return "0 semitones round-tripped"
    finally:
        k2 = d.read_kit(kit)
        k2.set("BD", "tune", was)
        d.write_kit(kit, k2)


# ------------------------------------------------------------- listening

@check("the machine plays when told to")
def t_transport(d, st):
    st.monitor.state.hits = []
    tools.call("device.transport", {"action": "start"})
    # long enough for a couple of bars: identifying a variation needs to hear
    # enough *different* material, not just a lot of notes
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.3)
        hits = st.monitor.snapshot().get("hits") or []
        if len({(x[1], x[2]) for x in hits}) >= 20:
            break
    tools.call("device.transport", {"action": "stop"})
    hits = st.monitor.snapshot().get("hits") or []
    assert hits, ("no notes arrived. The machine may have nothing to play, or "
                  "notes are not being transmitted")
    return f"{len(hits)} notes heard"


@check("every note maps to an instrument")
def t_notes(d, st):
    hits = st.monitor.snapshot().get("hits") or []
    if not hits:
        raise SkipCheck("nothing was heard")
    insts = {i for _, _, i in hits}
    assert insts <= set(INST_NOTES.values()), insts
    return ", ".join(sorted(insts))


@check("what the machine is playing can be found in its own memory")
def t_search(d, st):
    """
    The machine will not say which pattern it is on and does not act on a
    Program Change, so the only way to line the studio up with it is to
    recognise what is being played. Search the banks for it.
    """
    hits = st.monitor.snapshot().get("hits") or []
    heard = {(s_, i) for _, s_, i in hits}
    if len(heard) < 4:
        raise SkipCheck(f"only {len(heard)} distinct hits were heard")

    def score(expected):
        """F1, symmetric — see fingerprint.score."""
        best = -1.0
        for shift in range(16):
            rot = {((k + shift) % 16, i) for k, i in heard}
            best = max(best, 2 * len(rot & expected) / (len(rot) + len(expected)))
        return best

    found = []
    for slot in range(0, 128):
        try:
            p = d.read_pattern(slot)
        except Exception:
            continue
        for v in "ABCDEFGH":
            tracks = p.variation_summary(v)
            exp = {(k, inst) for inst, steps in tracks.items()
                   for k, c in enumerate(steps) if c != "."}
            if exp:
                found.append((score(exp), slot, v, p.name))
    found.sort(reverse=True)
    if not found or found[0][0] < 0.8:
        raise SkipCheck("nothing in memory matches what was heard")
    sc, slot, v, name = found[0]
    st.select(slot)
    globals()["_HEARD"] = (slot, v)
    return f"{name} {slot_to_panel(slot)} {v} at {round(sc, 2)}"


@check("the variation being played is recognised")
def t_variation(d, st):
    hits = st.monitor.snapshot().get("hits") or []
    if not st.pattern:
        raise SkipCheck("no pattern is loaded in the studio")
    from tr8s.fingerprint import heard_set
    m = st.prints.identify(heard_set(hits), only=st.slot) if len(st.prints) else None
    v, conf = (m.variation, round(m.score, 2)) if m else (None, 0.0)
    if v is None:
        raise SkipCheck(
            f"could not tell (best {conf}) — the studio is showing "
            f"{st.pattern['panel']}, which may not be what the machine is on")
    expected = globals().get("_HEARD")
    if expected and expected[0] == st.slot:
        assert v == expected[1], f"the search said {expected[1]}, this says {v}"
    return f"{v} at {conf}"


@check("knob and fader moves arrive by name")
def t_controls(d, st):
    """
    Needs UTILITY:MIDI:Tx EditData ON and a hand on the panel, so this can
    only report what it saw. A CC that arrives but is unmapped is a bug; none
    arriving is a skip, not a pass.
    """
    from tr8s.ccmap import describe, BEAT_CC
    ccs = [c for _, ch, cc, v in (st.monitor.snapshot().get("recent_cc") or [])
           if cc != BEAT_CC for c in [cc]]
    if not ccs:
        raise SkipCheck("no control change arrived; turn a knob with "
                        "Tx EditData ON to exercise this")
    unmapped = sorted({c for c in ccs if describe(c) is None})
    assert not unmapped, f"unmapped CCs arrived: {unmapped}"
    seen = sorted({(describe(c)[0] or "master", describe(c)[1]) for c in ccs})
    return ", ".join(f"{i} {p}" for i, p in seen[:6])


@check("a control change reaches a browser over SSE while stopped")
def t_sse_control(d, st):
    """
    The bug that hid every knob move from the user: a CC arriving while the
    machine was stopped was recorded and never published. Prove delivery on
    the live event stream, not by calling the UI's functions directly.
    """
    import json, threading, urllib.request
    seen = []
    def listen():
        try:
            req = urllib.request.Request("http://127.0.0.1:8733/api/events")
            with urllib.request.urlopen(req, timeout=8) as r:
                for raw in r:
                    line = raw.decode(errors="replace").strip()
                    if line.startswith("data:"):
                        ev = json.loads(line[5:])
                        if ev.get("type") == "control":
                            seen.append(ev)
                            return
        except Exception:
            pass
    th = threading.Thread(target=listen, daemon=True); th.start()
    time.sleep(0.5)
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8733/api/inject", data=b'{"hex":"b9 18 14"}',
            headers={"content-type": "application/json"}), timeout=5)
    except Exception as e:
        raise SkipCheck(f"studio not running on :8733 ({e})")
    th.join(4)
    assert seen, "a BD LEVEL change was injected and never reached the stream"
    c = seen[0]["changes"][0]
    assert (c["instrument"], c["param"], c["value"]) == ("BD", "level", 20), c
    return "BD level 20 delivered"


@check("the playhead follows the clock")
def t_clock(d, st):
    snap = st.monitor.snapshot()
    if not snap.get("bpm"):
        raise SkipCheck("no clock is arriving")
    assert 20 < snap["bpm"] < 400, snap["bpm"]
    return f"{snap['bpm']:.1f} BPM"


# ---------------------------------------------------------------- the tools

@check("undo puts back what was overwritten")
def t_undo(d):
    from tr8s.history import HISTORY
    HISTORY.clear()
    before = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})
    tools.call("pattern.set_steps", {"slot": SCRATCH_PATTERN, "variation": "A",
                                     "instrument": "CC", "steps": "X" * 16})
    mid = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})
    assert mid["variations"]["A"]["CC"] == "X" * 16, "the write did not land"
    tools.call("history.undo", {})
    after = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})
    assert after["variations"] == before["variations"], "undo did not restore"
    return "restored"


@check("a fader colour writes and reads back")
def t_color(d):
    kit = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})["kit"]
    was = tools.call("kit.get", {"slot": kit})["instruments"]["RC"]["color"]
    want = (was + 5) % 12
    try:
        tools.call("kit.set_color", {"slot": kit, "colors": {"RC": want}})
        got = tools.call("kit.get", {"slot": kit})["instruments"]["RC"]["color"]
        assert got == want, f"wrote {want}, read {got}"
        return f"{was} -> {want}"
    finally:
        tools.call("kit.set_color", {"slot": kit, "colors": {"RC": was}})


@check("a pattern exports and imports unchanged")
def t_export(d):
    doc = tools.call("pattern.export", {"slot": SCRATCH_PATTERN,
                                        "ctrl_is_coarse_tune": True})
    tools.call("pattern.set_steps", {"slot": SCRATCH_PATTERN, "variation": "A",
                                     "instrument": "HT", "steps": "x" * 16})
    tools.call("pattern.import", {"slot": SCRATCH_PATTERN, "pattern": doc})
    back = tools.call("pattern.export", {"slot": SCRATCH_PATTERN,
                                         "ctrl_is_coarse_tune": True})
    for v in doc["variations"]:
        assert back["variations"][v]["tracks"] == doc["variations"][v]["tracks"], v
    assert back["name"] == doc["name"] and back["tempo"] == doc["tempo"]
    return f"{len(doc['variations'])} variations"


@check("a melody survives a round trip through the machine")
def t_melody(d):
    kit = tools.call("pattern.get", {"slot": SCRATCH_PATTERN})["kit"]
    k = tools.call("kit.get", {"slot": kit})["instruments"]
    melodic = [i for i, f in k.items() if f.get("melodic") and f.get("root")]
    if not melodic:
        raise SkipCheck("no instrument in this kit can carry a melody")
    inst = melodic[0]
    root = k[inst]["root"]
    notes = "C2 . D#2 . G2 . A#2 ."
    from tr8s.melody import note_to_midi
    # keep it inside Coarse Tune's reach from whatever this tone's root is
    shift = 0
    while abs(note_to_midi("C2") + shift - note_to_midi(root)) > 20:
        shift += 12
    r = tools.call("pattern.set_line", {
        "slot": SCRATCH_PATTERN, "variation": "H", "instrument": inst,
        "shape": "bass", "key": "C minor", "seed": 1})
    got = tools.call("pattern.get_melody", {
        "slot": SCRATCH_PATTERN, "variation": "H", "instrument": inst,
        "root": r["root"]})["melody"]
    written = [n for n in r["notes"].split() if n != "."]
    read = [n for n in got.split() if n != "."]
    assert read[:len(written)] == written, f"wrote {written[:4]}, read {read[:4]}"
    return f"{inst}: {len(written)} notes"


@check("a read and a write are as fast as they should be")
def t_speed(d):
    """A regression here is what makes the whole UI feel broken."""
    t0 = time.time()
    blob = d.transport.read_blob("pattern", SCRATCH_PATTERN)
    read = time.time() - t0
    t0 = time.time()
    d.transport.send_blob("pattern", SCRATCH_PATTERN, blob)
    write = time.time() - t0
    assert read < 2.5, f"a pattern read took {read:.2f}s"
    assert write < 1.5, f"a pattern write took {write:.2f}s"
    return f"read {read:.2f}s, write {write:.2f}s"


# ------------------------------------------------------------------- driver

def main():
    # Two readers on one MIDI node split the stream: this process would see
    # none of the machine's notes or clock while the studio holds the port,
    # and the listening checks would all "fail" for a reason that has nothing
    # to do with the machine. Refuse to start rather than report that.
    import subprocess
    held = subprocess.run(["fuser", "/dev/snd/midiC1D0"], capture_output=True,
                          text=True).stdout.split()
    others = [pid for pid in held if pid.strip() and int(pid) != __import__("os").getpid()]
    if others:
        print(f"the MIDI port is held by pid {', '.join(others)} (the studio?). "
              f"Stop it first: this test needs the port to itself.")
        return 2
    d = tools.device()
    st = Studio()
    d.transport.on_realtime = st.monitor.feed
    d.transport.on_channel = st.monitor.feed_channel
    st.connected = True

    print(f"scratch pattern: {slot_to_panel(SCRATCH_PATTERN)}", flush=True)
    saved = d.transport.read_blob("pattern", SCRATCH_PATTERN)
    if not saved:
        print("could not read the scratch slot; aborting rather than risk it")
        return 2

    try:
        print("\nwire:", flush=True)
        t_info(d)
        t_roundtrip(d)
        t_kit_reference(d)

        print("\ntools:", flush=True)
        t_undo(d)
        t_color(d)
        t_export(d)
        t_melody(d)
        t_speed(d)

        print("\ncalibration:", flush=True)
        t_tune(d)

        print("\nlistening:", flush=True)
        try:
            st.select(SCRATCH_PATTERN)
        except Exception:
            pass
        t_transport(d, st)
        t_notes(d, st)
        t_clock(d, st)
        t_controls(d, st)
        t_sse_control(d, st)
        t_search(d, st)
        t_variation(d, st)
    finally:
        print("\nputting the scratch slot back", flush=True)
        d.transport.send_blob("pattern", SCRATCH_PATTERN, saved)
        d.transport.commit("pattern", SCRATCH_PATTERN)
        try:
            tools.call("device.transport", {"action": "stop"})
        except Exception:
            pass

    print()
    for kind in ("fail", "skip", "pass"):
        n = len([r for r in RESULTS if r[0] == kind])
        if n:
            print(f"{kind}: {n}")
    return 1 if any(r[0] == "fail" for r in RESULTS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
