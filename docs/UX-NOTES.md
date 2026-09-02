# UX notes — rough edges seen while demoing (2026-09-02)

Observed while building a house track through the assistant with the studio
on screen. Each is small; together they are the difference between "works"
and "feels finished". Good first issues.

## The assistant panel

1. **Markdown shows as raw asterisks.** The assistant writes `**bold**` and
   backticks; the log prints them literally. Render a light markdown subset
   (bold, code, bullets) in bot lines.
2. **No progress signal on long turns.** A track build takes 60–110 s. The
   thinking lines help, but an elapsed-time counter in the chip (or on the
   "working" line) would say "still going" without words.
3. **First turn pays a ~5 s CLI start.** Pre-warm the session when the studio
   starts (connect the SDK client in the background) so the first reply is as
   fast as the second.
4. **Tool result lines are noisy.** The raw JSON summary is useful to a
   developer, less so to a producer. Collapse tool lines by default with a
   toggle ("show what it did").
5. **The assistant repeats the PTN/SYSTEM caveat every time.** Tempo, shuffle
   and kit per pattern are ignored unless UTILITY GENERAL points at PTN. The
   studio could read the system blob once, know the answer, and put it in the
   context block ("tempo source: PTN"), so the assistant only mentions it when
   it is actually SYSTEM. Same for "MOTION ON".
6. **Melodies need a hand on the panel** (Coarse Tune on CTRL, MOTION ON).
   A one-time setup checklist in the SETUP readout, with a "done" tick the
   assistant can see, would end the repeated instructions.
7. **The sign-in flow is untested** end to end (the machine was already
   signed in). Worth one run: Sign out → Sign in → browser → back.
8. **Model switch mid-conversation** works but is silent; log a line.

## The studio

9. **A tool write is sometimes logged as a USER edit.** After the assistant
   wrote 8-02, the change log showed `[USER] steps LT: +8 steps` and the
   status said "picked up an edit made on the machine". The read-back after a
   write can differ from the bytes the studio remembered (the machine
   normalises some fields), and the diff is attributed to the panel. Mark a
   slot "just written by us" and treat the first read-back after it as
   confirmation, not as a panel edit.
10. **Restart while playing loses the kit view** (no colours, no knob values)
    until the next stop, because a kit cannot be read while playing. Persist
    the last kit view across restarts.
11. **Startup pattern.** The studio remembers the last slot it was on, but the
    machine cannot be asked which pattern it holds; if they differ, nothing
    lines up until the dial moves. Option: on start, move the machine to the
    studio's slot (device.select works with Rx Prog Chg off) and say so.
12. **Variation buttons in the studio are display-only.** Selecting a
    variation on screen does not move the machine; the assistant has to say
    "press B on the panel". A temp-address write for the variation would make
    A–H clickable for real, and give the assistant a `device.select_variation`.
13. **Layout under ~1400 CSS px stacks the chat below the machine** and the
    page does not scroll to it. Either a responsive breakpoint that keeps the
    chat visible (side-by-side down to ~1100 px, tabs below that) or make the
    body scroll.
14. **The SOUND picker repeats rows.** The six suggestions under the
    instrument repeat three times in the panel view — likely one list rendered
    per row of pads. Render once.
15. **Levels.** Faders can only be read. A short hint on the fader ("the
    physical fader owns this") would stop people dragging it.

## Small and cheap

16. `FOLLOW WAITING` reads like a fault when the machine has simply not sent a
    Program Change yet; say `FOLLOW READY` once the channel is known.
17. The change log's per-step detail (`+5,13 (heard)`) is great for the
    assistant; the human view could group it ("SD: 2 steps added").
18. Screenshots for the README were taken at 1280×664; a 1600-wide capture
    would show the grid better.
