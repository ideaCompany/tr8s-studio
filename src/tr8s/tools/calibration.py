"""calibration tools — see the package docstring for the conventions."""

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

@tool("calibration.describe",
      "The measured relationships between kit bytes and what is actually "
      "heard, with the tone each was measured on and the caveats. Read this "
      "before assuming a byte means milliseconds.",
      {})
def calibration_describe():
    from ..calibration import describe_decay, describe_tune
    return {"decay": describe_decay(), "tune": describe_tune()}


