#!/usr/bin/env python3
"""
TR-8S pattern library generator.

Writes Standard MIDI Files (format 0, one per pattern) using the TR-8S
instrument note map. No external dependencies.

Patterns are written as step strings so they stay editable by hand:
    X = accented hit   (vel 112)
    x = normal hit     (vel 100)
    o = ghost note     (vel  55)
    . = rest
One character per 16th note. Length is free: 16 = one bar, 32 = two bars.

Usage:
    python3 gen_patterns.py [--outdir DIR] [--map note_map.json]
"""

import argparse
import json
import os
import struct

PPQ = 96  # ticks per quarter note

# TR-8S factory MIDI note map. Override with --map once confirmed on the unit.
DEFAULT_NOTE_MAP = {
    "BD": 36,  # bass drum
    "RS": 37,  # rim shot
    "SD": 38,  # snare
    "HC": 39,  # hand clap
    "LT": 43,  # low tom
    "CH": 42,  # closed hat
    "MT": 47,  # mid tom
    "OH": 46,  # open hat
    "HT": 50,  # high tom
    "CC": 49,  # crash
    "RC": 51,  # ride
}

VEL = {"X": 112, "x": 100, "o": 55}

MIDI_CHANNEL = 9  # 0-based; ch10 in 1-based terms, the drum channel


# --------------------------------------------------------------------------
# Standard MIDI File writing
# --------------------------------------------------------------------------

def vlq(n):
    """Variable-length quantity encoding used by SMF delta times."""
    if n == 0:
        return b"\x00"
    out = bytearray()
    while n:
        out.append(n & 0x7F)
        n >>= 7
    out[0] |= 0  # last byte written first has no continuation bit
    out.reverse()
    for i in range(len(out) - 1):
        out[i] |= 0x80
    return bytes(out)


def write_smf(path, events, bpm, name):
    """events: list of (tick, status, data1, data2), absolute ticks."""
    track = bytearray()

    # Track name
    nm = name.encode("ascii", "replace")
    track += vlq(0) + b"\xff\x03" + vlq(len(nm)) + nm

    # Tempo
    usec = int(round(60_000_000 / bpm))
    track += vlq(0) + b"\xff\x51\x03" + struct.pack(">I", usec)[1:]

    # Time signature 4/4, 24 clocks/beat, 8 32nds per quarter
    track += vlq(0) + b"\xff\x58\x04" + bytes([4, 2, 24, 8])

    last = 0
    for tick, status, d1, d2 in sorted(events, key=lambda e: (e[0], e[1])):
        track += vlq(tick - last) + bytes([status, d1, d2])
        last = tick

    track += vlq(0) + b"\xff\x2f\x00"  # end of track

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ)
    chunk = b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    with open(path, "wb") as f:
        f.write(header + chunk)


# --------------------------------------------------------------------------
# Pattern -> events
# --------------------------------------------------------------------------

def build_events(tracks, note_map, swing=0.0, gate=0.5, repeats=1):
    """
    tracks: dict of instrument -> step string
    swing:  0.0 = straight, 0.2..0.6 = progressively harder shuffle.
            Delays every odd 16th by swing * half a 16th.
    gate:   note length as a fraction of one 16th step.
    """
    step_ticks = PPQ // 4
    length = max(len(s) for s in tracks.values())
    events = []

    for rep in range(repeats):
        bar_offset = rep * length * step_ticks
        for inst, pattern in tracks.items():
            if inst not in note_map:
                raise KeyError(f"unknown instrument {inst!r}")
            note = note_map[inst]
            for i, ch in enumerate(pattern):
                if ch not in VEL:
                    continue
                tick = bar_offset + i * step_ticks
                if swing and i % 2 == 1:
                    tick += int(step_ticks * 0.5 * swing)
                dur = max(6, int(step_ticks * gate))
                events.append((tick, 0x90 | MIDI_CHANNEL, note, VEL[ch]))
                events.append((tick + dur, 0x80 | MIDI_CHANNEL, note, 0))
    return events


# --------------------------------------------------------------------------
# The library
# --------------------------------------------------------------------------
# Each genre is a "track": a sequence of patterns forming an arc that maps
# onto TR-8S variations A-H of a single pattern slot.

LIBRARY = {
    "techno": {
        "bpm": 134,
        "swing": 0.0,
        "patterns": [
            ("A_intro", {
                "BD": "X...x...X...x...",
                "CH": "..x...x...x...x.",
                "RS": "................",
            }),
            ("B_main", {
                "BD": "X...x...X...x...",
                "OH": "..x...x...x...x.",
                "CH": "x.x.x.x.x.x.x.x.",
                "RS": "....x.......x...",
            }),
            ("C_rolling", {
                "BD": "X...x...X...x..x",
                "OH": "..x...x...x...x.",
                "CH": "xoxoxoxoxoxoxoxo",
                "RS": "....x.......x..x",
                "HC": "............x...",
            }),
            ("D_hypnotic", {
                "BD": "X...x...X...x...",
                "OH": "..x...x...x...x.",
                "CH": "x.xox.xox.xox.xo",
                "RC": "....x.......x...",
                "LT": "..........o.....",
            }),
            ("E_break", {
                "BD": "................",
                "OH": "..x...x...x...x.",
                "CH": "xoxoxoxoxoxoxoxo",
                "HC": "....X.......X...",
                "RC": "x...x...x...x...",
            }),
            ("F_peak", {
                "BD": "X...X...X...X...",
                "OH": "..x...x...x...x.",
                "CH": "xoxoxoxoxoxoxoxo",
                "HC": "....X.......X...",
                "CC": "X...............",
                "RS": "..x...x...x...x.",
            }),
            ("G_fill", {
                "BD": "X...x...X.......",
                "CH": "x.x.x.x.x.......",
                "LT": "..........x.x...",
                "MT": "..............x.",
                "HT": "...............x",
                "CC": "X...............",
            }),
            ("H_stripped", {
                "BD": "X...x...X...x...",
                "RC": "..o...o...o...o.",
            }),
        ],
    },

    "dnb": {
        "bpm": 174,
        "swing": 0.0,
        "patterns": [
            ("A_intro", {
                "BD": "X.......X.......",
                "SD": "....X.......X...",
                "CH": "..x...x...x...x.",
            }),
            ("B_twostep", {
                "BD": "X.........X.....",
                "SD": "....X.......X...",
                "CH": "x.x.x.x.x.x.x.x.",
                "RC": "..o...o...o...o.",
            }),
            ("C_amen", {
                "BD": "X.....X...X.....",
                "SD": "....X..o.X..X..o",
                "CH": "x.x.x.x.x.x.x.x.",
                "OH": "..............x.",
            }),
            ("D_rolling", {
                "BD": "X.......X...X...",
                "SD": "....X..o....X..o",
                "CH": "xoxoxoxoxoxoxoxo",
                "RC": "..o...o...o...o.",
            }),
            ("E_liquid", {
                "BD": "X.........X.....",
                "SD": "....X.......X...",
                "CH": "x.o.x.o.x.o.x.o.",
                "RC": "..x...x...x...x.",
                "RS": "......o.......o.",
            }),
            ("F_break", {
                "SD": "....X.......X...",
                "CH": "xoxoxoxoxoxoxoxo",
                "RC": "x...x...x...x...",
            }),
            ("G_fill", {
                "BD": "X.......X.......",
                "SD": "....X...o.o.o.o.",
                "LT": "............x...",
                "MT": "..............x.",
                "HT": "...............X",
            }),
            ("H_drop", {
                "BD": "X.........X.....",
                "SD": "....X.......X...",
                "CH": "x.x.x.x.x.x.x.x.",
                "CC": "X...............",
                "OH": "..............x.",
            }),
        ],
    },

    "house": {
        "bpm": 124,
        "swing": 0.18,
        "patterns": [
            ("A_intro", {
                "BD": "X...x...X...x...",
                "CH": "..x...x...x...x.",
            }),
            ("B_main", {
                "BD": "X...x...X...x...",
                "OH": "..x...x...x...x.",
                "CH": "x.o.x.o.x.o.x.o.",
                "HC": "....X.......X...",
            }),
            ("C_shuffle", {
                "BD": "X...x...X...x...",
                "OH": "..x...x...x...x.",
                "CH": "xoxoxoxoxoxoxoxo",
                "HC": "....X.......X...",
                "RS": "..o...o...o...o.",
            }),
            ("D_deep", {
                "BD": "X...x...X...x...",
                "OH": "..x...x...x...x.",
                "CH": "x...x...x...x...",
                "RS": "....o.......o...",
                "LT": "..........o.....",
            }),
            ("E_percy", {
                "BD": "X...x...X...x...",
                "OH": "..x...x...x...x.",
                "CH": "x.o.x.o.x.o.x.o.",
                "HC": "....X.......X...",
                "MT": "......o...o.....",
                "LT": "..........o...o.",
            }),
            ("F_break", {
                "OH": "..x...x...x...x.",
                "CH": "xoxoxoxoxoxoxoxo",
                "HC": "....X.......X...",
                "RC": "x...x...x...x...",
            }),
            ("G_fill", {
                "BD": "X...x...X.......",
                "CH": "x.x.x.x.........",
                "HC": "....X...X.X.X.X.",
                "CC": "X...............",
            }),
            ("H_outro", {
                "BD": "X...x...X...x...",
                "CH": "..o...o...o...o.",
                "RC": "x.......x.......",
            }),
        ],
    },

    "lofi": {
        "bpm": 82,
        "swing": 0.42,
        "patterns": [
            ("A_intro", {
                "BD": "X.......X.......",
                "CH": "x...x...x...x...",
            }),
            ("B_main", {
                "BD": "X.....X.o.......",
                "SD": "....X.......X...",
                "CH": "x.o.x.o.x.o.x.o.",
            }),
            ("C_dusty", {
                "BD": "X.....X...X.....",
                "SD": "....X.......X..o",
                "CH": "x.o.x.o.x.o.x.o.",
                "RS": "..o...........o.",
            }),
            ("D_laidback", {
                "BD": "X.......X.......",
                "SD": "....X.......X...",
                "CH": "x.oox.oox.oox.oo",
                "RC": "..o.......o.....",
            }),
            ("E_swung", {
                "BD": "X.....X.....X...",
                "SD": "....X.......X...",
                "CH": "x.o.x.o.x.o.x.o.",
                "HC": "............o...",
                "LT": "..........o.....",
            }),
            ("F_break", {
                "SD": "....o.......o...",
                "CH": "x.o.x.o.x.o.x.o.",
                "RC": "x.......x.......",
            }),
            ("G_fill", {
                "BD": "X.......X.......",
                "SD": "....X.....o.o.o.",
                "LT": "..........o.....",
                "MT": "............o...",
                "HT": "..............o.",
            }),
            ("H_outro", {
                "BD": "X.......X.......",
                "CH": "x...x...x...x...",
                "RC": "x...............",
            }),
        ],
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--map", help="JSON file overriding the instrument note map")
    ap.add_argument("--repeats", type=int, default=4,
                    help="how many times each pattern loops in its .mid file")
    args = ap.parse_args()

    note_map = dict(DEFAULT_NOTE_MAP)
    if args.map:
        with open(args.map) as f:
            note_map.update(json.load(f))

    count = 0
    for genre, spec in LIBRARY.items():
        gdir = os.path.join(args.outdir, genre)
        os.makedirs(gdir, exist_ok=True)
        for name, tracks in spec["patterns"]:
            events = build_events(
                tracks, note_map,
                swing=spec["swing"],
                repeats=args.repeats,
            )
            path = os.path.join(gdir, f"{genre}_{name}.mid")
            write_smf(path, events, spec["bpm"], f"{genre} {name}")
            count += 1
        print(f"{genre:8s} bpm={spec['bpm']:3d} swing={spec['swing']:.2f} "
              f"patterns={len(spec['patterns'])}")

    print(f"\n{count} MIDI files written under {args.outdir}")


if __name__ == "__main__":
    main()
