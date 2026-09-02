# Lessons learned

How this device was reverse-engineered, what went wrong, and what to do
differently. Written for whoever picks this up next — including a future
session with no memory of the first one.

---

## The method that worked

Almost every field in this project was found the same way:

> **Write a blob you know byte-for-byte. Change exactly one thing on the panel.
> Read it back. Diff.**

That's it. Whatever changed *is* the field. It found tempo, kit reference,
scale, shuffle, the variation mask, per-step tune, Coarse Tune, pan, both
sends and LFO depth — most of them in a single round trip each.

Three things make it work:

1. **Own the baseline.** Write the blob yourself so there is no ambiguity about
   what was there before. Reading "before", changing something, reading "after"
   also works, but only if nothing else touched the device in between.
2. **Use extreme, distinctive values.** `+12` and `−12` on separate steps beat
   two mid-range values, because the arithmetic falls out of the diff
   immediately. `0x00` is a poor choice — it collides with an empty baseline
   and the change becomes invisible.
3. **Change several *unrelated* things at once.** Different parameters on
   different instruments land in different records, so attribution is free. Four
   parameters in one pass instead of four passes.

### Corollary: ask for the panel's own numbers

The single most efficient measurement in the whole project was asking what the
display read: *"step 1 is −80, step 9 is 0, step 10 is +10"*. That gave the
exact encoding (`display = byte − 128`) in one message, where acoustic
measurement had already burned an hour and produced garbage.

**Prefer reading the device's own display over measuring its output.** Measure
only what the device won't tell you — which here was just one thing: how many
tune units make a semitone.

---

## Traps, ranked by time lost

### 1. Realtime bytes hang read loops

The TR-8S streams MIDI clock and active sensing continuously. A read loop that
extends its idle timeout whenever *any* byte arrives will never time out.

**Filter bytes `>= 0xF8` before judging whether data is still arriving.** This
cost the first real debugging session and looked exactly like a dead device.

### 2. Vendor documentation can be wrong

Roland's own web client lists `kitReference` at `20 00 00 14` and
`kitReferenceSw` at `20 00 01 06`. Writing either does nothing. The real field
is a single byte at pattern offset 18.

Those addresses are presumably real for something — but not for what the panel
writes. **When a documented field doesn't work, stop deriving and go measure.**
One diff settled what an hour of address arithmetic couldn't.

### 3. "Writable" is not "understood"

A probe showed 51 of 52 kit-record bytes accept writes. That was recorded as a
result and treated as sufficient — and then a kit was built that set a sample
tone id without touching bytes `+28..+41`, which carry that sample's envelope
and gain. Every sample instrument played, but at near-zero gain.

**Knowing a byte can be written says nothing about what it means.** The
catalogue of "writable but unidentified" offsets was a list of unexploded
mines, not a completed inventory.

### 4. Verify the fix produced different bytes, not just different code

The first attempt at fixing the above loaded its donor record with
`k.load(61)` — which reads the *backup file*, where that instrument still holds
the original ACB tone and the sample bytes are zero. The patch was applied, the
script ran, the kit "verified", and the user was asked to go and listen to a
kit that had not changed in the relevant bytes at all.

**After a fix, dump the bytes you claim to have fixed.** One line of output
would have caught it before wasting someone's time.

### 5. Measuring one thing in isolation says nothing about the mix

`LT` and `MT` were reported as "sounding fine" because triggering them alone
measured close to the kick's peak. The user, listening to the actual pattern,
heard them buried. They were right.

**A measurement that contradicts the person listening is a bad measurement
until proven otherwise.** In this case it was measuring the wrong kit entirely
— the trigger test ran before the new kit was selected.

### 6. Plain autocorrelation does not detect pitch

It always peaks at the shortest lag and reports the frequency ceiling. Every
tone came back as exactly 1200 Hz. Use the cumulative-mean normalised
difference (the core of YIN); it's ~30 lines and was accurate to 0.1% on
synthetic tones immediately.

### 7. Don't guess a musical root

Coarse Tune is relative to a sample's own pitch. `ROOT = 'C3'` was written
because something had to be written, and the measured roots turned out to be
`C2`, `C1`, `D#1` and `A1` for the four instruments in one kit — so a pad was
playing a D♯ minor 7th chord under a C minor melody.

**If a parameter is relative to an unknown, measure the unknown.** That is what
`tone_analysis.py` exists for, and it took twenty minutes to build and ten to
run.

### 8. A convenient story is not a finding

The transfer/commit split was documented as "transfer goes to a scratch buffer,
commit saves it". That was inferred from one observation — an uncommitted
pattern write being audible — and it was *convenient*: it implied a safe
scratch space, so a live jam could be described as leaving nothing behind.

It was wrong, and it was told to the user as fact. An uncommitted write changes
the slot, and the jam overwrote a saved pattern. The test that settled it took
one minute: write two different slots without committing, then re-read the
first. A single buffer cannot hold both.

**When an inference makes something convenient, that is exactly when to test
it.** The pleasant version of a finding deserves more scrutiny than the
inconvenient one, not less.

### 9. `pkill -f <pattern>` matches its own shell

`pkill -f 'foo.py'` run from a shell whose command line contains `foo.py` kills
that shell. The bracket trick (`pkill -f 'fo[o].py'`) protects the pattern, but
not a *later* literal mention in the same command line — a compound command that
kills and then restarts a server matches itself on the restart half. Manage
long-running processes with a PID file instead.

---

## Device behaviours worth knowing

| Behaviour | Consequence |
|---|---|
| Any transfer writes the slot at once — no scratch buffer exists | There is no undo. Read before you overwrite. |
| Patterns are re-read into playback immediately; kits are not | A step editor can be interactive. A kit editor needs a commit before you hear it. |
| `commit` is presumed to be durability across power-off (untested) | Send it for anything worth keeping. |
| `level` is owned by the physical faders | A UI can display it, never set it. Don't build a mixer page. |
| Per-pattern tempo/shuffle/kit need `UTILITY GENERAL` set to `PTN` | On `SYSTEM` everything written to the header is silently ignored. |
| `MOTION [ON]` gates motion playback | A melody written from software is silent until a human presses that button. |
| Coarse Tune exists only on **sample** tones | Byte 17 of a tone record is the predicate: `2` = sample. Check it before promising melodies. |
| The device recomputes the variation mask on write | Don't bother setting it. |

## Recording patterns over MIDI is lossy

`INST REC` *does* capture USB MIDI notes — the manual only mentions the pads,
and forum consensus said otherwise. But it drops ghost notes in dense 16th runs
and occasionally shifts the last step: only 1 of 8 test variations came back
byte-exact.

It was the right first move — it produced music within an hour, while the
format was still unknown — but it is not the tool for exact work. Once SysEx
writing worked, the recorded patterns were replaced with byte-exact ones.

---

## Things still unknown

- Motion byte `+1` is probably decay; never tested.
- The presence mask for a step carrying *both* tune and CTRL motion is
  presumably `0x89`; untested.
- Kit record bytes `+5`, `+9`, `+10` and most of `+12..+27`.
- Which of `+28..+41` is which sample parameter — only that `+37` looks like
  gain and that they must be copied wholesale.
- The CTRL knob assignment and `KIT: CTRL Sel` are **not** in the kit blob.
  They are probably in the 752-byte system blob; a baseline of it is saved in
  the data directory, so one diff would settle it.
- The last two of the ten variation blocks (believed to be fill-ins).

## The CTRL byte is not pitch just because I write pitch to it

`pattern.export` read every step's CTRL byte as semitones and turned it into
note names. Running it over a factory pattern produced melodies like `D#10` —
+104 semitones from the tone's root.

Nothing was wrong with the decode. Byte `+2` really does hold Coarse Tune when
Coarse Tune is what's assigned to that instrument's CTRL knob. The bug was that
I only ever *wrote* CTRL, always as tune, and then read it back the same way.
Factory patterns use CTRL for pan and for sends, and the assignment lives in
system state that isn't in the kit blob — so software cannot check.

Export now emits raw values for CTRL motion unless the caller passes
`ctrl_is_coarse_tune`. Byte `+0` is always Tune, so fine motion still exports
as notes with no flag.

The pattern to watch for: a field whose meaning I established by writing it,
then confirmed by reading back my own writes. That round trip proves the
encoding and nothing about what the field means when someone else fills it.
Same shape as the "commit sends to a scratch buffer" claim — a mechanism I
described confidently without ever testing the case where I wasn't the author.

## `x or default` is wrong whenever an empty x is meaningful

`kitbuild.build()` took an optional catalogue and resolved it with
`catalog or Catalog.load()`. `Catalog` defines `__len__`, so an *empty*
catalogue is falsy — and passing one silently fell back to the machine's real
614-tone catalogue. The test that was supposed to prove "an empty catalogue
tells you to run `analyse-tones`" instead ran the whole selection against real
data and passed the wrong thing.

The trap is that the idiom reads as "use the argument if it was given", but it
actually means "use the argument if it is truthy". Those differ for every empty
container, `0`, and `False` — which is to say, for exactly the edge cases a
test is trying to reach. `if x is None` is the version that says what it means.

Worth grepping for whenever an optional argument can legitimately be empty.

## Range is not trend, and trend is not proportionality

The byte-probe interpreter decided a kit offset was a tuning parameter when the
pitch at the top of the sweep differed from the pitch at the bottom by more
than 1.5 semitones. Three offsets came back "tuning (pitch tracks the value)"
with **high** confidence. None of them tunes anything.

`+29` was unpitched through the middle of its range and non-monotonic at the
edges — the sample was breaking, not bending. Adding a rank correlation caught
that one.

`+5` and `+28` survived the correlation check, because they *are* monotonic: a
couple of values sound one way, the rest sound another, and it never goes back.
Perfect rank correlation, and still not tuning. What gives them away is that
the entire change happens between two adjacent values and the rest of the range
is flat — a switch, not a sweep. Hence `_step_dominance`.

Three checks, each catching what the previous one missed:

  range        the ends differ           — necessary, nowhere near sufficient
  trend        it moves *with* the value — kills the noisy ones
  dominance    it *keeps* moving         — kills the switches

The general shape: I had a measurement, extracted one number from it, and let
that number name a mechanism. Every intermediate verdict was plausible, and
I would have written all three into PROTOCOL.md as facts. What saved it was
reading the raw sweep rows rather than the verdict — the numbers were right
there, and 78, 78, 65, 65, 65, 65, 65, 65 is visibly not a tuning curve.
Confidence labels are generated by the same code that generates the mistake,
so "high confidence" is not evidence of anything.

## The off-by-one that was the machine talking

Four tracks were built in a loop: build a kit, then write the pattern that uses
it. Every pattern came back pointing at the *next* track's kit — 123 became
125, 125 became 126, 126 became 127. It read exactly like an off-by-one in slot
conversion, and there are two plausible ones in this codebase (kits are 1-based
on the panel, and the pattern's kit byte is 1-based in the blob).

It was neither. The same code run against the offline device gave the right
answer every time, which ruled out the arithmetic and pointed at the hardware.
One three-line experiment — set a kit reference, commit an unrelated kit, read
the reference again — showed the machine rewriting it.

Two things worth keeping:

The offline device paid for itself here. Being able to run the identical code
path with no machine attached turned "somewhere in these four layers" into
"not in any of them" in one command.

**It came back.** Having found and documented the behaviour, I then hit it
twice more: once building a kit for one track (which re-pointed the previous
track), and once running `kit.tune_to` as a *test* — a tuning experiment,
nothing to do with patterns, which silently re-pointed a pattern written
minutes earlier. Knowing about a trap is not the same as being safe from it,
because the rule I had written down was "commit kits before patterns" and the
real rule is "any kit commit stamps whatever pattern was last written". The
fix that actually holds is not a rule for callers to remember: `Device` now
re-sends the last pattern's bytes after every kit commit, so the behaviour
cannot reach anyone.

And the shape of the wrong answer was seductive. `+2, +1, +1, 0` looks like a
loop index leaking into a slot number, and I could have written a plausible fix
for that non-existent bug. What it actually was: each pattern had been stamped
by the *following* iteration's kit commit, so the last pattern in the loop was
correct — which the off-by-one theory does not explain, and which I only
noticed by checking whether the theory covered all four values rather than the
first one.


## Two messages, one meaning each, and no way to tell them apart

Following the machine's pattern selection worked on the first try, and was
wrong. The user was on `1-01`; the studio showed `8-13`.

`8-13` is slot 124, and `1-01`'s kit is 125. The machine announces a pattern
change **twice** — the pattern on `Pattern Ch` and its kit on `Kit Ch` — and my
listener took whichever arrived last. It had been following the kit number as
though it were a pattern.

Two things about how this went:

I had already predicted it. Reading the manual for the *setup instructions*, I
noticed `Pattern Ch` and `Kit Ch` were separate parameters, wrote a test that a
program change on the kit channel must be ignored, and shipped it — with the
channel defaulting to "any", because I did not know which channel was which and
wanted it to work without configuration. The defensive code was right there and
switched off by its own default. Knowing about a hazard and defaulting to the
unsafe side of it is not much better than not knowing.

The fix is better than a setting. The two numbers are not independent: the kit
announcement must equal the kit stored inside the pattern the other message
names. So the program can read the candidates and check which way round that
holds, and learn both channels from one pattern change. That is a nicer answer
than asking the user which channel to trust, and it is *checkable* — where a
default of "channel 10, probably" would have been another guess wearing a
number.

## The tests were reading the machine

Adding a settings file — so the studio would remember which MIDI channel
carries the pattern instead of relearning it after every restart — broke a test
that had nothing to do with settings. The new `Studio` loaded the real
`~/.local/share/tr8s/studio.json`, found the channel this particular TR-8S had
taught it, and stopped being the blank object the test assumed.

Pointing the suite at a temporary data directory fixed that and immediately
broke five more, all in kit building. They had been quietly reading the
614-tone catalogue swept off this machine. On any other machine — or before
running `analyse-tones` — they would have failed, and I would have believed
the code was broken. A 117-tone fixture replaced it.

Then one test still failed, and only sometimes: the test that exercises
channel learning *persists* what it learns, into the shared temp directory, and
a later test inherited it. An autouse fixture clearing the file fixed that.

Three layers of the same mistake. Every one of them was invisible while the
tests passed, and each was only exposed by removing the layer above it. The
general shape: a test that reads anything outside its own inputs is not testing
what it says it is, and it fails on someone else's computer rather than mine.
Worth checking whenever a test needs no fixture and passes anyway.

## I "fixed" a correct answer because I misremembered where the machine was

A hardware self-test reported "the variation being played is recognised —
**A at 0.97**". I knew the machine had been playing `1-10` and the studio was
showing `8-16`, so I called it a false positive, tightened the evidence
threshold until it went away, wrote a test asserting the answer had been wrong,
and recorded a lesson about it.

All of that was mistaken. The machine had moved to `8-16` at some point during
the session. Variation A of that pattern is `BD` on steps 1 and 11, `CH` on 1,
9 and 11 — and what the machine played was exactly that, rotated by two. The
detector had been right, and I had broken a working case by raising the bar
until a true positive fell under it.

What actually caught it was measuring instead of reasoning: printing the score
of every variation of four different patterns against the same hearing. The
correct one scored 1.0 with a 0.57 margin; the best variation of three patterns
that were *not* playing scored 0.35–0.53 with margins of 0.03–0.15. That table
also showed the real defect, which was not the threshold at all: the score was
one-sided, measuring only "what fraction of the hearing does this variation
explain". A sparse variation explains a sparse hearing perfectly, so an intro
of five hits scored 1.0 against almost anything. F1 over the two sets fixed it.

The failure was diagnosing from a remembered fact about a system I do not
control. The machine's selection is exactly the state I had just spent hours
establishing I cannot read — and I used my memory of it as ground truth anyway.
When the evidence is about external state, re-measure the state; do not reason
from what it was last time you looked.

## The self-test found a bug by being wrong in a way I could see

A hardware self-test reported "the variation being played is recognised —
**A at 0.97**". It was a lie, and an obvious one once written down: the studio
was showing `8-16` and the machine was demonstrably playing `1-10`. The check
had passed with a confident number for a pattern that was not playing.

Ten notes had arrived. Ten notes can be three distinct hits repeated three
times, and a sparse variation matches three hits almost perfectly. The gate was
`len(hits) < 10`, counting raw notes, when what actually discriminates is how
much *different* material has been heard — distinct `(step, instrument)` pairs.
Raising the gate to fourteen distinct pairs turned the false pass into an
honest skip that names the reason.

Two things worth keeping:

**A check that cannot run must not report a pass.** The self-test has three
outcomes rather than two, and the skip says why. Had "could not tell" been
folded into failure I would have gone looking for a bug in the matcher; had it
been folded into success I would never have looked at all.

(The verdict above was itself wrong — see the entry before this one. What the
self-test did do right was print *what the studio was showing* alongside its
answer, which is what let the disagreement be seen at all, even though I then
resolved it the wrong way round.)

**The wrong answer was more informative than a right one.** A correct
identification would have told me nothing, because it would have been correct
for the wrong reason. What exposed the flaw was a confident answer next to a
fact that contradicted it — which is only possible because the check printed
what the studio was showing alongside its verdict. Reports that carry their own
context are how a test tells you something you were not already looking for.


## I swept the wrong address space for hours

Following the machine's pattern selection was built on MIDI Program Change,
which needs a setting on the panel and turned out to carry the kit on a second
channel. Before that I had checked whether the current pattern could simply be
read instead, and concluded it could not: every unmapped offset in the utility
space returned nothing useful, and the system blob was byte-identical across a
change. I wrote that up as a limitation of the machine.

It was a limitation of where I looked. The address table this project was built
from — Roland's own, already cited in the protocol notes — has a second space
for live state, and in it `currentPattern`, `nextPattern` and `patternSelect`.
Writing those moves the machine. Roland's client has never used Program Change
for this at all.

I had read that file to get the transfer protocol and stopped reading once I
had what I came for. Everything afterwards — the Program Change listener, the
two-channel disambiguation, the "there is no readable current pattern" note in
the protocol doc — was work done around a wall I had put up myself.

The useful part is what it unlocked rather than what it cost. Being able to
*put* the machine somewhere, and already being able to recognise what it plays,
closes a loop: set a known state, listen, compare. That is what makes it
possible to hunt for the variation control by writing candidate addresses and
hearing whether the pattern changed, instead of asking someone to press a
button and describe what happened.

When a source has already answered one question, read the rest of it before
concluding the next answer is not there.

## The evidence was in the log the user pasted, and I had already logged it

The user pasted a MIDI capture to make a point about steps. In it, every beat:
`CC 2 = 0, 1, 2, 3, 0, 1, 2, 3`. A beat counter. The bar phase I had spent
an afternoon reconstructing by scoring sixteen rotations, transmitted plainly
once per beat by the machine itself.

I had built the CC decoder that produced those lines, and labelled the `control`
row "nothing yet — would follow knobs and faders". I saw CC 2 as a knob I had
not mapped, because that is what I had decided the control-change column was
for. The decoder was right; the reading was wrong; and it was wrong because I
had filed the whole message class under one purpose before looking at values.

Then the smear. Live steps landed a beat late and doubled at boundaries. I
chased the beat re-anchor, the timing offset, the clock rate. The measurement
that settled it — clocks per beat reading 19, 13, 32, 16 — pointed at
*ordering*, not timing: the transport handed over every clock in a chunk before
any note in it. A bug in code I wrote on the first day, invisible until
something depended on notes and clocks being interleaved correctly.

Two things to keep. Look at the *values* in a message class before deciding
what the class is for. And when a measurement is impossible — a beat cannot be
13 clocks — the instrument is broken, not the phenomenon.

## The knob map was in a column I had been throwing away

Every knob and fader on the TR-8S transmits a named Control Change, and the
MIDI Implementation Chart says which is which — BD TUNE is 20, BD LEVEL is 24,
RC CTRL is 110. I had read that chart twice and come away with a bare list of
numbers, because `pdftotext` without `-layout` drops the label column. With
`-layout` the whole map is there, fifty-five controls, no mapping session
needed.

Then, once wired, the moves seemed not to arrive: 1,606 control messages
counted, none visible. They were all the beat counter (CC 2), which fires
every beat while playing and had pushed every real knob move out of a
300-entry window within seconds. The path was fine; the window was full of
the thing I had just learned to read.

Two small lessons under one bigger one. Check what an extraction dropped
before concluding the source lacks it. And when a count says "hundreds
arrived" while the view says "nothing", the view is filtering, not the wire.
The bigger one: the machine had been telling me exactly which knob moved from
the first day `Tx EditData` was on. I was reading its messages as a class —
"control change: nothing yet" — instead of as values.

## I proved the feature worked by calling the function

The user said the knobs did not move on screen. I had a screenshot showing them
moving. Both were true, and the screenshot was worthless: I had produced it by
calling `moveControl('BD','tune',110)` from the browser console, which
exercises the last two centimetres of a path and skips everything before it.

The actual path was broken. A Control Change arriving while the machine was
**stopped** came in through `feed_channel`, whose callback handed over the
*full* snapshot — and I had only added the `controls` key to the *light* one.
So the move was recorded and never published. While the machine played, the
clock's light snapshots happened to carry the controls along, which is why
every test of mine passed: I always tested with the machine running.

The proof that finally counted was the one that could have failed: a listener
on the real SSE stream, a CC injected into the server's own monitor, and the
browser's own event counter. Seven events, the right instrument, the right
value, the fader visibly dropped.

Two things to keep. A screenshot is evidence of what the *screen* did, not of
what the *system* did — ask what produced it. And when the user says "I don't
see it" and I have a picture saying otherwise, the user is the one looking at
the real thing.

## Splitting a module is a rename in disguise

`tools.py` had grown to 47 tools and 1,664 lines, so I split it into a package
with one module per namespace. Mechanically simple; three things bit anyway.

Six tools vanished with no error. The `device` namespace module never
registered, because `from . import device` in the package `__init__` resolved
to the *helper function* `device()` defined above it — Python bound the name
first, the import found it already taken, and the submodule was never loaded.
Loading by `importlib.import_module` fixed that and immediately broke the other
way: importing a submodule binds it as a package attribute, so now `device`
*was* the module and every `tools.device()` call in seventeen files became
"'module' object is not callable". Aliasing inside each namespace module did
not help, because the alias came from the same package attribute. What worked
was the boring answer: the helpers live in `_core.py`, every module imports
them from there, and `__init__` re-binds the public names *after* loading the
namespaces.

Then eighteen in-function imports (`from .style import STYLES`, inside a body)
were one directory shallower than the new location and only failed when that
branch ran — which the suite caught, but only because the suite runs them.

The lesson is not about Python's import rules. It is that "split this file"
reads as a file operation and is actually a rename of every name that crosses
the new boundary — and the ones that collide fail silently. Count what
registered before and after. Forty-seven is the only number that mattered.

## I wrote to the machine's storage index with a stride I had not checked

Importing a sample worked first time: the format and the six-step sequence
were read off the machine's own records and confirmed byte-exact. Then I went
to delete the test tone, and my first attempt wrote the "deletable" flag with
the wrong address stride — 1 instead of 16384 — putting a byte 667 into a
temp block that is not any tone's category. The correct write followed a
minute later. Somewhere in there the machine's free-space report went from
10.2 MB to 910 bytes and has not come back, and every delete since is refused.

A full walk of every user sample shows all 115 intact and my test tone
playing. So nothing is lost — but I cannot say which of two writes broke the
accounting, and I could not make the machine's own optimize repair it. I
stopped probing rather than keep writing at an index I had already damaged
once.

The rule I broke has a name in the protocol doc already: verify the address
before writing to live state. I had `blockSize: [1, 0, 0]` in front of me,
decoded it correctly for `temp.ptn` an hour earlier, and used stride 1 anyway
because `offset_address` defaults to 1. The default was the trap. Writes to a
"temp" space are not scratch — they are the machine's working index.

## I turned "reads hang" into "nothing works" and shipped it as a rule

The user hit "cannot read kit 128 while the machine is playing" trying to
change a sound mid-pattern, and asked the obvious question: the panel can do
that, so why can't we? Because `kit.set_instrument` reads the kit before
writing it, and I had made *all* reads refuse during playback. The write was
never the problem — measured, it goes through in 1.4 s with the sequencer
running. I had generalised a true finding about one operation into a
prohibition on the whole feature, and the machine's own behaviour was the
counter-example the whole time.

The fix was small — serve the kit from the bytes already held — and the cost
of not asking "which half of this actually hangs?" was a feature reported as
impossible that was possible all along.


## The record I wrote was accepted, and still wrong

My first pcmTone record put the sample's addresses at +8/+12 as a "right
channel" and a 1 at +56, from a reading of one field name in Roland's config.
The machine took it and played the sample, so I recorded the layout as
verified. Then a delete kept refusing, and comparing my record byte for byte
against three of the machine's own showed +8 is the byte length, +12 is zero,
+56 is zero, and +36..+47 hold constants and a per-sample word I had never
written. Playing was not proof of correctness — the machine only reads the
fields it needs to play.

The delete turned out to be dead on this firmware regardless (`01` for every
argument, every id, even empty), so the wrong record was not the cause. But I
would not have known the record was wrong without it, and the next thing that
does read those fields — a firmware update, a backup tool — would have found
out for me.

Two habits from this. Compare a record you constructed against several the
device made, before calling the layout verified — one accepted write proves
the fields you got right were the only ones checked. And when a device
command refuses, test it with *nonsense* inputs early: `deleteTone` refusing
an empty argument the same way it refused mine settled in one call that the
argument was never the problem.

## Detecting a step edit while the machine plays: by ear is not reliable

The panel transmits nothing when a step is toggled, and a bulk read hangs
during playback, so the only in-playback signal for a step edit is the note
that step fires as the playhead reaches it. It is tempting to diff what is
heard against the pattern we already know. Measured against real patterns, it
does not hold up:

- **Rolls and sub-steps.** On `8-16` ROLLERS the stored line for CH is
  `0,4,8,10`, but played it sounds every even step, `0,2,4,6,8,10,12,14` — the
  rolls fire hits that are not in the stored grid. The heard grid is simply not
  the stored grid.
- **Pitched voices.** A tom used as a bassline sends a different MIDI note per
  pitch; a fixed note→instrument map mis-hears it all over the grid (LT heard on
  the kick steps).
- **±1 anchoring jitter.** Swing and MIDI latency push an offbeat hit onto the
  neighbouring step. Every false positive sits next to a real step.
- **Bar-boundary spill.** A downbeat hit lands on the last step of the previous
  bar for several instruments at once — a whole phantom column.

Filters help (skip pitched voices, suppress columns hit on ≥3 instruments,
require a candidate isolated by ±1 from any known step, demand it on every
recent bar) but never reach zero: on roll/melodic patterns the premise is
broken, not the tuning. Empirically ~10 false "user added a step" per 15s.

So `live_by_ear` is **off by default**. The reliable path is a read-back diff,
which is exact but only possible while stopped: panel edits are caught the
moment the machine stops and by a gentle stopped-poll (~1.6s). This is the
"hearing is unreliable" lesson, re-proved with numbers — trust the reads.

## Pattern-follow died while playing: channel messages split by the clock

Symptom: with Tx Prog Chg on, changing the pattern on the machine no longer
moved the studio; the follow readout sat on "waiting". The MIDI log showed the
Program Changes arriving, yet `program_channels` stayed empty -- the monitor
never parsed them.

Cause: MIDI realtime bytes (clock, 0xF8) may appear *anywhere*, even between a
status byte and its data. The reader delivers realtime and channel bytes in
arrival order (correct, for note step-stamping), which means while the machine
plays a clock byte lands between a Program Change's status byte (0xC9) and its
value, ending one channel payload and starting the next. `feed_channel` parsed
each payload on its own, so it saw `[0xC9]` with no value (dropped) and then a
lone data byte (dropped). Every panel-triggered pattern change while playing
was lost -- and the whole point of follow is to work while playing.

Fix: `feed_channel` keeps a leftover buffer and carries a trailing incomplete
message to the next call, reassembling messages split by an interleaved clock.
A message's length is known from its status nibble (2 bytes for 0xC0/0xD0, 3
otherwise), so "incomplete" is unambiguous. Realtime bytes never reach
`feed_channel` (the reader routes >=0xF8 to `feed`), so the buffer only ever
holds channel bytes. Tested with split Program Change and split note-on.


## Panel-edit follow "never worked": five small bugs in one chain

Symptom (2026-09-02): a step entered on the panel never brought TRACK to that
instrument in the studio, although the read-back diff had been proven with a
simulated write. The simulation passed because it wrote to the slot the
studio was showing. A human never does that. What was actually happening,
found by reading the live state rather than the code:

1. **Follow-while-playing gave up on any slot with no cached bytes and no
   fingerprint.** The index build had silently skipped ten slots (reads that
   failed, probably during playback). The user was dialling exactly those.
   Fix: follow onto a *placeholder* (empty view, correct slot) and read on
   stop; fill missing fingerprints one read per idle pass while stopped;
   record empty patterns in the index too, so "empty" is known, not missing.
2. **The stopped-poll diffed the studio's slot, not the machine's.** With 1,
   the studio sat on 8-16 while the machine was on 8-12; the poll re-read
   8-16 forever and nothing ever changed.
3. **`_resync` published the re-read pattern but never made it the current
   slot.** Even after a resync the next poll went back to the stale slot.
4. **A Program Change was treated as state.** The monitor keeps the last PC;
   `_on_transport` runs on every step tick and re-applied it, so a pattern
   picked in the studio was dragged back sixteen times a bar, and a follow
   that could not complete was retried on every tick. Now each arrival
   (timestamped `pattern_at`) is acted on once.
5. **The ear could override the machine's own word.** By-ear recognition
   preferred a look-alike pattern and moved the slot away from the one the PC
   named. Once the machine has announced a pattern, the ear only picks the
   variation within it.

Also settled with a hand on the panel: **a slot read reflects unsaved panel
edits** (no WRITE needed). And an empty pattern being built sends no notes,
which made the studio think it was stopped and poll it -- a bulk read during
playback, 25s hang. The beat counter (CC 2) now proves "playing" on its own.

The method that found all five: query `/api/state`, `/api/midilog` and the
SSE stream *while the user works*, and compare what the machine said with
what the studio believed. The code read fine; the running state did not.

## TRACK by ear while playing: compare heard with heard, not with stored

The "by ear is unreliable" lesson above stands for *exact steps*: rolls,
sub-steps and swing make the heard grid differ from the stored one. But those
differences repeat identically every bar. So an instrument whose heard steps
in the last bar differ from its own previous two bars (with ±1 tolerance) is
one somebody just edited -- and that is all TRACK-follow needs. It moves
TRACK only; the exact edit still comes from the read on stop. Rules that made
it clean on real patterns:

- exactly one instrument changed (several at once is a variation change);
- the current-bar window is a bar *and a bit* -- with exactly one bar a hit
  on the window's edge dropped out for a tick and read as "removed" (CH step
  13 reported edited while nobody touched CH; SD, with twelve hits a bar,
  fired constantly);
- the same change must be seen on two consecutive checks (0.5s apart);
- the live overlay must last at least a bar at the *current tempo*: a fixed
  2.2s window made a heard step vanish mid-bar at 82 BPM.

Toggle: `focus_by_ear` (`POST /api/follow {"ear": false}`).

**Playing is the normal state; the stop is a technical detail.** A producer
edits while it plays. So a confirmed heard edit is merged into the pattern on
screen *and* the cached model at once (`_merge_heard`), logged at once as
`steps SD: +5,13 (heard)`, and the exact read on stop reconciles silently
(no "picked up an edit" line for what was already announced). The UI shows
no "unconfirmed" state; a hit on an unset pad is a small dot, never a frame.
The one limitation that still surfaces, at the moment it bites: a studio
write while the machine holds edits the studio has only heard is refused
(`_refuse_stale_write`) -- it would carry stale bytes over the panel work.
Reading is impossible until the machine stops, and the message says so.

The clock the machine sends while stopped is NOT the pattern tempo (78.0
stopped vs 82.0 playing on this unit, matching its own display), so a tempo
readout that changes on stop is correct, not a bug.

## The tempo readout wandered because recognition ran on the MIDI thread

The BPM readout drifted 81.8 / 82.2 / 79.5 while the machine sat on 82.0.
Measured via `/api/midilog` with clocks shown: every couple of seconds a
~200ms gap, then six clocks with the same timestamp. That is the reader
thread stalled -- variation recognition (set arithmetic over 128 x 8 prints)
was called from the MIDI callback and held the GIL. Two fixes, both needed:
recognition and ear-focus run on their own `tr8s-listen` thread (the reader
now shows zero bunched clocks), and the period estimate is a least-squares
slope over 145 (index, time) samples that drops any sample on the wrong side
of a stall, snapped to 0.1 with a half-tenth dead-band. Keep `_on_transport`
cheap: it runs between MIDI bytes.


## The assistant on a subscription, and what it needed to actually work

The chat used the Anthropic SDK and an API key nobody had. The Claude Agent
SDK drives the `claude` binary the user is already signed into, so a Pro/Max
subscription carries the studio's chat -- proven with a bare `query()` (4s)
and then end to end with the tool bridge. Things that had to be true:

- **Tools must run in-process.** Only the studio holds the MIDI port, so the
  registry is served as an SDK MCP server (`create_sdk_mcp_server`), with
  `tools=[]` (none of Claude Code's own), `allowed_tools=["mcp__tr8s__*"]`,
  `permission_mode="dontAsk"` (never hang on a prompt), `setting_sources=[]`
  (not the user's Claude Code config or CLAUDE.md).
- **Wrap events, never merge them.** `{"type": "chat", **ev}` let the inner
  event's `type` overwrite `chat`, so the UI never recognised a single chat
  event -- replies arrived and nothing was drawn. This had been broken before
  the backend change too.
- **The model needs the studio's eyes.** Asked "which pattern is selected",
  it said the machine cannot be asked -- true of the protocol, false of the
  studio, which follows the machine. Every turn now starts with a `[studio]`
  block (pattern on screen, tempo, kit, playing/stopped, variation heard,
  recent changes) and there is a `studio_context` tool for after its own
  writes. With that, "make me a techno track on 8-06" read the slot, chose a
  safe kit, built the track, moved the machine there and reported the seed.
- **A SysEx select sends no Program Change.** When the assistant moves the
  machine, the studio would sit on the old pattern and diff the wrong slot;
  the tool bridge reports the move (`on_machine_moved`).
- **`library_list` returned nothing**: `_library_dir` was one `parent` short
  after the tools became a package (`src/library`). A silent empty list, for
  weeks. Path helpers deserve a test that touches a real file.
- **Terms.** Anthropic's Agent SDK docs disallow third-party products offering
  claude.ai login without approval. Personal use on one's own account is what
  this is; distribution with subscription login is not.


## Variation recognition died on generated tracks: a perfect match was refused

MELOTEK, built by the assistant, played variation D and the studio showed
nothing. Measured: D scored 1.00 against what was heard (not one hit off), H
scored 0.90 -- and `identify` refused any win narrower than 0.12. That rule
was written to tell *patterns* apart; sibling variations of one generated
track are a few hits apart by design. Now an exact match (>= 0.95) always
wins, a strong one (>= 0.8) needs only a 0.04 margin, and the studio moves
only when two consecutive checks agree, which is what the margin was really
guarding against. Two other things had to hold for recognition to survive
changes: the fingerprint index is refreshed on every pattern write or read
(`Device.remember` is wrapped -- before, a freshly written track kept the old
slot's print until the next stop), and a heard edit updates the print of the
variation it lands in. Measure the scores before touching the thresholds:
`fingerprint.score` over the live rows from `/api/state` takes ten lines.
