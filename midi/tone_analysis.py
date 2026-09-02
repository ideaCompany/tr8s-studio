#!/usr/bin/env python3
"""
Measure every melodic tone on the TR-8S and write a catalogue.

Picking tones by name is guesswork: "Deep SH Bass" says nothing about what note
it sounds at, how loud it is, or how long it rings. This assigns each tone to a
scratch kit, triggers it over MIDI, records the TR-8S's own USB audio output,
and extracts:

    root      the fundamental it actually sounds at -- THE important one.
              Coarse Tune is relative to this, so without it every melody is
              transposed by an unknown amount and instruments disagree.
    peak/rms  loudness, for balancing a kit
    decay_ms  time to fall 20 dB below peak: stab vs pad vs drone
    centroid  spectral centre of mass in Hz -- brightness, for avoiding clashes

Output: tones.json, keyed by tone id.

Runs unattended. Restores the scratch kit when finished, including on Ctrl-C.
"""

import json
import math
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t   # noqa: E402
import tr8s_write as w   # noqa: E402
import tr8s_kit as k     # noqa: E402

SCRATCH_KIT = 123          # panel 124, an empty "----" slot
PROBE_INST = 'LT'
NOTE = 43                  # LT
CHAN = 9
DONOR_KIT, DONOR_INST = 61, 'LT'    # a working SAMPLE instrument, read from DEVICE
GAP = 2.6                  # per tone: kit write + commit + trigger + tail
BATCH = 12                 # tones per continuous recording
OUT = "/home/svh/tr8s/tones.json"
TMP = "/tmp/claude-1000/-home-svh/145ac41c-4596-41f5-b9b6-290f63582c68/scratchpad"

CATS = ['IMPORT', 'BD', 'SD', 'TOM', 'RS', 'HC', 'CH/OH', 'CC/RC', 'PERC1',
        'PERC2', 'PERC3', 'PERC4', 'PERC5', 'FX/HIT', 'VOICE', 'SYNTH1',
        'SYNTH2', 'BASS', 'SCALED', 'CHORD', 'OTHERS']
MELODIC = {'SYNTH1', 'SYNTH2', 'BASS', 'SCALED', 'CHORD'}
# melodic tones live in this span; scanning all 1024 wastes minutes
SCAN_LO, SCAN_HI = 120, 540
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


# ------------------------------------------------------------------ audio

def read_float_wav(path):
    d = open(path, 'rb').read()
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(d):
        cid = d[pos:pos + 4]
        sz = struct.unpack('<I', d[pos + 4:pos + 8])[0]
        if cid == b'fmt ':
            fmt = struct.unpack('<HHIIHH', d[pos + 8:pos + 8 + 16])
        elif cid == b'data':
            data = d[pos + 8:pos + 8 + sz]
            break
        pos += 8 + sz + (sz & 1)
    import array
    a = array.array('f')
    a.frombytes(data[:len(data) // 4 * 4])
    return fmt[1], fmt[2], a


def mono_decimate(a, ch, factor):
    """Interleaved float frames -> mono, decimated, in one pass."""
    out = []
    n = len(a) // ch
    acc = 0.0
    cnt = 0
    for f in range(n):
        s = 0.0
        base = f * ch
        for c in range(ch):
            s += a[base + c]
        acc += s / ch
        cnt += 1
        if cnt == factor:
            out.append(acc / factor)
            acc = 0.0
            cnt = 0
    return out


def yin(seg, rate, fmin=30.0, fmax=2000.0, thresh=0.15):
    if len(seg) < 256:
        return None
    m = sum(seg) / len(seg)
    seg = [x - m for x in seg]
    if sum(x * x for x in seg) < 1e-10:
        return None
    lo = max(2, int(rate / fmax))
    hi = min(len(seg) // 2, int(rate / fmin))
    if hi <= lo:
        return None
    d = [0.0] * (hi + 1)
    for lag in range(lo, hi + 1):
        s = 0.0
        for i in range(0, len(seg) - lag, 2):
            df = seg[i] - seg[i + lag]
            s += df * df
        d[lag] = s
    cm = [1.0] * (hi + 1)
    run = 0.0
    for lag in range(lo, hi + 1):
        run += d[lag]
        cm[lag] = d[lag] * (lag - lo + 1) / run if run > 0 else 1.0
    best = None
    for lag in range(lo + 1, hi):
        if cm[lag] < thresh and cm[lag] <= cm[lag - 1] and cm[lag] <= cm[lag + 1]:
            best = lag
            break
    if best is None:
        best = min(range(lo, hi + 1), key=lambda L: cm[L])
        if cm[best] > 0.55:
            return None
    if lo < best < hi:
        x, y, z = cm[best - 1], cm[best], cm[best + 1]
        den = 2 * (x - 2 * y + z)
        if den:
            best = best + (x - z) / den
    return rate / best


def fft(x):
    """Iterative radix-2 FFT; x is zero-padded to a power of two."""
    n = len(x)
    j = 0
    x = list(x)
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            x[i], x[j] = x[j], x[i]
    ln = 2
    while ln <= n:
        ang = -2 * math.pi / ln
        wl = complex(math.cos(ang), math.sin(ang))
        for i in range(0, n, ln):
            wv = complex(1)
            for m in range(ln // 2):
                u = x[i + m]
                v = x[i + m + ln // 2] * wv
                x[i + m] = u + v
                x[i + m + ln // 2] = u - v
                wv *= wl
        ln <<= 1
    return x


def centroid(seg, rate, n=2048):
    seg = seg[:n]
    if len(seg) < 64:
        return None
    seg = seg + [0.0] * (n - len(seg))
    win = [seg[i] * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)))
           for i in range(n)]
    spec = fft([complex(v) for v in win])
    half = n // 2
    num = den = 0.0
    for i in range(1, half):
        mag = abs(spec[i])
        num += mag * (i * rate / n)
        den += mag
    return num / den if den else None


def note_of(freq):
    if not freq or freq <= 0:
        return None
    m = 12 * math.log2(freq / 440.0) + 69
    i = int(round(m))
    return f"{NAMES[i % 12]}{i // 12 - 1}", round((m - i) * 100)


def analyse(seg, rate):
    if not seg:
        return {}
    peak = max(abs(x) for x in seg)
    if peak < 0.002:
        return {'peak': round(peak, 5), 'silent': True}
    rms = (sum(x * x for x in seg) / len(seg)) ** 0.5
    # decay: time to fall 20 dB below peak
    win = max(1, int(0.005 * rate))
    env = []
    for i in range(0, len(seg) - win, win):
        env.append(max(abs(x) for x in seg[i:i + win]))
    target = peak * 0.1
    decay_ms = None
    sustained = False
    pk_i = env.index(max(env))
    for i in range(pk_i, len(env)):
        if env[i] < target:
            decay_ms = round((i - pk_i) * win / rate * 1000)
            break
    else:
        sustained = True    # never fell 20 dB inside the measured window
    f = yin(seg[int(0.02 * rate):int(0.20 * rate)], rate)
    out = {'peak': round(peak, 5), 'rms': round(rms, 5), 'decay_ms': decay_ms,
           'sustained': sustained, 'centroid': round(centroid(seg, rate) or 0)}
    if f:
        nm, cents = note_of(f)
        out.update(hz=round(f, 2), root=nm, cents=cents)
    return out


# ------------------------------------------------------------------ device

def tone_meta(port, tid):
    b = t.read_blob(port, 'tone', tid, timeout=6, verbose=False)
    if not b or len(b) < 18:
        return None
    nm = ''.join(chr(c) for c in b[:16] if 32 <= c < 127).rstrip()
    if not nm:
        return None
    return {'id': tid, 'name': nm,
            'cat': CATS[b[16]] if b[16] < len(CATS) else str(b[16]),
            'type': b[17]}


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    port = t.Port("/dev/snd/midiC1D0")
    original = t.read_blob(port, 'kit', SCRATCH_KIT, timeout=20, verbose=False)
    donor = t.read_blob(port, 'kit', DONOR_KIT, timeout=20, verbose=False)
    dsrc = k.rec(k.TRACKS.index(DONOR_INST))
    if not donor or not any(donor[dsrc + 28:dsrc + 42]):
        port.close()
        sys.exit(f"donor kit {DONOR_KIT+1}/{DONOR_INST} has empty sample "
                 f"parameters -- probes would be silent")

    print("enumerating tones...", flush=True)
    tones = []
    for tid in range(SCAN_LO, SCAN_HI):
        m = tone_meta(port, tid)
        if not m:
            continue
        if m['cat'] not in MELODIC or m['type'] != 2:
            continue
        if only and m['cat'] != only:
            continue
        tones.append(m)
    if limit:
        tones = tones[:limit]
    print(f"{len(tones)} melodic sample tones to measure "
          f"(~{len(tones)*GAP/60:.1f} min)\n", flush=True)

    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT))

    pi = k.TRACKS.index(PROBE_INST)
    pbase = k.rec(pi)
    try:
        for start in range(0, len(tones), BATCH):
            group = tones[start:start + BATCH]
            wav = os.path.join(TMP, "tone_batch.wav")
            dur = int(GAP * len(group) + 6)
            rec = subprocess.Popen(
                ["arecord", "-D", "hw:1,0", "-f", "FLOAT_LE", "-c", "2",
                 "-r", "96000", "-d", str(dur), wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            t0 = time.time()
            marks = []
            for gi, m in enumerate(group):
                blob = bytearray(original)
                blob[pbase:pbase + 52] = donor[dsrc:dsrc + 52]
                k.put(blob, PROBE_INST, 'tone', m['id'])
                k.put(blob, PROBE_INST, 'tune', 0)
                k.put(blob, PROBE_INST, 'decay', 255)
                k.put(blob, PROBE_INST, 'pan', 0)
                k.put(blob, PROBE_INST, 'reverb', 0)
                k.put(blob, PROBE_INST, 'delay', 0)
                w.send_blob(port, 'kit', SCRATCH_KIT, bytes(blob), verbose=False)
                w.commit(port, 'kit', SCRATCH_KIT, verbose=False)
                # fire on an absolute schedule so slow writes cannot drift the
                # trigger out of the recording window
                due = gi * GAP + 1.0
                slack = due - (time.time() - t0)
                if slack > 0:
                    time.sleep(slack)
                marks.append(time.time() - t0)
                port.send(bytes([0x90 | CHAN, NOTE, 120]))
                time.sleep(0.05)
                port.send(bytes([0x80 | CHAN, NOTE, 0]))
            rec.wait()

            ch, rate, a = read_float_wav(wav)
            F = 8
            mono = mono_decimate(a, ch, F)
            r = rate / F
            for m, mark in zip(group, marks):
                s = int((mark + 1.5 + 0.01) * r)
                seg = mono[s:s + int(0.9 * r)]
                res = dict(m)
                res.update(analyse(seg, r))
                results[str(m['id'])] = res
                json.dump(results, open(OUT, 'w'), indent=1, sort_keys=True)
                print(f"  {m['id']:4d} {m['cat']:<7s} {m['name']:<18s} "
                      f"root={res.get('root','-'):>5s} "
                      f"{res.get('hz',0):7.1f}Hz peak={res.get('peak',0):.3f} "
                      f"decay={('sust' if res.get('sustained') else str(res.get('decay_ms'))):>5s} "
                      f"bright={res.get('centroid',0):5d}Hz", flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        w.send_blob(port, 'kit', SCRATCH_KIT, bytes(original), verbose=False)
        w.commit(port, 'kit', SCRATCH_KIT, verbose=False)
        port.close()
        print(f"\nscratch kit {SCRATCH_KIT+1} restored; "
              f"{len(results)} tones catalogued -> {OUT}")


if __name__ == "__main__":
    main()
