#!/usr/bin/env python3
"""
Write the 30-style library to consecutive TR-8S pattern slots.

    python3 write_all.py [START_SLOT]     default 0

Slot 0 is bank 1-01, so the default fills banks 1 and 2 (1-01 .. 2-14),
which is where they are easiest to find on the panel.

Every write is verified by reading the blob back and comparing byte for byte;
any slot that fails to round-trip is reported at the end.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t          # noqa: E402
import tr8s_write as w          # noqa: E402
from styles import STYLES, validate  # noqa: E402

# Panel-friendly 16-character names
NAMES = {
    "techno_peak": "TECHNO PEAK", "techno_hypnotic": "TECHNO HYPNO",
    "techno_industrial": "TECHNO INDUS", "techno_dub": "DUB TECHNO",
    "techno_acid": "ACID TECHNO", "techno_hardgroove": "HARDGROOVE",
    "techno_detroit": "DETROIT",
    "dnb_liquid": "LIQUID DNB", "dnb_neuro": "NEUROFUNK",
    "dnb_jumpup": "JUMP UP", "dnb_jungle": "JUNGLE",
    "dnb_halftime": "HALFTIME DNB", "dnb_rollers": "ROLLERS",
    "house_deep": "DEEP HOUSE", "house_tech": "TECH HOUSE",
    "house_garage": "UK GARAGE", "house_disco": "DISCO HOUSE",
    "house_afro": "AFRO HOUSE", "house_jackin": "JACKIN HOUSE",
    "house_french": "FRENCH HOUSE",
    "lofi_boombap": "BOOM BAP", "lofi_chillhop": "CHILLHOP",
    "lofi_dusty": "DUSTY LOFI", "lofi_triphop": "TRIP HOP",
    "lofi_lounge": "LOFI LOUNGE",
    "breakbeat": "BREAKBEAT", "electro": "ELECTRO",
    "dubstep": "DUBSTEP", "downtempo": "DOWNTEMPO",
    "ambient_perc": "AMBIENT PERC",
}


# style -> kit index (0-based, as in backups/kits/); panel shows index+1
KITS = {
    "techno_peak": 71, "techno_hypnotic": 25, "techno_industrial": 49,
    "techno_dub": 27, "techno_acid": 47, "techno_hardgroove": 73,
    "techno_detroit": 27,
    "dnb_liquid": 12, "dnb_neuro": 92, "dnb_jumpup": 48,
    "dnb_jungle": 48, "dnb_halftime": 112, "dnb_rollers": 12,
    "house_deep": 33, "house_tech": 41, "house_garage": 45,
    "house_disco": 35, "house_afro": 55, "house_jackin": 32,
    "house_french": 99,
    "lofi_boombap": 66, "lofi_chillhop": 110, "lofi_dusty": 102,
    "lofi_triphop": 90, "lofi_lounge": 21,
    "breakbeat": 48, "electro": 20, "dubstep": 50,
    "downtempo": 93, "ambient_perc": 24,
}


def kit_names():
    import os
    out = {}
    d = "/home/svh/tr8s/backups/kits"
    for k in set(KITS.values()):
        f = os.path.join(d, f"kit_{k:03d}.bin")
        if os.path.exists(f):
            b = open(f, "rb").read()
            out[k] = "".join(chr(c) for c in b[:16] if 32 <= c < 127).rstrip()
    return out


def main():
    errs = validate()
    if errs:
        sys.exit("style library has problems:\n  " + "\n  ".join(errs))

    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    order = list(STYLES.keys())
    if start + len(order) > 128:
        sys.exit(f"{len(order)} styles from slot {start} would run past slot 127")

    print(f"writing {len(order)} styles to slots {start}..{start+len(order)-1}\n")
    knames = kit_names()
    port = t.Port("/dev/snd/midiC1D0")
    good, bad = [], []
    try:
        for i, style in enumerate(order):
            slot = start + i
            bank, pat = slot // 16 + 1, slot % 16 + 1
            name = NAMES.get(style, style.upper())
            blob = w.build_blob(style, name=name, kit=KITS.get(style))
            ok = w.send_blob(port, "pattern", slot, blob, verbose=False)
            if ok:
                w.commit(port, "pattern", slot, verbose=False)
                time.sleep(0.25)
                back = t.read_blob(port, "pattern", slot, timeout=20, verbose=False)
                ok = back == blob
            bpm = STYLES[style]["bpm"]
            kn = knames.get(KITS.get(style), "?")
            print(f"  {bank}-{pat:02d} (slot {slot:3d})  {name:<14s} {bpm:3d} BPM  "
                  f"kit {KITS.get(style,0)+1:3d} {kn:<18s} "
                  f"{'verified' if ok else 'FAILED'}", flush=True)
            (good if ok else bad).append((slot, name))
            time.sleep(0.15)
    finally:
        port.close()

    print(f"\n{len(good)} verified, {len(bad)} failed")
    if bad:
        print("failed slots:", ", ".join(f"{s} {n}" for s, n in bad))


if __name__ == "__main__":
    main()
