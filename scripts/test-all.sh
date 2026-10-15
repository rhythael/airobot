#!/usr/bin/env bash
# 回归门：服务端 pytest + 库存桥 pytest（语音链路用到的三组）。
# 改 TTS 文本处理时两组都必须跑（HANDOFF §6）。测试日志写 tmp/pytest.log，不进线上 server.log。
set -u
. "$(dirname "$0")/_env.sh"
rc=0
echo "== 服务端（${AIROBOT_SERVER_DIR}）"
( cd "${AIROBOT_SERVER_DIR}" && "${SERVER_PY}" -m pytest -q ) || rc=1
echo
echo "== 库存桥（${AIROBOT_ROOT}/bridge）"
( cd "${AIROBOT_ROOT}/bridge" && "${BRIDGE_PY}" -m pytest -q \
    tests/test_machine_context_route.py tests/test_machine_mcp_server.py tests/test_inventory.py ) || rc=1
echo
[ $rc -eq 0 ] && echo "全部通过" || echo "有失败，见上方输出"
exit $rc
