"""
MCP server — exposes the TR-8S over the Model Context Protocol on stdio.

Any MCP client (Claude Desktop, Claude Code, a custom harness) can then drive
the drum machine directly. Nothing is hardcoded here: the tool list is
generated from `tools.REGISTRY`, so anything added there appears automatically.

    tr8s-mcp                    # speaks JSON-RPC 2.0 on stdin/stdout

Claude Desktop config:

    {"mcpServers": {"tr8s": {"command": "tr8s-mcp"}}}

MCP tool names must match ^[a-zA-Z0-9_-]{1,64}$, so the registry's dotted names
are exposed with underscores (`pattern.set_steps` -> `pattern_set_steps`) and
mapped back on call.

Diagnostics go to stderr only. Anything written to stdout that is not a
JSON-RPC message corrupts the stream.
"""

from __future__ import annotations

import json
import sys
import traceback

from . import config
from .tools import REGISTRY, ToolError, call, close, schemas

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "tr8s", "version": "0.1.0"}


def _mcp_name(name: str) -> str:
    return name.replace(".", "_")


def _registry_name(mcp_name: str) -> str | None:
    for real in REGISTRY:
        if _mcp_name(real) == mcp_name:
            return real
    return None


def log(msg: str):
    print(f"[tr8s-mcp] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ resources

RESOURCES = [
    {
        "uri": "tr8s://device/state",
        "name": "Device state",
        "description": "Firmware, connection, and the currently selected "
                       "pattern and kit if they can be read.",
        "mimeType": "application/json",
    },
    {
        "uri": "tr8s://tones/catalog",
        "name": "Tone catalogue",
        "description": "Every melodic tone measured for its real root pitch, "
                       "loudness, decay and brightness.",
        "mimeType": "application/json",
    },
    {
        "uri": "tr8s://docs/constraints",
        "name": "Hardware constraints",
        "description": "Things software cannot change about the TR-8S. Read "
                       "this before promising a user something.",
        "mimeType": "text/markdown",
    },
]

CONSTRAINTS = """\
# TR-8S constraints that software cannot work around

1. **MOTION [ON] must be lit** for any melody (per-step tune motion) to be
   audible. It is a front-panel state; nothing over USB can set it. If a user
   writes a melody and hears nothing, this is the first thing to check.

2. **Coarse Tune exists only on SAMPLE tones.** ACB modelled tones -- the
   808/909/707 drums -- have no semitone control at all. Filter with
   `tones_search {"melodic": true}`; a tone's `type` is 2 for sample, 1 for ACB.
   Melodies on an ACB tone can only use fine Tune, which spans under an octave.

3. **Level is owned by the physical faders.** It can be read but never written.
   Do not offer to balance a kit's levels.

4. **Per-pattern tempo, shuffle and kit are ignored** unless the matching
   `[UTILITY] GENERAL` source is set to `PTN` rather than `SYSTEM`.

5. **`commit: false` is not a scratch edit.** Any transfer changes the slot
   immediately and it reads back changed. A pattern is re-read by the sequencer
   at once, so you hear it; a kit is not, so the loaded kit keeps playing until
   committed. Commit is presumed to be what survives power-off. If a user wants
   a pattern left alone, do not write to it at all -- there is no undo.

6. **A sample tone needs its sample parameters.** Assigning a sample tone id to
   an instrument whose record holds ACB defaults produces a near-silent sound.
   Pass `inherit_from` / `sample_donor` pointing at a working sample instrument.

7. **Coarse Tune is relative to the sample's own pitch.** Always take `root`
   from `tones_search`; guessing it transposes the whole melody.
"""


def read_resource(uri: str) -> dict:
    if uri == "tr8s://tones/catalog":
        p = config.tone_catalog_path()
        text = p.read_text() if p.exists() else "{}"
        return {"uri": uri, "mimeType": "application/json", "text": text}
    if uri == "tr8s://docs/constraints":
        return {"uri": uri, "mimeType": "text/markdown", "text": CONSTRAINTS}
    if uri == "tr8s://device/state":
        try:
            state = call("device.info")
        except Exception as e:  # device may simply be unplugged
            state = {"connected": False, "error": str(e)}
        return {"uri": uri, "mimeType": "application/json",
                "text": json.dumps(state, indent=2, default=str)}
    raise ToolError(f"unknown resource {uri!r}")


# -------------------------------------------------------------------- server

class Server:
    def __init__(self):
        self.initialized = False

    def handle(self, req: dict) -> dict | None:
        method = req.get("method")
        rid = req.get("id")
        params = req.get("params") or {}

        # notifications carry no id and expect no reply
        if rid is None and method and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                want = params.get("protocolVersion")
                version = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                self.initialized = True
                return self.ok(rid, {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": SERVER_INFO,
                    "instructions": (
                        "Controls a Roland TR-8S drum machine over USB. Read "
                        "tr8s://docs/constraints before promising anything: "
                        "several limits (MOTION [ON], sample-only Coarse Tune, "
                        "fader-owned level) cannot be worked around in software."
                    ),
                })

            if method == "ping":
                return self.ok(rid, {})

            if method == "tools/list":
                return self.ok(rid, {"tools": [
                    {
                        "name": _mcp_name(t["name"]),
                        "description": t["description"],
                        "inputSchema": t["input_schema"],
                        "annotations": {
                            "readOnlyHint": not t["mutates_device"],
                            "destructiveHint": t["mutates_device"],
                        },
                    }
                    for t in schemas()
                ]})

            if method == "tools/call":
                name = params.get("name", "")
                real = _registry_name(name)
                if real is None:
                    return self.tool_error(
                        rid, f"unknown tool {name!r}; call tools/list for the set")
                args = params.get("arguments") or {}
                try:
                    result = call(real, args)
                except ToolError as e:
                    return self.tool_error(rid, str(e))
                except Exception as e:
                    log(traceback.format_exc())
                    return self.tool_error(rid, f"{type(e).__name__}: {e}")
                text = json.dumps(result, indent=2, default=str)
                return self.ok(rid, {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                })

            if method == "resources/list":
                return self.ok(rid, {"resources": RESOURCES})

            if method == "resources/read":
                uri = params.get("uri", "")
                return self.ok(rid, {"contents": [read_resource(uri)]})

            return self.err(rid, -32601, f"method not found: {method}")

        except ToolError as e:
            return self.err(rid, -32602, str(e))
        except Exception as e:
            log(traceback.format_exc())
            return self.err(rid, -32603, f"internal error: {e}")

    @staticmethod
    def ok(rid, result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def err(rid, code, message):
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": code, "message": message}}

    @staticmethod
    def tool_error(rid, message):
        """Tool failures are results, not protocol errors -- the model sees them."""
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }}


def main(argv=None):
    server = Server()
    log(f"ready: {len(REGISTRY)} tools, data in {config.data_dir()}")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                print(json.dumps(Server.err(None, -32700, f"parse error: {e}")),
                      flush=True)
                continue
            for one in (req if isinstance(req, list) else [req]):
                resp = server.handle(one)
                if resp is not None:
                    print(json.dumps(resp, default=str), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        close()
        log("shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
