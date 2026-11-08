**Title:** Jam mode: the FM-1 in the studio, driven by the assistant

**Labels:** `rig`, `studio`, `assistant`, `fm-1`

## Context

Jam mode is the Mac connected to both boxes, with the assistant in charge.
You say "bring in a dub stab", "make the acid nastier" or "drop the pad for
the break", and it happens on the FM-1 while the TR-8S plays, the way drum
edits already land live. What you keep is saved to the boxes for Live mode.

The studio already follows the TR-8S, logs who changed what, and keeps an undo
ring. This issue brings the FM-1 into the same loop.

See [`docs/RIG-FM1.md`](../RIG-FM1.md), section 1, "Jam mode in the studio".

## Tasks

**Connection**

- [ ] The studio opens the FM-1's port (`synth/port.py`) next to the TR-8S's,
      shows whether it is connected, and reconnects after an unplug like the
      TR-8S watchdog does.
- [ ] Never send clock. The FM-1 keeps following the TR-8S over the DIN/TRS
      chain.

**Assistant tools**, small enough for live prompting:

- [ ] `synth.voice`: put an engine on a track.
- [ ] `synth.regenerate`: a new part for one track, same key, new seed or
      energy.
- [ ] `synth.mute`: bring a part in or take it out, now or at the next bar or
      section.
- [ ] `synth.cc`: set cutoff, resonance, decay, glide or a send on a track.
- [ ] `synth.save`: save the FM-1 project.
- [ ] The tools state what they changed in musical terms, as the TR-8S tools
      do.

**UI**: an FM-1 panel in `src/tr8s/web/`, vanilla JS as the rest.

- [ ] Per track: engine, a mute toggle, and knobs for 74 / 71 / 75 / 5 and the
      sends.
- [ ] Buttons: Generate, Audition (write to the playing FM-1), Save.
- [ ] The panel mirrors what the assistant does, so both ways in stay in step.

**Memory**

- [ ] FM-1 changes go into the change log tagged `studio` or `ai`.
- [ ] The history ring snapshots an FM-1 track before it is overwritten, so
      `history.undo` covers the FM-1 as it covers TR-8S slots.

**Tests**

- [ ] Tools on a fake FM-1 port.
- [ ] Change log and undo with FM-1 entries.
- [ ] Server routes, if new ones are added.

## Acceptance

- On the Mac with both boxes connected and playing: three prompts ("bring in a
  pad", "make the acid more aggressive", "take the pad out at the break") each
  change the FM-1 audibly within a bar or at the named point. The assistant
  says what it did.
- Undo puts the FM-1 track back.
- Save, unplug the Mac, power-cycle the FM-1: the saved project plays from the
  TR-8S's clock.

## Depends on

Issues 00 (macOS backend), 04 and 05.

## Pipeline

Sonnet implements; Opus reviews.
