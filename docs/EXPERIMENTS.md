# Open questions, and the experiments that would settle them

Written for a session with the machine in front of you. Each one says what is
unknown, what to do, and what the answer would unlock. Most need nothing but
the machine switched on and reachable — the ones that need a hand are marked.

## 1. Which palette index is which colour  *(needs you to look)*

The eleven bytes at kit header `+42…+52` are the per-instrument fader colour;
that much is established. What is *not* established is what each index looks
like — the names in `kit.COLOUR_NAMES` are fitted to the factory default and to
product photographs, nothing stronger.

**Kit 125 has already been written with indices 0–10 across the eleven
instruments.** Load it and read the fader colours left to right. That settles
the whole mapping in one glance, and I can correct the palette from what you
see.

## 2. Does anything announce the A–H variation?  *(needs a setting)*

The MIDI Implementation Chart has no message for the variation, and a sweep of
every address in the `temp` space that Roland's own client knows about (`01 00
00 03` through `2F`, with the pattern playing and the result checked by ear)
moved nothing. Recognition-by-listening works and is verified, but it only
works while the pattern is playing.

**Turn on `UTILITY → MIDI → Tx EditData`** and change variation a few times.
That setting makes the machine transmit panel operations as MIDI, and the
studio now logs every Control Change it receives (`POST /api/cc`). If a CC
appears when you press A–H, following works while stopped too.

Worth doing in the same pass: turn a `TUNE` knob, a `DECAY` knob, and move a
fader, pausing between each. The chart says CCs 9, 12, 14–20, 23–25, 28–29,
46–63, 70–71, 80–88, 91, 96–97, 102–110 are transmitted but does not say which
is which. A few seconds per control maps them, and then the studio can follow
knob moves live.

## 3. Is `Rx Prog Chg` off, or is the current pattern simply unreadable?

A Program Change sent to the machine changed nothing, and the system blob was
byte-identical across it. Those two possibilities are not separable from
software.

Now largely moot: pattern selection works through the `temp` space regardless
of `Rx Prog Chg` (docs/PROTOCOL.md). Worth one look at the setting anyway, to
turn a guess into a fact.

## 4. Can pattern fields be read individually?  *(no help needed)*

Roland's address table has `temp.ptn.name` at `20 00 00 00` and
`kitReference` at `20 00 00 14`, with a per-pattern block stride — i.e. named
fields inside a pattern, addressed directly. The `temp.stp` parameters turned
out to be write-only, but these may not be.

If they can be read, a pattern's name costs 16 bytes instead of 24,576, which
would make the fingerprint index build in seconds rather than a minute, and
make checking for edits nearly free. **Try an RQ1 to `20 00 00 00`, size 16.**

## 5. What are the other 36 kit-record bytes for?

Thirty-six of the forty-three unidentified bytes did nothing audible on a
sustained sample tone. That is a much weaker result than "unused": a sweep on
one tone misses anything that only applies to ACB tones, anything that
interacts with a parameter left at its default, and anything inaudible in a
single unprocessed hit. The raw sweep data is kept in
`~/.local/share/tr8s/kit_byte_probe.json` and can be re-read against a better
probe tone without touching the machine.

## 6. The second eleven-byte run at `+285…+295`

Varies per instrument like the colour bytes but with a wider range (0–35).
Unidentified. Setting one to an extreme value and looking at the panel would
probably name it in seconds.
