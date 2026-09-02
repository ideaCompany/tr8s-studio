#!/usr/bin/env python3
"""
Live acid-techno jam: mutate the playing pattern in place, no commit.

Each stage is transferred to the edit buffer, so the TR-8S changes what it is
playing on the next loop without anything being saved. Nothing on the machine
is modified permanently.

Requires: pattern 8-05 selected and playing, MOTION [ON] lit, and LT holding a
sample tone with Coarse Tune on its CTRL knob (kit 62).

    python3 jam.py [seconds_per_stage]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t      # noqa: E402
import tr8s_write as w      # noqa: E402
import tr8s_melody as M     # noqa: E402

SLOT = 116
ROOT = 'C3'
BASE = '/home/svh/tr8s/notes/ctrl_test_baseline.bin'

# (label, drum tracks, bassline)
STAGES = [
    ("just the kick",
     {'BD': "X...x...X...x..."},
     "C2 . . . . . . . C2 . . . . . . ."),

    ("bass wakes up",
     {'BD': "X...x...X...x..."},
     "C2 . . C2 . . C2 . C2 . . C2 . . D#2 ."),

    ("hats in",
     {'BD': "X...x...X...x...", 'CH': "..x...x...x...x."},
     "C2 . . C2 . . C2 . C2 . . C2 . . D#2 ."),

    ("16th hats, bass opens up",
     {'BD': "X...x...X...x...", 'CH': "x.x.x.x.x.x.x.x.", 'OH': "..x...x...x...x."},
     "C2 . G2 . C3 . G2 . C2 . G2 . D#3 . G2 ."),

    ("clap on the backbeat",
     {'BD': "X...x...X...x...", 'CH': "xoxoxoxoxoxoxoxo",
      'OH': "..x...x...x...x.", 'HC': "....X.......X..."},
     "C2 . G2 A#2 C3 . G2 . C2 . G2 A#2 D#3 . G2 ."),

    ("acid line",
     {'BD': "X...x...X...x...", 'CH': "xoxoxoxoxoxoxoxo",
      'OH': "..x...x...x...x.", 'HC': "....X.......X..."},
     "C2 C3 G2 A#2 C3 D#3 G2 C3 C2 C3 G2 A#2 D#3 G3 D#3 C3"),

    ("drop the kick, bass carries it",
     {'CH': "xoxoxoxoxoxoxoxo", 'OH': "..x...x...x...x.",
      'HC': "....X.......X..."},
     "C2 C3 G2 A#2 C3 D#3 G2 C3 C2 C3 G2 A#2 D#3 G3 D#3 C3"),

    ("everything, peak",
     {'BD': "X...X...X...X...", 'CH': "xoxoxoxoxoxoxoxo",
      'OH': "..x...x...x...x.", 'HC': "....X.......X...",
      'RS': "..o...o...o...o.", 'CC': "X..............."},
     "C2 C3 G2 A#2 C3 D#3 G3 C4 C2 C3 G2 A#2 D#3 G3 D#3 C3"),

    ("stripped, fade out",
     {'BD': "X...x...X...x...", 'RC': "..o...o...o...o."},
     "C2 . . . . . . . C2 . . . . . . ."),
]


def build(drums, bass):
    blob = bytearray(open(BASE, 'rb').read())
    blob[0:16] = b'LIVE JAM        '[:16]
    for blk in range(8):
        for tn in w.TRACKS:
            for k in range(16):
                blob[w.track_offset(blk, tn, k)] = 0
    blob, _ = M.write_coarse_melody(bytes(blob), 'LT', bass, ROOT, velocity=105)
    blob = bytearray(blob)
    for inst, pat in drums.items():
        for k, ch in enumerate(pat[:16]):
            if ch in ('X', 'x', 'o'):
                blob[w.track_offset(0, inst, k)] = {'X': 112, 'x': 100, 'o': 55}[ch]
    return bytes(blob)


def main():
    dwell = float(sys.argv[1]) if len(sys.argv) > 1 else 7.0
    port = t.Port("/dev/snd/midiC1D0")
    print(f"{len(STAGES)} stages, {dwell:.0f}s each "
          f"(~{len(STAGES)*dwell/60:.1f} min). Nothing is committed.\n")
    try:
        for i, (label, drums, bass) in enumerate(STAGES, 1):
            blob = build(drums, bass)
            w.send_blob(port, 'pattern', SLOT, blob, verbose=False)  # no commit
            print(f"  [{i}/{len(STAGES)}] {label}", flush=True)
            time.sleep(dwell)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        port.close()
    print("\ndone -- nothing was saved; the stored pattern is untouched")


if __name__ == "__main__":
    main()
