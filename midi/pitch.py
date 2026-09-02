#!/usr/bin/env python3
"""
Measure the pitch of each hit in a TR-8S recording.

The TR-8S streams its audio back over USB (card 1, FLOAT_LE, 96 kHz), so the
tune scale can be calibrated by ear-free measurement: write known tune values
into a motion lane, record the pattern, and read the frequencies back.

Pitch detection is autocorrelation over a window just after each onset --
no numpy needed, and drum tones are strongly periodic at their fundamental.

    python3 pitch.py capture.wav [expected_hits]
"""

import array
import struct
import sys


def read_float_wav(path):
    d = open(path, 'rb').read()
    if d[:4] != b'RIFF' or d[8:12] != b'WAVE':
        raise SystemExit("not a RIFF/WAVE file")
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(d):
        cid = d[pos:pos + 4]
        sz = struct.unpack('<I', d[pos + 4:pos + 8])[0]
        body = d[pos + 8:pos + 8 + sz]
        if cid == b'fmt ':
            fmt = struct.unpack('<HHIIHH', body[:16])
        elif cid == b'data':
            data = body
        pos += 8 + sz + (sz & 1)
    if fmt is None or data is None:
        raise SystemExit("missing fmt or data chunk")
    _, ch, rate, _, _, _ = fmt
    a = array.array('f')
    a.frombytes(data[:len(data) // 4 * 4])
    return ch, rate, a


def to_mono(ch, samples):
    if ch == 1:
        return list(samples)
    return [sum(samples[i:i + ch]) / ch for i in range(0, len(samples) - ch + 1, ch)]


def envelope(mono, win):
    """Coarse RMS envelope, one value per `win` samples."""
    out = []
    for i in range(0, len(mono) - win, win):
        s = 0.0
        for j in range(i, i + win, 4):        # decimate; plenty for onsets
            s += mono[j] * mono[j]
        out.append((s / (win / 4)) ** 0.5)
    return out


def find_onsets(mono, rate, thresh_ratio=0.25, min_gap_s=0.05):
    win = 256
    env = envelope(mono, win)
    if not env:
        return []
    peak = max(env)
    if peak <= 0:
        return []
    thresh = peak * thresh_ratio
    onsets = []
    min_gap = int(min_gap_s * rate / win)
    last = -10**9
    for i in range(1, len(env)):
        if env[i] > thresh and env[i - 1] <= thresh and i - last > min_gap:
            onsets.append(i * win)
            last = i
    return onsets


def decimate(mono, factor):
    """Cheap low-pass by averaging, then downsample. Plenty for fundamentals."""
    out = []
    for i in range(0, len(mono) - factor, factor):
        out.append(sum(mono[i:i + factor]) / factor)
    return out


def yin_pitch(mono, rate, start, dur=0.12, fmin=40.0, fmax=900.0, thresh=0.15):
    """
    Cumulative-mean normalised difference (the core of YIN).

    Plain autocorrelation peaks at the smallest lag and reports nonsense;
    the normalised difference function removes that bias.
    """
    seg = mono[start:start + int(dur * rate)]
    if len(seg) < 512:
        return None
    factor = 8
    seg = decimate(seg, factor)
    r = rate / factor
    m = sum(seg) / len(seg)
    seg = [x - m for x in seg]
    if sum(x * x for x in seg) < 1e-9:
        return None

    lo = max(2, int(r / fmax))
    hi = min(len(seg) // 2, int(r / fmin))
    if hi <= lo:
        return None

    d = [0.0] * (hi + 1)
    for lag in range(lo, hi + 1):
        s = 0.0
        for i in range(len(seg) - lag):
            diff = seg[i] - seg[i + lag]
            s += diff * diff
        d[lag] = s

    # cumulative mean normalisation
    cmnd = [1.0] * (hi + 1)
    running = 0.0
    for lag in range(lo, hi + 1):
        running += d[lag]
        cmnd[lag] = d[lag] * (lag - lo + 1) / running if running > 0 else 1.0

    best = None
    for lag in range(lo + 1, hi):
        if cmnd[lag] < thresh and cmnd[lag] <= cmnd[lag - 1] and cmnd[lag] <= cmnd[lag + 1]:
            best = lag
            break
    if best is None:
        best = min(range(lo, hi + 1), key=lambda L: cmnd[L])
        if cmnd[best] > 0.6:
            return None

    # parabolic interpolation around the minimum for sub-sample accuracy
    if lo < best < hi:
        a, b, c = cmnd[best - 1], cmnd[best], cmnd[best + 1]
        denom = 2 * (a - 2 * b + c)
        if denom != 0:
            best = best + (a - c) / denom
    return r / best


def note_name(freq):
    if not freq or freq <= 0:
        return "-"
    import math
    n = 12 * math.log2(freq / 440.0) + 69
    i = int(round(n))
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    cents = (n - i) * 100
    return f"{names[i % 12]}{i // 12 - 1} ({cents:+.0f}c)"


def main():
    path = sys.argv[1]
    ch, rate, samples = read_float_wav(path)
    mono = to_mono(ch, samples)
    peak = max(abs(x) for x in mono) if mono else 0
    print(f"{path}: {len(mono)} frames @ {rate} Hz, peak {peak:.4f}")
    if peak < 0.001:
        print("  silence -- was the pattern playing?")
        return
    onsets = find_onsets(mono, rate)
    print(f"  {len(onsets)} onsets detected\n")
    print(f"  {'#':>3} {'time':>8} {'freq':>9}  note")
    for i, o in enumerate(onsets):
        f = yin_pitch(mono, rate, o)
        print(f"  {i:>3} {o/rate:>7.3f}s {f:>8.1f}Hz  {note_name(f)}"
              if f else f"  {i:>3} {o/rate:>7.3f}s        -  -")


if __name__ == "__main__":
    main()
