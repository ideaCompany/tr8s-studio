#!/usr/bin/env python3
"""
Author TR-8S pattern blobs and write them over SysEx.

Blob layout (decoded 2026-08-28 by diffing a known recording against an
empty slot, then validated against a byte-exact variation):

    0..15                    pattern name, ASCII, space padded
    144 + blk*2436           variation block, blk 0..9 (A-H plus 2 fill-ins)
      blockBase + 4 + t*64   track t, panel order BD SD LT MT HT RS HC CH OH CC RC
        trackBase + k*4      velocity byte for step k (0 = step off)

Velocities follow the generator: X=112 accent, x=100 normal, o=55 ghost.

Writing uses the transfer protocol from Roland's AIRA client:
    1. DT1(send.pattern, encode7(slot,4) + encode7(count,4))   -- initiate
    2. DT1(data.<size>, pack7(chunk))  repeatedly, 1024 bytes then halving
    3. DT1(write.pattern, encode7(slot,2))                     -- commit

An unwritten transfer only lands in the edit buffer; step 3 is what saves it,
exactly like pressing WRITE on the panel.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t  # noqa: E402
from gen_patterns import LIBRARY, VEL  # noqa: E402

HEADER = 144
BLOCK = 2436
NBLOCK = 10
TRACK_STRIDE = 64
STEP_STRIDE = 4
TRACK_BASE = 4
TRACKS = ['BD', 'SD', 'LT', 'MT', 'HT', 'RS', 'HC', 'CH', 'OH', 'CC', 'RC']

SEND_OFFSET = {"pattern": 0x40, "kit": 0x50}
WRITE_OFFSET = {"pattern": 0x01, "kit": 0x02}

TEMPLATE = "/home/svh/tr8s/backups/patterns/pattern_116.bin"  # known-empty slot


# ------------------------------------------------------------------ authoring

def track_offset(blk, tname, step):
    ti = TRACKS.index(tname)
    return HEADER + blk * BLOCK + TRACK_BASE + ti * TRACK_STRIDE + step * STEP_STRIDE


KIT_REF_OFFSET = 18   # single byte, 1-BASED kit number (panel numbering)
                      # Verified 2026-08-28: selecting kit 48 "Acid Transfusion"
                      # on the panel and pressing WRITE changed exactly this one
                      # byte, 0x01 -> 0x30 (=48). The kitReference/kitReferenceSw
                      # addresses in Roland's config are NOT what the panel uses.


SHUFFLE_OFFSET  = 32    # offset-binary: 0x80 == 0, +100 stored as 0xE4 (228)
SCALE_OFFSET    = 19    # 0=8th(T) 1=16th(T) 2=16th 3=32nd
VARMASK_OFFSET  = 48    # bitmask of variations A..H in play (0xFF = all eight)

SCALES = {"8T": 0, "16T": 1, "16": 2, "32": 3}


def set_shuffle(blob, amount):
    """amount is -128..+127 in panel terms; stored offset-binary at byte 32."""
    a = max(-128, min(127, int(round(amount))))
    blob[SHUFFLE_OFFSET] = (a + 128) & 0xFF


def swing_to_shuffle(swing):
    """
    Map the generator's swing float onto the TR-8S shuffle scale.

    The generator delays odd 16ths by swing * half a step, so a full triplet
    feel (delay = 1/3 of a step) corresponds to swing ~= 0.667. Treating the
    TR-8S maximum (+127) as roughly that same full-triplet bounce:
    """
    return max(0, min(127, int(round(swing * 190))))


def set_kit_reference(blob, kit_index):
    """Point a pattern at a kit. kit_index is 0-based (as in the kit dumps);
    the blob stores it 1-based, matching the number shown on the panel."""
    if not 0 <= kit_index <= 127:
        raise ValueError(f"kit index {kit_index} out of range 0..127")
    blob[KIT_REF_OFFSET] = kit_index + 1


def resolve(genre):
    """Look the style up in the 30-style library first, then the original four."""
    try:
        from styles import STYLES
        if genre in STYLES:
            return STYLES[genre]
    except ImportError:
        pass
    if genre in LIBRARY:
        return LIBRARY[genre]
    raise SystemExit(f"unknown style {genre!r}")


def build_blob(genre, template_path=TEMPLATE, name=None,
               kit=None):
    blob = bytearray(open(template_path, 'rb').read())
    if len(blob) != 24504:
        raise SystemExit(f"template is {len(blob)} bytes, expected 24504")

    spec = resolve(genre)
    label = (name or genre.upper())[:16].ljust(16)
    blob[0:16] = label.encode('ascii')

    # tempo: little-endian uint16 at offset 16, in tenths of a BPM
    # (verified: a slot written at 134 BPM reads 1340 here)
    bpm10 = int(round(spec["bpm"] * 10))
    blob[16] = bpm10 & 0xFF
    blob[17] = (bpm10 >> 8) & 0xFF

    if kit is not None:
        set_kit_reference(blob, kit)

    set_shuffle(blob, swing_to_shuffle(spec.get("swing", 0.0)))
    blob[SCALE_OFFSET] = SCALES.get(spec.get("scale", "16"), 2)
    blob[VARMASK_OFFSET] = 0xFF     # mark all eight variations as in use

    for blk, (vname, tracks) in enumerate(spec["patterns"]):
        if blk >= NBLOCK:
            break
        # clear all step velocities in this block first
        for tname in TRACKS:
            for k in range(16):
                blob[track_offset(blk, tname, k)] = 0
        for tname, pattern in tracks.items():
            for k, ch in enumerate(pattern[:16]):
                if ch in VEL:
                    blob[track_offset(blk, tname, k)] = VEL[ch]
    return bytes(blob)


def decode_blob(blob):
    """Read a blob back into step strings, for verification."""
    out = []
    for blk in range(8):
        v = {}
        for tname in TRACKS:
            s = ''.join(
                ('X' if blob[track_offset(blk, tname, k)] >= 112
                 else 'x' if blob[track_offset(blk, tname, k)] >= 90
                 else 'o' if blob[track_offset(blk, tname, k)] else '.')
                for k in range(16))
            if s.strip('.'):
                v[tname] = s
        out.append(v)
    return out


# ------------------------------------------------------------------ transfer

def send_blob(port, kind, slot, blob, verbose=True, settle=0.03):
    util = t.UTILITY_ADDR
    init_addr = t.offset_address(util, SEND_OFFSET[kind])
    args = t.encode7(slot, 4) + t.encode7(1, 4)

    port.drain()
    port.send(t.make_sysex(t.DT1, init_addr, args))
    if verbose:
        print(f"  initiate: slot {slot}, {len(blob)} bytes")
    time.sleep(0.15)
    # drain the device's acknowledgement / progress chatter
    port.collect(0.4, hard_cap=2.0)

    pos = 0
    n = 0
    while pos < len(blob):
        size = 1024
        while pos + size > len(blob):
            size >>= 1
            if size == 0:
                break
        if size == 0:
            break
        chunk = blob[pos:pos + size]
        addr = t.offset_address(util, t.decode7(t.DATA_OFFSETS[size]))
        port.send(t.make_sysex(t.DT1, addr, t.pack7(chunk)))
        pos += size
        n += 1
        time.sleep(settle)
        port.collect(0.02, hard_cap=0.2)
    if verbose:
        print(f"  sent {n} chunks, {pos} bytes")
    return pos == len(blob)


def commit(port, kind, slot, verbose=True):
    addr = t.offset_address(t.UTILITY_ADDR, WRITE_OFFSET[kind])
    port.send(t.make_sysex(t.DT1, addr, t.encode7(slot, 2)))
    if verbose:
        print(f"  commit: WRITE {kind} to slot {slot}")
    time.sleep(0.5)
    return port.collect(0.6, hard_cap=3.0)


def write_pattern(slot, genre, name=None, verify=True):
    blob = build_blob(genre, name=name)
    port = t.Port("/dev/snd/midiC1D0")
    try:
        print(f"writing '{genre}' to slot {slot} "
              f"(bank {slot // 16 + 1}-{slot % 16 + 1:02d})")
        if not send_blob(port, "pattern", slot, blob):
            print("  transfer incomplete")
            return False
        commit(port, "pattern", slot)
        if not verify:
            return True
        time.sleep(0.4)
        back = t.read_blob(port, "pattern", slot, timeout=20, verbose=False)
        if not back:
            print("  VERIFY: could not read back")
            return False
        if back == blob:
            print(f"  VERIFY: byte-exact round-trip ({len(back)} bytes)")
            return True
        diffs = sum(1 for a, b in zip(back, blob) if a != b)
        print(f"  VERIFY: {diffs} bytes differ")
        want = decode_blob(blob)
        got = decode_blob(back)
        steps_ok = want == got
        print(f"  step data matches: {steps_ok}")
        return steps_ok
    finally:
        port.close()


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("usage: tr8s_write.py SLOT GENRE [NAME]")
        print(f"genres: {', '.join(LIBRARY)}")
        return
    slot = int(sys.argv[1])
    genre = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else None
    if genre not in LIBRARY:
        sys.exit(f"unknown genre {genre!r}")
    if not 0 <= slot <= 127:
        sys.exit("slot must be 0..127")
    ok = write_pattern(slot, genre, name)
    print("OK" if ok else "FAILED")


if __name__ == "__main__":
    main()
