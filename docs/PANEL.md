# The TR-8S front panel

Taken from the Owner's Manual "Panel Descriptions" (Roland, 2018), so the
studio's PANEL view mirrors the real thing rather than an invented layout.
Section numbers are Roland's own.

```
 ┌1 COMMON ─────────┬2 ACC┬3 REV┬4 DELAY────┬5 MFX┬6 FILL──┬9 COMMON 2 ──────┐
 │ VOLUME  EXT IN   │LEVEL│LEVEL│LEV TIM FBK│ON   │ON      │   [ display ]   │
 │ SHIFT            │STEP │     │           │CTRL │KNOB    │ WRITE   ENTER   │
 │ PTN SELECT       │     │     │           │     │MANUAL  │ KIT INST SAMPLE │
 │ TR-REC  INST REC │     │     │           │     │  TRIG  │ CTRL SEL  COPY  │
 │ CLEAR   INST PLAY│     │     │           │     │        │ UTILITY         │
 │ MOTION: ON  REC  │     │     │           │     │        │ [ TEMPO ]       │
 │ A B C D E F G H  │     │     │           │     │        │ VALUE  SHUFFLE  │
 │ LAST SUB  ST/STP │     │     │           │     │        │                 │
 ├7 INST EDIT + 8 INST SELECT ───────────────────────────────────────────────┤
 │  ○    ○    ○    ○    ○    ○    ○    ○    ○    ○    ○     TUNE  per inst    │
 │  ○    ○    ○    ○    ○    ○    ○    ○    ○    ○    ○     DECAY per inst    │
 │  ○    ○    ○    ○    ○    ○    ○    ○    ○    ○    ○     CTRL  per inst    │
 │  ▮    ▮    ▮    ▮    ▮    ▮    ▮    ▮    ▮    ▮    ▮     faders, each lit  │
 │ [BD] [SD] [LT] [MT] [HT] [RS] [HC] [CH] [OH] [CC] [RC]   its own colour    │
 ├10 PADS ───────────────────────────────────────────────────────────────────┤
 │ [1][2][3][4][5][6][7][8][9][10][11][12][13][14][15][16]                   │
 └───────────────────────────────────────────────────────────────────────────┘
```

**Every instrument has its own TUNE, DECAY and CTRL knob.** They are three rows
of eleven, stacked above the faders — not one shared set. The manual lists them
under a single heading ("7 INST edit section"), which reads as though there is
one of each; the photographs show otherwise, and there are 53 knobs and sliders
on the machine, which only adds up with 11 faders and 33 knobs.

Each fader is lit its own colour, saved with the kit — see the kit header
bytes `+42…+52` in docs/PROTOCOL.md.

## What each control does

**1 Common** — `VOLUME` (MIX OUT and PHONES, not ASSIGNABLE OUT), `EXT IN`,
`SHIFT` (hold for alternate functions; also makes VALUE move in bigger steps),
`PTN SELECT`, `TR-REC` (step record), `INST REC` (realtime record), `CLEAR`,
`INST PLAY` (pads 1–13 play instruments live), `MOTION [ON]` (play back knob
motion) and `MOTION [REC]`, `[A]`–`[H]` variations, `LAST` (pattern length),
`SUB` (duplets/triplets/quadruplets), `START/STOP`.

**2 ACCENT** — `LEVEL`, and `STEP` (during TR-REC, pads pick accented steps).

**3 REVERB / 4 DELAY / 5 MASTER FX** — reverb `LEVEL`; delay `LEVEL`, `TIME`,
`FEEDBACK`; master FX `ON` and `CTRL`.

**6 AUTO FILL IN** — `ON`, an interval knob, and `MANUAL TRIG`.

**7 INST EDIT** — `TUNE`, `DECAY` and `CTRL`, one of each **per instrument**.
The `CTRL` knob does whatever `CTRL SELECT` assigns to it, which is why
software cannot know what per-step CTRL motion means (docs/PROTOCOL.md).

**8 INST SELECT** — eleven instruments, each with a select button and a level
fader lit in the kit's colour for that instrument.

**9 Common 2** — the display, `WRITE`, `ENTER`, `VALUE`, `KIT`, `INST`,
`SAMPLE`, `CTRL SELECT`, `COPY`, `UTILITY`, the TEMPO display, `TEMPO` and
`SHUFFLE`.

**10 Pads 1–16** — steps in TR-REC, instruments in INST PLAY, bank/number in
PTN SELECT.

## What the studio can and cannot reach

Everything above is *panel* state. Over SysEx the studio reads and writes
pattern and kit memory, and nothing else — so `MOTION [ON]`, `CTRL SELECT`,
the faders, and the effect knobs are all visible on the panel and invisible
here. The PANEL view therefore draws them as context, greyed, rather than as
controls that do something.
