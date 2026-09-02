"""
Layer 4 — the command surface.

Every capability is exposed as a named tool with a JSON schema, so an LLM (or
an HTTP layer, or a CLI) can drive the TR-8S without knowing anything about
SysEx. Tools take and return plain JSON-serialisable values, and raise
ToolError with an actionable message rather than leaking byte offsets.

    from tr8s.tools import REGISTRY, call, schemas
    schemas()                       -> list of JSON schemas
    call("pattern.get", {"slot": 0})

Layout: this file is the registry and the helpers every tool shares. Each
namespace lives in its own module (`pattern.py`, `kit.py`, ...) and registers
its tools on import; the imports at the bottom of this file are what make
`import tr8s.tools` bring the whole surface in.

Design rules:
  * Slots are accepted as either a linear 0..127 index or a panel string
    like "8-03" / "1-01"; kits additionally accept their 1-based panel number.
  * Anything that changes the device says so in its result.
  * Nothing silently truncates or transposes: out-of-range values raise, and
    clamped notes come back in `warnings`.
"""

from __future__ import annotations

import inspect
import re
import subprocess
from pathlib import Path

from .. import config
from ..device import Device, DeviceError, panel_to_slot, slot_to_panel
from ..history import HISTORY
from ..kit import FIELDS as KIT_FIELDS
from ..kit import TRACKS, Kit
from ..melody import MelodyError
from ..melody import read as melody_read
from ..melody import write as melody_write
from ..pattern import VARIATIONS, Pattern
from ..tones import Catalog

REGISTRY: dict[str, dict] = {}
_session: Device | None = None


class ToolError(RuntimeError):
    pass


def tool(name: str, description: str, params: dict, mutates: bool = False):
    def deco(fn):
        REGISTRY[name] = {
            "name": name,
            "description": description,
            "mutates_device": mutates,
            "input_schema": {
                "type": "object",
                "properties": params,
                "required": [k for k, v in params.items()
                             if not v.pop("_optional", False)],
                "additionalProperties": False,
            },
            "fn": fn,
        }
        return fn
    return deco


def opt(schema: dict) -> dict:
    schema["_optional"] = True
    return schema


def schemas() -> list[dict]:
    """JSON schemas for every tool, ready to hand to an LLM."""
    return [{k: v for k, v in t.items() if k != "fn"} for t in REGISTRY.values()]


def device() -> Device:
    global _session
    if _session is None:
        _session = Device().open()
    return _session


def set_device(dev):
    """Point the registry at a specific Device -- used by tests."""
    global _session
    _session = dev


def close():
    global _session
    if _session is not None:
        _session.close()
        _session = None


def call(name: str, args: dict | None = None):
    if name not in REGISTRY:
        raise ToolError(f"unknown tool {name!r}; available: {sorted(REGISTRY)}")
    fn = REGISTRY[name]["fn"]
    args = dict(args or {})
    sig = inspect.signature(fn)
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD
                      for p in sig.parameters.values())
    if not accepts_any:
        unknown = set(args) - set(sig.parameters)
        if unknown:
            allowed = sorted(k for k in sig.parameters)
            raise ToolError(
                f"{name}: unexpected arguments {sorted(unknown)}; "
                f"accepts {allowed}")
    _capture_for_undo(name, args)
    try:
        return fn(**args)
    except (DeviceError, MelodyError, ValueError) as e:
        raise ToolError(f"{name}: {e}") from e


def _capture_for_undo(name: str, args: dict):
    """
    Snapshot whatever a mutating tool is about to overwrite.

    Best effort by design: if the slot cannot be resolved or read, the edit
    still goes ahead. Losing a step of undo is a nuisance; refusing to write
    because history failed would be worse.
    """
    spec = REGISTRY[name]
    if not spec.get("mutates_device") or name.startswith("history."):
        return
    kind = "kit" if name.startswith("kit.") else "pattern"
    raw = args.get("slot")
    if raw is None:
        return
    try:
        slot = _slot(raw, kind)
        HISTORY.capture(device(), kind, slot, f"{name} on {kind} {raw}")
    except Exception:
        pass


def _slot(value, kind: str = "pattern") -> int:
    """Accept 0..127, '8-03', or for kits the 1-based panel number as a string."""
    if isinstance(value, int):
        if not 0 <= value <= 127:
            raise ToolError(f"slot {value} out of range 0..127")
        return value
    s = str(value).strip()
    m = re.fullmatch(r"(\d)\s*-\s*(\d{1,2})", s)
    if m:
        return panel_to_slot(int(m.group(1)), int(m.group(2)))
    if s.isdigit():
        return _slot(int(s), kind)
    raise ToolError(f"cannot parse slot {value!r}; use 0..127 or '8-03'")


# ===================================================================== device

DEFAULT_KEYS = {
    # techno and its neighbours live in minor and phrygian; the flat second is
    # what makes phrygian sound like the genre rather than like house
    "techno": "C minor", "hypnotic": "F# phrygian", "hard": "G phrygian",
    "acid": "A minor", "dub": "D minor", "broken": "E minor",
    "dnb": "F minor", "lofi": "A minor", "house": "C minor",
}
DEFAULT_LINE = {
    "dub": "stab", "hypnotic": "arp", "acid": "acid",
}


def _library_dir() -> Path:
    # repo root / library. This file is src/tr8s/tools/_core.py: when the
    # tools became a package the path was left one level short (src/library)
    # and library.list quietly reported no tracks at all.
    return Path(__file__).resolve().parents[3] / "library"
