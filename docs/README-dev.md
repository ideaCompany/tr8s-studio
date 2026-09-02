# tr8s

Drive a Roland TR-8S over USB — patterns, kits and melodies — from code, or by
talking to an LLM that calls these tools.

The TR-8S's SysEx implementation is undocumented. This is a reverse-engineered
one, verified against real hardware (firmware 2.51). What it does:

- **Patterns** — read, author and write byte-exact, with tempo, shuffle, scale
  and kit assignment. A write changes what is *currently playing* straight away,
  so editing is interactive.
- **Kits** — pick the sound per instrument, tune it, shape decay, place it in
  the stereo field, set both effect sends.
- **Melodies** — per-step Coarse Tune motion, four octaves, exact semitones.
  The thing the hardware makes almost impossible by hand.
- **Tone catalogue** — every melodic tone measured for its *actual* root pitch,
  loudness, decay and brightness, so sounds are chosen from data, not names.

## Quick start

```bash
export PYTHONPATH=$PWD/src
python3 -m tr8s.cli info
python3 -m tr8s.cli tools                       # every command + schema
python3 -m tr8s.cli patterns 0 15
python3 -m tr8s.cli tones --category BASS --melodic
python3 -m tr8s.cli backup                      # all 128 patterns and kits
python3 -m tr8s.cli analyse-tones               # measure every tone (unattended)
python3 -m tr8s.cli probe-byte 12               # what does kit byte +12 do?
```

From Python, or from an LLM harness:

```python
from tr8s.tools import call, schemas

schemas()                                        # hand these to the model

call("tones.search", {"category": "BASS", "melodic": True, "darker_than": 300})
call("kit.create", {"slot": 122, "name": "MELODIC TECHNO", "from_kit": 1,
                    "sample_donor": {"kit": 61, "instrument": "LT"},
                    "instruments": {"LT": {"tone": 465, "decay": 150}}})
call("pattern.set_many", {"slot": "8-07", "variation": "A",
                          "tracks": {"BD": "X...x...X...x...",
                                     "CH": "..x...x...x...x."}})
call("pattern.set_melody", {"slot": "8-07", "variation": "C", "instrument": "LT",
                            "notes": "C2 . G2 C3 . D#3 G3 .", "root": "C2"})
```

`root` should come from `tones.search`, never a guess — Coarse Tune is relative
to the sample's own pitch, and getting it wrong transposes the whole line.

Step notation: `X` accent, `x` normal, `o` ghost, `.` rest. Slots accept
`0..127` or a panel string like `"8-03"`.

## Making music

The generators are the interface; hand-typed step strings do not survive a
request like "same but sparser".

```
track.create                 the whole thing in one call: kit, all eight
                             variations arranged, a bassline in key, and an
                             audit of the result
track.remix                  another one like that — keeps the kit, key and
                             tempo, rerolls the rest
styles.list                  techno, hypnotic, dub, acid, hard, broken, dnb,
                             lofi, house — with what each one means
kit.auto_build               picks every tone from the MEASURED catalogue: a
                             kick whose pitch is in the key, parts kept off
                             each other's brightness, sustained sample tones
                             on the melodic tracks
pattern.arrange              fills A–H as one track: intro, main, fill,
                             break, drop, peak
pattern.generate             one variation, at an energy, with a seed
pattern.set_line             bass / acid / stab / arp, in key — looks the
                             tone's real root up so the line is not transposed
pattern.audit                what is wrong with a variation, from the
                             measured tones and where the hits land
kit.fix                      acts on it — shortens a decay that rings past
                             the next hit, using a measured curve
kit.tune_to                  makes an instrument sound at a named note
history.undo                 put back what the last edit overwrote
kit.swap                     change a sound by description — "a darker kick",
                             "much shorter" — from the measured catalogue
kit.neighbours               the tones most like the one an instrument has
sample.import                put a WAV on the machine as a user tone (any
                             PCM WAV; resampled to the machine's 16-bit mono
                             44.1 kHz) and optionally assign it
sample.space                 how much sample memory is free
```

Two kit parameters have been measured against the machine's own output rather
than assumed, which is what makes the last two possible: `TUNE` is exactly one
octave either way, linear in the byte; `DECAY` runs 60 ms to 745 ms over bytes
16–224, with 0 and 255 both meaning "does not decay". `calibration.describe`
returns the curves and their caveats.

Energy is not a density knob. Raising it adds layers in the order a producer
would: the open hat arrives, the hats subdivide to 16ths, the ride comes in,
then ghost notes fill the gaps. Every generator reports its seed, so a bar you
liked can be asked for again — a different seed is a different pattern.

## The change log

Every change to the kit and patterns is logged this session, tagged by who did
it: **you · panel** (a knob, fader or step on the machine), **you · studio** (a
click in the browser UI), or **AI** (a tool the chat assistant ran). The LOG
button in the header opens it; it is on by default and toggles there. It is the
memory an AI collaborator will use to reason about a track's history — and it
answers "what just changed and who did it" while developing.

Panel edits are detected by reading the pattern back and diffing, not by
listening to the audio (which proved unreliable). Steps entered while the
sequencer plays show up when it stops or within a couple of seconds of the
stopped-poll; knobs and faders are immediate.

## Following the machine

The studio can follow the pattern you select on the TR-8S, but the machine only
announces it if you switch that on:

1. Press **[UTILITY]**
2. Turn **[VALUE]** to **MIDI: Tx Prog Chg**, press **[ENTER]**
3. Turn **[VALUE]** to **ON**
4. Press **[UTILITY]** again to leave

If **UTILITY → GENERAL: Auto Save** is **OFF**, press **[WRITE]** once so it
survives a power cycle.

The FOLLOW readout in the header shows `WAITING` until the machine speaks, then
`ON`. Clicking it while waiting brings up these steps.

**Knobs and faders follow the machine.** With `UTILITY → MIDI → Tx EditData`
ON, every TUNE, DECAY, CTRL and fader on all eleven strips, plus accent,
reverb, delay, master FX and shuffle, sends a named Control Change (the map is
in `docs/PROTOCOL.md`). The studio moves the matching control on screen and
flashes it. This is one-way by nature — a CC the studio *sends* is applied but
never echoed — so the screen follows the panel; writing the other way goes
through the kit tools as before.

**A–H and step edits.** The machine transmits nothing for either — checked
with every Tx setting on, and against the MIDI implementation chart and
Roland's own client. So while a pattern **plays**, the studio listens: every
note lights its step on the grid live, and the variation is recognised from
the sound within a bar. With `Tx EditData` ON the machine also sends its beat
counter (`CC 2`), which fixes the bar phase exactly. While stopped there is
nothing to hear, so a press made then appears on the next START. One hard rule
follows from the hardware: **bulk reads hang while the machine plays** (25 s,
measured), so the studio never reads during playback and catches up the moment
it stops.

Two caveats worth knowing. The same MIDI menu has **Pattern Ch** and **Kit Ch**;
switching a kit sends a program change too, and since both carry a bare 0–127
only the channel separates them — the studio can be pinned to one channel from
that dialog if the view ever jumps somewhere odd. And there is no way to *read*
the current pattern instead: every unmapped utility address returns nothing
useful, the system blob is byte-identical across a pattern change, and the
machine does not echo a program change it receives. Program Change is the only
route it offers.

## Colours

The TR-8S lights each fader a colour that is saved with the kit. Those eleven
bytes were found in the kit header and the studio reads them, so the channel
strips are lit the way the machine is. Click the chip under any instrument to
change one — it writes to the kit.

Which palette index is which colour is **inferred, not confirmed**. Kit 125 has
been written with indices 0–10 across the eleven instruments, so one look at
that kit on the panel settles it.

## The library

`library/` holds nine finished tracks as JSON — every variation, the melodies
as note names, and the style, key and seed each was built from. Verified to
round-trip through the machine byte-for-byte, so they are a real backup and not
just a listing. `library/README.md` says what each one is.

```
tr8s call pattern.import '{"slot": "8-12", "pattern": <the json>}'
```

## Changing sounds

The panel is laid out instruments, then steps, then the SOUND bar for the
selected instrument: its tone with measured pitch, decay and brightness, and
the six tones nearest to it. **Click a sound, then click an instrument lane**
to put it there — the lanes light up as targets while a sound is held, and
ESC or DROP lets go. Click the same sound twice to hear it on the selected
instrument first. Type "darker", "a bit shorter", "brighter and longer" to
get candidates that move that way; `BROWSE` opens the whole catalogue.

All of it works while the pattern is playing, as on the panel — only bulk
*reads* hang during playback, and a swap needs none.

`sample.import` puts a WAV from disk on the machine as a new user tone; the
format and the sequence were read off the machine's own samples and verified
byte-exact. One caution in `docs/PROTOCOL.md`: deleting a tone over SysEx is
refused on this machine and a test tone (651) is still on it.

## Testing against the machine

```
PYTHONPATH=src .venv/bin/python tests/hardware/selftest.py
```

Runs the whole stack against a real TR-8S: a byte-exact pattern round trip, the
kit-reference repair, the TUNE calibration, transport, note decoding, the clock,
and variation recognition. It writes only to a scratch slot and puts the
original back, including when a check raises.

Every check reports pass, **fail**, or skipped-with-a-reason. A check that
cannot run is never counted as a pass — which is how it caught the matcher
naming a variation of a pattern the machine was not playing.

## Trying it without a TR-8S

```
tr8s-studio --offline
```

Runs the whole studio against an in-memory machine: three demo patterns, a kit
built from real measured tone IDs, and two melodies. Edits behave exactly as
they do on hardware — they land in the slot immediately, and `level` is taken
back by the faders on every write — so the UI can be worked on, and the
behaviour demonstrated, with nothing plugged in. See `src/tr8s/demo.py`.

## Five things the hardware imposes

These cannot be abstracted away, so the API states them rather than hiding
them:

1. **`MOTION [ON]` must be lit** for any melody to be audible. Software cannot
   set it.
2. **Coarse Tune must be on that instrument's CTRL knob**, and nothing here can
   check it — the assignment is system state, not part of the kit. Byte `+2`
   carries whatever that knob controls, so a factory pattern's CTRL motion is
   as likely to be a pan sweep as a melody. `pattern.export` reports raw values
   unless you assert `ctrl_is_coarse_tune`.
3. **Coarse Tune exists only on sample tones.** ACB modelled tones (the 808/909
   drums) have no semitone control at all. `tones.search(melodic=True)` filters
   to the ones that work.
4. **Level is owned by the physical faders.** It can be read, never written.
5. **Per-pattern tempo, shuffle and kit need `UTILITY GENERAL` set to `PTN`.**
   On `SYSTEM` the panel knobs win and the header is silently ignored.

## Layout

```
src/tr8s/             the package -- see docs/ARCHITECTURE.md
src/tr8s/tools/       the 47 tools, one module per namespace; _core.py is
                      the registry and the helpers they share
src/tr8s/web/         the studio UI (no build step)
tests/                offline tests: run `pytest` with PYTHONPATH=src
docs/PROTOCOL.md      the wire format and every decoded byte, marked
                      [V]erified / [M]easured / [I]nferred
docs/LESSONS.md       how it was reverse-engineered, and what went wrong
docs/ARCHITECTURE.md  layers, conventions, what is still missing
midi/                 the original exploratory scripts (hardcoded paths,
                      superseded by the package, but they produced the
                      content currently on the machine)
```

Data — backups, the tone catalogue, the authoring template — lives under
`$TR8S_DATA`, defaulting to `~/.local/share/tr8s`.

## Safety

**There is no undo, and `commit: false` is not one.** Any transfer changes the
slot immediately — the commit step only adds durability across power-off. Read a
slot before overwriting it.

`device.backup` pulls all 128 patterns and kits to disk; `device.restore` puts
one back. Do that before writing anything you would miss. Every write reports
`verified` from a read-back comparison.

## The studio, and MCP

```bash
python3 -m tr8s.server           # http://127.0.0.1:8733
```

A terminal-styled web UI with two views of the machine, plus a chat panel.

**PANEL** is a representation of the TR-8S itself: eleven channel strips whose
faders sit at their *real* positions (level is written by the hardware fader, so
the UI can read it even though it can never set it), TUNE/DECAY/PAN knobs, the
tone loaded on each instrument, variation lamps, and the sixteen step pads.
Select an instrument and the pads show its steps, exactly like TR-REC.

**GRID** shows all eleven instruments at once, with note names on any
instrument carrying tune motion.

Both follow the TR-8S's own MIDI clock, so the playhead and BPM readout are the
real machine. Click a step to edit — about 0.4s, so it tracks the loop.

Click a tone name to open the **tone picker**: every tone with its measured root,
decay and brightness, filterable by category, so you choose a sound by character
rather than by name. The **pattern browser** (▤) indexes all 128 slots in the
background and lets you jump to any of them.

Five themes; the whole palette is CSS custom properties on `:root`.

The chat needs `ANTHROPIC_API_KEY` (or `ant auth login`). Without one the
machine view still works, and the MCP server needs no key of its own:

```bash
python3 -m tr8s.mcp_server       # JSON-RPC 2.0 on stdio
```

```json
{"mcpServers": {"tr8s": {"command": "tr8s-mcp"}}}
```

All 23 tools plus three resources (device state, the tone catalogue, and the
hardware constraints an agent must not promise around).

## Status

Working, and used to build real tracks. `pytest` covers the models offline
against captured blobs (41 tests, no hardware needed). Remaining gaps are listed
at the end of `docs/ARCHITECTURE.md`.
