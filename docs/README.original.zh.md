<h1 align="center">airobot</h1>
<p align="center"><b>SmartFoodie 041 号售货机语音助手</b><br/>
顾客用中文、德语或英语开口，机器结合实时库存回答——自建服务端，不依赖任何厂商云</p>

<p align="center">
  <a href="docs/ARCHITECTURE.md">架构</a> ·
  <a href="docs/DEPLOY.md">部署</a> ·
  <a href="CONTRIBUTIONS.md">代码来源</a> ·
  <a href="docs/debug-2026-10-05.md">调试记录</a> ·
  <a href="https://github.com/SmartFoodieEu/voice_robot/releases/tag/v1.0-handoff">v1.0-handoff</a>
</p>

<p align="center">
  <a href="README.md"><img alt="README in English" src="https://img.shields.io/badge/English-DFE0E5"></a>
  <a href="README.zh.md"><img alt="简体中文自述文件" src="https://img.shields.io/badge/简体中文-DBEDFA"></a>
  <img alt="release" src="https://img.shields.io/badge/release-v1.0--handoff-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="platform" src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Docker-lightgrey">
  <img alt="tests" src="https://img.shields.io/badge/tests-334%20server%20%7C%2029%20bridge-brightgreen">
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-proprietary%20%2B%20MIT%20upstream-white?labelColor=black"></a>
</p>

## 目录

- [工作原理](#工作原理)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [运行环境](#运行环境)
- [验收与测试素材](#验收与测试素材)
- [性能记录](#性能记录)
- [文档索引](#文档索引)
- [服务端里 SmartFoodie 定制的位置](#服务端里-smartfoodie-定制的位置)
- [已知问题与待决事项](#已知问题与待决事项)
- [合并记录](#合并记录)
- [许可](#许可)

## 工作原理

顾客站在 041 号售货机前用中文 / 德语 / 英语提问，ESP32 设备把语音送到自建服务端，服务端结合实时库存回答并播报。完全独立于涂鸦平台和小智官方云。

```
ESP32（aa:bb:cc:dd:ee:ff，固件 2.2.2）
   │ websocket
   ▼
服务端 xiaozhi-esp32-server  :8000（OTA :8003）
   ├─ ASR  sherpa-onnx：SenseVoice 优先，拿不准再问 Whisper
   ├─ LLM  任一 OpenAI 兼容接口（默认火山方舟豆包；ClaudeCLI 仅开发机）
   ├─ TTS  EdgeTTS（另有本地 sherpa-onnx + Piper 离线 provider）
   ├─ http  GET /context  ──► 库存桥 :8766   每轮刷新库存，注入提示词；多数问题本地直答
   └─ mcp   /mcp          ──► 库存桥 :8766   工具调用（预取生效后很少走）
                                   │
                                   ▼
                        Central Kitchen API  inventory-api.example.com/prod-api
```

## 目录结构

| 目录 | 内容 | 真实路径 / 性质 |
|---|---|---|
| `server/` | 小智服务端（含 SmartFoodie 定制：菜单知识、提示词、TTS 切句、预取、ClaudeCLI、回归测试） | subtree 并入，33 条历史；2.1 GB，其中 `models/` 1.9 GB 不入 git |
| `bridge/` | 041 库存桥 `tuya-enterprise-bridge`（`/context`、`/mcp`、中央厨房客户端） | subtree 并入，45 条历史 |
| `launchers/` | `start_server.py`、`start_bridge.py`（凭据来自 `.env` / 环境变量）、`config.example.yaml`、`serve_inventory_bridge.py`、`device_sim.py` 仿真器、`import_menu_knowledge.py`、`nvs_add_ota_url.py`、`HANDOFF.md` | subtree 并入 |
| `deploy/` | Dockerfile ×2、docker-compose、systemd 单元 | 公司部署用 |
| `firmware/` | ESP32 固件源码（`main/`：application、mcp_server、ota、audio、boards…） | 真实目录（原 `~/xiaozhi/firmware-src`） |
| `tools/nvs-tool/` | NVS 分区解析 / 校验 / 日志工具 | 真实目录 |
| `tools/ota-alias/` | 让 Mac 始终持有设备认的 192.168.0.201（launchd 系统守护进程 + 安装脚本） | 安装副本在 `/usr/local/libexec`、`/Library/LaunchDaemons` |
| `device-backup/` | 设备 NVS 镜像（含 WiFi 凭据，**不入库**，gitignore） | 交付时单独提供；开发机在 `~/airobot-device-backup/` |
| `docs/` | `041语音助手链路.pdf`、交接说明、基线说明、桥的 runbook | PDF 为真实文件，其余为指向各仓库内文档的链接 |
| `tests/acceptance/` | `ASR听力测试稿.txt`（24 句三语听力稿）、`tts-对比样本/`（4 组新旧 TTS 对比音频） | 真实目录（原在桌面） |
| `scripts/` | 一键启停、状态、回归、仿真（bash，Linux / macOS 通用） | 真实目录 |
| `logs/` | `start-all.sh` 写的 `server.log` / `bridge.log` | 运行时生成 |

**本目录是唯一的 git 仓库**（2026-10-02 用 `git subtree` 合并，三个来源的提交历史都在，`git log -- server` 可查）。

交接文档：`docs/ARCHITECTURE.md`（模块与接口）、`docs/DEPLOY.md`（部署与运维）、`CONTRIBUTIONS.md`（代码来源与作者）、`docs/debug-2026-10-05.md`（沙盒调试记录）。

## 快速开始

```bash
cp .env.example .env                                   # 首次：填 LLM_API_KEY、SF_APP_KEY
cp launchers/config.example.yaml server/main/xiaozhi-server/data/.config.yaml   # 首次
scripts/start-all.sh     # 先桥后服务端，后台运行，PID 在 run/，日志在 logs/
scripts/status.sh        # 两个服务在不在、桥 /context 是否可达、最近日志
scripts/stop-all.sh
scripts/test-all.sh      # 回归门：服务端 pytest + 桥 pytest
scripts/sim.sh "41号机器现在有什么吃的？"              # 仿真器，跳过 ASR，测直答/LLM+TTS
scripts/sim.sh "有什么吃的？" "那个牛肉炒面还有吗？"    # 多轮
scripts/sim.sh audio tests/acceptance/xxx.wav           # 完整链路
```

两个服务都**不是开机自启**；Linux 用 `deploy/systemd/`，容器用 `deploy/docker-compose.yml`，详见 `docs/DEPLOY.md`。

## 运行环境

- 服务端：Python 3.10（上游锁定 torch 2.2.2），依赖 `server/main/xiaozhi-server/requirements.txt`；解释器位置由 `SERVER_PYTHON` 指定，默认找 `<repo>/.venv`
- 桥：Python 3.11+，`pip install -e bridge`（只需 fastmcp + httpx；涂鸦侧和钥匙串是可选依赖 `[tuya]` `[macos]`）；默认找 `<repo>/bridge/.venv`
- 刷机 / 读写 NVS：esptool
- 服务端配置 `server/main/xiaozhi-server/data/.config.yaml`（gitignore）；示例 `launchers/config.example.yaml`；密钥只在 `.env`

## 验收与测试素材

- `tests/acceptance/ASR听力测试稿.txt`：中 / 德 / 英各 8 句，覆盖问菜、问价、问过敏原、问货道、换语言。每句说一次，等机器复述完再说下一句。
- `tests/acceptance/tts-对比样本/`：中文句夹德语菜名、德语句夹中文菜名等 4 组，各有"旧"(mp3) 与"新"(wav)。
- 延迟基线（HANDOFF §2）：中文首包 3.6–4.3 s，德语 4.5 s，英语 4.3 s；桥故障时 9.3 s。测延迟至少复测三次、打乱顺序、丢弃重启后第一轮。

## 性能记录

| 日期 | 路径 | 首包音频（仿真器，跳过 ASR） | 说明 |
|---|---|---|---|
| 2026-10-02 优化前 | 全部走 LLM | 1.9–4.1 s（中位 2.7） | `docs/perf/baseline-2026-10-02-before.log` |
| 2026-10-02 优化后 | 模板直答（有什么吃的 / 过期 / 空货道 / X 货道） | **0.4–1.1 s** | 跳过 LLM；首句本地合成 |
| 2026-10-02 优化后 | 其他问题走 LLM | 1.4–2.5 s | 首句本地合成 + EdgeTTS 流式；`docs/perf/after-2026-10-02.log` |

优化项（均可配置关闭，见 `server/main/xiaozhi-server/CONFIG_NOTES.md`）：EdgeTTS 流式转码 `edge_stream_decode`、首句本地合成 `first_sentence_local`（zh Matcha / de·en Piper high）、四类问题三语模板直答 `local_template_answers` + 首句音频预热、启动期预热 ClaudeCLI、VAD 尾部静音 900→600 ms、提示词德英首句规则、每轮 `TURN …` 分阶段计时日志（`grep "TURN " tmp/server.log`）。

## 文档索引

| 文档 | 讲什么 |
|---|---|
| `docs/041语音助手链路.pdf` | 整条链路的图文说明（6 页） |
| `docs/HANDOFF-2026-09-17.md` | 交接说明：预取改造原理与实测、三个易错耦合点、已知问题（降级话术、快照过期、降级 9 s、定价数据缺失）、待用户决定事项 |
| `docs/BASELINE-2026-09-22.md` | P-1 基线：`mvp-baseline` tag、回归门、文件归属、备份方式、桥迁移的耦合点清单、待裁决事项 |
| `docs/bridge-runbook.md` | 桥的运维手册 |
| `server/docs/` | 上游 xiaozhi-esp32-server 的部署、固件、MCP、OTA 等文档 |
| `bridge/docs/` | 桥的 specs / plans / 041 验证记录 |
| `docs/debug-2026-10-05.md` | 2026-10-05 四轮沙盒调试的问题、根因与修法 |

## 服务端里 SmartFoodie 定制的位置

- `main/xiaozhi-server/core/utils/menu_knowledge.py`、`resources/smartfoodie/`、`agent-smartfoodie-prompt.txt`
- `main/xiaozhi-server/tests_smartfoodie/`（断句、标点、菜单知识等）
- 相对上游 `mvp-baseline`：36 个文件、+2460 行；提交历史见 `git -C server log`

## 已知问题与待决事项

1. 桥挂掉时模型会去调 `get_lunar` 并把内部错误念给顾客；根因是上游把它写死为必要函数，关掉要 fork 上游——**待拍板**。
2. ~~库存快照只在握手时抓一次~~ 已改为每轮对话入口刷新（`turn_context.py`），长对话不再过期。
3. 降级路径仍需 9.28 s（`mcp_manager.py` 的 10 s 等待），不要简单调短。
4. 中央厨房 API 没有挂牌价，提示词已禁止报价；定价主数据在哪**待回答**。
5. 方舟 API key 曾在截图中暴露，**待轮换**。
6. ~~桥仓库 14 个未提交文件待裁决~~ 2026-10-09 已作为提交 `feat(bridge): /context 支持 fresh=1…` 入库。
7. ~~没有远端~~ 2026-10-15 已推送到 https://github.com/SmartFoodieEu/voice_robot（标签 `v1.0-handoff`）。
8. ~~launchd 开机自启未做~~ 交付版提供 `deploy/systemd/` 与 `deploy/docker-compose.yml`；开发机（macOS）仍是手动 `scripts/start-all.sh`。
9. ~~设备连不上服务端（Mac 换 IP）~~ 2026-10-09 已处理：设备固定连 192.168.0.201，`tools/ota-alias` 的系统守护进程保证这个地址一直在 Mac 上（开机、换 IP、重连 Wi-Fi 都会自动补回）。状态看 `scripts/status.sh` 最后两行，说明见 `tools/ota-alias/README.md`。

## 合并记录

2026-10-02：`~/airobot` 初始化为 git 仓库；`bridge/`（45 commits）、`launchers/`（2）、`server/`（33，浅克隆边界 e4a7c18 = 上游合入点）用 `git subtree add` 并入；工作区文件（含 gitignore 的模型、配置、桥的未提交改动）rsync 同步；`start_server.py` / `start_bridge.py` 改为仓库相对路径；桥 venv 重装 editable。合并前快照在 `~/xiaozhi-backups/pre-monorepo-20261002-100520/`。

## 许可

SmartFoodie 专属代码（bridge、launchers、scripts、deploy、docs、tools，以及所有首行带标记的文件）由 Heyao Rong 为 SmartFoodie GmbH 编写，属公司内部代码。语音服务端基于 [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)（MIT），设备运行 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) 固件（MIT）。详见 [LICENSE](LICENSE) 与 [CONTRIBUTIONS.md](CONTRIBUTIONS.md)。

