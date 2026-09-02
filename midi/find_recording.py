#!/usr/bin/env python3
"""
Locate the pattern recorded from the computer, and use it as labelled data
to decode the TR-8S pattern blob layout.

Blob layout deduced so far:
    offset 0    16 bytes  pattern name (ASCII)
    offset 0    144 bytes header
    offset 144  10 blocks of 2436 bytes  ((24504-144)/2436 == 10 exactly)
                -> 8 variations A-H plus 2 more (fill-ins)

Signature of the recorded pattern: blocks 0 and 1 populated (variations A
and B), blocks 2..9 empty -- because an empty slot was chosen and only A
and B were played in.
"""

import glob
import os
import sys

HEADER = 144
BLOCK = 2436
NBLOCK = 10
DUMPS = "/home/svh/tr8s/backups/patterns"


def blocks(blob):
    return [blob[HEADER + i * BLOCK: HEADER + (i + 1) * BLOCK]
            for i in range(NBLOCK)]


def nz(b):
    return sum(1 for x in b if x)


def main():
    files = sorted(glob.glob(os.path.join(DUMPS, "pattern_*.bin")))
    if not files:
        sys.exit(f"no dumps in {DUMPS}")
    print(f"scanning {len(files)} pattern dumps\n")
    cands = []
    for path in files:
        blob = open(path, "rb").read()
        if len(blob) != 24504:
            continue
        pid = int(os.path.basename(path)[8:11])
        name = "".join(chr(c) for c in blob[:16] if 32 <= c < 127).rstrip()
        bs = blocks(blob)
        counts = [nz(b) for b in bs]
        active = [i for i, c in enumerate(counts) if c]
        # our recording: exactly blocks 0 and 1 active
        if active and set(active) <= {0, 1}:
            cands.append((pid, name, counts))
        elif len(active) <= 2:
            cands.append((pid, name, counts))
    if not cands:
        print("no slot matches the signature; showing block profiles instead")
        for path in files[:5]:
            blob = open(path, "rb").read()
            pid = int(os.path.basename(path)[8:11])
            print(f"  {pid:3d} {[nz(b) for b in blocks(blob)]}")
        return
    print("candidates (block non-zero counts, index 0 = variation A):")
    for pid, name, counts in cands:
        print(f"  slot {pid:3d}  {name:<18s} {counts}")


if __name__ == "__main__":
    main()
