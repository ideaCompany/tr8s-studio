#!/usr/bin/env python3
"""
Send TR-8S patterns in lock-step with the TR-8S's own MIDI clock.

The TR-8S stays the tempo master. This script listens to its MIDI clock
(24 pulses per quarter note), counts every 6th pulse as one 16th-note step,
and fires the notes for that step. Notes therefore land exactly on the
sequencer grid, so INST REC captures them cleanly with no drift.

    probe            - watch the port and report what the TR-8S transmits
    play GENRE VAR   - play one variation once, synced (e.g. play techno B_main)
    list             - list available genres/variations

Typical use, per variation:
    1. On the TR-8S: select the pattern slot and variation, press [INST REC]
    2. Run:  python3 tr8s_send.py play techno B_main
    3. Press [START/STOP] on the TR-8S -- the script is already waiting
    4. It stops itself after exactly one pass
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_patterns import LIBRARY, DEFAULT_NOTE_MAP, VEL, MIDI_CHANNEL  # noqa: E402

DEVICE = "/dev/snd/midiC1D0"

CLOCK = 0xF8
START = 0xFA
CONT = 0xFB
STOP = 0xFC

PULSES_PER_STEP = 6  # 24 ppqn / 4 sixteenths per quarter


def open_port():
    try:
        fd = os.open(DEVICE, os.O_RDWR)
    except PermissionError:
        sys.exit(f"no permission on {DEVICE} -- are you in the 'audio' group?")
    except FileNotFoundError:
        sys.exit(f"{DEVICE} not found -- is the TR-8S connected and powered on?")
    return fd


def probe(seconds=20):
    fd = open_port()
    os.set_blocking(fd, False)
    print(f"listening on {DEVICE} for {seconds}s -- press START/STOP on the TR-8S")
    seen = {}
    clocks = 0
    t0 = time.time()
    first_clock = None
    while time.time() - t0 < seconds:
        try:
            data = os.read(fd, 256)
        except BlockingIOError:
            time.sleep(0.001)
            continue
        for b in data:
            if b == CLOCK:
                clocks += 1
                if first_clock is None:
                    first_clock = time.time()
            elif b >= 0xF8:
                seen[b] = seen.get(b, 0) + 1
                print(f"  realtime byte 0x{b:02X} "
                      f"({ {0xFA:'START', 0xFB:'CONTINUE', 0xFC:'STOP'}.get(b,'?') })")
    os.close(fd)
    print(f"\nclock pulses received: {clocks}")
    if clocks and first_clock:
        elapsed = time.time() - first_clock
        bpm = (clocks / 24.0) / (elapsed / 60.0)
        print(f"implied tempo: ~{bpm:.1f} BPM")
        print("TR-8S IS transmitting MIDI clock -- sync will work.")
    else:
        print("No clock received. Enable clock transmission on the TR-8S,")
        print("or we fall back to free-running playback.")


def collect_steps(tracks, note_map):
    """step index -> list of (note, velocity)"""
    length = max(len(s) for s in tracks.values())
    steps = {i: [] for i in range(length)}
    for inst, pattern in tracks.items():
        note = note_map[inst]
        for i, ch in enumerate(pattern):
            if ch in VEL:
                steps[i].append((note, VEL[ch]))
    return steps, length


def play(genre, varname, passes=1):
    if genre not in LIBRARY:
        sys.exit(f"unknown genre {genre!r}; try: {', '.join(LIBRARY)}")
    spec = LIBRARY[genre]
    match = [t for n, t in spec["patterns"] if n == varname or n.endswith(varname)]
    if not match:
        names = ", ".join(n for n, _ in spec["patterns"])
        sys.exit(f"unknown variation {varname!r}; try: {names}")
    steps, length = collect_steps(match[0], DEFAULT_NOTE_MAP)

    fd = open_port()
    os.set_blocking(fd, False)
    print(f"{genre}/{varname}: {length} steps, {passes} pass(es)")
    print("waiting for START from the TR-8S... (press [START/STOP])")

    running = False
    pulse = 0
    step_no = 0
    total_steps = length * passes
    pending = []

    try:
        while True:
            try:
                data = os.read(fd, 256)
            except BlockingIOError:
                time.sleep(0.0005)
                continue

            for b in data:
                if b == START or b == CONT:
                    running = True
                    pulse = 0
                    step_no = 0
                    print("START received -- recording")
                    # fire step 0 immediately
                    fire(fd, steps, 0, pending)
                    step_no = 1
                elif b == STOP:
                    if running:
                        print("STOP received")
                        all_off(fd, pending)
                        os.close(fd)
                        return
                elif b == CLOCK and running:
                    pulse += 1
                    if pulse % PULSES_PER_STEP == 0:
                        if step_no >= total_steps:
                            all_off(fd, pending)
                            print(f"done -- {total_steps} steps sent")
                            os.close(fd)
                            return
                        fire(fd, steps, step_no % length, pending)
                        step_no += 1
    except KeyboardInterrupt:
        all_off(fd, pending)
        os.close(fd)
        print("\ninterrupted")


def session(genre, varnames=None):
    """
    Play several variations back to back, one per START.

    The script advances to the next variation each time the TR-8S sends a
    fresh MIDI Start, so the operator just repeats:
        [START/STOP] to stop -> press the next variation button -> [START/STOP]
    No interaction with this script is needed between takes.
    """
    if genre not in LIBRARY:
        sys.exit(f"unknown genre {genre!r}; try: {', '.join(LIBRARY)}")
    spec = LIBRARY[genre]
    allnames = [n for n, _ in spec["patterns"]]
    if varnames:
        missing = [v for v in varnames if v not in allnames]
        if missing:
            sys.exit(f"unknown variation(s): {', '.join(missing)}")
        names = varnames
    else:
        names = allnames

    bypat = dict(spec["patterns"])
    fd = open_port()
    os.set_blocking(fd, False)

    print(f"=== {genre} @ {spec['bpm']} BPM -- {len(names)} takes ===")
    for i, n in enumerate(names, 1):
        print(f"  {i}. variation [{n[0]}]  {n}")
    print("\nFor each take: stop the sequencer, press the variation button,")
    print("then press [START/STOP]. This script follows along.\n")

    try:
        for i, name in enumerate(names, 1):
            steps, length = collect_steps(bypat[name], DEFAULT_NOTE_MAP)
            print(f"[{i}/{len(names)}] waiting for START -> [{name[0]}] {name} "
                  f"({length} steps)", flush=True)
            pending = []
            running = False
            pulse = 0
            step_no = 0
            done = False
            while not done:
                try:
                    data = os.read(fd, 256)
                except BlockingIOError:
                    time.sleep(0.0005)
                    continue
                for b in data:
                    if b in (START, CONT) and not running:
                        running = True
                        pulse = 0
                        fire(fd, steps, 0, pending)
                        step_no = 1
                    elif b == CLOCK and running:
                        pulse += 1
                        if pulse % PULSES_PER_STEP == 0:
                            if step_no >= length:
                                all_off(fd, pending)
                                done = True
                                break
                            fire(fd, steps, step_no % length, pending)
                            step_no += 1
                    elif b == STOP and running:
                        all_off(fd, pending)
                        print(f"     stopped early at step {step_no}/{length}")
                        done = True
                        break
            print(f"     recorded {name}", flush=True)
        print("\nall takes sent -- stop the sequencer and WRITE the pattern")
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        os.close(fd)


def fire(fd, steps, idx, pending):
    # release anything from the previous step
    all_off(fd, pending)
    msg = bytearray()
    for note, vel in steps.get(idx, []):
        msg += bytes([0x90 | MIDI_CHANNEL, note, vel])
        pending.append(note)
    if msg:
        os.write(fd, msg)


def all_off(fd, pending):
    if not pending:
        return
    msg = bytearray()
    for note in pending:
        msg += bytes([0x80 | MIDI_CHANNEL, note, 0])
    os.write(fd, msg)
    pending.clear()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "probe":
        probe(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif cmd == "list":
        for g, spec in LIBRARY.items():
            print(f"{g} (bpm {spec['bpm']}):")
            for n, _ in spec["patterns"]:
                print(f"    {n}")
    elif cmd == "play":
        if len(sys.argv) < 4:
            sys.exit("usage: tr8s_send.py play GENRE VARIATION")
        play(sys.argv[2], sys.argv[3],
             int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    elif cmd == "session":
        if len(sys.argv) < 3:
            sys.exit("usage: tr8s_send.py session GENRE [VAR,VAR,...]")
        vars_ = sys.argv[3].split(",") if len(sys.argv) > 3 else None
        session(sys.argv[2], vars_)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
