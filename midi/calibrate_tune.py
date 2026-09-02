#!/usr/bin/env python3
"""
Calibrate the TR-8S tune parameter against real pitch.

Rather than fighting sequencer alignment, this drives everything itself:
for each tune value it writes the kit to the edit buffer (no commit, so
nothing is saved), triggers the instrument over MIDI, and records. Notes are
spaced far enough apart that onset detection is trivial.

    python3 calibrate_tune.py [INSTRUMENT] [KIT_INDEX]

The sequencer must be STOPPED, or its hits will be picked up as extra onsets.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t   # noqa: E402
import tr8s_write as w   # noqa: E402
import tr8s_kit as k     # noqa: E402
import pitch as P        # noqa: E402

NOTE = {'BD': 36, 'RS': 37, 'SD': 38, 'HC': 39, 'CH': 42, 'LT': 43,
        'OH': 46, 'MT': 47, 'CC': 49, 'HT': 50, 'RC': 51}
CHAN = 9
GAP = 1.4                       # seconds between triggers
TUNES = [-96, -64, -32, 0, 32, 64, 96]
WAV = "/tmp/claude-1000/-home-svh/145ac41c-4596-41f5-b9b6-290f63582c68/scratchpad/caltrig.wav"


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else 'LT'
    kit_id = int(sys.argv[2]) if len(sys.argv) > 2 else 61

    base = k.load(kit_id)
    dur = GAP * (len(TUNES) + 1) + 2.0

    rec = subprocess.Popen(
        ["arecord", "-D", "hw:1,0", "-f", "FLOAT_LE", "-c", "2",
         "-r", "96000", "-d", str(int(dur)), WAV],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)                      # let the capture settle

    port = t.Port("/dev/snd/midiC1D0")
    try:
        for tune in TUNES:
            blob = bytearray(base)
            k.put(blob, inst, 'tune', tune)
            # no commit: this only touches the edit buffer
            w.send_blob(port, 'kit', kit_id, bytes(blob), verbose=False)
            time.sleep(0.25)
            n = NOTE[inst]
            port.send(bytes([0x90 | CHAN, n, 110]))
            time.sleep(0.05)
            port.send(bytes([0x80 | CHAN, n, 0]))
            print(f"  triggered {inst} at tune {tune:+4d}", flush=True)
            time.sleep(GAP - 0.30)
    finally:
        port.close()
    rec.wait()

    ch, rate, a = P.read_float_wav(WAV)
    mono = P.to_mono(ch, a)
    peak = max(abs(x) for x in mono)
    print(f"\nrecorded {len(mono)/rate:.1f}s, peak {peak:.4f}")
    if peak < 0.002:
        print("  too quiet -- is the instrument's level fader up?")
        return

    onsets = P.find_onsets(mono, rate, thresh_ratio=0.18, min_gap_s=0.5)
    print(f"  {len(onsets)} onsets (expected {len(TUNES)})")
    if len(onsets) != len(TUNES):
        print("  onset count mismatch -- is the sequencer stopped?")
        if len(onsets) < len(TUNES):
            return

    import math
    rows = []
    for tune, o in zip(TUNES, onsets):
        f = P.yin_pitch(mono, rate, o + int(0.02 * rate), dur=0.15,
                        fmin=25.0, fmax=500.0)
        rows.append((tune, f))
        print(f"  tune {tune:+4d} -> {f:8.2f} Hz  {P.note_name(f)}"
              if f else f"  tune {tune:+4d} -> no pitch")

    good = [(t_, f) for t_, f in rows if f]
    ref = dict(good).get(0)
    if not ref or len(good) < 4:
        print("\nnot enough clean measurements to fit")
        return
    pts = [(t_, 12 * math.log2(f / ref)) for t_, f in good if t_ != 0]
    num = sum(t_ * s for t_, s in pts)
    den = sum(t_ * t_ for t_, _ in pts)
    slope = num / den
    resid = max(abs(s - slope * t_) for t_, s in pts)
    print(f"\n  {slope:.5f} semitones per tune unit")
    print(f"  {1/slope:.2f} tune units per semitone" if slope else "")
    print(f"  full -128..+127 spans {255*slope:.1f} semitones "
          f"({255*slope/12:.2f} octaves)")
    print(f"  worst residual {resid:.2f} semitones "
          f"({'linear in pitch' if resid < 0.6 else 'NOT linear -- needs a curve'})")


if __name__ == "__main__":
    main()
