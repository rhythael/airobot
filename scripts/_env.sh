#!/usr/bin/env bash
# 所有 scripts/*.sh 共用：定位仓库、解释器、PID 目录。bash 3.2+（macOS 自带）和 Linux 都能跑。
# 解释器查找顺序：环境变量 → <repo>/.venv → 旧开发机的 ~/.venvs/… → PATH 里的 python3。
AIROBOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIROBOT_SERVER_DIR="${AIROBOT_ROOT}/server/main/xiaozhi-server"
AIROBOT_RUN_DIR="${AIROBOT_ROOT}/run"
mkdir -p "${AIROBOT_RUN_DIR}" "${AIROBOT_ROOT}/logs"
[ -f "${AIROBOT_ROOT}/.env" ] && { set -a; . "${AIROBOT_ROOT}/.env"; set +a; }

pick_python() {
  for candidate in "$@"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && { echo "$candidate"; return; }
  done
  command -v python3 || command -v python
}
SERVER_PY="$(pick_python "${SERVER_PYTHON:-}" "${AIROBOT_ROOT}/.venv/bin/python" "$HOME/.venvs/xiaozhi-server/bin/python")"
BRIDGE_PY="$(pick_python "${BRIDGE_PYTHON:-}" "${AIROBOT_ROOT}/bridge/.venv/bin/python" "$HOME/.venvs/tuya-enterprise-bridge/bin/python" "${SERVER_PY}")"
export SERVER_PYTHON="${SERVER_PY}" BRIDGE_PYTHON="${BRIDGE_PY}"

port_up() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }
pid_alive() { [ -n "$1" ] && kill -0 "$1" 2>/dev/null; }
pid_of() { cat "${AIROBOT_RUN_DIR}/$1.pid" 2>/dev/null; }
