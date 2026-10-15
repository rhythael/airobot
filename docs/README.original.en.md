<h1 align="center">airobot</h1>
<p align="center"><b>Voice assistant for SmartFoodie vending machine 041</b><br/>
Chinese · German · English speech in, live-inventory answers out — self-hosted, independent of any vendor cloud</p>

<p align="center">
  <a href="docs/ARCHITECTURE.en.md">Architecture</a> ·
  <a href="docs/DEPLOY.en.md">Deployment</a> ·
  <a href="CONTRIBUTIONS.en.md">Authorship</a> ·
  <a href="docs/debug-2026-10-05.md">Debug record</a> ·
  <a href="https://github.com/SmartFoodieEu/voice_robot/releases/tag/v1.0-handoff">v1.0-handoff</a>
</p>

<p align="center">
  <a href="README.md"><img alt="README in English" src="https://img.shields.io/badge/English-DBEDFA"></a>
  <a href="README.zh.md"><img alt="简体中文自述文件" src="https://img.shields.io/badge/简体中文-DFE0E5"></a>
  <img alt="release" src="https://img.shields.io/badge/release-v1.0--handoff-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="platform" src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Docker-lightgrey">
  <img alt="tests" src="https://img.shields.io/badge/tests-334%20server%20%7C%2029%20bridge-brightgreen">
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-proprietary%20%2B%20MIT%20upstream-white?labelColor=black"></a>
</p>

## Contents

- [How it works](#how-it-works)
- [Layout](#layout)
- [Quick start](#quick-start)
- [Runtime requirements](#runtime-requirements)
- [Acceptance material](#acceptance-material)
- [Performance record](#performance-record)
- [Where the SmartFoodie customisations live](#where-the-smartfoodie-customisations-live)
- [Known issues and open decisions](#known-issues-and-open-decisions)
- [Merge record](#merge-record)
- [License](#license)

## How it works

A customer stands in front of vending machine 041 and asks a question in Chinese, German or English. The ESP32 device streams the audio to a self-hosted server, which answers using the live inventory and speaks the reply. Fully independent of the Tuya platform and the Xiaozhi public cloud.

```
ESP32 (aa:bb:cc:dd:ee:ff, firmware 2.2.2)
   │ websocket
   ▼
Server  xiaozhi-esp32-server  :8000 (OTA :8003)
   ├─ ASR  sherpa-onnx: SenseVoice first, Whisper only when unsure
   ├─ LLM  any OpenAI-compatible endpoint (default: Volcengine Doubao; ClaudeCLI is dev-machine only)
   ├─ TTS  EdgeTTS (plus an offline sherpa-onnx + Piper provider)
   ├─ http  GET /context  ──► inventory bridge :8766   refreshed every turn, injected into the prompt; most questions answered locally
   └─ mcp   /mcp          ──► inventory bridge :8766   tool calls (rarely used once the snapshot is injected)
                                   │
                                   ▼
                        Central Kitchen API  inventory-api.example.com/prod-api
```

## Layout

| Directory | Contents | Notes |
|---|---|---|
| `server/` | Xiaozhi server with the SmartFoodie customisations (menu knowledge, prompt, TTS sentence splitting, per-turn inventory refresh, local answers, regression tests) | merged via git subtree, 33 commits of history on top of upstream; 2.1 GB of which `models/` (1.9 GB) is not in git |
| `bridge/` | Inventory bridge for machine 041, `tuya-enterprise-bridge` (`/context`, `/mcp`, Central Kitchen client) | merged via git subtree, 45 commits |
| `launchers/` | `start_server.py`, `start_bridge.py` (credentials from `.env` / environment), `config.example.yaml`, `serve_inventory_bridge.py`, `device_sim.py` (device simulator), `import_menu_knowledge.py`, `nvs_add_ota_url.py`, `HANDOFF.md` | merged via git subtree |
| `deploy/` | two Dockerfiles, docker-compose, systemd units | for company deployment |
| `firmware/` | ESP32 firmware source (`main/`: application, mcp_server, ota, audio, boards …) | upstream, unmodified |
| `tools/nvs-tool/` | NVS partition parse / verify / log tools | |
| `tools/ota-alias/` | keeps 192.168.0.201 (the address stored in the device) on the dev Mac: launchd daemon + install script | macOS dev machine only |
| `device-backup/` | device NVS images (**contain WiFi credentials, not in git**, gitignored) | handed over separately; on the dev machine in `~/airobot-device-backup/` |
| `docs/` | `041语音助手链路.pdf` (6-page overview), handoff notes, baseline notes, bridge runbook, architecture and deployment guides | |
| `tests/acceptance/` | `ASR听力测试稿.txt` (24 trilingual listening-test sentences), `tts-对比样本/` (4 pairs of old/new TTS samples) | |
| `scripts/` | start / stop / status / regression / simulator (bash, Linux and macOS) | |
| `logs/` | `server.log` / `bridge.log` written by `start-all.sh` | generated at runtime |

**This directory is the single git repository** (merged with `git subtree` on 2026-10-02; the full history of all three sources is present, e.g. `git log -- server`). Remote: https://github.com/SmartFoodieEu/voice_robot, tag `v1.0-handoff`.

Handoff documents: `docs/ARCHITECTURE.en.md` (modules and interfaces), `docs/DEPLOY.en.md` (deployment and operations), `CONTRIBUTIONS.en.md` (provenance and authorship), `docs/debug-2026-10-05.md` (sandbox debugging record, Chinese with an English summary).

## Quick start

```bash
cp .env.example .env                                   # first time: fill in LLM_API_KEY, SF_APP_KEY
cp launchers/config.example.yaml server/main/xiaozhi-server/data/.config.yaml   # first time
scripts/start-all.sh     # bridge first, then server; both in the background, PIDs in run/, logs in logs/
scripts/status.sh        # are both services up, is the bridge /context reachable, recent log lines
scripts/stop-all.sh
scripts/test-all.sh      # regression gate: server pytest + bridge pytest
scripts/sim.sh "41号机器现在有什么吃的？"              # simulator, skips ASR: tests local answers / LLM + TTS
scripts/sim.sh "What can I buy?" "Is the beef noodle still there?"   # multi-turn on one connection
scripts/sim.sh audio tests/acceptance/xxx.wav           # full chain including ASR
```

Neither service starts on boot by itself; use `deploy/systemd/` on Linux or `deploy/docker-compose.yml` for containers, see `docs/DEPLOY.en.md`.

## Runtime requirements

- Server: Python 3.10 (upstream pins torch 2.2.2), dependencies in `server/main/xiaozhi-server/requirements.txt`; interpreter chosen via `SERVER_PYTHON`, defaults to `<repo>/.venv`
- Bridge: Python 3.11+, `pip install -e bridge` (only fastmcp + httpx; Tuya side and macOS keychain are optional extras `[tuya]` `[macos]`); defaults to `<repo>/bridge/.venv`
- Flashing / NVS read-write: esptool
- Server config `server/main/xiaozhi-server/data/.config.yaml` (gitignored); example in `launchers/config.example.yaml`; secrets only in `.env`

## Acceptance material

- `tests/acceptance/ASR听力测试稿.txt`: 8 sentences each in Chinese, German and English covering dishes, prices, allergens, slot numbers and language switching. Say each sentence once and wait for the reply before the next.
- `tests/acceptance/tts-对比样本/`: 4 pairs of mixed-language sentences, "old" (mp3) vs "new" (wav).
- Latency baseline (HANDOFF §2): first audio in Chinese 3.6–4.3 s, German 4.5 s, English 4.3 s; 9.3 s when the bridge is down. Measure at least three times, shuffle the order, discard the first round after a restart.

## Performance record

| Date | Path | First audio (simulator, ASR skipped) | Notes |
|---|---|---|---|
| 2026-10-02 before | everything through the LLM | 1.9–4.1 s (median 2.7) | `docs/perf/baseline-2026-10-02-before.log` |
| 2026-10-02 after | template answers (what's available / expired / empty slots / slot X) | **0.4–1.1 s** | LLM skipped; first sentence synthesised locally |
| 2026-10-02 after | other questions through the LLM | 1.4–2.5 s | local first sentence + streaming EdgeTTS; `docs/perf/after-2026-10-02.log` |
| 2026-10-05 | allergen / diet / spiciness / greeting / menu overview answered locally | 0.4–1.1 s | see `docs/debug-2026-10-05.md` |

All optimisations can be switched off individually, see `server/main/xiaozhi-server/CONFIG_NOTES.md`: EdgeTTS streaming decode `edge_stream_decode`, local first sentence `first_sentence_local` (zh Matcha / de·en Piper high), template answers `local_template_answers`, local allergen / diet / spiciness answers, LLM warm-up at startup, VAD trailing silence 900→600 ms, per-turn `TURN …` timing lines (`grep "TURN " tmp/server.log`).

## Where the SmartFoodie customisations live

- Every custom Python file carries a first-line marker (`SmartFoodie 041 语音助手 · 定制模块 … | SmartFoodie 041 voice assistant · custom module …`); modified upstream files carry a different marker. `CONTRIBUTIONS.en.md` lists them.
- `core/utils/`: menu knowledge, per-turn inventory refresh, local answer modules, turn shaping, slot-number normalisation, ASR routing
- `core/providers/`: local first-sentence TTS, offline TTS, ClaudeCLI provider (dev only)
- `agent-smartfoodie-prompt.txt`, `resources/smartfoodie/menu_catalog.json`, `tests_smartfoodie/`, `tests_live/`

## Known issues and open decisions

1. When the bridge is down the model may call `get_lunar` and read an internal error to the customer; upstream hard-codes it as a required function, disabling it means forking upstream — **decision pending**.
2. ~~Inventory snapshot fetched only at handshake~~ now refreshed at the start of every turn (`turn_context.py`).
3. The degraded path still takes 9.28 s (10 s wait in `mcp_manager.py`); do not simply shorten it.
4. The Central Kitchen API has no list prices; the catalogue price from the menu import is spoken with "the price on the machine applies". Where the price master data lives is **unanswered**.
5. The Volcengine API key was once visible in a screenshot — **rotate it**.
6. ~~14 uncommitted bridge files~~ committed on 2026-10-09.
7. ~~No remote~~ pushed to GitHub on 2026-10-15.
8. ~~No autostart~~ `deploy/systemd/` and `deploy/docker-compose.yml` provided; on the macOS dev machine it is still a manual `scripts/start-all.sh`.
9. ~~Device could not reach the server after the Mac changed IP~~ fixed 2026-10-09 on the dev machine with `tools/ota-alias`; on a company server give the host a fixed IP (see `docs/DEPLOY.en.md` §3).
10. The machine number 041 is hard-coded in about 20 places (bridge, server, prompt, example config). Serving a second machine requires consolidating it into one setting.

## Merge record

2026-10-02: `~/airobot` initialised as a git repository; `bridge/` (45 commits), `launchers/` (2) and `server/` (33, shallow boundary e4a7c18 = upstream merge point) added with `git subtree add`. 2026-10-15: the shallow server history was completed from upstream (`git fetch --unshallow`), the device NVS images were removed from all history (they contain WiFi credentials), and the repository was pushed to GitHub.

## License

The SmartFoodie-specific code (bridge, launchers, scripts, deploy, docs, tools and every file marked in its first line) was written by Heyao Rong for SmartFoodie GmbH and is company-internal. The voice server builds on [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) (MIT) and the device runs [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) firmware (MIT). See [LICENSE](LICENSE) and [CONTRIBUTIONS.en.md](CONTRIBUTIONS.en.md).

