#!/usr/bin/env python3
"""
Change an instrument's tone (and optionally tune/decay) in a kit.

    python3 set_tone.py INST TONE_ID [KIT_INDEX] [--decay N] [--tune N]
    python3 set_tone.py --list [CATEGORY]      browse tones by category

Kit writes need the commit step to take effect -- unlike pattern writes, a kit
transfer to the edit buffer does nothing. This commits, so the kit slot IS
modified. All 128 kits are backed up in backups/kits/.

Coarse Tune (and therefore melodies) needs a tone of **type 2** -- a sample.
ACB modelled tones (type 1) have no semitone control at all.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8s_sysex as t   # noqa: E402
import tr8s_kit as k     # noqa: E402

CATS = ['IMPORT', 'BD', 'SD', 'TOM', 'RS', 'HC', 'CH/OH', 'CC/RC', 'PERC1',
        'PERC2', 'PERC3', 'PERC4', 'PERC5', 'FX/HIT', 'VOICE', 'SYNTH1',
        'SYNTH2', 'BASS', 'SCALED', 'CHORD', 'OTHERS']
TYPES = {1: 'ACB', 2: 'sample', 3: 'other'}


def tone_info(port, tid):
    b = t.read_blob(port, 'tone', tid, timeout=6, verbose=False)
    if not b or len(b) < 18:
        return None
    name = ''.join(chr(c) for c in b[:16] if 32 <= c < 127).rstrip()
    cat = CATS[b[16]] if b[16] < len(CATS) else f"?{b[16]}"
    return {'id': tid, 'name': name, 'category': cat, 'type': b[17]}


def cmd_list(category=None, lo=0, hi=1023):
    port = t.Port("/dev/snd/midiC1D0")
    try:
        for tid in range(lo, hi + 1):
            info = tone_info(port, tid)
            if not info or not info['name']:
                continue
            if category and info['category'].upper() != category.upper():
                continue
            melodic = ' [melodic]' if info['type'] == 2 else ''
            print(f"  {tid:4d}  {info['category']:<7s} "
                  f"{TYPES.get(info['type'], info['type']):<6s} "
                  f"{info['name']}{melodic}")
    finally:
        port.close()


def set_tone(inst, tone_id, kit_id=61, decay=None, tune=None):
    port = t.Port("/dev/snd/midiC1D0")
    try:
        info = tone_info(port, tone_id)
        cur = t.read_blob(port, 'kit', kit_id, timeout=20, verbose=False)
        if not cur:
            print("could not read the kit")
            return False
        blob = bytearray(cur)
        old = k.get(blob, inst, 'tone')
        k.put(blob, inst, 'tone', tone_id)
        if decay is not None:
            k.put(blob, inst, 'decay', decay)
        if tune is not None:
            k.put(blob, inst, 'tune', tune)
        blob = bytes(blob)

        import tr8s_write as w
        w.send_blob(port, 'kit', kit_id, blob, verbose=False)
        w.commit(port, 'kit', kit_id, verbose=False)   # kits need the commit
        time.sleep(0.4)
        back = t.read_blob(port, 'kit', kit_id, timeout=20, verbose=False)
        ok = back and k.get(bytearray(back), inst, 'tone') == tone_id
        nm = info['name'] if info else '?'
        ty = TYPES.get(info['type'], '?') if info else '?'
        print(f"kit {kit_id + 1} (panel) {inst}: tone {old} -> {tone_id} "
              f"'{nm}' [{ty}]  {'OK' if ok else 'FAILED'}")
        if info and info['type'] != 2:
            print("  WARNING: not a sample tone -- Coarse Tune will not be "
                  "available, so melodies will not work on this instrument")
        return ok
    finally:
        port.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == '--list':
        cmd_list(sys.argv[2] if len(sys.argv) > 2 else None)
        return
    inst = sys.argv[1]
    tone_id = int(sys.argv[2])
    kit_id = int(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else 61
    decay = tune = None
    for i, a in enumerate(sys.argv):
        if a == '--decay':
            decay = int(sys.argv[i + 1])
        if a == '--tune':
            tune = int(sys.argv[i + 1])
    set_tone(inst, tone_id, kit_id, decay, tune)


if __name__ == "__main__":
    main()
