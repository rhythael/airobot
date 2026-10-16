# Deployment guide (Linux / Docker / macOS)

<p><a href="DEPLOY.en.md"><img alt="English" src="https://img.shields.io/badge/English-DBEDFA"></a> <a href="DEPLOY.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DFE0E5"></a></p>

## 0. Prerequisites

| Item | Notes |
|---|---|
| A host on the same LAN as the vending machine | Linux x86_64 recommended; 4 cores / 8 GB is enough (whisper-small inference ≈ 1 s) |
| A fixed LAN IP | the device stores the server address in its NVS; the host's IP must not change: DHCP reservation on the router, or a static IP |
| Model files, about 1.9 GB | `server/main/xiaozhi-server/models/`: `snakers4_silero-vad`, `sherpa-onnx-whisper-small`, `sherpa-onnx-sense-voice-…`, `tts/` (optional, local first sentence). Copy from the existing machine or download per the upstream docs in `server/docs/` |
| Credentials | an LLM API key (any OpenAI-compatible service) and the Central Kitchen `SF_APP_KEY` |
| Internet access | EdgeTTS and the LLM need the public internet; the bridge needs inventory-api.example.com |

## 1. Configuration

```bash
cp .env.example .env                                   # fill in LLM_API_KEY, SF_APP_KEY
cp launchers/config.example.yaml server/main/xiaozhi-server/data/.config.yaml
# check selected_module (default LLM=CloudLLM, any type: openai entry works), model directories, ports
```

Secrets live only in `.env`; the launchers inject them into memory. `data/.config.yaml` never holds a key.

## 2A. Running directly (Linux / macOS)

```bash
python3.10 -m venv .venv && .venv/bin/pip install -r server/main/xiaozhi-server/requirements.txt pytest pytest-asyncio
python3 -m venv bridge/.venv && bridge/.venv/bin/pip install -e bridge
scripts/start-all.sh      # bridge first, then server; background, PIDs in run/, logs in logs/
scripts/status.sh
scripts/stop-all.sh
```

The server needs Python 3.10 (upstream pins torch 2.2.2); the bridge needs 3.11+. Point `SERVER_PYTHON` / `BRIDGE_PYTHON` at the interpreters if they are not in the default locations.

Autostart on Linux: copy `deploy/systemd/*.service` to `/etc/systemd/system/`, adjust paths and user, then `systemctl enable --now airobot-bridge airobot-server`.

## 2B. Docker

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f server
```

Host networking: the device reaches 8000/8003 through the LAN IP, the server reaches the bridge at 127.0.0.1:8766. The model directory is mounted read-only. The server image is based on upstream `ghcr.io/xinnan-tech/xiaozhi-esp32-server:server-base`. **Image builds have not been verified on the delivery machine** (Docker daemon was not running).

## 3. Letting the device find the server

The device only knows the `wifi:ota_url` in its NVS (currently `http://192.168.0.201:8003/xiaozhi/ota/`). Two options:

1. **Give the server 192.168.0.201** (DHCP reservation / static IP); nothing to change on the device.
2. Change the device: the current NVS images are handed over separately (they contain WiFi credentials and are not in git); `tools/nvs-tool/` parses and verifies them. `launchers/nvs_add_ota_url.py` *appends* an `ota_url` entry — the device already has one, so delete the old entry in the image first, then `esptool --port <serial> write_flash 0x9000 <image>`.

The websocket address the server hands out defaults to the host's current IP; with several network interfaces pin it via `server.websocket` in `data/.config.yaml`.

On the macOS development machine the IP drifts; `tools/ota-alias/` keeps .201 on the interface with a launchd daemon. A company server does not need it.

## 4. Verification

```bash
scripts/test-all.sh                                     # offline regression: server + bridge
cd server/main/xiaozhi-server && ../../../.venv/bin/python -m pytest -q tests_live   # against the running services
scripts/sim.sh "现在有什么吃的" "Was ist in den Teigtaschen drin?" "I'm allergic to peanuts."   # simulator, no real device
scripts/sim.sh audio tests/acceptance/<16k-mono>.wav   # full chain including ASR
```

The acceptance script `tests/acceptance/ASR听力测试稿.txt` has 24 trilingual sentences; latency baselines are in the README.

## 5. Day-to-day operations

| Symptom | Where to look |
|---|---|
| Device screen shows "检查新版本失败 code=113" | the device cannot reach its ota_url: server not running, host IP changed, port 8003 blocked |
| The machine says "inventory temporarily unavailable" | bridge down or Central Kitchen failing: `curl 127.0.0.1:8766/context`, `logs/bridge.log` |
| Slow replies | `grep "TURN " server/main/xiaozhi-server/tmp/server.log`: asr / llm_first / tts_first timings per turn |
| Menu changed | regenerate `resources/smartfoodie/menu_catalog.json` from the menu Markdown with `launchers/import_menu_knowledge.py` |

Logs: `logs/server.log`, `logs/bridge.log` (written by the start script) and `server/main/xiaozhi-server/tmp/server.log` (the server's own size-rotated log).
