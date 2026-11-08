**Title:** Rig wiring and hardware verification (TR-8S, EMP16, FM-1)

**Labels:** `rig`, `hardware`, `docs`

## Context

[`docs/RIG-FM1.md`](../RIG-FM1.md) specifies the wiring, the MIDI channels,
the clock rules, the EMP16 map, gain staging and sidechain. Several of those
facts are marked **[?]**: likely, but not yet seen on our hardware. Code in
later issues depends on some of them, so they get checked first and the doc is
updated from **[?]** to **[V]** (or corrected).

Wiring, the same in Jam and Live mode:

```
TR-8S MIDI OUT ──► EMP16 MIDI IN │ thru │ EMP16 MIDI OUT ──► (TRS adapter) ──► FM-1 TRS MIDI IN
FM-1 audio out ──► TR-8S EXT IN L/R
```

## Tasks

**MIDI**

- [ ] FM-1 TRS MIDI type, A or B. Get the right adapter and confirm notes
      arrive.
- [ ] EMP16: confirm DIN (or TRS) MIDI IN and OUT, and that thru passes the
      TR-8S's traffic through to its OUT merged with its own controls.
- [ ] EMP16: turn its clock out off. Confirm with a MIDI monitor that only one
      clock stream reaches the FM-1.
- [ ] EMP16: count its knobs, faders and pads, and set up four banks on
      channels 1–4 with the CC map in RIG-FM1.md section 3. Save the setup.
- [ ] TR-8S: find and record the names of the sync-out and Soft Thru settings
      on firmware 2.51.
- [ ] Confirm the TR-8S's pattern channel (default 10) and that nothing on
      channel 10 reaches the FM-1's tracks once the FM-1 is on a channel block
      starting at 1. This is done after issue 02's flash.

**Clock acceptance test** (after 02's flash)

- [ ] Record the TR-8S main out for five minutes at 130 BPM with a 16th-note
      TB303 line on the FM-1, through the EMP16. Check the 303 against the kick
      at the start and the end for drift or audible wobble.
- [ ] Repeat with the TR-8S wired straight to the FM-1.
- [ ] If the EMP16 adds jitter, switch to the fallback (EMP16 into the TR-8S's
      MIDI IN with Soft Thru on) and test that.

**Audio**

- [ ] FM-1 out → TR-8S EXT IN L/R, EXT IN type stereo.
- [ ] Gain: FM-1 master about 70%. Set the TR-8S EXT IN level so the loudest
      part (a pad chord, or a TB303 at full resonance with accents) peaks about
      6 dB under the kick. Write down the settings.
- [ ] Sidechain: set up the TR-8S kit's sidechain on EXT IN triggered by BD.
      Record the real parameter names and the values that work for a 303 and
      for a pad.

**FM-1 safety, before 02 flashes anything**

- [ ] Read the FM-1's flash chip ID: Puya or UC25HQ80. This decides whether
      fork patch (a) in issue 03 comes first.
- [ ] Back up the FM-1's projects and confirm it is on stock V15.

## Acceptance

- Every **[?]** in RIG-FM1.md that this issue covers is now **[V]** with what
  was seen, or corrected.
- The clock test results, with dates, are written into RIG-FM1.md.
- A photo or diagram of the actual wiring is in the doc.

## Depends on

Nothing for the MIDI and audio checks. The clock test and the channel-10 check
need issue 02's flash.

## Pipeline

Hands on hardware. Opus reviews the doc changes.
