"""
Layer 3 — closed-loop measurement. The device tells us about itself.

Two sweeps live here:

  `catalogue_tones()`   assign each tone in turn, trigger it, record, measure.
                        Produces the root pitch / loudness / decay / brightness
                        catalogue that makes sound selection a query instead of
                        a guess.

  `probe_kit_byte()`    sweep one unidentified byte of a kit instrument record
                        and report what moved in the audio. Pitch shifting means
                        tuning, envelope stretching means decay, centroid moving
                        means a filter, and so on. This is how the remaining
                        "writable but unknown" offsets get identified without a
                        human at the panel.

Both are resumable and both restore the scratch slot they borrow, including on
Ctrl-C. Neither needs supervision.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from . import audio, config
from .kit import SAMPLE_PARAM_OFFSETS, Kit
from .tones import CATEGORIES

# a scratch kit slot to host the tone under test, restored afterwards
SCRATCH_KIT = 123
PROBE_INST = "LT"
PROBE_NOTE = 43
CHANNEL = 9

# donors supply a whole instrument record, because a sample tone needs its
# sample-parameter bytes (+28..+41) or it plays near-silently
SAMPLE_DONOR = (61, "LT")
ACB_DONOR = (1, "BD")

# The probe tone decides what a sweep can even detect, so it is chosen from the
# catalogue rather than by taste: a SINGLE oscillator (so pitch is unambiguous
# -- a chord tone would defeat the detector), SUSTAINED (so a shortened envelope
# shows up), and harmonically rich at ~1300 Hz (so a filter moves the centroid).
DEFAULT_PROBE_TONE = 465        # "OSC Saw Low", root C2

GAP = 2.6                 # seconds per tone: write + commit + trigger + tail
BATCH = 12                # tones per continuous recording
SETTLE = 0.35             # after commit, before triggering
DECIMATE = 16             # 96k -> 6k is ample for anything below ~2.5 kHz


def _tone_meta(dev, tid: int) -> dict | None:
    blob = dev.transport.read_blob("tone", tid, timeout=6)
    if not blob or len(blob) < 18:
        return None
    name = "".join(chr(c) for c in blob[:16] if 32 <= c < 127).rstrip()
    if not name:
        return None
    cat = CATEGORIES[blob[16]] if blob[16] < len(CATEGORIES) else str(blob[16])
    return {"id": tid, "name": name, "cat": cat, "type": blob[17]}


def _donor_records(dev) -> dict[int, bytes]:
    """One whole 52-byte record per tone type, read from the DEVICE.

    Reading from a backup file would hand back the original ACB record whose
    sample bytes are zero -- the bug that once made a whole kit inaudible.
    """
    out = {}
    for kind, (slot, inst) in ((2, SAMPLE_DONOR), (1, ACB_DONOR)):
        blob = dev.transport.read_blob("kit", slot, timeout=20)
        if not blob:
            raise RuntimeError(f"could not read donor kit {slot}")
        k = Kit.from_bytes(blob)
        o = Kit.record_offset(inst)
        rec = bytes(k.raw[o:o + 52])
        if kind == 2 and sum(1 for d in SAMPLE_PARAM_OFFSETS if rec[d]) < 4:
            raise RuntimeError(
                f"sample donor kit {slot+1}/{inst} has empty sample parameters; "
                f"every sample tone would measure as silent")
        out[kind] = rec
    return out


def _flush_print(*a):
    print(*a, flush=True)      # nohup buffers otherwise, hiding all progress


def catalogue_tones(dev, lo: int = 0, hi: int = 1023, only=None,
                    out_path: Path | None = None, log=_flush_print) -> dict:
    """
    Measure every tone in a range. Resumable: existing entries are skipped.
    """
    out_path = out_path or config.tone_catalog_path()
    results: dict = {}
    if out_path.exists():
        try:
            results = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            results = {}

    original = dev.transport.read_blob("kit", SCRATCH_KIT, timeout=20)
    if not original:
        raise RuntimeError(f"could not read scratch kit {SCRATCH_KIT}")
    donors = _donor_records(dev)

    log(f"enumerating tones {lo}..{hi}")
    todo = []
    for tid in range(lo, hi + 1):
        if str(tid) in results and "peak" in results[str(tid)]:
            continue
        m = _tone_meta(dev, tid)
        if not m:
            continue
        if only and m["cat"] not in only:
            continue
        todo.append(m)
    log(f"{len(todo)} tones to measure (~{len(todo) * GAP / 60:.0f} min)")

    pbase = Kit.record_offset(PROBE_INST)
    tmp = config.subdir("recordings") / "tone_batch.wav"
    try:
        for start in range(0, len(todo), BATCH):
            group = todo[start:start + BATCH]
            dur = int(GAP * len(group) + 6)
            proc, wav = audio.record_async(dur, tmp)
            time.sleep(1.5)
            t0 = time.time()
            marks = []
            for i, meta in enumerate(group):
                blob = bytearray(original)
                blob[pbase:pbase + 52] = donors.get(meta["type"], donors[1])
                k = Kit(blob)
                k.set(PROBE_INST, "tone", meta["id"])
                k.set(PROBE_INST, "tune", 0)
                k.set(PROBE_INST, "decay", 255)
                k.set(PROBE_INST, "pan", 0)
                k.set(PROBE_INST, "reverb", 0)
                k.set(PROBE_INST, "delay", 0)
                dev.transport.send_blob("kit", SCRATCH_KIT, k.to_bytes())
                dev.transport.commit("kit", SCRATCH_KIT)
                # fire on an absolute schedule: a slow write must not push the
                # trigger outside the recording window
                due = i * GAP + 1.0
                slack = due - (time.time() - t0)
                if slack > 0:
                    time.sleep(slack)
                marks.append(time.time() - t0)
                dev.transport.note(PROBE_NOTE, 120)
            proc.wait()

            ch, rate, samples = audio.read_wav(wav)
            mono = audio.mono(samples, ch, DECIMATE)
            r = rate / DECIMATE
            for meta, mark in zip(group, marks):
                s = int((mark + 1.5 + 0.01) * r)
                seg = mono[s:s + int(0.9 * r)]
                m = audio.measure(seg, r)
                row = dict(meta)
                row.update(m.as_dict())
                results[str(meta["id"])] = row
                out_path.write_text(json.dumps(results, indent=1, sort_keys=True))
                log(f"  {meta['id']:4d} {meta['cat']:<7s} {meta['name']:<18s} "
                    f"root={row.get('root') or '-':>5s} peak={row.get('peak', 0):.3f} "
                    f"decay={'sust' if row.get('sustained') else row.get('decay_ms')} "
                    f"bright={row.get('centroid') or 0}")
    finally:
        dev.transport.send_blob("kit", SCRATCH_KIT, original)
        dev.transport.commit("kit", SCRATCH_KIT)
        log(f"scratch kit {SCRATCH_KIT + 1} restored; "
            f"{len(results)} tones catalogued -> {out_path}")
    return results


# ------------------------------------------------------------------- probing

def probe_kit_byte(dev, offset: int, values=None, tone: int | None = None,
                   log=_flush_print) -> dict:
    """
    Sweep one byte of a kit instrument record and report what changed in the
    audio. Returns the per-value measurements plus a suggested interpretation.

    The interpretation is a hint, never a conclusion -- a byte that only moves
    loudness could be gain, a send with the effect off, or an envelope. Anything
    ambiguous stays labelled unknown.
    """
    values = list(values or (0, 32, 64, 96, 128, 160, 192, 224, 255))
    if tone is None:
        tone = DEFAULT_PROBE_TONE
    original = dev.transport.read_blob("kit", SCRATCH_KIT, timeout=20)
    if not original:
        raise RuntimeError("could not read the scratch kit")
    donors = _donor_records(dev)
    pbase = Kit.record_offset(PROBE_INST)

    base = bytearray(original)
    base[pbase:pbase + 52] = donors[2]        # a sample tone: most parameters apply
    seed = Kit(bytearray(base))
    seed.set(PROBE_INST, "tone", tone)
    seed.set(PROBE_INST, "tune", 0)
    seed.set(PROBE_INST, "decay", 200)
    seed.set(PROBE_INST, "pan", 0)
    seed.set(PROBE_INST, "reverb", 0)
    seed.set(PROBE_INST, "delay", 0)

    rows = []
    tmp = config.subdir("recordings") / f"probe_{offset}.wav"
    try:
        dur = int(GAP * len(values) + 6)
        proc, wav = audio.record_async(dur, tmp)
        time.sleep(1.5)
        t0 = time.time()
        marks = []
        for i, v in enumerate(values):
            k = Kit(bytearray(seed.raw))
            k.raw[pbase + offset] = v & 0xFF
            dev.transport.send_blob("kit", SCRATCH_KIT, k.to_bytes())
            dev.transport.commit("kit", SCRATCH_KIT)
            due = i * GAP + 1.0
            slack = due - (time.time() - t0)
            if slack > 0:
                time.sleep(slack)
            marks.append(time.time() - t0)
            dev.transport.note(PROBE_NOTE, 120)
        proc.wait()

        ch, rate, samples = audio.read_wav(wav)
        mono = audio.mono(samples, ch, DECIMATE)
        r = rate / DECIMATE
        for v, mark in zip(values, marks):
            s = int((mark + 1.5 + 0.01) * r)
            m = audio.measure(mono[s:s + int(0.9 * r)], r)
            rows.append({"value": v, **m.as_dict()})
            log(f"  +{offset:<3} = {v:3d}: peak={m.peak:.4f} "
                f"hz={m.hz or '-'} decay={'sust' if m.sustained else m.decay_ms} "
                f"bright={m.centroid or '-'}")
    finally:
        dev.transport.send_blob("kit", SCRATCH_KIT, original)
        dev.transport.commit("kit", SCRATCH_KIT)

    return {"offset": offset, "values": rows,
            "interpretation": interpret(rows)}


# what each offset is already known to be, so probing skips them
KNOWN_KIT_OFFSETS = {
    0: "tone (low byte)", 1: "tone (high byte)", 2: "tune", 3: "decay",
    4: "level (read-only: the fader owns it)", 6: "pan",
    7: "reverb send", 8: "delay send", 11: "LFO depth",
}
# these carry a sample's envelope/gain; sweeping them can silence the probe
# tone, which is a result in itself but worth flagging in the report
SAMPLE_REGION = range(28, 42)


def probe_many(dev, offsets=None, out_path: Path | None = None,
               tone: int | None = None, log=_flush_print) -> dict:
    """
    Probe every unidentified byte of a kit instrument record, unattended.

    Resumable: offsets already in the report are skipped. Roughly 25 s per
    offset, so a full pass over the unknowns is about fifteen minutes.
    """
    out_path = out_path or (config.data_dir() / "kit_byte_probe.json")
    report: dict = {}
    if out_path.exists():
        try:
            report = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            report = {}

    if offsets is None:
        offsets = [o for o in range(52) if o not in KNOWN_KIT_OFFSETS]
    todo = [o for o in offsets if str(o) not in report]
    log(f"{len(todo)} offsets to probe (~{len(todo) * 25 / 60:.0f} min); "
        f"{len(report)} already done")

    for off in todo:
        note = ""
        if off in SAMPLE_REGION:
            note = ("inside the sample envelope/gain region: silence here is "
                    "expected and does not mean the byte is inert")
        log(f"\noffset +{off}{'  (' + note + ')' if note else ''}")
        try:
            res = probe_kit_byte(dev, off, tone=tone, log=log)
        except Exception as e:
            log(f"  probe failed: {e}")
            continue
        if note:
            res["caveat"] = note
        report[str(off)] = res
        out_path.write_text(json.dumps(report, indent=1, sort_keys=True))
        i = res["interpretation"]
        log(f"  => {i['verdict']} ({i['confidence']})")
    log(f"\n{len(report)} offsets probed -> {out_path}")
    return report


def probe_report(report: dict) -> str:
    """A readable summary, ordered so the confident findings come first."""
    rows = []
    for off_s, res in report.items():
        i = res.get("interpretation", {})
        rows.append((int(off_s), i.get("verdict", "?"), i.get("confidence", "?"),
                     i.get("signals", {}), res.get("caveat")))
    order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (order.get(r[2], 3), r[0]))

    out = ["| offset | finding | confidence | pitch st | level | bright | decay |",
           "|---|---|---|---|---|---|---|"]
    for off, verdict, conf, sig, caveat in rows:
        out.append(
            f"| `+{off}` | {verdict}{' ¹' if caveat else ''} | {conf} | "
            f"{sig.get('pitch_semitones', '-')} | {sig.get('level_spread', '-')} | "
            f"{sig.get('brightness_spread', '-')} | {sig.get('decay_spread', '-')} |")
    if any(r[4] for r in rows):
        out.append("")
        out.append("¹ inside the sample envelope/gain region — silence there is "
                   "expected and is not evidence the byte does nothing.")
    return "\n".join(out)


def _spread(vals) -> float:
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return 0.0
    lo, hi = min(vals), max(vals)
    return 0.0 if lo == 0 else (hi - lo) / abs(lo)


def _rank_corr(xs, ys) -> float:
    """
    Spearman's rho, over the pairs where both are known.

    A real continuous parameter moves the sound in one direction as the byte
    rises. Something that swaps in a different sample at low values produces a
    huge range with no trend at all — which reads identically to tuning if you
    only look at max over min.
    """
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 4:
        return 0.0

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):                 # average ranks within a tie
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return 0.0 if dx == 0 or dy == 0 else num / (dx * dy)


def _step_dominance(xs, ys) -> float:
    """
    How much of the total change happens in one adjacent step, 0..1.

    Monotonicity is not enough on its own. A byte that swaps the sample once at
    the bottom of its range and is then flat gives a perfect rank correlation:
    two values high, seven low, never going back up. But a parameter that
    *tunes* spreads its change across the range. Near 1.0 here means a switch.
    """
    pairs = sorted(((x, y) for x, y in zip(xs, ys)
                    if x is not None and y is not None), key=lambda p: p[0])
    if len(pairs) < 3:
        return 0.0
    vals = [y for _, y in pairs]
    total = max(vals) - min(vals)
    if total <= 0:
        return 0.0
    biggest = max(abs(b - a) for a, b in zip(vals, vals[1:]))
    return biggest / total


def interpret(rows: list[dict]) -> dict:
    """
    Suggest what a swept byte controls. Deliberately conservative: it reports
    what moved and by how much, and only names a parameter when one dimension
    dominates AND moves monotonically with the byte. Everything else comes back
    "unclear".

    The trend checks are not decoration. Three kit offsets swept as "tuning,
    high confidence" on range alone; their pitch actually stepped once at the
    bottom of the range and then sat flat, or vanished entirely in the middle.
    That is a byte that selects something, not one that tunes — so a verdict of
    "tuning" needs the pitch to move *with* the value (rank correlation) and to
    keep moving *across* the range (step dominance), not just to differ between
    the ends.
    """
    live = [r for r in rows if not r.get("silent")]
    if len(live) < 3:
        return {"verdict": "mostly silent", "confidence": "low",
                "note": "the byte may gate output, or the probe tone was quiet"}

    import math
    hz = [r.get("hz") for r in live]
    known_hz = [h for h in hz if h]
    semis = 0.0
    if len(known_hz) >= 2 and min(known_hz) > 0:
        semis = 12 * math.log2(max(known_hz) / min(known_hz))

    peak_spread = _spread([r.get("peak") for r in live])
    cent = [r.get("centroid") for r in live if r.get("centroid")]
    cent_spread = _spread(cent)
    decays = [r.get("decay_ms") for r in live if r.get("decay_ms")]
    decay_spread = _spread(decays)
    silent_count = len(rows) - len(live)

    values = [r.get("value") for r in live]
    rho_hz = _rank_corr(values, hz)
    rho_peak = _rank_corr(values, [r.get("peak") for r in live])
    rho_cent = _rank_corr(values, [r.get("centroid") for r in live])
    rho_decay = _rank_corr(values, [r.get("decay_ms") for r in live])
    pitched = len(known_hz) / len(live) if live else 0.0
    step_hz = _step_dominance(values, hz)

    signals = {
        "pitch_semitones": round(semis, 2),
        "level_spread": round(peak_spread, 2),
        "brightness_spread": round(cent_spread, 2),
        "decay_spread": round(decay_spread, 2),
        "silent_values": silent_count,
        "pitch_trend": round(rho_hz, 2),
        "level_trend": round(rho_peak, 2),
        "brightness_trend": round(rho_cent, 2),
        "decay_trend": round(rho_decay, 2),
        "pitched_fraction": round(pitched, 2),
        "pitch_step_dominance": round(step_hz, 2),
    }

    if (semis > 1.5 and abs(rho_hz) > 0.8 and pitched > 0.7
            and step_hz < 0.6):
        verdict, conf = "tuning (pitch tracks the value)", "high"
    elif semis > 1.5:
        # a big pitch range with no trend, or with the pitch dropping out in
        # the middle: the byte is choosing something, not tuning it
        verdict, conf = ("selects or switches something (the sound changes a "
                         "lot but not with the value)"), "medium"
    elif decay_spread > 0.5 and peak_spread < 0.5 and abs(rho_decay) > 0.6:
        verdict, conf = "envelope length (decay/hold)", "medium"
    elif cent_spread > 0.4 and semis < 0.5 and abs(rho_cent) > 0.6:
        verdict, conf = "filter or tone colour (brightness moves, pitch does not)", "medium"
    elif peak_spread > 0.5 and abs(rho_peak) > 0.6:
        verdict, conf = "level or gain", "medium"
    elif max(signals[k] for k in ("pitch_semitones", "level_spread",
                                  "brightness_spread", "decay_spread")) < 0.15:
        verdict, conf = "no audible effect on this tone", "medium"
    else:
        verdict, conf = "unclear", "low"

    return {"verdict": verdict, "confidence": conf, "signals": signals}
