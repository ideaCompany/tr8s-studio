**Title:** Mini-Tone fork: the patches the rig needs

**Labels:** `rig`, `firmware`, `fm-1`

## Context

The fork (`Besermenji/Mini-Tone`, issue 02) should stay thin: the smallest
changes that make the rig work, each offered upstream. Issue 02's spike decides
which of these are needed. Skip any that the firmware already covers.

See [`docs/RIG-FM1.md`](../RIG-FM1.md), section 2, "Fork policy".

## Tasks

- [ ] **(a) UC25HQ80 flash detection.** Only if our FM-1 has that chip.
      Backport the detection from Felucca 1.8.2-beta (JEDEC ID `0xB36014`,
      Felucca issue #320). This patch is flashed before anything else.
- [ ] **(b) Program Change follow.** A Program Change on a configurable channel
      selects a project or song section at the end of the current bar, so the
      FM-1 follows the TR-8S's pattern changes on stage. Off by default.
- [ ] **(c) Whole-project writes over SysEx.** Steps, track parameters,
      generator settings and song sections, plus save. Only what the spike
      found missing.
- [ ] **(d) Mute CC.** A fixed CC for track mute and unmute on each track's
      channel, if MIDI LEARN cannot do it. EMP16 pads use it to bring parts in.

For each patch:

- [ ] Host tests and simulator scenarios, in the fork's own test setup.
- [ ] Build and flash locally, and test on the FM-1 with the TR-8S as clock.
- [ ] Update `docs/FM1-PROTOCOL.md` in this repo.
- [ ] Open a PR upstream with a short description of why the change is useful
      beyond this rig.

## Acceptance

- Every needed patch is merged in the fork, tested on hardware, and documented.
- With (b): change pattern on the TR-8S while playing, and the FM-1 follows at
  the bar.
- With (d): an EMP16 pad mutes and unmutes an FM-1 track.

## Depends on

Issue 02.

## Pipeline

Sonnet implements (C, JieLi toolchain); Opus reviews. Local builds and flashes
only.
