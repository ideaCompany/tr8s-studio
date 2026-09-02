"""
Layer 4, second backend — the chat agent on Claude Code.

`chat.py` talks to the Claude API directly and needs an API key. This module
runs the same conversation through the Claude Agent SDK, which drives the
`claude` binary the user is already signed into -- so a Claude subscription
(Pro/Max) carries the studio's chat, with no key to manage. The tools are the
same registry as everywhere else, served to the model as an in-process MCP
server, so the machine is driven from inside this process (which is the only
process that can hold the MIDI port).

Note on terms: Anthropic's Agent SDK docs say third-party developers may not
offer claude.ai login for their products without approval. This is a personal
tool on the user's own machine and account; distributing it with subscription
login is not what this code is for.

Events emitted through `emit` (same vocabulary as chat.py, plus a few):

    {"type": "thinking"}                      the model is reasoning
    {"type": "delta",  "text": ...}           streamed prose, append to the line
    {"type": "text",   "text": ...}           the complete prose block (replaces)
    {"type": "tool",   "id":..., "name":..., "input":...}
    {"type": "result", "id":..., "name":..., "ok": bool, "summary": ...}
    {"type": "done",   "stop_reason":..., "cost_usd":..., "duration_ms":...,
                       "turns":..., "session": ...}
    {"type": "error",  "message": ...}
    {"type": "ratelimit", ...}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .chat import MAX_TURNS, SYSTEM, _mcp_name, _summarise
from .tools import REGISTRY, ToolError, call, schemas

REPO = Path(__file__).resolve().parents[2]
SERVER_NAME = "tr8s"
DEFAULT_MODEL = "opus"
MODELS = ("opus", "sonnet")


# --------------------------------------------------------------- availability

def cli_path() -> str | None:
    """The `claude` binary the SDK will drive, if there is one."""
    return os.environ.get("TR8S_CLAUDE_CLI") or shutil.which("claude")


def sdk_available() -> tuple[bool, str]:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False, ("the 'claude-agent-sdk' package is not installed "
                       "(pip install claude-agent-sdk)")
    if cli_path() is None:
        return False, ("Claude Code is not installed: the chat runs through the "
                       "`claude` command. Install it from claude.com/code, then "
                       "sign in.")
    return True, "ready"


_status_cache: tuple[float, dict] = (0.0, {})


def auth_status(max_age: float = 15.0) -> dict:
    """
    Who is signed in to Claude Code, as `claude auth status --json` reports it:
    loggedIn, email, subscriptionType ("max", "pro", ...), authMethod. Cached
    briefly: it is asked on every state refresh.
    """
    global _status_cache
    at, cached = _status_cache
    if cached and time.monotonic() - at < max_age:
        return cached
    exe = cli_path()
    if exe is None:
        out = {"loggedIn": False, "error": "claude is not installed"}
    else:
        try:
            r = subprocess.run([exe, "auth", "status", "--json"],
                               capture_output=True, text=True, timeout=15)
            out = json.loads(r.stdout or "{}")
            if not isinstance(out, dict):
                out = {"loggedIn": False}
        except Exception as e:
            out = {"loggedIn": False, "error": f"{type(e).__name__}: {e}"}
    out["apiKey"] = bool(api_key())
    _status_cache = (time.monotonic(), out)
    return out


def forget_status():
    global _status_cache
    _status_cache = (0.0, {})


# ------------------------------------------------------------- the API key

KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")


def saved_key() -> str | None:
    from . import config
    return config.load_settings().get("anthropic_api_key") or None


def api_key() -> str | None:
    """A pasted key (kept in the studio's settings file) or one from the
    environment. The studio's own file, not the environment, so a key pasted
    in the UI survives a restart without touching the shell."""
    return saved_key() or os.environ.get("ANTHROPIC_API_KEY") or None


def save_key(key: str | None):
    from . import config
    key = (key or "").strip()
    if key and not KEY_RE.match(key):
        raise ValueError("that does not look like an Anthropic API key "
                         "(they start with sk-ant-)")
    config.save_settings({"anthropic_api_key": key or None})
    try:
        os.chmod(config.settings_path(), 0o600)
    except Exception:
        pass
    forget_status()


def auth_mode() -> str:
    """Which credential the chat uses: "claude" (the Claude Code sign-in) or
    "apikey". Chosen by the user; defaults to whatever is available."""
    from . import config
    mode = config.load_settings().get("chat_auth")
    if mode in ("claude", "apikey"):
        return mode
    return "apikey" if (api_key() and not auth_status().get("loggedIn")) else "claude"


def set_auth_mode(mode: str):
    from . import config
    if mode not in ("claude", "apikey"):
        raise ValueError("auth mode must be 'claude' or 'apikey'")
    config.save_settings({"chat_auth": mode})


def test_key(key: str | None = None) -> dict:
    """One tiny request with the key, to prove it works before relying on it."""
    key = (key or api_key() or "").strip()
    if not key:
        return {"ok": False, "error": "no key"}
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "error": "the 'anthropic' package is not installed"}
    t0 = time.monotonic()
    try:
        client = anthropic.Anthropic(api_key=key)
        r = client.messages.create(model="claude-sonnet-5", max_tokens=16,
                                   messages=[{"role": "user",
                                              "content": "Reply with OK."}])
        text = "".join(b.text for b in r.content if b.type == "text")
        return {"ok": True, "model": r.model, "ms": int((time.monotonic() - t0) * 1000),
                "reply": text.strip()}
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "the key was rejected (invalid or revoked)"}
    except anthropic.PermissionDeniedError as e:
        return {"ok": False, "error": f"the key is not allowed to do this: {e.message}"}
    except anthropic.APIStatusError as e:
        return {"ok": False, "error": f"API error {e.status_code}: {e.message}"}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "could not reach the API (network)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def available() -> tuple[bool, str]:
    ok, why = sdk_available()
    if not ok:
        return False, why
    mode = auth_mode()
    if mode == "apikey":
        if api_key():
            return True, "ready"
        return False, "no API key -- paste one, or sign in to Claude"
    if auth_status().get("loggedIn"):
        return True, "ready"
    if api_key():
        return True, "ready"          # falls back to the key
    return False, "not signed in to Claude -- use Sign in"


# ------------------------------------------------------------- sign-in flow

class Login:
    """
    Run `claude auth login` the way a person would at a terminal: it opens the
    browser on the Anthropic sign-in page and waits for the callback. The
    lines it prints (including the URL, for when no browser opens) are handed
    to `on_line`, and `on_done` fires with the new auth status.
    """

    URL = re.compile(r"https?://\S+")

    def __init__(self, on_line, on_done, console: bool = False):
        self.on_line = on_line
        self.on_done = on_done
        self.console = console
        self.proc = None
        self.url: str | None = None
        self.lines: list[str] = []
        self.thread = None

    def start(self):
        exe = cli_path()
        if exe is None:
            raise RuntimeError("claude is not installed")
        args = [exe, "auth", "login"] + (["--console"] if self.console else [])
        # a pty, because the CLI's login flow expects a terminal
        import pty
        pid, fd = pty.fork()
        if pid == 0:                         # child
            os.execvp(args[0], args)
        self.pid, self.fd = pid, fd
        self.thread = threading.Thread(target=self._pump, daemon=True,
                                       name="tr8s-login")
        self.thread.start()

    def _pump(self):
        buf = b""
        try:
            while True:
                try:
                    chunk = os.read(self.fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf or b"\r" in buf:
                    i = min(x for x in (buf.find(b"\n"), buf.find(b"\r")) if x >= 0)
                    line, buf = buf[:i], buf[i + 1:]
                    self._line(line.decode("utf-8", "replace"))
            if buf:
                self._line(buf.decode("utf-8", "replace"))
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass
            try:
                os.waitpid(self.pid, 0)
            except ChildProcessError:
                pass
            forget_status()
            try:
                self.on_done(auth_status(max_age=0))
            except Exception:
                pass

    def _line(self, text: str):
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).strip()
        if not text:
            return
        self.lines.append(text)
        m = self.URL.search(text)
        if m and self.url is None:
            self.url = m.group(0).rstrip(".,)")
        try:
            self.on_line(text, self.url)
        except Exception:
            pass

    def cancel(self):
        try:
            os.kill(self.pid, 15)
        except Exception:
            pass


def logout() -> dict:
    exe = cli_path()
    if exe is None:
        return {"loggedIn": False}
    try:
        subprocess.run([exe, "auth", "logout"], capture_output=True, text=True,
                       timeout=20)
    except Exception:
        pass
    forget_status()
    return auth_status(max_age=0)


# --------------------------------------------------------------- the tools

def tool_result(payload, ok: bool = True) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    out = {"content": [{"type": "text", "text": text}]}
    if not ok:
        out["is_error"] = True
    return out


# The studio registers what to do when the assistant moves the machine to
# another pattern: the machine sends no Program Change for a SysEx select,
# so the studio would otherwise stay on the old one (and diff the wrong slot).
on_machine_moved = None


def run_tool(real: str, args: dict) -> dict:
    """Execute one registry tool for the model, logging what it changed."""
    try:
        out = call(real, args or {})
    except ToolError as e:
        return tool_result(str(e), ok=False)
    except Exception as e:
        return tool_result(f"{type(e).__name__}: {e}", ok=False)
    if real == "device.select" and on_machine_moved:
        try:
            slot = ((out or {}).get("pattern") or {}).get("slot")
            if slot is not None:
                on_machine_moved(int(slot))
        except Exception:
            pass
    try:
        spec = REGISTRY.get(real)
        if spec and spec.get("mutates_device"):
            from .changelog import CHANGELOG
            CHANGELOG.add("ai", real.split(".")[-1].replace("_", " "),
                          instrument=args.get("instrument") or args.get("assign_to"),
                          detail=str(args.get("tone") or args.get("description")
                                     or args.get("note") or ""))
    except Exception:
        pass
    return tool_result(out)


def build_server(extra=()):
    """Every registry tool, as an in-process MCP server the SDK can mount."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    def make(spec):
        real = spec["name"]

        async def handler(args):
            return await asyncio.to_thread(run_tool, real, args or {})

        return tool(_mcp_name(real), spec["description"],
                    spec["input_schema"])(handler)

    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0",
                                 tools=[make(s) for s in schemas()] + list(extra))


# ---------------------------------------------------------------- the agent

class Agent:
    """
    One conversation with Claude, on the user's own Claude Code sign-in.

    The SDK is async; the studio is threads. The agent owns an event loop on
    a thread of its own and everything here is a blocking wrapper over it.
    """

    def __init__(self, model: str = DEFAULT_MODEL, context=None,
                 resume: str | None = None):
        self.model = model
        self.context = context        # callable -> str: what the studio sees
        self.client = None
        self.session_id: str | None = None
        self._resume = resume         # a previous session to pick up
        self.busy = False
        self.last: dict = {}
        self.turns = 0
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        daemon=True, name="tr8s-agent")
        self._thread.start()
        self._server = None

    # ------------------------------------------------------------ plumbing

    def _run(self, coro, timeout: float | None = None):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions
        if self._server is None:
            self._server = build_server(extra=[self._context_tool()])
        # The credential: the sign-in the `claude` binary already has, or the
        # pasted key handed to that subprocess alone -- never exported into
        # the studio's own environment.
        env = {}
        key = api_key()
        if key and (auth_mode() == "apikey" or not auth_status().get("loggedIn")):
            env["ANTHROPIC_API_KEY"] = key
        self.credential = "apikey" if env else "claude"
        return ClaudeAgentOptions(
            env=env,
            thinking={"type": "adaptive", "display": "summarized"},
            tools=[],                                  # none of Claude Code's own
            mcp_servers={SERVER_NAME: self._server},
            allowed_tools=[f"mcp__{SERVER_NAME}__*"],
            permission_mode="dontAsk",                 # never hang on a prompt
            system_prompt=SYSTEM,
            model=self.model,
            max_turns=MAX_TURNS,
            cwd=str(REPO),
            setting_sources=[],                        # not the user's Claude Code config
            include_partial_messages=True,             # stream prose as it comes
            cli_path=cli_path(),
            resume=self._resume,
        )

    def _context_tool(self):
        from claude_agent_sdk import tool

        async def handler(args):
            text = self.context() if self.context else "(no studio context)"
            return {"content": [{"type": "text", "text": text}]}

        return tool("studio_context",
                    "What the studio shows right now: the pattern on screen "
                    "(the one the machine is on), tempo, kit, whether the "
                    "machine is playing, the variation heard, and the recent "
                    "changes. Call it after your own writes to see the result.",
                    {})(handler)

    async def _connect(self):
        from claude_agent_sdk import ClaudeSDKClient
        self.client = ClaudeSDKClient(options=self._options())
        await self.client.connect()

    async def _disconnect(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    # ------------------------------------------------------------- surface

    def reset(self):
        """A fresh conversation."""
        self._run(self._disconnect(), timeout=30)
        self.session_id = None
        self._resume = None
        self.turns = 0
        self.last = {}

    def set_model(self, model: str):
        if model not in MODELS:
            raise ToolError(f"model must be one of {', '.join(MODELS)}")
        self.model = model
        if self.client is not None:
            try:
                self._run(self.client.set_model(model), timeout=30)
            except Exception:
                self.reset()

    def interrupt(self):
        if self.client is not None and self.busy:
            try:
                self._run(self.client.interrupt(), timeout=30)
            except Exception:
                pass

    def send(self, user_message: str, emit=None) -> str:
        """One user turn to completion. Returns the assistant's prose."""
        if self.busy:
            raise ToolError("still working on the previous message -- stop it "
                            "first, or wait")
        self.busy = True
        try:
            return self._run(self._send(user_message, emit))
        finally:
            self.busy = False

    async def _send(self, text: str, emit) -> str:
        from claude_agent_sdk import (AssistantMessage, RateLimitEvent,
                                      ResultMessage, StreamEvent, TextBlock,
                                      ThinkingBlock, ToolResultBlock,
                                      ToolUseBlock, UserMessage)

        def fire(ev):
            if emit:
                try:
                    emit(ev)
                except Exception:
                    pass

        if self.client is None:
            try:
                await self._connect()
            except Exception as e:
                msg = f"could not start Claude: {type(e).__name__}: {e}"
                fire({"type": "error", "message": msg})
                return msg

        fire({"type": "thinking"})
        names: dict[str, str] = {}
        final: list[str] = []
        prompt = text
        if self.context:
            try:
                ctx = self.context()
                if ctx:
                    prompt = f"[studio]\n{ctx}\n[/studio]\n\n{text}"
            except Exception:
                pass
        try:
            await self.client.query(prompt)
            async for m in self.client.receive_response():
                if isinstance(m, StreamEvent):
                    ev = m.event or {}
                    kind = ev.get("type")
                    if kind == "content_block_start":
                        if (ev.get("content_block") or {}).get("type") == "thinking":
                            fire({"type": "thinking"})
                    elif kind == "content_block_delta":
                        d = ev.get("delta") or {}
                        if d.get("type") == "text_delta" and d.get("text"):
                            fire({"type": "delta", "text": d["text"]})
                        elif d.get("type") == "thinking_delta" and d.get("thinking"):
                            fire({"type": "thought_delta", "text": d["thinking"]})
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, TextBlock) and b.text.strip():
                            final.append(b.text)
                            fire({"type": "text", "text": b.text})
                        elif isinstance(b, ToolUseBlock):
                            short = b.name.replace(f"mcp__{SERVER_NAME}__", "")
                            names[b.id] = short
                            fire({"type": "tool", "id": b.id, "name": short,
                                  "input": b.input})
                        elif isinstance(b, ThinkingBlock):
                            if (b.thinking or "").strip():
                                fire({"type": "thought", "text": b.thinking})
                            else:
                                fire({"type": "thinking"})
                elif isinstance(m, UserMessage):
                    content = m.content if isinstance(m.content, list) else []
                    for b in content:
                        if isinstance(b, ToolResultBlock):
                            ok = not b.is_error
                            summary = _flatten(b.content)
                            fire({"type": "result", "id": b.tool_use_id,
                                  "name": names.get(b.tool_use_id, "?"),
                                  "ok": ok,
                                  "summary": _summarise_text(summary)})
                elif isinstance(m, RateLimitEvent):
                    info = m.rate_limit_info
                    fire({"type": "ratelimit",
                          "info": info if isinstance(info, dict) else str(info)})
                elif isinstance(m, ResultMessage):
                    self.session_id = m.session_id
                    self._resume = m.session_id
                    self.turns += 1
                    self.last = {
                        "stop_reason": m.subtype,
                        "cost_usd": m.total_cost_usd,
                        "duration_ms": m.duration_ms,
                        "turns": m.num_turns,
                        "session": m.session_id,
                        "error": m.is_error,
                    }
                    if m.is_error and not final:
                        why = m.result or (", ".join(m.errors) if m.errors
                                           else m.subtype)
                        fire({"type": "error", "message": str(why)})
                    fire({"type": "done", **self.last})
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            fire({"type": "error", "message": msg})
            # a broken transport is not worth keeping; nor a session that
            # cannot be resumed
            await self._disconnect()
            self._resume = None
            return msg
        return "\n".join(final).strip()

    def status(self) -> dict:
        return {"backend": "claude-code", "model": self.model,
                "credential": getattr(self, "credential", None),
                "busy": self.busy, "session": self.session_id,
                "turns": self.turns, "last": self.last}


def _flatten(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for c in content:
        if isinstance(c, dict):
            if c.get("type") == "text":
                parts.append(str(c.get("text", "")))
        else:
            parts.append(str(c))
    return "\n".join(parts)


def _summarise_text(text: str) -> str:
    try:
        return _summarise(json.loads(text))
    except Exception:
        return text if len(text) <= 300 else text[:297] + "..."
