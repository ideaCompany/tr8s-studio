# Architecture

The goal is that a person can talk to their TR-8S through an LLM. That means
the backend has to expose *every* capability as a named, schema'd command with
useful errors — an LLM cannot read source to work out what it may call.

## Layers

```
  tools / cli          named commands + JSON schemas       <- what an LLM drives
      |
  device               facade: Patterns, Kits, Tones
      |
  pattern  kit  melody  tones                              <- models, pure logic
      |
  transport            SysEx framing, bulk transfer        <- bytes on the wire
      |
  config               paths, device discovery
```

Dependencies point downward only. Each layer is usable on its own: `transport`
without knowing what a pattern is, the models without a device attached
(they operate on blobs, so they are testable offline).

| Module | Responsibility |
|---|---|
| `config` | Data directory (`$TR8S_DATA`, else XDG), MIDI/audio device discovery. No machine-specific paths anywhere in the codebase. |
| `transport` | SysEx framing, checksum, 7-bit packing, chunked read/write, commit. Moves opaque blobs; knows nothing musical. |
| `pattern` | The 24504-byte model. Header fields as properties, steps as strings, motion as typed accessors. Validates on assignment. |
| `kit` | The 1312-byte model. Refuses to write `level`; can inherit a whole record from a donor. |
| `melody` | Note names ↔ per-step tune motion, both coarse and fine. Clamps out-of-range notes and *reports* it. |
| `tones` | The measured catalogue: search by root, decay, brightness, category. |
| `device` | Owns the connection; reads and writes models; backup and restore. |
| `tools` | The command surface. One decorator registers a function with its JSON schema. |
| `cli` | A shell over the same registry, so CLI and LLM can never drift. |
| `monitor` | Follows the device's MIDI clock: playing state, step, bar, live BPM. Clock free-runs while stopped, so transport state comes from Start/Stop. |
| `mcp_server` | The registry over the Model Context Protocol (stdio JSON-RPC), so any MCP client can drive the machine. |
| `chat` | The tool-calling loop against the Anthropic API, emitting events so a UI can show tool calls as they happen. |
| `server` | HTTP + SSE: serves the UI, bridges it to the device, streams live transport events. Also runs the background pattern index and a watchdog that reconnects after an unplug. |
| `web/` | The UI. Vanilla JS/CSS, no build step, themed entirely through CSS custom properties. Two views: a step grid and a representation of the machine's own panel. |
| `audio` | Capture from the device's USB audio stream, plus the DSP: YIN pitch detection, envelope/decay, spectral centroid. Stdlib only. |
| `analysis` | Closed-loop measurement — the tone catalogue sweep, and byte probing that identifies unknown record offsets from what moves in the audio. |

## The tool surface

`tr8s.tools` is a package: `_core.py` owns the registry, `ToolError`, the
`@tool` decorator and the helpers every tool shares (`device()`, `_slot()`,
undo capture). Each namespace — `pattern`, `kit`, `track`, `device`,
`library`, `tones`, `lines`, `styles`, `calibration`, `audio`, `history` — is
its own module and registers its tools on import. `__init__` re-exports the
public names and loads the namespaces *by name*: two of them (`device`, `kit`)
are also helper/model names, and a plain `from . import device` silently
rebinds the function to the module. That cost an hour; the comment in
`__init__` is there so it does not cost anyone else one.

```python
from tr8s.tools import call, schemas
schemas()                                  # every tool, JSON-schema'd
call("tones.search", {"category": "BASS", "melodic": True})
call("pattern.set_melody", {...})
```

23 tools across `device.*`, `pattern.*`, `kit.*`, `tones.*`, `audio.*`. Each
carries `mutates_device`, so a caller can distinguish a read from a write
without parsing the name.

Two of them exist because the measurement work made them possible:
`tones.search` filters by *measured* root, decay and brightness rather than by
name, and `kit.balance` compares a kit's instruments by measured loudness and
flags instruments sharing a frequency region. Balance is advisory only — level
belongs to the faders.

### Conventions

- **Slots** accept `0..127` or a panel string (`"8-03"`). Kits are 0-based
  internally and report `panel` (= index + 1) in every result, because the
  hardware displays 1-based and the mismatch is a reliable source of error.
- **Results say what happened**: `committed`, `verified`, `live`. Note that
  `committed: false` still means the slot was written.
- **Nothing silently degrades.** Out-of-range values raise; clamped notes come
  back in `warnings`. A melody quietly transposed is worse than an error.
- **Errors are actionable.** `"'level' is device-controlled (the physical
  fader) and cannot be written from software"`, not `KeyError: 4`.

### Hardware facts the API surfaces rather than hides

Some constraints cannot be abstracted away, so the schemas state them:

- `pattern.*` writes take `commit=False`, and its description says plainly that
  this is not an undo: the slot changes either way. `kit.*` does not offer the
  flag at all, because a kit only becomes audible once committed.
- `pattern.set_melody` says in its description that `MOTION [ON]` must be lit
  and that `root` should come from the catalogue rather than a guess.
- `kit.set_instrument` warns when a sample tone is assigned to a record without
  sample parameters — the bug that made a whole kit inaudible.

## Data

Everything lives under `$TR8S_DATA` (default `~/.local/share/tr8s`):

```
backups/patterns/pattern_NNN.bin    all 128, 24504 bytes each
backups/kits/kit_NNN.bin            all 128, 1312 bytes each
template_pattern.bin                an empty slot, the base for authoring
tones.json                          the measured catalogue
system_baseline.bin                 for diffing system settings later
```

Authoring builds from `template_pattern.bin` rather than from zeros: an empty
variation still carries setting bytes that matter.

## Closing the loop

The TR-8S streams its own audio back over USB, which converts "what does this
byte do?" from a guess into a measurement. `analysis` uses that in two ways:

- **Cataloguing tones** — assign, trigger, record, measure. Produces the real
  root pitch of every tone, which is what melodies need: Coarse Tune is
  relative to a sample's own pitch, so a guessed root transposes the line.
- **Probing bytes** — sweep an unidentified offset and report what moved.
  Pitch tracking the value means tuning; the envelope stretching means decay;
  the centroid moving with pitch static means a filter.

`interpret()` is deliberately conservative and only claims high confidence for
an unambiguous pitch shift. Everything else comes back "unclear" rather than
inventing a label — the project already has one entry in LESSONS.md about
treating a convenient inference as a finding.

## Listening: how the studio follows the machine

The TR-8S announces almost nothing. It transmits a note when an instrument
sounds, a clock, a beat counter (`CC 2`) and, with the right settings, a
Program Change on pattern select and a Control Change per knob. It transmits
**nothing** for the A–H variation or for a step being entered. So the studio
listens rather than asks, and the pieces are:

- **`fingerprint`** — every pattern's variations as sets of `(step,
  instrument)`, built once (~1 min) and cached. `Index.identify` is the one
  matcher: symmetric F1 at every rotation, refusing a narrow win. It is the
  only place recognition lives; an earlier duplicate on `Studio` is gone.
- **`monitor`** — turns bytes into state: step from the clock, phase from the
  beat counter, a live picture of which steps just sounded, and the last value
  of every control. Its `snapshot(light=True)` is what rides on every event;
  the heavy buffers are fetched on demand.
- **`Studio._recognise`** — a few times a second while playing, identify what
  is sounding; move the view if it is another pattern, mark the variation.
- **`Studio._check_for_edits`** — hits that arrive which the held pattern
  cannot explain mean a step was entered on the panel. That queues *one*
  read, run by `start_after_stop_reader` the moment the machine stops.

Two hardware facts shape all of it. Bulk reads **hang** during playback, so
`Device` refuses them while the studio knows the machine is playing, and the
view is served from the byte cache or the fingerprint index until it stops.
And the transport must deliver bytes **in arrival order** — a clock pile
followed by a note pile smears every note by up to a beat.

There is no poller. An earlier version re-read the pattern on a timer and
woke on every incoming message; while playing that is a note every step, and
the UI lurched. It was removed rather than tuned.

## Sharing one MIDI connection

The live monitor and all SysEx traffic share one `Transport`. This is not
because the OS forbids a second opener — two processes *can* open the rawmidi
node here — but because incoming bytes are delivered to whichever reader asks
first, so two readers silently split the stream and both get corrupt data.

The reader thread demultiplexes each read into three streams:

- **realtime** (`>= 0xF8`) → the monitor: clock, Start/Stop
- **SysEx** (between `F0` and `F7`) → a buffer the blob reads consume
- **channel** (everything else) → the monitor: Program Change

Splitting on the `F0`/`F7` state machine matters: without it, stray note bytes
land in the SysEx buffer and corrupt blob reassembly.

Within a process, every SysEx exchange is serialised by a re-entrant lock in
`Transport`. An exchange is stateful — send, then read until the reply is
complete — so two threads (the background pattern index and a user's step edit,
say) would each consume part of the other's reply and both would see garbage.
Argument validation happens *before* the lock, so a bad call fails immediately
instead of queueing behind real traffic.

The practical consequence across processes: **run one process against the device
at a time.**
The studio and the CLI will both start, but sharing the port makes their reads
unreliable. The MCP server and the studio should not run together either.

## Not done yet

- **The scripts in `midi/`** are the exploratory originals with hardcoded
  paths. They still work and are what produced the current content on the
  machine, but the package supersedes them; they should be ported or removed.
- **The real API path is unverified.** There were no credentials on the machine
  this was written on. The chat loop itself is covered by a scripted fake client
  (tool dispatch, one-message result batching, thinking-block replay, error
  handling, turn bounding), but nothing has spoken to Anthropic.
- **The UI has no tests.** Its logic is exercised by driving the real page in a
  browser; the rendering functions are pure enough to test with a DOM shim but
  none exists.
- **`server` has no automated tests.** The HTTP handlers and the SSE hub are
  only exercised by hand.
- **`commit` semantics are unproven.** A transfer alone changes the slot;
  whether commit is what survives power-off has not been confirmed.


## Offline mode

`demo.py` provides `DemoTransport`, which implements the Transport surface the
layers above use and stores blobs in memory. `demo.install()` builds a `Device`
around it and hands it to the tool layer through `tools.set_device()` — the
same injection point the tests use. `tr8s-studio --offline` calls it before
`Studio.connect()`, so every layer above the wire runs unchanged.

It is a fake of *behaviour*, not of content: transfers land immediately,
`level` is overwritten on write, and unknown slots read as `None`. Anything
that only holds on real hardware (MOTION [ON], the CTRL knob assignment) is
absent there too, so offline cannot be used to prove those work.


## The musical layer

Three modules sit above the byte models and below the tools. None of them
touches the wire.

`style.py` — the groove engine. Nine styles, each a function of
`(rng, energy, role)` returning step strings. Energy adds layers in a fixed
order rather than scaling density uniformly; role (intro/main/break/fill/drop)
shapes a bar for where it sits in an arrangement. `arrangement()` writes all
eight variations against an energy curve shaped like a track — the break sits
*below* the intro so the return lands.

`kitbuild.py` — selection from measurement. Each track has a target window for
centroid and decay, adjusted per style; candidates are scored against it, and
penalised for sitting within 120 Hz of something already chosen. The kick is
picked first and scored on *pitch*: the tonic of the key scores highest, the
fifth next, out-of-key is penalised — a kick a semitone off the bassline beats
against it on every downbeat. Every choice carries the reason it was made.

`lines.py` — basslines, acid lines, stabs and arpeggios constrained to a scale.
All four keep to a register floor (an octave below the tone's own root) and to
Coarse Tune's ±24 semitones, raising by octaves rather than clamping so a note
never leaves the key to fit.

`history.py` — undo. Mutating tools snapshot the slot they are about to
overwrite, taken from `Device`'s byte cache rather than the wire, because a
0.6 s SysEx read before every step edit would make editing feel broken. The
studio's own edit paths capture explicitly, since they bypass `tools.call`.

## The change log

`changelog.py` records every change to the kit and patterns this session,
tagged by source — **user** (a hand on the machine: knobs and faders from
Control Change, steps from the read-back diff), **studio** (a tool the browser
UI called), **ai** (a tool the chat assistant called). It is the memory an AI
collaborator needs to reason about a track's history, and during development it
answers "what just happened and who did it" across MIDI, SysEx and three UIs.

Entries persist to a per-session JSONL file so they survive a studio restart.
A rapid control sweep coalesces into one entry (final value), and the disk is
touched once per settled control rather than per CC. Read it in the studio via
the LOG header button, or over `/api/changelog` (which also toggles logging and
clears); it is on by default.
