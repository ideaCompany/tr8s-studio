#!/usr/bin/env python3
"""
Read, author and write TR-8S kits.

Kit blob, 1312 bytes. Layout decoded 2026-08-28 by writing probe values and by
changing one parameter at a time on the panel then diffing:

    0..15            kit name, ASCII, space padded
    388 + i*52       instrument record, i = 0..10 in panel order
                     BD SD LT MT HT RS HC CH OH CC RC

Within an instrument record:

    +0..1   tone      uint16 LE, selects the sound
    +2      tune      offset-binary, 0x80 = 0, panel range -128..+127
    +3      decay     0..255, default 0x80
    +4      level     0..255  -- READ-ONLY, the device overwrites this with the
                      physical fader position on every write
    +6      pan       offset-binary, 0x80 = centre, 0x00 = L127, 0xFF = R127
    +7      reverb send   0..255
    +8      delay send    0..255
    +11     LFO depth     0..255

A probe of all 52 bytes found 51 of them writable; only +4 is rejected.
Offsets +5, +9, +10 and +12.. are writable but not yet identified.

    python3 tr8s_kit.py show 0           # dump a kit's instrument records
    python3 tr8s_kit.py tones            # labelled tone ids from classic kits
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t   # noqa: E402
import tr8s_write as w   # noqa: E402

TRACKS = ['BD', 'SD', 'LT', 'MT', 'HT', 'RS', 'HC', 'CH', 'OH', 'CC', 'RC']
REC_BASE = 388
REC_STRIDE = 52
KIT_SIZE = 1312
KIT_DIR = "/home/svh/tr8s/backups/kits"

FIELDS = {
    'tone':   (0, 2),   # uint16 LE
    'tune':   (2, 1),   # offset-binary
    'decay':  (3, 1),
    'level':  (4, 1),   # read-only
    'pan':    (6, 1),   # offset-binary
    'reverb': (7, 1),
    'delay':  (8, 1),
    'lfo':    (11, 1),
}
SIGNED = {'tune', 'pan'}          # stored offset-binary, 0x80 == 0
READONLY = {'level'}

# The six single-machine factory kits: everything in them belongs to that machine
CLASSIC = {0: '808', 1: '909', 2: '707', 3: '727', 4: '606', 5: '626'}


def rec(i):
    return REC_BASE + i * REC_STRIDE


def get(blob, inst, field):
    off, size = FIELDS[field]
    o = rec(TRACKS.index(inst)) + off
    if size == 2:
        return struct.unpack('<H', blob[o:o + 2])[0]
    v = blob[o]
    return v - 128 if field in SIGNED else v


def put(blob, inst, field, value):
    if field in READONLY:
        raise ValueError(f"{field} is device-controlled and cannot be written")
    off, size = FIELDS[field]
    o = rec(TRACKS.index(inst)) + off
    if size == 2:
        blob[o:o + 2] = struct.pack('<H', value & 0xFFFF)
        return
    if field in SIGNED:
        value = max(-128, min(127, int(value))) + 128
    blob[o] = int(value) & 0xFF


def load(kit_id, from_dir=KIT_DIR):
    path = os.path.join(from_dir, f"kit_{kit_id:03d}.bin")
    blob = bytearray(open(path, 'rb').read())
    if len(blob) != KIT_SIZE:
        raise SystemExit(f"{path} is {len(blob)} bytes, expected {KIT_SIZE}")
    return blob


def set_name(blob, name):
    blob[0:16] = name[:16].ljust(16).encode('ascii', 'replace')


def name_of(blob):
    return ''.join(chr(c) for c in blob[:16] if 32 <= c < 127).rstrip()


def describe(blob):
    out = [f"kit '{name_of(blob)}'"]
    hdr = f"  {'inst':<4}{'tone':>6}{'tune':>6}{'decay':>7}{'level':>7}" \
          f"{'pan':>6}{'rev':>5}{'dly':>5}{'lfo':>5}"
    out.append(hdr)
    for inst in TRACKS:
        out.append(f"  {inst:<4}" + "".join(
            f"{get(blob, inst, f):>{width}}"
            for f, width in (('tone', 6), ('tune', 6), ('decay', 7),
                             ('level', 7), ('pan', 6), ('reverb', 5),
                             ('delay', 5), ('lfo', 5))))
    return "\n".join(out)


def tone_map(from_dir=KIT_DIR):
    """Label tone ids using the six single-machine factory kits."""
    labels = {}
    for kid, machine in CLASSIC.items():
        blob = load(kid, from_dir)
        for i, inst in enumerate(TRACKS):
            labels[get(blob, inst, 'tone')] = f"{machine} {inst}"
    return labels


def write_kit(slot, blob, verify=True):
    """Write a kit and verify. Note +4 (level) always reads back as the fader."""
    port = t.Port("/dev/snd/midiC1D0")
    try:
        blob = bytes(blob)
        if not w.send_blob(port, "kit", slot, blob, verbose=False):
            return False
        w.commit(port, "kit", slot, verbose=False)
        if not verify:
            return True
        import time
        time.sleep(0.4)
        back = t.read_blob(port, "kit", slot, timeout=20, verbose=False)
        if not back:
            return False
        # ignore the level bytes, which the device owns
        a = bytearray(back)
        b = bytearray(blob)
        for i in range(len(TRACKS)):
            a[rec(i) + 4] = b[rec(i) + 4] = 0
        return a == b
    finally:
        port.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "show":
        kid = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        print(describe(load(kid)))
    elif sys.argv[1] == "tones":
        labels = tone_map()
        for tid in sorted(labels):
            print(f"  {tid:4d}  {labels[tid]}")
        print(f"\n{len(labels)} tones labelled from the six classic kits")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
