"""
Layer 4 — the command surface.

Every capability is exposed as a named tool with a JSON schema, so an LLM (or
an HTTP layer, or a CLI) can drive the TR-8S without knowing anything about
SysEx. Tools take and return plain JSON-serialisable values, and raise
ToolError with an actionable message rather than leaking byte offsets.

    from tr8s.tools import REGISTRY, call, schemas
    schemas()                       -> list of JSON schemas
    call("pattern.get", {"slot": 0})

Layout: `_core` owns the registry and the helpers every tool shares. Each
namespace (`pattern`, `kit`, `track`, ...) is its own module and registers its
tools on import. This file re-exports the public surface and loads the
namespaces -- by name, because `device` and `kit` are both helper names AND
module names, and a plain `from . import device` would rebind one to the other.
"""

from ._core import (DEFAULT_KEYS, DEFAULT_LINE, REGISTRY, ToolError,  # noqa: F401
                    _capture_for_undo, _library_dir, _slot, call, close, device,
                    opt, schemas, set_device, tool)

import importlib as _importlib

for _ns in ("device", "pattern", "kit", "track", "library", "tones", "lines",
            "styles", "calibration", "audio", "history"):
    _importlib.import_module(f"{__name__}.{_ns}")
del _ns, _importlib

# the submodule imports above bound `device` (and `kit`, via tools/kit.py) as
# package attributes; put the public names back on top of them
from ._core import device  # noqa: E402,F401,F811
from ..kit import Kit  # noqa: E402,F401
