**Title:** Fork Mini-Tone, build locally, flash safely, spike the editor protocol

**Labels:** `rig`, `firmware`, `fm-1`, `spike`

## Context

The FM-1 runs [Mini-Tone](https://github.com/eldontyrellcorp/Mini-Tone)
(GPL-3.0, a fork of Felucca 1.5). The reasons are in
[`docs/RIG-FM1.md`](../RIG-FM1.md), section 2: six tracks with a TB303 next to
non-acid engines, EUCLID and STOCHASTIC generators, a pinnable clock source,
and the same CCs on every engine.

The studio writes parts to the FM-1 through Felucca's SysEx editor protocol.
Mini-Tone keeps it and its web editor follows the firmware, but what exactly
it can write is **not documented**. The protocol: `F0 7D 46 4C <cmd> … F7`,
one reply per request. It has INFO, TRACK, TRACK_STEP (notes, accent and slide
flags), TRACK_PARAM, PROJECT save and others. Felucca's version is described in
[EDITOR_PROTOCOL.md](https://github.com/charlesvestal/fm1-x0x/blob/main/web/EDITOR_PROTOCOL.md).
This issue finds out what works, before issue 04 writes an encoder against it.

Risks (RIG-FM1.md, "Risks before the first flash"):

- the flash has a single bank and the board has no debug header;
- custom firmware expects stock V15;
- **on units with the newer UC25HQ80 flash chip, a firmware that does not
  recognise it loses saves and blocks later installs.** Felucca recognises it
  only from 1.8.2-beta, and Mini-Tone forks 1.5.

## Tasks

**Fork and build**

- [ ] Fork to `Besermenji/Mini-Tone`. Keep `upstream` as a remote.
- [ ] Build locally: JieLi's toolchain natively on Linux x86-64, or in a
      `linux/amd64` Docker container on macOS. Follow the repo's BUILDING.md.
- [ ] Run its host tests and simulator, if it has them, before touching
      hardware.
- [ ] Write the exact build steps that worked into `docs/FM1-BUILD.md` in this
      repo.

**Flash safely**

- [ ] Gate: the flash chip ID from issue 01. **If it is UC25HQ80, stop here and
      do fork patch (a) in issue 03 first.**
- [ ] Back up the FM-1's projects. Confirm stock V15.
- [ ] Confirm the recovery paths before flashing: safe mode, and the restore to
      stock V15.
- [ ] Flash the locally built `.fwsc` with the local installer tool or the web
      installer.
- [ ] Power-cycle it. Confirm a saved project survives.

**Spike the protocol**

Write a throwaway script, not studio code. For each command, record whether it
works, its exact reply, and anything surprising:

- [ ] INFO: version, engines, parameter count, tracks.
- [ ] TRACK: select a track and query.
- [ ] TRACK_STEP: write steps to a track that is **not** selected, while
      playing. Do notes, accent (force) and slide come through? When does a
      write become audible?
- [ ] TRACK_PARAM: set an engine and a parameter on any track.
- [ ] Generator modes: can EUCLID and STOCHASTIC settings be written, and how?
- [ ] Song sections A–D: can they be written?
- [ ] PROJECT save and load. Does a saved project survive power-off?
- [ ] Program Change: does the FM-1 react to one at all?
- [ ] Mute: is there a CC for track mute, or can MIDI LEARN map one?
- [ ] Clock: set the source to TRS. Confirm a clock on USB is then ignored.
- [ ] MIDI IN channel blocks: which blocks really exist (the README lists them
      two ways).

## Acceptance

- `docs/FM1-PROTOCOL.md` exists. Every command above is marked **[V]**
  verified, **[I]** inferred or "not supported", as in PROTOCOL.md. It includes
  example frames.
- The list of fork patches issue 03 needs is final.
- The FM-1 runs our own build and survives a power cycle with a saved project.

## Depends on

Issue 01's chip check, before flashing. Otherwise none.

## Pipeline

Hands on hardware. Sonnet can write the spike script; Opus reviews
FM1-PROTOCOL.md. Local builds and flashes only, no GitHub Actions.
