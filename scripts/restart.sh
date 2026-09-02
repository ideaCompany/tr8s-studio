#!/usr/bin/env bash
# Restart the TR-8S studio safely.
#
# Two hard-won rules are baked in:
#   1. Never `pkill -f tr8s.server` -- the pattern matches this very shell and
#      kills your terminal. Kill the old studio by the PID we wrote down.
#   2. Wait until the MIDI port is really free before starting the new one.
#      Starting while the old process still holds it splits the SysEx stream
#      and the machine's replies come back garbled ("pppp777", "p7dp").
#
# Usage:  scripts/restart.sh [--slot 8-16] [--port 8733] [--offline]
#         With no --slot the studio resumes on the slot the machine was last on.
# Env:    TR8S_PORT=/dev/snd/midiCxDy  to force the MIDI node.
set -u
cd "$(dirname "$0")/.."
RUN=.run; mkdir -p "$RUN"
PID=$RUN/studio.pid; LOG=$RUN/studio.log
PORT_NODE=${TR8S_PORT:-$(ls /dev/snd/midiC*D* 2>/dev/null | head -1)}

[ -f "$PID" ] && kill "$(cat "$PID")" 2>/dev/null
if [ -n "${PORT_NODE:-}" ]; then
  for _ in $(seq 1 40); do
    fuser "$PORT_NODE" >/dev/null 2>&1 || break
    sleep 0.25
  done
  if fuser "$PORT_NODE" >/dev/null 2>&1; then
    echo "MIDI port still held by:"; fuser -v "$PORT_NODE"; exit 1
  fi
fi

PYTHON=${PYTHON:-$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)}
PYTHONPATH=src nohup "$PYTHON" -m tr8s.server "$@" > "$LOG" 2>&1 &
echo $! > "$PID"
for _ in $(seq 1 60); do
  grep -q "tr8s studio ->" "$LOG" 2>/dev/null && break
  sleep 0.25
done
grep -E "device:|tr8s studio ->" "$LOG" | head -3
