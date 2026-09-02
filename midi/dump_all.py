#!/usr/bin/env python3
"""Read every pattern blob off the TR-8S over SysEx (read-only) into files."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t  # noqa: E402

OUT = "/home/svh/tr8s/backups/patterns"


def main():
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else 127
    os.makedirs(OUT, exist_ok=True)
    port = t.Port("/dev/snd/midiC1D0")
    ok = fail = 0
    try:
        for pid in range(lo, hi + 1):
            dest = os.path.join(OUT, f"pattern_{pid:03d}.bin")
            if os.path.exists(dest) and os.path.getsize(dest) == 24504:
                ok += 1
                continue
            blob = t.read_blob(port, "pattern", pid, timeout=12, verbose=False)
            if blob and len(blob) == 24504:
                with open(dest, "wb") as f:
                    f.write(blob)
                name = "".join(chr(c) for c in blob[:16] if 32 <= c < 127).rstrip()
                nz = sum(1 for b in blob if b)
                print(f"{pid:3d}  {name:<18s} nonzero={nz}", flush=True)
                ok += 1
            else:
                print(f"{pid:3d}  FAILED ({len(blob) if blob else 0} bytes)",
                      flush=True)
                fail += 1
            time.sleep(0.05)
    finally:
        port.close()
    print(f"\ndone: {ok} read, {fail} failed -> {OUT}")


if __name__ == "__main__":
    main()
