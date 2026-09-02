"""
Layer 2 — criticising a pattern before you hear it.

Every tone has been played and measured, and the pattern says exactly which of
them fire on which step. That is enough to catch the mistakes that actually
spoil a techno loop, without recording anything:

  **The low end colliding.** A kick and a bassline both under ~150 Hz landing
  on the same step is the single most common reason a loop sounds weak on a
  big system. Two low sounds at once do not add up; they cancel and smear.

  **Masking.** Two parts whose measured brightness sits within a few hundred
  hertz of each other, playing at the same time, do not both get heard. One of
  them is wasted.

  **Smearing.** At 140 BPM a sixteenth is 107 ms. An open hat that decays over
  400 ms is still sounding when the next one starts. Sometimes that is the
  sound you want; if it was not deliberate it is why the pattern feels muddy.
  Instruments carrying per-step motion are exempt: they are playing a line, and
  one note running into the next is legato rather than a mistake.

  **Nothing in a register.** A loop with no energy above 1 kHz reads as dull;
  one with nothing below 150 Hz has no floor.

The measurement has a ceiling: brightness is computed on audio decimated to
6 kHz, so everything above 3 kHz folds into the top of the scale. Hats, rides
and crashes are therefore indistinguishable by centroid, and are never reported
as masking each other — a finding that fires on every kit ever built is not a
finding.

The findings are advisory. Level is owned by the physical faders, so this can
name the problem but cannot fix it by turning something down — what it can
suggest is moving a hit, choosing a shorter tone, or picking a different sound.
"""

from __future__ import annotations

from .calibration import decay_ms_for_byte

LOW_HZ = 150            # below this, two sounds at once fight
MASK_HZ = 250           # centroids closer than this mask each other
BRIGHT_HZ = 1000        # a loop with nothing above this reads as dull

# Hats, rides and crashes all measure between about 1.4 and 2.1 kHz, because
# the tone analysis decimates to 6 kHz and everything above 3 kHz folds into
# the top of that range. So a closed hat and a ride "50 Hz apart" is a limit of
# the measurement, not a fact about the sounds. Reporting those as collisions
# would bury the real findings under noise the user must learn to ignore.
METAL = {"CH", "OH", "CC", "RC"}

SEVERITY = ("info", "warning")


def _steps_of(pattern, variation, inst) -> str:
    try:
        return pattern.get_steps(variation, inst)
    except Exception:
        return "." * 16


def step_ms(tempo: float, scale: str = "16") -> float:
    """Milliseconds per step. A 16th at 140 BPM is 107 ms."""
    per_beat = 60000.0 / max(tempo, 1.0)
    return per_beat / {"8T": 3, "16T": 6, "16": 4, "32": 8}.get(scale, 4)


def audit(pattern, kit, catalog, variation: str = "A",
          tempo: float | None = None) -> dict:
    """
    Look over one variation and report what will not work.

    `kit` is a Kit, `catalog` a Catalog. Instruments whose tone was never
    measured are skipped rather than guessed at, and reported as such.
    """
    tempo = float(tempo or getattr(pattern, "tempo", 130.0) or 130.0)
    scale = getattr(pattern, "scale", "16") or "16"
    ms = step_ms(tempo, scale)

    parts = []
    unmeasured = []
    for inst in getattr(kit, "TRACKS", None) or _tracks(kit):
        steps = _steps_of(pattern, variation, inst)
        hits = [i for i, c in enumerate(steps) if c != "."]
        if not hits:
            continue
        tone_id = kit.get(inst, "tone")
        info = catalog.get(tone_id)
        if info is None:
            unmeasured.append({"instrument": inst, "tone": tone_id})
            continue

        # How long this instrument actually rings is the tone's own length AND
        # the kit's DECAY envelope, whichever runs out first -- the envelope
        # can shorten a sound but cannot make a short sample ring on. Reading
        # only the catalogue makes the audit disagree with kit.fix, which has
        # just shortened the envelope and changed nothing the audit can see.
        env_ms = decay_ms_for_byte(kit.get(inst, "decay"))
        natural = info.decay_ms
        if info.sustained:
            decay_ms, sustained = env_ms, env_ms is None
        elif env_ms is None:
            decay_ms, sustained = natural, False
        else:
            decay_ms, sustained = min(natural or env_ms, env_ms), False

        # an instrument carrying per-step motion is playing a line, not a
        # drum part. A bass note that rings until the next one is legato, which
        # is what a bassline is supposed to do -- flagging it as smearing is
        # the audit misreading the part
        melodic = any(pattern.get_motion(variation, inst, i)["mask"]
                      for i in range(16))

        parts.append({
            "instrument": inst, "tone": tone_id, "name": info.name,
            "melodic": melodic,
            "hits": hits, "steps": steps,
            "centroid": info.centroid, "decay_ms": decay_ms,
            "tone_decay_ms": natural, "envelope_ms": env_ms,
            "sustained": sustained, "peak": info.peak,
            "root": info.root,
        })

    findings = []
    findings += _low_end_collisions(parts)
    findings += _masking(parts)
    findings += _smearing(parts, ms)
    findings += _register_gaps(parts)
    findings += _density(parts)

    order = {"warning": 0, "info": 1}
    findings.sort(key=lambda f: (order.get(f["severity"], 2), f["instrument"]))
    return {
        "variation": variation, "tempo": tempo, "step_ms": round(ms, 1),
        "parts": [{k: p[k] for k in ("instrument", "name", "centroid",
                                     "decay_ms", "root", "melodic")}
                  for p in parts],
        "findings": findings,
        "unmeasured": unmeasured,
        "verdict": _verdict(findings, parts),
    }


def _tracks(kit):
    from .kit import TRACKS
    return TRACKS


def _low(p) -> bool:
    return p["centroid"] is not None and p["centroid"] < LOW_HZ


def _low_end_collisions(parts) -> list[dict]:
    lows = [p for p in parts if _low(p)]
    out = []
    for i, a in enumerate(lows):
        for b in lows[i + 1:]:
            shared = sorted(set(a["hits"]) & set(b["hits"]))
            if not shared:
                continue
            sev = "warning" if len(shared) >= 2 else "info"
            out.append({
                "severity": sev,
                "kind": "low-end collision",
                "instrument": a["instrument"],
                "with": b["instrument"],
                "steps": [s + 1 for s in shared],
                "detail": (
                    f"{a['instrument']} ({a['name']}, {a['centroid']:.0f} Hz) "
                    f"and {b['instrument']} ({b['name']}, "
                    f"{b['centroid']:.0f} Hz) both land on step"
                    f"{'s' if len(shared) > 1 else ''} "
                    f"{', '.join(str(s + 1) for s in shared)}. Two sounds this "
                    f"low at once cancel rather than add."),
                "fix": (f"move {b['instrument']} off the downbeat -- a techno "
                        f"bassline belongs between the kicks, not on them"),
            })
    return out


def _masking(parts) -> list[dict]:
    out = []
    known = [p for p in parts if p["centroid"] is not None and not _low(p)]
    for i, a in enumerate(known):
        for b in known[i + 1:]:
            if a["instrument"] in METAL and b["instrument"] in METAL:
                continue                    # unresolvable, see METAL
            gap = abs(a["centroid"] - b["centroid"])
            if gap >= MASK_HZ:
                continue
            shared = sorted(set(a["hits"]) & set(b["hits"]))
            if len(shared) < 2:
                continue
            out.append({
                "severity": "info",
                "kind": "masking",
                "instrument": a["instrument"],
                "with": b["instrument"],
                "steps": [s + 1 for s in shared],
                "detail": (
                    f"{a['instrument']} ({a['centroid']:.0f} Hz) and "
                    f"{b['instrument']} ({b['centroid']:.0f} Hz) sit "
                    f"{gap:.0f} Hz apart and share {len(shared)} steps. One of "
                    f"them will not be heard."),
                "fix": (f"pick a brighter or darker tone for "
                        f"{b['instrument']}, or move it off those steps"),
            })
    return out


def _smearing(parts, ms: float) -> list[dict]:
    out = []
    for p in parts:
        if p.get("melodic"):
            continue                # notes running into each other is legato
        gaps = [b - a for a, b in zip(p["hits"], p["hits"][1:])]
        if not gaps:
            continue
        tightest = min(gaps) * ms
        if p["sustained"]:
            out.append({
                "severity": "info", "kind": "smearing",
                "instrument": p["instrument"], "with": None,
                "steps": [], "detail":
                    f"{p['instrument']} is on '{p['name']}', a sustained tone, "
                    f"repeating every {tightest:.0f} ms. It never stops "
                    f"sounding.",
                "fix": "fine if it is a pad or a bassline; wrong for a "
                       "percussive part",
            })
            continue
        if p["decay_ms"] and p["decay_ms"] > tightest * 1.5:
            out.append({
                # 2.5x the gap is already audibly muddy, not a matter of taste
                "severity": "warning" if p["decay_ms"] > tightest * 2.5 else "info",
                "kind": "smearing",
                "instrument": p["instrument"], "with": None,
                "steps": [], "detail":
                    f"{p['instrument']} ('{p['name']}') decays over "
                    f"{p['decay_ms']:.0f} ms but repeats every "
                    f"{tightest:.0f} ms, so each hit is still sounding when "
                    f"the next arrives.",
                "fix": ("shorten it with kit.set_instrument decay, or choose a "
                        "tighter tone -- tones.search reports decay_ms"),
            })
    return out


def _register_gaps(parts) -> list[dict]:
    if not parts:
        return []
    cents = [p["centroid"] for p in parts if p["centroid"] is not None]
    if not cents:
        return []
    out = []
    if not any(c < LOW_HZ for c in cents):
        out.append({
            "severity": "warning", "kind": "register", "instrument": "-",
            "with": None, "steps": [],
            "detail": "nothing in this variation is below 150 Hz: the loop has "
                      "no floor.",
            "fix": "add a kick, or give a track a low tone",
        })
    if not any(c > BRIGHT_HZ for c in cents):
        out.append({
            "severity": "info", "kind": "register", "instrument": "-",
            "with": None, "steps": [],
            "detail": "nothing above 1 kHz: the loop will read as dull however "
                      "loud it is.",
            "fix": "add a hat or a rim -- tones.search with a high centroid",
        })
    return out


def _density(parts) -> list[dict]:
    total = sum(len(p["hits"]) for p in parts)
    if total > 70:
        return [{
            "severity": "info", "kind": "density", "instrument": "-",
            "with": None, "steps": [],
            "detail": f"{total} hits in 16 steps across {len(parts)} parts. "
                      f"Techno is usually subtractive; this is a lot.",
            "fix": "thin the busiest part, or drop one layer entirely",
        }]
    if total and total < 6:
        return [{
            "severity": "info", "kind": "density", "instrument": "-",
            "with": None, "steps": [],
            "detail": f"only {total} hits in the whole bar.",
            "fix": "fine for an intro or a break; sparse for a main groove",
        }]
    return []


def _verdict(findings, parts) -> str:
    if not parts:
        return "nothing plays in this variation"
    warnings = [f for f in findings if f["severity"] == "warning"]
    if not findings:
        return f"{len(parts)} parts, nothing obviously in each other's way"
    if not warnings:
        return (f"{len(parts)} parts; {len(findings)} thing"
                f"{'s' if len(findings) > 1 else ''} worth a look, none serious")
    return (f"{len(warnings)} problem{'s' if len(warnings) > 1 else ''} worth "
            f"fixing: " + "; ".join(sorted({f["kind"] for f in warnings})))
