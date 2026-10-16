# 部署手册（Linux / Docker / macOS）

<p><a href="DEPLOY.en.md"><img alt="English" src="https://img.shields.io/badge/English-DFE0E5"></a> <a href="DEPLOY.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DBEDFA"></a></p>

## 0. 需要准备

| 项 | 说明 |
|---|---|
| 一台与售货机同一局域网的主机 | Linux x86_64 推荐；4 核 8 GB 够用（whisper-small 推理约 1 秒） |
| 固定的局域网 IP | 设备 NVS 里写死服务端地址，主机 IP 不能变：在路由器做 DHCP 保留，或配静态 IP |
| 模型文件约 1.9 GB | `server/main/xiaozhi-server/models/`：`snakers4_silero-vad`、`sherpa-onnx-whisper-small`、`sherpa-onnx-sense-voice-…`、`tts/`（首句本地合成，可选）。从现有机器拷贝，或按 `server/docs/` 上游文档下载 |
| 凭据 | 大模型 API Key（任一 OpenAI 兼容服务）、中央厨房 `SF_APP_KEY` |
| 出网 | EdgeTTS 与大模型需要访问公网；桥需要访问 inventory-api.example.com |

## 1. 配置

```bash
cp .env.example .env                                   # 填 LLM_API_KEY、SF_APP_KEY
cp launchers/config.example.yaml server/main/xiaozhi-server/data/.config.yaml
# 检查 selected_module（默认 LLM=CloudLLM，可换成任一 type: openai 的条目）、模型目录、端口
```

密钥只在 `.env` 里，启动脚本注入内存；`data/.config.yaml` 里不放密钥。

## 2A. 直接运行（Linux / macOS）

```bash
python3.10 -m venv .venv && .venv/bin/pip install -r server/main/xiaozhi-server/requirements.txt pytest pytest-asyncio
python3 -m venv bridge/.venv && bridge/.venv/bin/pip install -e bridge
scripts/start-all.sh      # 先桥后服务端，后台运行，PID 在 run/，日志在 logs/
scripts/status.sh
scripts/stop-all.sh
```

服务端用 Python 3.10（上游依赖锁定 torch 2.2.2）；桥 3.11+。两者也可以共用一个解释器时由 `SERVER_PYTHON` / `BRIDGE_PYTHON` 指定。

开机自启（Linux）：`deploy/systemd/*.service` 复制到 `/etc/systemd/system/`，改路径与用户，`systemctl enable --now airobot-bridge airobot-server`。

## 2B. Docker

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f server
```

用 host 网络：设备靠局域网 IP 直连 8000/8003，服务端靠 127.0.0.1:8766 找桥。模型目录以只读卷挂进容器。
镜像基于上游 `ghcr.io/xinnan-tech/xiaozhi-esp32-server:server-base`。**镜像构建未在交付机上验证**（基础镜像较大）。

## 3. 让设备找到服务端

设备只认 NVS 里的 `wifi:ota_url`（当前为 `http://192.168.0.201:8003/xiaozhi/ota/`）。两种办法：

1. **服务器就用 192.168.0.201**（DHCP 保留 / 静态 IP），设备不用动。
2. 改设备：当前 NVS 镜像不在仓库里（含 WiFi 凭据，交接时单独提供，放到 `device-backup/`，该目录已 gitignore），`tools/nvs-tool/` 能解析校验；
   `launchers/nvs_add_ota_url.py` 是「追加」一条 ota_url，设备已有该键时会出现重复条目，需先在镜像里删旧条目再追加，
   然后 `esptool --port <串口> write_flash 0x9000 <新镜像>`。

服务端下发给设备的 websocket 地址默认取主机当前 IP；多网卡时在 `data/.config.yaml` 的 `server.websocket` 写死。

开发机（macOS）上 IP 会漂移，`tools/ota-alias/` 的守护进程把 .201 常驻在网卡上；公司服务器不需要它。

## 4. 验证

```bash
scripts/test-all.sh                                     # 离线回归：服务端 + 桥
cd server/main/xiaozhi-server && ../../../.venv/bin/python -m pytest -q tests_live   # 打在运行中的服务上
scripts/sim.sh "现在有什么吃的" "Was ist in den Teigtaschen drin?" "I'm allergic to peanuts."   # 仿真器，不碰真机
scripts/sim.sh audio tests/acceptance/<16k-mono>.wav   # 完整 ASR 链路
```

验收稿 `tests/acceptance/ASR听力测试稿.txt` 共 24 句三语；延迟基线见 README「性能记录」。

## 5. 日常运维

| 现象 | 看哪里 |
|---|---|
| 设备屏幕「检查新版本失败 code=113」 | 设备连不上 ota_url：服务端没起、主机 IP 变了、8003 被防火墙挡 |
| 机器说「暂时查不到库存」 | 桥挂了或中央厨房接口失败：`curl 127.0.0.1:8766/context`、`logs/bridge.log` |
| 回答慢 | `grep "TURN " server/main/xiaozhi-server/tmp/server.log`：asr / llm_first / tts_first 分段计时 |
| 换了菜单 | 用菜单 MD 重新生成 `resources/smartfoodie/menu_catalog.json`：`launchers/import_menu_knowledge.py` |

日志：`logs/server.log`、`logs/bridge.log`（启动脚本）与 `server/main/xiaozhi-server/tmp/server.log`（服务端自己按大小轮转）。
