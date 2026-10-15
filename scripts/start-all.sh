#!/usr/bin/env bash
# 拉起整条语音链路：先库存桥（:8766），再服务端（:8000 / :8003）。两个进程放到后台，
# PID 写到 run/，日志写到 logs/。凭据来自 .env 或环境变量（见 .env.example）。
set -u
. "$(dirname "$0")/_env.sh"

start_one() {  # name port script
  local name="$1" port="$2" script="$3" pid
  pid="$(pid_of "$name")"
  if pid_alive "$pid"; then echo "$name 已在运行（pid $pid）"; return; fi
  if port_up "$port"; then
    echo "错误：:$port 被别的进程占用（pid $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t | head -1)），先处理它再启动"; return
  fi
  echo "启动 $name …"
  nohup "${SERVER_PY}" "${AIROBOT_ROOT}/launchers/$script" >> "${AIROBOT_ROOT}/logs/$name.log" 2>&1 &
  echo $! > "${AIROBOT_RUN_DIR}/$name.pid"
  for _ in $(seq 1 60); do port_up "$port" && break; sleep 1; done
  port_up "$port" && echo "  $name 已监听 :$port" || echo "  $name 60 秒内没起来，看 logs/$name.log"
}

start_one bridge 8766 start_bridge.py
start_one server 8000 start_server.py
echo
"${AIROBOT_ROOT}/scripts/status.sh"
