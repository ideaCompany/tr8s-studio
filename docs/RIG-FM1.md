# The rig: TR-8S + FM-1 + EMP16

Written 2026-11-08. This is the plan for growing the studio from one drum
machine into a small live techno rig, in two modes:

- **Jam mode.** The Mac is connected. You talk to the assistant ("bring in a
  dub stab", "make the acid nastier", "drop the pad for the break") and it
  writes drums to the TR-8S and synth parts to the FM-1 while they play. What
  you keep gets saved on the boxes.
- **Live mode.** No laptop. The TR-8S, the EMP16 and the FM-1 play what Jam
  mode saved, by hand, from a printed cue sheet.

The cables are the same in both modes, and the laptop never sends MIDI clock.
Unplugging it changes nothing about timing.

Nothing here is built yet. The work is split into issues in
[`docs/issues/`](issues/), numbered in the order they unblock each other.

Each fact about hardware or firmware we have not run ourselves is marked, in the
spirit of [`PROTOCOL.md`](PROTOCOL.md):

- **[D]** documented: the firmware's README or manual, or Roland's
  documentation, says so. We have not seen it on our hardware.
- **[?]** to verify: likely, but needs a hand on the hardware before anything
  depends on it.

Nothing is **[V]** yet. Issue 01 exists to change that.

## The machines

| Box | Role |
|---|---|
| Roland TR-8S | Master clock, drums, mixer. The FM-1 comes in on its EXT IN, so the TR-8S's sidechain and master FX apply to the synth too. |
| M-VAVE FM-1 | The synths: acid, and everything that is not acid. Runs a forked open-source firmware (below). |
| Avatar EMP16 | Hands on the FM-1: knobs for filter and sends, pads to bring parts in. Sits in the MIDI chain with thru. |
| Mac (Jam mode only) | The studio and the assistant. Talks to the TR-8S and the FM-1 over their own USB cables. |

## 1. Architecture

### Two modes, one set of cables

```
 Jam mode (Mac connected)                      Live mode (no laptop)
 ────────────────────────                      ─────────────────────
 Mac: studio + assistant                       (nothing)
   ├─ USB ── TR-8S  (patterns, follow)
   └─ USB ── FM-1   (parts, knobs, save)

 Both modes, always:
   TR-8S MIDI OUT ──► EMP16 MIDI IN │ thru + its own knobs/pads │ EMP16 MIDI OUT ──► FM-1 TRS MIDI IN
   FM-1 audio out ──► TR-8S EXT IN L/R  (sidechained on BD, through the master FX)
```

The DIN/TRS chain carries the clock, Start/Stop and the EMP16's controls in
both modes. USB to the Mac carries only editing traffic, never clock.

### What the studio gains

**A macOS backend for the TR-8S** (issue 00). `transport.py` does two jobs
today. One is the operating system's port: `os.open` on an ALSA rawmidi node
and a reader thread, which only exists on Linux (`config.find_port`). The other
is the protocol: demultiplexing realtime, SysEx and channel bytes in arrival
order, the `_io` lock, and blob framing. Split them:

- A `MidiBackend` interface that delivers bytes in arrival order and sends bytes.
- `RawMidiBackend`: today's Linux code, moved, not changed.
- `RtMidiBackend`: CoreMIDI through `python-rtmidi`, as an optional extra so the
  core keeps zero dependencies. Use callback mode, not polling, since a 24 KB
  blob read overflows rtmidi's polling queue. Receive SysEx and timing
  (`ignore_types(sysex=False, timing=False, active_sense=True)`).
- Port discovery by name on macOS. **[?]** The TR-8S's CoreMIDI port names.

The arrival-order rule (`transport.py`, the comment in `_reader`, and
LESSONS.md) is the thing most likely to break in a port. It lives in the
shared layer, so both backends inherit it.

USB audio capture (`audio.py` runs `arecord`) is Linux-only too. Only the
optional mix check below needs it, so it is not part of issue 00.

**Synth parts that are not all acid** (issue 04). `lines.py` already makes
`bass`, `acid`, `stab` and `arp` lines, seeded and in key. Two things stop them
from serving the FM-1 as they are:

- `_finish` clamps every note to the TR-8S's Coarse Tune reach (±24 semitones
  from the tone's root). The FM-1 has no such limit.
- `acid()` returns accents but no slides, and a 303 line without slides is
  half a 303 line.

A new `src/tr8s/synth/` package:

- **`line.py`** has a step model, `SynthStep(notes, force, slide, tie, ratchet)`.
  It covers every existing shape without the clamp, plus `pad` and `drone` (long
  tied chords) and `lead`. Acid gains slides, placed only between two notes and
  never into a rest. Lines can be 16, 32 or 64 steps, on a Euclidean rhythm
  from `style.euclid` when asked. Extract a shared core from `lines.py` so the
  TR-8S path stays byte-identical, and let the existing tests prove it.
- **`minitone.py`** is the firmware profile: engines, MIDI channels, the CC map,
  and the 8-voice budget (warn when the parts' polyphony goes over it).
  - `to_syx(project)` produces the SysEx that writes a whole FM-1 project. Its
    exact form waits on the protocol spike (issue 02).
  - `to_mid(parts)` produces a multi-channel MIDI file, for listening checks
    and as a fallback any player can send.
  - EUCLID and STOCHASTIC generator settings are written as track settings, so
    the FM-1 keeps varying on stage with no host.
- **`port.py`** is the FM-1's USB port, through `python-rtmidi`. It sends SysEx,
  waits for each reply, and **refuses to send realtime bytes (`F8`–`FC`)**, so
  the studio can never become a second clock.

**A voicing per song, so not every track is acid** (issue 04). A table like
`DEFAULT_LINE` in `tools/_core.py` decides which FM-1 parts a style gets and on
which engine:

| Style | FM-1 parts |
|---|---|
| acid | TB303 acid + bass |
| hypnotic | SWARM drone + WAVETONE arp; a TB303 may come in late |
| dub | FMTONE stab + SWARM pad |
| techno | DUALVCO bass + ANALOG4 stab |
| peak | TB303 + DUALVCO lead |

A song with no 303 is an ordinary case, not an exception. Any track can
override its voicing.

**Parts that enter with the arrangement** (issue 05). `pattern.arrange`
already shapes A–H as intro, main, fill, break and peak against an energy
curve. The same curve decides when each FM-1 part comes in: the pad holds
through the break, the acid arrives with the main groove. On the FM-1 that
becomes song sections A–D with parts muted per section. On paper it is the cue
sheet line "pad 2 in at the break".

**Tools** (issues 05 and 06), a new `synth` namespace added to the list in
`tools/__init__.py`:

- `synth.parts` (pure): generate the parts for a style.
- `synth.export`: write `.syx`, `.mid` and `.json` into the library.
- `synth.send` (mutates): push parts to a connected FM-1.
- `track.create` and `track.remix` take an optional `synth` argument and build
  the FM-1 parts from the same key, tempo, seed and arrangement as the drums.
  The TR-8S's own melodic line then defaults to `none`.
- Library JSON gains an optional `"synth"` block.
- `set.build`: an ordered list of tracks becomes TR-8S slots, FM-1 project
  slots and a markdown cue sheet. The sheet lists each TR-8S slot with its FM-1
  project, key, BPM and seed, which parts play in which section, and the EMP16
  map.

**Jam mode in the studio** (issue 06). The FM-1 port opens alongside the
TR-8S. The assistant is the main way in, and a panel in the UI mirrors what it
does:

- per track: voice, engine, mute;
- knobs for cutoff, resonance, decay, glide and the sends;
- **Generate** a part (same key and seed as the TR-8S pattern), **Audition**
  it on the playing FM-1, **Save** to the FM-1.

FM-1 changes go into the change log tagged `studio` or `ai`, and the history
ring snapshots an FM-1 track before it is overwritten, as it does for TR-8S
slots. The system prompt in `chat.py` (shared by `agent.py`) gains a short FM-1
section: the voicings, the voice budget, and that not every song needs a 303.

A mix check comes nearly free. The TR-8S streams its master mix back over USB,
EXT IN included, so `tr8s.audio` can measure the FM-1 against the kick. That
needs audio capture on macOS, a later item.

**Live mode needs nothing new.** It is whatever Jam mode saved on the two
boxes, plus the cue sheet. CC movement on stage comes from the EMP16's knobs,
plus any per-step motion and LFOs saved in the FM-1 project. Playing back CC
automation from a host is out of scope: there is no host.

## 2. Firmware: Mini-Tone

Dozens of open-source firmwares now run on the FM-1. The
[awesome-fm-1](https://github.com/cicloid/awesome-fm-1) list is the index. The
brief named four. All four exist, and none of them is the best fit:

- **Jangada** and **Melodee** are general Felucca forks.
- **fm1-t1** aims at Torso T1 functionality and is unfinished.
- **fm1_open** is M-VAVE's official SDK base, with a closed binary engine.

The requirement that settled it: **other synths have to be able to come in, not
only acid.** That rules out the best pure acid firmware, X0X, and points to a
multi-engine firmware where a 303 is one voice among several.

| Firmware | Non-acid synths | Acid | On-device generation | Clock source | CC 74 / 71 / 75 | Verdict |
|---|---|---|---|---|---|---|
| **[Mini-Tone](https://github.com/eldontyrellcorp/Mini-Tone)** | SWARM, FMTONE, WAVETONE, DUALVCO, ANALOG4, SID, CHIP | TB303, accent force and slide per step | EUCLID and STOCHASTIC per track | internal, USB or TRS | yes, every engine | **pick** |
| [FOMAJAM](https://github.com/konsumer/fomajam) | Felucca engines + SUPERSAW, STRING | ANALOG ACID preset, accent, slide, ratchet | no | both, USB or TRS | decay only; cutoff and resonance are engine-specific (CC 20–27) | runner-up; very new |
| [X0X](https://github.com/charlesvestal/fm1-x0x) | none: two 303s and drums | Open303 with Devilfish ranges, the best here | TB-3PO, seeded, with MUTATE | follows any | yes, on the 303 channel | acid-only fallback |
| [Jangada](https://github.com/zednaked/jangada) | Felucca engines + superwave | ratchets | no | Felucca's | not documented | general-purpose |
| [Melodee](https://github.com/keremimo/melodee) | ten engines | not documented | no | not documented | not documented | general-purpose |
| [fm1-t1](https://github.com/tensor-programming/fm1-t1) | — | — | T1-style, in progress | — | — | unfinished |
| [fm1_open](https://github.com/m-vave/fm1_open) | stock DX7, 303, 808, PSG, pluck | stock 303 | no | stock | stock | the base others build on |

**Why Mini-Tone** [D] (from its README):

- Six tracks share eight voices, so one firmware covers an acid line, a bass, a
  stab and a pad.
- The engines include **TB303** (four-pole ladder) next to SWARM, FMTONE,
  WAVETONE, DUALVCO, ANALOG4, SID and CHIP. The filter engines share a resonant
  multimode filter.
- **EUCLID** and **STOCHASTIC** generator modes per track keep parts moving on
  stage without a laptop.
- Per-step **SLIDE**, per-note force up to **ACC**, ratchets, 16–64 steps, and
  a song mode with sections A–D.
- The **clock source can be pinned** to internal, USB or TRS.
- The **same CCs on every engine**: 74 brightness (cutoff), 71 resonance,
  75 decay, 72/73 release and attack, 5 glide, 7 level, 10 pan, and 91/93/94 the
  reverb, chorus and delay sends. MIDI LEARN maps 16 more.
- It keeps Felucca's **SysEx editor protocol**, which is how the studio will
  write parts. Mini-Tone keeps its web editor in step with the firmware.

**Why X0X stays on the list.** For an all-acid set it is better: Open303,
TB-3PO's seeded generator (the same seed always gives the same line, which
matches how this studio works), and clock follow with no settings. The
generator in `synth/` keeps its interface target-neutral so an `x0x.py` profile
can be added later.

### Risks before the first flash

- **[D]** The FM-1's flash has a single bank and the board has no debug
  header. Custom firmwares expect stock V15 first.
- **[D]** **Units sold since autumn have a different flash chip, the
  UC25HQ80.** A firmware that only recognises the older Puya chip keeps saves
  in RAM, loses them at power-off, and refuses later installs (Felucca issue
  #320). Felucca recognises the new chip only from 1.8.2-beta. **Mini-Tone
  forks Felucca 1.5.** If our unit has the new chip, backporting the detection
  is the first patch, before Mini-Tone is ever flashed.
- **[?]** Recovery paths (safe mode, the restore to stock) need confirming for
  Mini-Tone specifically.

### Fork policy

Fork to `Besermenji/Mini-Tone`, keep `upstream`, and add the smallest patches
that make the rig work. Offer each one upstream. Candidates, each only if the
spike (issue 02) shows it is missing:

- **(a)** UC25HQ80 detection, backported from Felucca 1.8.2-beta.
- **(b)** Program Change selects a project or song section at the end of the
  bar, so the FM-1 follows the TR-8S's pattern changes on stage.
- **(c)** SysEx to write a whole project (steps, track parameters, song
  sections) and save it.
- **(d)** A fixed CC for track mute and unmute, if MIDI LEARN cannot cover it,
  so EMP16 pads can bring parts in.

Builds and flashes are local. There is no CI and there are no tokens.
Felucca-family firmware builds with JieLi's Linux toolchain: natively on Linux
x86-64, in a `linux/amd64` Docker container on macOS. **[?]** Mini-Tone's build
script and flasher match its siblings' (`./build.sh`, a `.fwsc`, a
USB-MIDI installer).

## 3. Signal specification

### MIDI wiring

TR-8S MIDI OUT (DIN) → EMP16 MIDI IN.
EMP16 MIDI OUT (its thru merged with its own knobs and pads) → TRS adapter →
FM-1 TRS MIDI IN.

- **[?]** The FM-1's TRS type, A or B, which decides the adapter.
- **[?]** That the EMP16's thru passes clock without adding jitter (see the
  acceptance test below).
- Fallback if it does: TR-8S OUT straight to the FM-1, and EMP16 OUT into the
  TR-8S's MIDI IN with Soft Thru on. **[?]** The TR-8S's name for that setting.

### Clock rules

- **One master: the TR-8S**, with its sync out on. Its clock free-runs even
  while stopped (see `monitor.py`), so the FM-1 stays locked between songs and
  starts on the TR-8S's Start.
- **EMP16:** clock out off. It passes the TR-8S's clock and never makes its own.
- **FM-1:** clock source **TRS**, pinned, so a stray clock on USB is ignored.
  MIDI and clock out off.
- **Studio:** never sends clock. `synth/port.py` refuses realtime bytes.
- On stage, the TR-8S's Tx EditData can be off. Only the studio needs its CCs,
  and fewer bytes through the thru is better.

A merge does not prevent jitter. One clock source and a passive thru do. The
acceptance test checks that:

> Record the TR-8S main out for five minutes at 130 BPM with a 16th-note TB303
> line on the FM-1. Line the 303 up against the kick at the start and the end;
> there should be no drift and no audible wobble. Do it through the EMP16 and
> then direct, and write both results here.

### Channels

The TR-8S sends its notes, Program Changes and CCs on its pattern channel,
10 by default. The FM-1 must not listen there, or the TR-8S's kick plays the
FM-1 and its knobs move the FM-1's parameters.

Mini-Tone listens to the tracks on a block of channels. **[D/?]** Its README
lists the blocks as CH1-4, CH5-8, CH9-12 and CH13-16 in one place, and as
CH1-6, CH5-10, CH9-14 and CH13-16 in another. Either way, use the block that
starts at 1 and **never one that includes 10**.

| Channel | Who | What |
|---|---|---|
| 10 | TR-8S | its own traffic; outside the FM-1's block, ignored |
| 1 | FM-1 track 1 | the song's main voice: the TB303 in an acid song, the drone or pad otherwise |
| 2 | FM-1 track 2 | bass |
| 3 | FM-1 track 3 | stab or chord |
| 4 | FM-1 track 4 | arp or lead |
| 5–6 | FM-1 tracks 5–6 | extra layers, if the block reaches them |

### EMP16 map

Four banks, one per FM-1 track channel. Every bank has the same layout, so
knob 1 is the cutoff whichever voice is selected.

| Control | CC | Mini-Tone parameter |
|---|---|---|
| Knob 1 | 74 | brightness / cutoff |
| Knob 2 | 71 | resonance |
| Knob 3 | 75 | decay |
| Knob 4 | 5 | glide (the slide time on a TB303) |
| Fader 1 | 94 | delay send: the "FX depth" |
| Fader 2 | 91 | reverb send |
| Fader 3 | 93 | chorus send |
| Fader 4 | 7 | track level |
| Pads 1–4 | MIDI LEARN, or fork patch (d) | mute and unmute tracks 1–4: a synth jumps in |

**[?]** How many knobs and faders the EMP16 really has. Retail listings
disagree; the table assumes four of each.

### Audio and gain staging

FM-1 3.5 mm stereo out → a TRS-to-two-TS cable → TR-8S EXT IN L and R. Set the
TR-8S's EXT IN type to stereo.

- FM-1 master volume at about 70%. Leave room for pads: eight voices of chord
  are louder than one 303.
- TR-8S EXT IN level (it is CC 12 on the TR-8S, `ccmap.MASTER_CC`) set so the
  loudest FM-1 part peaks about 6 dB under the kick. The loudest part is a pad
  chord, or the TB303 at full resonance with accents.
- Check by ear and on the master. With the Mac connected, the studio can
  measure it from the TR-8S's USB audio once capture works on macOS.

### Sidechain ducking

Duck in **one** place only: the TR-8S's kit sidechain on EXT IN, triggered by
BD.

- Moderate depth for a 303, deeper for pads, release about an eighth note.
- Leave any ducking inside the FM-1's firmware off, or the two stack.
- **[?]** The TR-8S's parameter names on firmware 2.51, against Roland's
  guide to sidechain on External In.

## 4. Issues

Ready to paste into GitHub, one file each:

| # | Issue | Depends on |
|---|---|---|
| [00](issues/00-macos-midi-backend.md) | macOS MIDI backend for the TR-8S | — |
| [01](issues/01-rig-verification.md) | Rig wiring and hardware verification | — |
| [02](issues/02-fork-minitone-and-spike.md) | Fork Mini-Tone, build, flash safely, spike the protocol | — |
| [03](issues/03-firmware-patches.md) | Firmware patches in the fork | 02 |
| [04](issues/04-synth-part-generator.md) | Multi-voice part generator and Mini-Tone encoder | 02 for `to_syx` only |
| [05](issues/05-tools-set-builder-cue-sheet.md) | Tools, arrangement-aware parts, set builder and cue sheet | 04 |
| [06](issues/06-jam-mode.md) | Jam mode: the FM-1 in the studio, driven by the assistant | 00, 04, 05 |

00, 01 and 02 can run in parallel. Each issue is implemented by Sonnet and
reviewed by Opus.

## Sources

- awesome-fm-1, the curated index: https://github.com/cicloid/awesome-fm-1
- Mini-Tone README: https://github.com/eldontyrellcorp/Mini-Tone
- X0X manual: https://github.com/charlesvestal/fm1-x0x/blob/main/docs/MANUAL.md
- Felucca editor protocol: https://github.com/charlesvestal/fm1-x0x/blob/main/web/EDITOR_PROTOCOL.md
- FOMAJAM README and CC map: https://github.com/konsumer/fomajam
- Felucca (UC25HQ80 note, 1.8.2-beta): https://github.com/hugelton/Felucca
- Roland, sidechain on External In: https://rolandindonesia.com/the-ultimate-guide-to-the-tr-8s-rhythm-performer-applying-sidechain-fx-to-another-instrument-using-external-in
