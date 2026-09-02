# Roland TR-8S — SysEx protocol and data formats

Complete reference for reading and writing TR-8S patterns, kits and melodies
over USB. Everything here was verified against real hardware
(**firmware 2.51, rev 0B97**) on 2026-08-28.

Each fact is marked:

- **[V]** verified — observed directly, usually by writing and reading back
- **[M]** measured — derived from acoustic measurement, carries stated error
- **[I]** inferred — strongly indicated but not proven; treat with care

Provenance: the address map and transfer protocol were reconstructed from
Roland's own AIRA web client, archived at
`github.com/compuphonic/TR-8S-SysEx` (`js/Com/MidiManager.js`,
`js/Tr8s/Tr8sData.js` — the latter holds the address table as a base64 JSON
blob). The implementation here is our own; none of Roland's code is reused.
Note that **two of that config's fields are wrong in practice** — see
[Traps](#traps).

---

## 1. Transport

### Connection

The TR-8S enumerates as USB `0582:020a`, an ALSA card exposing two MIDI ports:

```
hw:1,0,0   "TR-8S MIDI 1"    seq 20:0    /dev/snd/midiC1D0
hw:1,0,1   "TR-8S MIDI 2"    seq 20:1    (no device node; use amidi)
```

**[V]** SysEx works on either port. `/dev/snd/midiC1D0` opened `O_RDWR` is the
simplest transport; ALSA rawmidi subdevice 1 has no device node, so reaching
port 2 needs `amidi -p hw:1,0,1`.

### Message format

```
F0 41 <devId> 00 00 00 45 <cmd> <addr x4> <data...> <checksum> F7
```

| Field | Value |
|---|---|
| `41` | Roland manufacturer ID |
| `devId` | **[V]** `0x10` works; `0x7F` (broadcast) also works; `0x00` does **not** |
| `00 00 00 45` | TR-8S model ID |
| `cmd` | `0x12` = DT1 (data set), `0x11` = RQ1 (data request) |
| `checksum` | `127 & (128 - (127 & sum(addr + data)))` |

**[V]** RQ1 requests for pattern/kit names were never answered in testing; all
reads here use the DT1-based bulk transfer below.

### Addresses

Addresses are **7-bit packed 28-bit integers**. To offset one, decode to an
integer, add, and re-encode — do not add to individual bytes.

```python
def decode7(addr):                  # [0x50,0,0,0] -> 167772160
    v = 0
    for b in addr: v = (v << 7) | (b & 0x7F)
    return v

def encode7(value, n):
    out = [0]*n
    for i in range(n-1, -1, -1):
        out[i] = value & 0x7F; value >>= 7
    return out
```

Utility base is `50 00 00 00`:

| Offset | Meaning |
|---|---|
| `+0x10` | playing status |
| `+0x11` | system lock |
| `+0x13` | firmware version |
| `+0x14` | device UID |
| `+0x30 / +0x31` | send / get **system** |
| `+0x40 / +0x41` | send / get **pattern** |
| `+0x50 / +0x51` | send / get **kit** |
| `+0x60 / +0x61` | send / get **tone** |
| `+0x01 / +0x02 / +0x03` | **write** (commit) pattern / kit / tone |

Blob sizes: **pattern 24504**, **kit 1312**, **system 752**, tone 36.

### Bulk data packing

Bulk payloads use Roland's 7-bit packing: one header byte carries the MSBs of
the following seven bytes.

```python
def unpack7(packed):
    out = bytearray(); f = 0
    while f < len(packed):
        e = packed[f] << 7; f += 1
        for _ in range(7):
            if f >= len(packed): break
            out.append(packed[f] | (0x80 & e)); f += 1; e >>= 1
    return bytes(out)
```

### Reading a blob

```
DT1(get.<kind>, encode7(index,4) + encode7(count,4))
```

**[V]** Two 4-byte arguments — index **and** count. Sending only the index
gets no reply at all, silently. The device then streams DT1 messages whose
address is one of the data-chunk addresses (`utility + decode7([1,n])`,
n = 0..10 for chunk sizes 1..1024, i.e. `50 00 01 00` … `50 00 01 0A`);
progress arrives at `50 00 01 10`. Unpack each payload and concatenate.

### Writing a blob

Three steps. **All three are required.**

```
1. DT1(send.<kind>, encode7(slot,4) + encode7(count,4))     initiate
2. DT1(data.<size>, pack7(chunk))  repeatedly                stream
3. DT1(write.<kind>, encode7(slot,2))                        commit
```

Chunks are 1024 bytes, halving to fit the tail. For a 24504-byte pattern that
is 23×1024, then 512, 256, 128, 32, 16, 8 — **29 chunks**.

**[V]** There is **no CRC over the pattern or kit body**; writes are accepted
as sent.

### What a transfer actually does — corrected

An earlier version of this document claimed a transfer without step 3 lands in
a scratch "edit buffer". **That is wrong**, and the correction matters because
it means there is no such thing as a throwaway write.

**[V] A transfer writes the slot immediately, for patterns and kits alike.**
Proof: an uncommitted write to slot 116 was still present after a subsequent
uncommitted write to slot 117. A single shared edit buffer cannot hold both.
An uncommitted kit write likewise reads back changed.

**[V] The real asymmetry is whether the device re-reads the slot into what it
is playing.** A pattern is re-read at once — an uncommitted pattern write is
audible on the next loop, which is what makes an interactive editor possible. A
kit is not: the loaded kit keeps sounding until commit (or the user reselects
it). That is why writing seven different kit tunes without commit produced seven
identical sounds — the slot changed each time, the audio did not.

**[I] What commit adds is presumed to be durability across power-off.** This is
NOT verified: confirming it needs a power cycle, which cannot be done from
software. Send it for anything you want to keep.

**There is no undo.** Read a slot before overwriting it.

### Slot numbering

**[V]** Panel `bank-pattern` maps to linear slot `(bank-1)*16 + (pattern-1)`.
So `8-03` is slot 114, and slot 0 is `1-01`.

**[V]** Kits and patterns are numbered **1-based on the panel** but **0-based**
in SysEx. Kit 48 on screen is index 47 in a dump.

---

## 2. Pattern blob — 24504 bytes

### Header

| Offset | Field | Notes |
|---|---|---|
| `0..15` | name | ASCII, space padded |
| `16..17` | tempo | **[V]** LE uint16, **tenths of a BPM** (1340 = 134.0) |
| `18` | kit number | **[V]** single byte, **1-based** panel numbering |
| `19` | scale | **[V]** `0`=8th(T) `1`=16th(T) `2`=16th `3`=32nd |
| `32` | shuffle | **[V]** offset-binary, `0x80` = 0, panel range −128…+127 |
| `48` | variation mask | **[V]** bitmask of variations A–H holding data; the device **recomputes it on write**, so setting it is unnecessary |

**[V] Critical:** per-pattern tempo, shuffle and kit are honoured only when the
matching `[UTILITY] GENERAL` source is `PTN`, not `SYSTEM` (`TempoSrc`,
`Shuffle`, `KitSel`). On `SYSTEM` the panel knobs win and everything written
into the header is silently ignored.

### Variation blocks

```
144 + blk*2436        blk = 0..9      (24504 - 144) / 2436 == 10 exactly
```

Eight blocks are variations A–H; **[I]** the last two are believed to be the
fill-ins.

### Tracks within a block

```
track t base = blockBase + 4 + t*64
step k       = trackBase + k*4        4 bytes per step
```

Instrument tracks are `t = 0..10` in panel order:

```
BD SD LT MT HT RS HC CH OH CC RC
```

**[V]** For instrument tracks, byte `+0` is velocity and `+1..+3` are always
zero. Velocity `0` means the step is off. The generator uses `112` accent,
`100` normal, `55` ghost.

### Motion lanes — the same geometry

**[V]** Motion lives in tracks `t >= 12`, using the identical layout. The lane
is **per instrument**, not per knob:

```
motion lane = 12 + instrument index      BD=12, SD=13, LT=14 ... RC=22

  +0  TUNE value      offset-binary, 0x80 = 0
  +1  probably DECAY  [I] never tested
  +2  CTRL value      whatever is assigned to that instrument's CTRL knob
  +3  presence mask   0x80 = tune present, 0x09 = ctrl present
```

**[V]** A step whose presence mask is `0` has *no* motion and plays at the
kit's own tune — which is **not** the same as writing tune `0`. Both the value
byte and the mask byte must be written per note.

**[I]** A step carrying both tune and CTRL motion presumably masks to `0x89`;
untested.

**[V] The CTRL byte's meaning is not knowable from the blob.** Byte `+0` is
always Tune, but `+2` holds whatever is assigned to that instrument's CTRL knob
— Coarse Tune, pan, a send. That assignment lives in system state, not the kit
(see below), so reading `+2` as semitones is an assumption the caller has to
supply. Factory patterns do carry CTRL motion that is *not* pitch: interpreting
it as Coarse Tune produces notes like `D#10`.

### Building a blob

**[V]** Build from an **empty-slot template**, not from zeros. An empty
variation still carries ~16 non-zero setting bytes per block (last-step and
similar) that matter. `backups/patterns/pattern_116.bin` was captured for this.

---

## 3. Kit blob — 1312 bytes

```
0..15            kit name, ASCII
388 + i*52       instrument record, i = 0..10 in panel order
```

Within an instrument record:

| Offset | Field | Notes |
|---|---|---|
| `+0..1` | tone | **[V]** uint16 LE, writable — verified by swapping in the 909 snare |
| `+2` | tune | **[V]** offset-binary, `0x80` = 0, range −128…+127 |
| `+3` | decay | **[V]** 0…255, default `0x80` |
| `+4` | level | **[V] READ-ONLY** — see below |
| `+6` | pan | **[V]** offset-binary, `0x80` = centre, `0x00` = L127 |
| `+7` | reverb send | **[V]** 0…255, default `0x80` |
| `+8` | delay send | **[V]** 0…255, default `0xE0` |
| `+11` | LFO depth | **[V]** 0…255 |
| `+28..+41` | envelope / gain for sample tones | **[M]** not exclusively sample fields: across 839 records on this device, ACB instruments have them set ~43% of the time and sample instruments ~95%, while a blank `----` slot has them all at zero. Individual offsets unidentified; `+37` reads `255` on working sample instruments and looks like gain |

**[V] Level cannot be set from software.** A probe of all 52 bytes found 51
writable; `+4` is the sole exception — the device overwrites it with the
physical fader position on every write. A UI can display level but never set it.

**[V] Writing a sample tone id is not enough.** A sample needs the envelope and
gain fields in `+28..+41` (`+37` reads `255` on a working instrument). A blank
`"----"` kit slot has all of them at **zero**, so assigning a sample tone there
produces a sound that plays but is almost inaudible.

**[M]** These are not a clean "sample only" marker — measured across 839
instrument records, ACB instruments populate `+29/+30/+33/+35/+37/+40` about 43%
of the time and sample instruments about 95%. So detection is a majority vote,
good enough to catch the blank-record case that actually bites.

**Build kits from a real factory kit**, and for an instrument taking a sample
tone, copy a whole 52-byte record from a working sample instrument first.
`kit.set_instrument` does this automatically (`auto_donor`).

**[V]** Tone ids are organised by machine family: 808 kicks `0–3`, 909 `26–29`,
707 `42–43`, 727 `57–58`, 606 `72`. `tr8s_kit.py tones` labels 64 of them by
reading the six single-machine factory kits.

**[V]** The CTRL knob assignment and `KIT: CTRL Sel` are **not** in the kit
blob — saving a kit after changing them altered nothing. **[I]** They most
likely live in the system blob (752 bytes); undecoded.

---

## 4. Melodies

A melody is per-step tune motion. Two mechanisms, and the second is far better.

### Fine Tune — byte `+0`

**[M]** ~**24.3 units per semitone**, linear in pitch (worst residual 0.09
semitones), measured by recording the TR-8S's own USB audio and pitch-tracking
it. The full −128…+127 range spans only **~10.5 semitones — less than an
octave**. Usable for basslines, too narrow for melodies. Works on any tone.

**[M] This is a different law from the kit's own TUNE parameter**, which was
measured separately (see below) at ~10.6 units per semitone over ±12
semitones. The per-step motion byte therefore has about 2.3× the resolution
over about 2.3× less range — a coherent trade for a field whose job is
recording knob movement. Both numbers are acoustic measurements; neither
constant may be used for the other field.

### Coarse Tune — byte `+2` — **use this**

**[V]** Stored as **semitones + 24**, i.e. exactly **one unit per semitone**,
range −24…+24 = **four octaves**. Verified: panel `+12` stored `36`, `−12`
stored `12`. Presence mask `0x09`. No calibration, no tuning error.

**Prerequisites — software supplies only the last one:**

1. **[V]** The instrument must have a **sample tone**. ACB modelled tones (the
   808/909 drums) have no Coarse Tune at all — the manual states *"Sample tone
   only"*. Assigning a sample tone also populates kit record bytes `+28..+40`.
2. Coarse Tune assigned to that instrument's CTRL knob: hold `[CTRL SELECT]`,
   press the instrument button, `[VALUE]` to choose.
3. Kit `CTRL Sel = User`: hold `[SHIFT]` + `[KIT]` → `KIT: CTRL` → `Sel`.
4. **`MOTION [ON]` lit.**

**[V]** Items 2 and 3 are **not** stored in the kit — see above.

**[V] `MOTION [ON]` gates playback entirely.** Motion is recorded and stored
regardless, but silent unless that button is lit. Software cannot set it, so
any UI must surface it as a prerequisite rather than a footnote.

---

## 5. Audio measurement

**[V]** The TR-8S is also a USB **capture** device, which makes ear-free
calibration possible.

```
arecord -D hw:1,0 -f FLOAT_LE -c 2 -r 96000
```

`FLOAT_LE` at 96 kHz is the **only** accepted format. 14 channels are offered,
giving individual instrument outputs; 2 channels gives the mix. Python's
`wave` module cannot parse IEEE-float WAVs (format tag 3) — parse manually.

`midi/pitch.py` implements a YIN detector. **Plain autocorrelation does not
work** — it always peaks at the shortest lag and reports the frequency ceiling.

---

## 6. Traps

Ranked by how much time each cost.

1. **[V] Realtime bytes hang read loops.** The TR-8S streams MIDI clock
   (`0xF8`) and active sensing continuously. Any read loop must discard bytes
   `>= 0xF8` **before** deciding whether data is still arriving, or the idle
   timeout never expires and the read blocks forever.

2. **[V] Roland's own config lies about kit reference.** It lists
   `kitReference` at `20 00 00 14` and `kitReferenceSw` at `20 00 01 06`.
   Writing either does nothing. The real field is a **single byte at pattern
   offset 18** holding the 1-based kit number. An empty template carries `01`
   there — kit 1, TR-808 — which makes a pattern with no kit set look like it
   "defaults to 808".

3. **[V] The two-argument request.** `get.<kind>` needs index *and* count.
   With only the index the device stays completely silent — no error.

4. **[V] Commit is separate.** Transfers without the commit step live in the
   edit buffer and die on power-off.

5. **[V] `PTN` vs `SYSTEM` sources.** Per-pattern tempo/shuffle/kit are inert
   unless `[UTILITY] GENERAL` points at `PTN`.

6. **[V] Recording patterns over MIDI is lossy.** `INST REC` does capture USB
   MIDI notes — the manual only mentions the pads — but it **drops ghost notes
   in dense 16th runs and occasionally shifts the last step**. Only 1 of 8 test
   variations came back byte-exact. Use SysEx; it is exact.

7. **[V] Level is device-owned**, and **[V] kit writes are not live** while
   pattern writes are.

## Kit record: the unidentified bytes, swept

All 43 unidentified offsets in a kit instrument record were swept across nine
values (0–255) on tone 465 "OSC Saw Low", with the result recorded and
measured. The honest summary is that **36 of 43 do nothing audible on this
tone.** That is the main finding, and it is worth stating plainly rather than
burying: the record is mostly sparse or holds state that a single sustained
sample tone does not reveal.

What did move:

| Offset | Reading | Confidence |
|---|---|---|
| `+32` | level or gain | medium |
| `+34` | envelope length (decay or hold) | medium |
| `+37` | filter or tone colour — brightness moves, pitch does not | medium |
| `+5`, `+28`, `+29` | **selects or switches something.** The sound changes a lot, but not *with* the value | medium |
| `+38` | unclear — something moves, nothing dominates | low |

**[V] `+5`, `+28` and `+29` are not tune parameters**, though the first pass
said they were with high confidence. Their pitch changes by 3 to 9 semitones
across the sweep, but the whole change happens between two adjacent values and
the rest of the range is flat — or, for `+29`, the pitch disappears entirely
through the middle. That is a byte selecting a sample or a mode, not tuning
one. See docs/LESSONS.md.

**[U] What this cannot tell you.** A sweep on one sustained sample tone will
miss anything that only applies to ACB tones, anything that interacts with a
parameter left at its default, and anything whose effect is inaudible in a
single unprocessed hit. "No audible effect on this tone" is a much weaker claim
than "unused", and the sweep data is kept in
`~/.local/share/tr8s/kit_byte_probe.json` so it can be re-read if a better
probe tone turns up.

## [V] Committing a kit rewrites the current pattern's kit reference

Discovered by accident, then isolated. Writing a kit and committing it causes
the machine to write that kit's index into byte 18 (the kit reference) of the
**most recently transferred pattern**. The pattern is not sent, not touched,
and not selected on the panel — it changes on the device anyway.

Reproduction:

```
pattern.set_header  slot=119  kit=10     ->  pattern 119 reads kit 10
pattern.set_header  slot=120  kit=11     ->  pattern 120 reads kit 11
write_kit + commit  kit 100
                                          ->  pattern 119 still reads kit 10
                                          ->  pattern 120 now reads kit 100
```

Only the last pattern transferred is affected; earlier ones are left alone.

**Consequence for any tool that builds a kit and a pattern together:** commit
every kit *before* writing the patterns, or the next kit you commit silently
re-points the pattern you just finished. Building four tracks in a
kit-then-pattern loop gave every pattern the *following* track's kit, which
looked like an off-by-one in the code and was not.

This is the second field the machine owns and overwrites behind a transfer,
after `level` in a kit record. Both are cases where the device's live state
wins over what was sent.

**It is not only `kit.auto_build`.** *Any* kit commit does this — `kit.fix`
and `kit.tune_to` included. Tuning a kick re-pointed an unrelated pattern that
happened to have been written a few minutes earlier.

**The library repairs it.** `Device` remembers the last pattern it transferred
and the exact bytes it sent, and re-sends them after every kit commit; the
result reports `repaired_kit_reference_of`. That costs one extra 24 KB write
per kit save, which is worth it against patterns silently re-pointing
themselves. The ordering advice above still holds for anything driving the
wire directly.


## Kit TUNE — record byte `+2`

**[M] Exactly one octave either way, linear in the byte.** Swept on tone 465
(OSC Saw Low) at seventeen points and pitch-tracked:

| byte | 0 | 32 | 64 | 96 | 128 | 160 | 192 | 224 | 255 |
|---|---|---|---|---|---|---|---|---|---|
| semitones | −11.99 | −8.99 | −6.00 | −2.99 | 0.00 | +3.03 | +6.03 | +9.10 | +11.99 |

`semitones = 24 × byte / 255 − 12` reproduces every point to within 0.05 of a
semitone. Centre is 128; the model exposes it signed (−128…127) so the stored
value is `byte − 128`.

This is what makes `kit.tune_to` possible: given a tone's measured root, the
byte that makes it sound at a named note is arithmetic rather than a hunt.

**[U]** Measured on one sustained sample tone. An ACB tone may follow a
different law, and a short sample may change character as well as pitch when
pushed an octave.

## Kit DECAY — record byte `+3`

**[M]** Swept on tone 1 (808 Bass1):

| byte | 16 | 32 | 48 | 64 | 96 | 128 | 160 | 192 | 224 |
|---|---|---|---|---|---|---|---|---|---|
| ms | 60 | 80 | 110 | 140 | 235 | 295 | 400 | 610 | 745 |

Monotonic and smooth, so interpolation between points is reasonable.

**[V] 255 does not decay** — the tone sustains.

**[V] 0 does not decay either, and is the loudest value measured** (peak 0.61
against 0.25–0.46 across the rest of the range). A value that is both louder
and longer than its neighbours is not the bottom of an envelope curve.
**[I]** it likely means "no envelope, play the sample". Not asserted; what
matters practically is that code wanting a short decay must never reach for 0.

## [U] There is no readable "current pattern"

The studio follows the machine's own pattern selection by listening for MIDI
Program Change. That works, but it depends on `Tx Prog Chg` being ON in the
machine's MIDI settings, so it was worth checking whether the current pattern
could simply be read instead. It cannot, as far as three attempts can show:

- **[V]** Sweeping every unmapped utility offset from `+0x04` to `+0x2F` turned
  up exactly one address not already known, `+0x15`, which returns a single
  `0x00`. `+0x10` ("playing status") is one byte and carries no pattern number.
- **[V]** The 752-byte system blob is **byte-identical** before and after
  sending a Program Change that should have changed the pattern. Either the
  current pattern is not stored there, or the machine ignored the message.
- **[V]** The machine does not echo a Program Change it receives, so that
  cannot be used to confirm the selection either.

The two possibilities are not separable from software alone: a machine with
`Rx Prog Chg` off looks exactly like one whose current pattern is not in the
system blob. Anyone with the panel in front of them can settle it in a second
by watching the display while the message is sent.

## Kit header `+42…+52` — per-instrument fader colour

The TR-8S lights each channel fader a colour, and the colour is saved with the
kit. **[I]** These eleven bytes are it — one per instrument, in `TRACKS` order,
values `0..11`.

Identified statistically rather than by watching the panel, so the reasoning
matters:

- Across 128 factory kits it is the only run of exactly eleven consecutive
  bytes sharing a small palette.
- The values vary between kits, and within a kit between instruments.
- An **empty** kit (`----`) still carries `[0,1,3,3,3,1,1,2,2,2,2]`, which
  groups by category: kick, snare, the three toms together, rimshot and clap
  together, the four hats and cymbals together. That is the shape a factory
  colour scheme has and is not the shape of a parameter.
- A demo kit (`Last Step DEMO`) carries a visibly custom scheme,
  `[7,7,0,1,1,6,7,8,8,6,5]`.

**[U] The palette is not confirmed.** Which index lights which colour has never
been checked against the machine — the names in `kit.COLOUR_NAMES` are labels
fitted to the default scheme and to product photography, nothing stronger.
Kit 125 has been written with indices `0..10` across the eleven instruments, so
looking at that kit on the panel settles the whole mapping in one glance.

A second eleven-byte run at `+285…+295` also varies per instrument, with a
wider range (`0..35`). **[U]** Unidentified.

## [V] Pattern selection is announced on two channels at once

With `Tx Prog Chg` ON, changing a pattern on the panel sends **two** Program
Changes, a few milliseconds apart, on different channels. Captured live:

```
ch 10  value   1        ch 1  value  25      -> pattern 1-02, kit 26
ch 10  value   0        ch 1  value 124      -> pattern 1-01, kit 125
```

Channel 10 (`Pattern Ch`) carries the **pattern**, 0-based, mapping directly to
a slot. Channel 1 (`Kit Ch`) carries that pattern's **kit**. Both are user
settable in `UTILITY → MIDI`; the values above are what this machine had.

**This is a trap for anything that follows pattern selection.** Both messages
are a bare 0-127 with nothing to distinguish them, so listening on any channel
and taking the last message means following the *kit* number as though it were
a pattern. Selecting `1-01` sent kit `124`, which reads as pattern slot 124 —
panel `8-13`. The view lands somewhere entirely unrelated and looks like an
off-by-a-lot bug in the slot arithmetic.

**What separates them is that the two numbers are not independent:** the kit
announcement equals the kit reference stored *inside* the pattern the other
message names. `Studio._learn_channel` reads the candidates and checks which
way round that holds, which settles both channels from a single pattern change
without the user configuring anything. If neither direction holds it says so
rather than guessing.

## [V] Transport, and what the machine does and does not say

Measured directly, by sending messages and listening:

- **The TR-8S sends MIDI Clock continuously**, whether or not it is playing.
  `clock_seen` is therefore not evidence of playback.
- **It acts on MIDI Start (`0xFA`) and Stop (`0xFC`)** — sending Start makes it
  play. **[V]** It does **not** echo them back, so a program that starts the
  machine itself never sees a Start and must not use that to decide whether it
  is playing. Notes are the reliable signal.
- **[V] It does not act on a Program Change** on the pattern channel — sending
  one changed nothing audible. `Rx Prog Chg` was presumably off; `Tx` was on.
  Transmit and receive are separate settings.

**[V] Every instrument transmits a note when it sounds**, from the MIDI
Implementation Chart (v1.10) and confirmed on the wire:

| BD | SD | LT | MT | HT | RS | HC | CH | OH | CC | RC |
|---|---|---|---|---|---|---|---|---|---|---|
| 36 | 38 | 43 | 47 | 50 | 37 | 39 | 42 | 46 | 49 | 51 |

Remappable at `UTILITY:MIDI:Inst Note`.

## [V] The A–H variation is never announced — but it can be heard

The MIDI Implementation Chart has no message for variation, and none was
observed. There is nothing to subscribe to.

What there *is*: the notes above, plus a free-running clock giving a step
position. Collecting `(step, instrument)` over a couple of bars and comparing
against each of A–H identifies the one playing. Confirmed against the machine:
listening to a pattern it was already playing scored `1.0` for the right
variation, with the next best pattern in the whole bank at `0.95`.

Two details that matter:

**Match every rotation.** Without a received Start the step counter's phase is
arbitrary, so the heard bar is offset from the pattern by an unknown amount.
Comparing at a fixed alignment fails completely; comparing at all sixteen
rotations and taking the best works.

**Refuse a narrow win.** Variations of one pattern share most of their steps.
The winner has to beat the runner-up by a clear margin, or the honest answer is
that it cannot be told.

## [V] The machine can be driven: selecting a pattern over SysEx

Roland's own web client does not use Program Change to move the machine. It
writes three parameters in a **`temp` address space** that this project had
never touched — every earlier sweep was of the `utility` space at `50 00 00 00`.

| name | address | size |
|---|---|---|
| `currentKit` | `01 00 00 00` | 1 |
| `currentPattern` | `01 00 00 01` | 1 |
| `nextPattern` | `01 00 00 02` | 1 |
| `patternSelect` | `01 00 00 1B` | 4 |

To move to pattern *n*, send three DT1 messages: `currentPattern = n`,
`nextPattern = n`, and `patternSelect` as the four nibbles of `1 << (n % 16)`
— a bitmask of which pad in the bank is lit. **[V]** Sending only the first
does not move it.

**[V] These are write-only.** An RQ1 to any of them returns nothing, which is
why sweeping for a readable "current pattern" found nothing: it is not that the
address does not exist, it is that it cannot be read.

**[V] This works with `Rx Prog Chg` OFF**, which is the state this machine is
in — a Program Change to the same slot does nothing, while these writes move it
immediately. Verified by selecting two patterns in turn and listening: the
audio changed to match each one.

Why it matters beyond convenience: together with recognising what is playing
from the notes, it closes a loop. The machine can be put in a known state and
the result checked, without anyone touching the panel — which is what makes it
possible to find things like this one automatically.

## [V] What the panel transmits, measured with every Tx setting ON

With `Tx Prog Chg`, `Tx EditData` and `Auto Save` all ON, pressing things on
the panel and logging every byte:

| action | transmitted |
|---|---|
| select a pattern | Program Change on `Pattern Ch` **and** its kit on `Kit Ch` |
| START / STOP | `FA` / `FC` |
| a pattern playing | one note per instrument hit, on `Pattern Ch` |
| **press A–H** | **nothing** |
| **enter a step in TR-REC** | **nothing** |
| turn a knob | a Control Change (Tx EditData) |

**The variation and step edits are not on MIDI at all.** Not with any setting.
The MIDI Implementation Chart has no message for either; the address table in
Roland's own client has no variation parameter; a sweep of the live-state
address space (which crashed the machine — do not repeat it) found nothing.
This is a property of the hardware.

**What works instead, verified on the machine:**

- **The variation is recognised from what plays.** Notes plus the clock give
  `(step, instrument)` pairs; matched against every variation's fingerprint at
  all sixteen rotations, the one playing scores 1.0 and locks in within one
  bar (4 s at 140 BPM). Three selections in a row all identified correctly.
- **A step entered on the machine is noticed by ear.** The sequencer plays it
  on the next pass; hits that arrive which the held pattern cannot explain
  trigger a single read. Crash hits written into a playing pattern over the
  raw wire appeared in the studio 12 s later.

**The boundary:** both need the pattern to be *playing*. While the machine is
stopped there is no audio and no message, so a variation pressed or a step
entered while stopped is invisible until START — at which point both catch up
within a bar. That is the hardware's limit, not a missing setting.

## [V] CC 2 is the beat counter — the bar phase, sent outright

With `Tx EditData` ON, the machine sends `CC 2` on `Pattern Ch` once per beat
while playing, cycling `0 1 2 3`. Measured against the accented downbeat kick:
`CC 2 = 0` lands within 10 ms of it every time, and the interval between CCs is
one beat (0.345 s at 174 BPM).

This is the bar phase that recognition had been recovering by trying all
sixteen rotations. With it, the free-running step counter is re-anchored on
every beat, notes land on their true step, and a variation change shows within
a bar of being pressed.

## [V] Bulk reads hang while the machine is playing

A pattern read (`get.pattern`) issued during playback does not fail — it gets
**no reply and waits out the full timeout** (measured: 25.6 s), holding the
port and freezing everything queued behind it. Three attempts while playing,
three hangs; three attempts stopped, three immediate successes.

`Device.read_pattern` / `read_kit` now refuse outright while the studio knows
the machine is playing (0.03 s instead of 25 s). Anything that needs a read
during playback — following to a newly recognised pattern, re-reading after an
edit heard by ear — is served from the byte cache or the fingerprint index and
queued for a real read the moment playback stops.

## [V] The transport must deliver bytes in arrival order

Not a machine finding; a bug of ours that masqueraded as one. The reader split
each `os.read` chunk into a pile of realtime bytes and a pile of channel bytes
and delivered the clocks first. Every note in a 4 KB chunk was then stamped
with the step after the chunk's *last* clock. At 174 BPM a chunk spans several
steps, so the live picture smeared by up to a beat and recognition scored
0.7 against the right variation. Delivering in order fixed both at once.

## [V] Every knob and fader is a named Control Change

The MIDI Implementation Chart names each transmitted controller — but the
label column only survives when the PDF is extracted with layout preserved
(`pdftotext -layout`). Without it the numbers come out as a bare list and the
names are lost, which is why this went unread until now.

With `UTILITY:MIDI:Tx EditData = ON`, on `Pattern Ch`:

| | TUNE | DECAY | LEVEL | CTRL |
|---|---|---|---|---|
| BD | 20 | 23 | 24 | 96 |
| SD | 25 | 28 | 29 | 97 |
| LT | 46 | 47 | 48 | 102 |
| MT | 49 | 50 | 51 | 103 |
| HT | 52 | 53 | 54 | 104 |
| RS | 55 | 56 | 57 | 105 |
| HC | 58 | 59 | 60 | 106 |
| CH | 61 | 62 | 63 | 107 |
| OH | 80 | 81 | 82 | 108 |
| CC | 83 | 84 | 85 | 109 |
| RC | 86 | 87 | 88 | 110 |

Master: `9` shuffle, `12` ext-in level, `15` master FX on, `16/17/18` delay
level/time/feedback, `19` master FX ctrl, `71` accent, `91` reverb level.
`14` (auto fill on) and `70` (manual trig) only with `LocalSw = SURFACE`.
`2` is the beat counter, not a control.

Values are 7-bit (0–127); the kit stores 8-bit. TUNE is centred at 64 on the
wire and 0 (signed) in the kit model — `ccmap.to_kit_value` converts.

**This is also the fader position.** LEVEL is the one kit field software could
never write, because the physical fader owns it; but the fader *reports* over
CC, so the on-screen fader can at last follow the real one.

**[V] A received CC is applied but not echoed.** Sending `BD TUNE = 110` to
the machine changes the sound; nothing comes back on the wire. Same as Program
Change. So the studio cannot confirm a value it sent by listening for it, and
only a *physical* move produces a CC — which is also why the on-screen knobs
follow the panel and not the other way round without a write.

## [V] User samples: the format and the import sequence

Read off one of the machine's own user samples (tone 624), not assumed:

- **Audio format: 16-bit signed little-endian PCM, mono, 44.1 kHz.** The
  pcmTone record's frame count divided by its byte span came to 2.00 exactly,
  and a slice read back decoded as a smooth waveform.
- **Sample memory** is a flat byte space, 13,631,488 … 67,108,863, allocated
  in 128 KB sectors. `free_area` returns three 7-bit-packed u32s: total free,
  longest free run, top free address.
- **User tones are ids 624 … 1023.** `free_tone` returns the next free id.

The 64-byte pcmTone record:

| offset | field |
|---|---|
| +0 / +4 | u32 start / end address (left) |
| +8 / +12 | u32 start / end address (right; == left for mono) |
| +16 / +20 | u32 frames, twice |
| +24 | u32 sample rate (44100) |
| +28 | `02 12 00 00 00 15 00 15`, meaning unknown, constant |
| +56 | channels |

The 36-byte tone record: 16-char name, category at +16, type at +17
(2 = sample), zeros.

**Import, exactly as Roland's client does it (verified end to end):**
`free_area` → `send sample` to the top free address → `free_tone` → send the
tone record → send the pcmTone record → commit the tone. A 48 kHz stereo
24-bit WAV went in as tone 651, read back byte-exact, and played on BD.

`send_blob` had capped every slot at 127; tone slots run to 1023.

## [V] The pcmTone record, corrected

The layout in the earlier section was wrong in three fields. Read off three
loaded mono samples (624, 650, 733), which all agree:

| offset | field |
|---|---|
| +0 / +4 | u32 start / end address |
| +8 | u32 **byte length** (not a right-channel address) |
| +12 | u32 zero |
| +16 / +20 | u32 frames, twice |
| +24 | u32 sample rate, 44100 |
| +28 | `02 12 00 00 00 15 00 15`, constant |
| +36 | `03 65 05 30 02 83 63 24`, constant |
| +44 | u32, **per-sample, no fixed ratio to length** — copied from a known-good record |
| +56 | zero (not a channel count) |

A record with the old layout was accepted for playback but is not what the
machine writes. `samples.pcm_tone_record` now produces the real one.

## [V] `deleteTone` is dead on firmware 2.51; reuse a slot instead

Roland's three-step delete — `temp.tone.category = 1`, utility `deleteTone`
with the id, commit — answers `01` **for every id and every argument shape**:
2-byte and 4-byte 7-bit, raw, offset from 624, an empty user slot, a factory
import, and an empty argument. It answers `01` with the system lock at 0 too.
It is not refusing a tone; the command is unavailable on this firmware.

**What works instead — verified end to end:** write the new sample over a
tone's *own span* (from its pcmTone record), rebuild its tone and pcmTone
records, commit. The slot recycles, the sample plays, and no memory is
consumed. `sample.import(reuse_tone=N)` does this. A replacement must fit in
the span it reuses.

**On the free-space index.** After a handful of imports the machine reports a
longest free run of ~900 bytes with ~7 MB free in total — shredded. Its own
`optimize` answers 101 ("nothing to do") and a whole-store commit changes
nothing, so it considers that state consistent. A full walk of every user
tone's span shows 22.4 MB in use and **23.75 MB allocated to no tone**, so the
fragmentation is real allocation, not a decode error. Fresh imports therefore
fail to fit; reuse does not need the free list at all. The `temp.tone` space
is write-only (an RQ1 returns nothing), so the live state cannot be read
back. A factory reset would restore the index; nothing in the samples is lost.

The 1.47 MB gaps between the FX presets (tones 733–738, each 1.41 MB) are the
machine's own allocation slack, not damage.

## [V] Heavy sample-index writing crashes the machine (needs a power cycle)

After a run of sample writes — imports, record rebuilds, `deleteTone` probes,
optimize calls — the TR-8S stopped responding entirely: no clock, no reply to
a version request. Same symptom as an earlier crash caused by writing to
`temp` addresses. A power cycle recovers it; nothing in stored memory is lost.

So the sample tools work (each step verified individually before the crash:
reuse-import played on HT, the browser upload route assigned and played, the
name refreshed through the catalogue), but hammering the index in a tight loop
is not safe. Space the writes out, and expect a power cycle after a heavy
session. This is an accepted cost here — the user green-lit factory-reset-level
risk — but worth stating so it is not mistaken for a code bug.

## [V] The sequencer transmits per-step accent as a LEVEL Control Change

With `Tx EditData` on, a playing pattern streams each instrument's per-step
accent as its LEVEL CC — the snare alone sent SD LEVEL (CC 29) 232 times in
six seconds. This is automation, not the physical fader and not a human
editing a sound. So: LEVEL CCs never move the studio's TRACK selection (only
TUNE/DECAY/CTRL do), and the on-screen fader ignores LEVEL CCs while playing so
it shows the fader position rather than the accent stream.

## [V] select() serves the cache during playback instead of raising

A tool-result refresh (or the follower) used to call the pattern read that
hangs while playing, surfacing "cannot read pattern … while the machine is
playing" into the chat. `Studio.select` now returns the bytes it already holds
(from before playback, or the fingerprint index) when the machine is playing,
and queues a real read for when it stops — the caller never sees the error.

## Following panel step-edits (which send nothing over MIDI)

A step entered on the machine transmits no MIDI at all, so the only way to see
it is to read the pattern back and diff. While the machine is STOPPED the
studio polls the current pattern every ~2.5s (a read is ~0.6s and disturbs
nothing while stopped; it never runs during playback, where reads hang). When
the bytes change, `_resync` diffs the per-instrument step strings and reports
the changed instruments, and the UI — if TRACK-follow is on — selects the one
that changed and shows the new steps.

TRACK-follow triggers: a step edit (this diff), and a TUNE/DECAY/CTRL Control
Change (a knob). It deliberately does NOT trigger on a LEVEL CC — that is the
fader, which players ride constantly, and the per-step accent the sequencer
streams while playing. Faders never move the selection.

## Detecting panel edits: MIDI read-back, not sound

An earlier version tried to notice a step entered on the machine by *hearing*
it — matching played notes against the pattern. It was unreliable and is gone.
The deterministic path is the only one now: read the pattern back over SysEx
and diff it. Reads hang during playback, so a step entered while playing is
noticed when the sequencer stops (the after-stop read) or by the ~2.5s
stopped-poll — a bar or two of lag, which is acceptable and reliable. Knobs and
faders remain immediate, since those the machine *does* transmit (Control
Change).
