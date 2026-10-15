#!/usr/bin/env bash
# 不碰真机，用仿真器打本地服务端。
#   scripts/sim.sh "41号机器现在有什么吃的？"
#   scripts/sim.sh "有什么吃的？" "那个牛肉炒面还有吗？"     # 同一连接多轮
#   scripts/sim.sh audio path/to/16k-mono.wav               # 走完整 ASR 链路
#   XIAOZHI_WS_URL=ws://127.0.0.1:8010/xiaozhi/v1/ scripts/sim.sh "…"   # 打另一个实例
set -u
. "$(dirname "$0")/_env.sh"
cd "${AIROBOT_ROOT}/launchers"
if [ "${1:-}" = "audio" ]; then
  exec "${SERVER_PY}" device_sim.py audio "${@:2}"
else
  SMARTFOODIE_SIM_READY_WAIT_SECONDS="${SMARTFOODIE_SIM_READY_WAIT_SECONDS:-6}" exec "${SERVER_PY}" device_sim.py text "$@"
fi
