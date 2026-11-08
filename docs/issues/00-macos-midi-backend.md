**Title:** macOS MIDI backend for the TR-8S

**Labels:** `rig`, `transport`, `macos`

## Context

Jam mode runs the studio on a Mac with the TR-8S on USB MIDI. Today the
studio only reaches the TR-8S on Linux:

- `config.find_port` looks under `/proc/asound` and `/dev/snd`.
- `Transport.open` does `os.open` on that rawmidi node and starts a reader
  thread.

Everything above that (the SysEx framing, blob transfer, the realtime / SysEx /
channel demux, the `_io` lock) does not care what the operating system is.
`transport.py` mixes the two jobs. This issue separates them and adds CoreMIDI.

The trap to avoid is in `transport.py`'s `_reader` comment and LESSONS.md:
bytes must reach the monitor **in arrival order**. Sorting a chunk into a clock
pile and a note pile smeared every note by up to a beat. The demux therefore
stays in the shared layer, so both backends inherit it.

See [`docs/RIG-FM1.md`](../RIG-FM1.md), section 1.

## Tasks

- [ ] Define a `MidiBackend` interface: `open()`, `close()`, `send(bytes)`, and
      a callback that receives incoming bytes in arrival order.
- [ ] Move today's rawmidi code into `RawMidiBackend` without changing its
      behaviour.
- [ ] Keep the demux, `_io` lock, `drain`, `collect`, `read_blob`, `send_blob`
      and `commit` in `Transport`, fed by whichever backend is open.
- [ ] Add `RtMidiBackend` using `python-rtmidi`:
  - [ ] Callback mode, not polling. The polling queue overflows during a
        24 KB blob read.
  - [ ] `ignore_types(sysex=False, timing=False, active_sense=True)`.
  - [ ] SysEx that CoreMIDI delivers in parts is reassembled before the demux
        sees it, or the demux's own `F0`/`F7` state machine handles it. Prove
        which, with a test.
- [ ] Port discovery by name on macOS in `config.find_port`. `TR8S_PORT` keeps
      working as an override and takes a port name on macOS. Record the TR-8S's
      CoreMIDI port names as found.
- [ ] Choose the backend by platform, with an override (`TR8S_MIDI_BACKEND`).
- [ ] Add `python-rtmidi` as an optional extra (`[project.optional-dependencies]
      mac`). The core keeps zero dependencies.
- [ ] `scripts/restart.sh` and the README quick start work on macOS.
- [ ] Note in LESSONS.md anything CoreMIDI does differently.

## Acceptance

- `pytest tests/` passes unchanged. The fake transport does not move.
- `tests/hardware/selftest.py` passes on the Mac against a real TR-8S: read a
  pattern, write it back byte-exact, select a pattern.
- On the Mac, the studio follows the machine: playing state, step, Program
  Change and the live overlay all behave as on Linux.
- The Linux path is not regressed (selftest on the Linux box).

## Out of scope

USB audio capture on macOS (`audio.py` uses `arecord`). It is a separate item.

## Depends on

Nothing. Can run in parallel with 01 and 02.

## Pipeline

Sonnet implements, Opus reviews. Local only, no CI.
