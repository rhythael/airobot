#!/usr/bin/env bash
# 停掉服务端和库存桥：按 run/ 里的 PID 停；没有 PID 文件（比如手工启动的）再按命令行找。
# 先 TERM，5 秒后仍活着则 KILL。
set -u
. "$(dirname "$0")/_env.sh"

stop_one() {  # name pattern
  local name="$1" pattern="$2" pids
  pids="$(pid_of "$name")"
  pid_alive "$pids" || pids="$(pgrep -f "$pattern" 2>/dev/null | tr '\n' ' ')"
  if [ -z "${pids// }" ]; then echo "$name 未运行"; rm -f "${AIROBOT_RUN_DIR}/$name.pid"; return; fi
  echo "停止 $name pid $pids"
  kill $pids 2>/dev/null
  for _ in $(seq 1 10); do
    local alive=""
    for p in $pids; do kill -0 "$p" 2>/dev/null && alive="$alive $p"; done
    [ -z "${alive// }" ] && { echo "  已停止"; rm -f "${AIROBOT_RUN_DIR}/$name.pid"; return; }
    sleep 0.5
  done
  echo "  仍在运行，强制结束$alive"; kill -9 $alive 2>/dev/null; rm -f "${AIROBOT_RUN_DIR}/$name.pid"
}
stop_one server "launchers/start_serv[e]r.py"
stop_one bridge "launchers/serve_inventory_bridg[e].py"
for port in 8000 8003 8766; do
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
  [ -n "$pid" ] && echo "注意：:$port 仍被 pid $pid 占用（$(ps -o command= -p "$pid" | cut -c1-60)）"
done
exit 0
