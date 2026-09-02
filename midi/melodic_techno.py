#!/usr/bin/env python3
"""
Build a melodic techno kit and an eight-section track, from scratch.

Kit  -> slot index 122 (panel 123), an empty "----" slot
Track-> slot index 118 (panel 8-07), 126 BPM, C minor

All eleven instruments are used:

    BD  909 Low Bass        deep techno kick
    SD  909 Snare2          builds and fills
    LT  OSC Saw Low         MELODIC LEAD -- Coarse Tune motion, four octaves
    MT  Deep SH Bass        bassline -- fine Tune motion, +/-5 semitones
    HT  SoftPad minor7th    sustained pad
    RS  909 Rim             offbeat percussion, panned left
    HC  909 Clap            backbeat
    CH  909 Closed Hat      panned slightly right
    OH  909 Open Hat        offbeat, panned slightly left
    CC  Atmosphere          breakdown swell, long, drenched in reverb
    RC  909 Ride            panned right
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t      # noqa: E402
import tr8s_write as w      # noqa: E402
import tr8s_kit as k        # noqa: E402
import tr8s_melody as M     # noqa: E402

KIT_SLOT = 122        # panel 123
PAT_SLOT = 118        # panel 8-07
BPM = 126
ROOT = 'C3'           # LT's reference pitch for Coarse Tune
VEL = {'X': 112, 'x': 100, 'o': 55}

# tone, tune, decay, pan, reverb, delay
KIT = {
    'BD': dict(tone=29,  tune=-12, decay=205, pan=0,   reverb=110, delay=100),
    'SD': dict(tone=31,  tune=-6,  decay=130, pan=0,   reverb=150, delay=120),
    'LT': dict(tone=465, tune=0,   decay=150, pan=18,  reverb=140, delay=205),
    'MT': dict(tone=486, tune=-40, decay=185, pan=0,   reverb=95,  delay=110),
    'HT': dict(tone=516, tune=-8,  decay=255, pan=0,   reverb=225, delay=180),
    'RS': dict(tone=36,  tune=10,  decay=100, pan=-48, reverb=130, delay=165),
    'HC': dict(tone=37,  tune=0,   decay=140, pan=8,   reverb=175, delay=140),
    'CH': dict(tone=38,  tune=6,   decay=70,  pan=22,  reverb=100, delay=105),
    'OH': dict(tone=39,  tune=4,   decay=125, pan=-22, reverb=145, delay=150),
    'CC': dict(tone=514, tune=-4,  decay=255, pan=0,   reverb=245, delay=200),
    'RC': dict(tone=41,  tune=8,   decay=115, pan=40,  reverb=150, delay=130),
}

# (name, drums, LT lead (coarse, 4 octaves), MT bass in semitones or '.')
SECTIONS = [
 ("A_intro",
  {'BD': "X...x...X...x...", 'CH': "..x...x...x...x.", 'HT': "X..............."},
  ". . . . . . . . . . . . . . . .",
  "0 . . . . . . . 0 . . . . . . ."),

 ("B_groove",
  {'BD': "X...x...X...x...", 'CH': "x.x.x.x.x.x.x.x.", 'OH': "..x...x...x...x.",
   'HT': "X..............."},
  ". . . . . . . . . . . . . . . .",
  "0 . . 0 . . -5 . 0 . . 0 . . -5 ."),

 ("C_melody",
  {'BD': "X...x...X...x...", 'CH': "x.x.x.x.x.x.x.x.", 'OH': "..x...x...x...x.",
   'RS': "..o...o...o...o.", 'HT': "X..............."},
  "C3 . D#3 . G3 . D#3 . F3 . D#3 . C3 . . .",
  "0 . . 0 . . -5 . 0 . . 0 . . -5 ."),

 ("D_full",
  {'BD': "X...x...X...x...", 'CH': "xoxoxoxoxoxoxoxo", 'OH': "..x...x...x...x.",
   'HC': "....X.......X...", 'RS': "..o...o...o...o.", 'RC': "x...x...x...x...",
   'HT': "X.......X......."},
  "C3 . D#3 G3 . A#3 G3 . F3 . D#3 . C3 . D3 .",
  "0 . . 0 . . -5 . 0 . . 0 . . -5 ."),

 ("E_break",
  {'CH': "..o...o...o...o.", 'HT': "X.......X.......", 'CC': "X...............",
   'RC': "x.......x......."},
  "G3 . . D#3 . . C3 . . A#2 . . C3 . . .",
  ". . . . . . . . . . . . . . . ."),

 ("F_build",
  {'BD': "X...x...X...x...", 'CH': "xoxoxoxoxoxoxoxo", 'OH': "..x...x...x...x.",
   'SD': "....o...o.o.o.oo", 'HT': "X.......X......."},
  "C3 D#3 G3 A#3 C4 A#3 G3 D#3 C3 D#3 G3 A#3 C4 D#4 G4 A#4",
  "0 . . 0 . . -5 . 0 . . 0 . . -5 ."),

 ("G_peak",
  {'BD': "X...X...X...X...", 'CH': "xoxoxoxoxoxoxoxo", 'OH': "..x...x...x...x.",
   'HC': "....X.......X...", 'RS': "..o.o...o.o.o...", 'RC': "x.x.x.x.x.x.x.x.",
   'CC': "X...............", 'HT': "X.......X......."},
  "C4 G3 D#4 G3 C4 A#3 G3 D#3 C4 G3 D#4 A#3 C4 D#4 G4 D#4",
  "0 . 0 . . 0 -5 . 0 . 0 . . 0 -5 ."),

 ("H_outro",
  {'BD': "X...x...X...x...", 'CH': "..x...x...x...x.", 'HT': "X.......X.......",
   'RC': "..o...o...o...o."},
  "C3 . . . D#3 . . . G3 . . . D#3 . . .",
  "0 . . . . . . . 0 . . . . . . ."),
]


# Instruments taking a SAMPLE tone must inherit a record that already has the
# sample parameter bytes (+28..+41: envelope, gain at +37, etc). The empty
# "----" slot has them all at ZERO, which makes a sample tone play almost
# silently -- it holds ACB defaults, and those bytes only exist for samples.
SAMPLE_INSTS = {'LT', 'MT', 'HT', 'CC'}
SAMPLE_DONOR_KIT, SAMPLE_DONOR_INST = 61, 'LT'   # known-good sample instrument
DRUM_DONOR_KIT = 1                               # TR-909, a complete real kit


def build_kit(port):
    # Donors MUST be read from the DEVICE, not from backups/. The backups are
    # the pristine factory state, where the donor instrument still holds an ACB
    # tone and the sample parameter bytes are all zero -- the exact record that
    # causes the silent-sample bug.
    blob = bytearray(t.read_blob(port, 'kit', DRUM_DONOR_KIT, timeout=20, verbose=False))
    donor = t.read_blob(port, 'kit', SAMPLE_DONOR_KIT, timeout=20, verbose=False)
    if not blob or not donor:
        raise SystemExit("could not read donor kits from the device")
    dsrc0 = k.rec(k.TRACKS.index(SAMPLE_DONOR_INST))
    if not any(donor[dsrc0 + 28:dsrc0 + 42]):
        raise SystemExit(
            f"donor kit {SAMPLE_DONOR_KIT+1} inst {SAMPLE_DONOR_INST} has empty "
            f"sample parameters (+28..+41) -- it is not a working sample "
            f"instrument, so copying it would produce silent tones")
    dsrc = dsrc0
    for inst in SAMPLE_INSTS:
        d = k.rec(k.TRACKS.index(inst))
        blob[d:d + 52] = donor[dsrc:dsrc + 52]   # inherit sample parameters
    k.set_name(blob, "MELODIC TECHNO")
    for inst, p in KIT.items():
        k.put(blob, inst, 'tone', p['tone'])
        k.put(blob, inst, 'tune', p['tune'])
        k.put(blob, inst, 'decay', p['decay'])
        k.put(blob, inst, 'pan', p['pan'])
        k.put(blob, inst, 'reverb', p['reverb'])
        k.put(blob, inst, 'delay', p['delay'])
    return bytes(blob)


def build_pattern():
    blob = bytearray(open(
        '/home/svh/tr8s/backups/patterns/pattern_116.bin', 'rb').read())
    blob[0:16] = b'MELODIC TECHNO  '[:16]
    bpm10 = BPM * 10
    blob[16] = bpm10 & 0xFF
    blob[17] = (bpm10 >> 8) & 0xFF
    blob[18] = KIT_SLOT + 1          # kit reference is 1-based
    blob[19] = 2                     # 16th scale
    blob[32] = 128                   # straight
    for blk in range(8):
        for tn in w.TRACKS:
            for kk in range(16):
                blob[w.track_offset(blk, tn, kk)] = 0

    warnings = []
    for blk, (name, drums, lead, bass) in enumerate(SECTIONS):
        # LT lead: Coarse Tune motion, four octaves
        b, warn = M.write_coarse_melody(bytes(blob), 'LT', lead, ROOT,
                                        blk=blk, velocity=104)
        warnings += [f"{name}: {x}" for x in warn]
        blob = bytearray(b)
        # MT bass: fine Tune motion, +/-5 semitones is all it can reach
        lane = M.tune_lane('MT')
        for step, tok in enumerate(bass.split()):
            if tok == '.':
                continue
            semis = int(tok)
            units = int(round(semis * M.UNITS_PER_SEMITONE))
            if abs(units) > 127:
                warnings.append(f"{name}: bass {semis:+d} st out of fine-tune range")
                units = max(-128, min(127, units))
            blob[w.track_offset(blk, 'MT', step)] = 106
            off = M.lane_offset(blk, lane, step)
            blob[off] = (units + 128) & 0xFF
            blob[off + 3] = M.MASK_TUNE
        for inst, pat in drums.items():
            for step, ch in enumerate(pat[:16]):
                if ch in VEL:
                    blob[w.track_offset(blk, inst, step)] = VEL[ch]
    return bytes(blob), warnings


def main():
    pat, warnings = build_pattern()
    for x in warnings:
        print("  WARNING:", x)
    port = t.Port("/dev/snd/midiC1D0")
    try:
        kit = build_kit(port)
        w.send_blob(port, 'kit', KIT_SLOT, kit, verbose=False)
        w.commit(port, 'kit', KIT_SLOT, verbose=False)     # kits need commit
        time.sleep(0.4)
        kb = t.read_blob(port, 'kit', KIT_SLOT, timeout=20, verbose=False)
        a, b = bytearray(kb), bytearray(kit)
        for i in range(11):
            a[k.rec(i) + 4] = b[k.rec(i) + 4] = 0          # level is the fader
        print(f"kit  -> panel {KIT_SLOT+1:3d} 'MELODIC TECHNO'  "
              f"{'verified' if a == b else 'MISMATCH'}")

        w.send_blob(port, 'pattern', PAT_SLOT, pat, verbose=False)
        w.commit(port, 'pattern', PAT_SLOT, verbose=False)
        time.sleep(0.4)
        pb = t.read_blob(port, 'pattern', PAT_SLOT, timeout=20, verbose=False)
        print(f"track-> panel 8-{PAT_SLOT%16+1:02d} @ {BPM} BPM  "
              f"{'byte-exact' if pb == pat else 'MISMATCH'}")
        print()
        print(k.describe(bytearray(kb)))
        print()
        for blk, (name, _, _, _) in enumerate(SECTIONS):
            print(f"  [{chr(65+blk)}] {name:<9s} "
                  f"{M.read_coarse_melody(pb, 'LT', ROOT, blk=blk)}")
    finally:
        port.close()


if __name__ == "__main__":
    main()
