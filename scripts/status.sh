#!/usr/bin/env bash
# 查看语音链路状态：服务端 :8000 / :8003，库存桥 :8766，桥的 /context，最近日志。
set -u
. "$(dirname "$0")/_env.sh"

printf '%-14s %-8s %s\n' "组件" "状态" "进程"
for spec in "服务端:8000" "服务端OTA:8003" "库存桥:8766"; do
  name="${spec%%:*}"; port="${spec##*:}"
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
  if [ -n "$pid" ]; then
    printf '%-14s %-8s pid %s  %s\n' "$name" "运行中" "$pid" "$(ps -o command= -p "$pid" | cut -c1-70)"
  else
    printf '%-14s %-8s —\n' "$name" "未运行"
  fi
done
echo
echo "桥 /context 探测（服务端每轮刷新库存用的端点）："
curl -s -m 3 http://127.0.0.1:8766/context | head -c 300 || echo "  不可达"
echo; echo
echo "最近服务端日志（${AIROBOT_SERVER_DIR}/tmp/server.log）："
tail -n 5 "${AIROBOT_SERVER_DIR}/tmp/server.log" 2>/dev/null || echo "  没有日志文件"

# 仅 macOS 开发机：设备 NVS 写死的 192.168.0.201 由 tools/ota-alias 的守护进程保证在本机。
# 公司部署按 docs/DEPLOY.md 给服务器固定 IP，这一段不适用。
if command -v launchctl >/dev/null 2>&1 && [ -x "${AIROBOT_ROOT}/tools/ota-alias/airobot-ota-alias.sh" ]; then
  echo
  echo "设备 NVS 里的 OTA 地址 192.168.0.201（macOS 开发机专用，见 tools/ota-alias/README.md）："
  state="$(DRY_RUN=1 "${AIROBOT_ROOT}/tools/ota-alias/airobot-ota-alias.sh" 2>/dev/null | sed -n 's/^state: //p')"
  case "$state" in
    ok)               echo "  在本机上（主地址 $(ipconfig getifaddr en0 2>/dev/null)）" ;;
    primary-is-alias) echo "  就是本机主地址" ;;
    added)            echo "  不在本机上！守护进程应在 30 秒内补上" ;;
    conflict)         echo "  被别的设备占用！售货机会连不上" ;;
    off-network)      echo "  本机当前不在公司网络" ;;
    *)                echo "  无法判断（$state）" ;;
  esac
  if launchctl print system/com.smartfoodie.airobot-ota-alias >/dev/null 2>&1; then
    echo "  守护进程 com.smartfoodie.airobot-ota-alias：已加载"
  else
    echo "  守护进程 com.smartfoodie.airobot-ota-alias：未加载（sudo tools/ota-alias/install.sh）"
  fi
fi
