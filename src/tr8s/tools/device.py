"""device tools — see the package docstring for the conventions."""

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
from ._core import (DEFAULT_KEYS, DEFAULT_LINE, REGISTRY, ToolError,
                    _library_dir, _slot, opt, tool)
from ._core import device as _device_helper

@tool("device.info", "Firmware version and connection details of the TR-8S.", {})
def device_info():
    return _device_helper().info()




@tool("device.trigger",
      "Play one instrument immediately, to audition a sound. Does not change "
      "anything.",
      {"instrument": {"type": "string", "enum": TRACKS},
       "velocity": opt({"type": "integer", "minimum": 1, "maximum": 127})})
def device_trigger(instrument: str, velocity: int = 110):
    _device_helper().trigger(instrument, velocity)
    return {"triggered": instrument, "velocity": velocity}




@tool("device.backup",
      "Read every pattern and kit off the device into the local backup "
      "directory. Read-only with respect to the TR-8S; takes several minutes.",
      {"kinds": opt({"type": "array", "items": {"type": "string",
                                                "enum": ["pattern", "kit"]}}),
       "lo": opt({"type": "integer"}), "hi": opt({"type": "integer"})})
def device_backup(kinds=("pattern", "kit"), lo: int = 0, hi: int = 127):
    counts = _device_helper().backup(tuple(kinds), lo, hi)
    return {"saved": counts, "directory": str(config.data_dir())}




@tool("device.restore",
      "Restore one pattern or kit from the local backup, overwriting the slot.",
      {"kind": {"type": "string", "enum": ["pattern", "kit"]},
       "slot": {"type": ["integer", "string"]}}, mutates=True)
def device_restore(kind: str, slot):
    return _device_helper().restore(kind, _slot(slot, kind))


# ==================================================================== pattern



@tool("device.select",
      "Move the MACHINE to a pattern or kit -- what pressing the pads does. "
      "Uses the same three writes Roland's own client uses, so it works "
      "whether or not Rx Prog Chg is on. Note this changes what the player "
      "hears, unlike loading a pattern in the studio, which only changes what "
      "is on screen.",
      {"pattern": opt({"type": ["integer", "string"],
                       "description": "slot or panel string, e.g. '8-09'"}),
       "kit": opt({"type": ["integer", "string"]})}, mutates=True)
def device_select(pattern=None, kit=None):
    d = _device_helper()
    out = {}
    if pattern is not None:
        s = _slot(pattern)
        d.transport.select_pattern(s)
        out["pattern"] = {"slot": s, "panel": slot_to_panel(s)}
    if kit is not None:
        k = _slot(kit, "kit")
        d.transport.select_kit(k)
        out["kit"] = {"slot": k, "panel": k + 1}
    if not out:
        raise ToolError("give a pattern, a kit, or both")
    return out




@tool("device.transport",
      "Start, stop or continue the machine's sequencer. Verified: the TR-8S "
      "acts on MIDI Start and Stop. It does NOT echo them, so the studio "
      "infers that it is playing from the notes it hears rather than from "
      "these messages.",
      {"action": {"type": "string", "enum": ["start", "stop", "continue"]}},
      mutates=True)
def device_transport(action):
    msg = {"start": 0xFA, "continue": 0xFB, "stop": 0xFC}[action]
    _device_helper().transport.send(bytes([msg]))
    return {"sent": action,
            "note": "the machine does not report back that it started; the "
                    "studio works that out from the notes it plays"}


