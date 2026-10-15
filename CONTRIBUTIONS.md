# 代码来源与贡献说明

<p><a href="CONTRIBUTIONS.en.md"><img alt="English" src="https://img.shields.io/badge/English-DFE0E5"></a> <a href="CONTRIBUTIONS.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DBEDFA"></a></p>

本仓库是 SmartFoodie 041 售货机语音助手的全部代码。三部分来源不同，交接时请分开看待：

| 目录 | 来源 | 许可 / 说明 |
|---|---|---|
| `server/` 中未标注的文件 | 上游开源项目 **xiaozhi-esp32-server**（xinnan-tech），合入点为上游提交 `e4a7c18` | 上游 LICENSE 见 `server/LICENSE` |
| `server/` 中文件头标注「SmartFoodie 041 … 定制模块」或「含 SmartFoodie 041 定制改动」的文件 | **Heyao Rong** 为 SmartFoodie 开发（2026-09 至 2026-10），部分借助 Codex / Claude Code 辅助编码 | 公司内部代码 |
| `bridge/`、`launchers/`、`scripts/`、`tools/`、`deploy/`、`docs/`、`tests/` | 全部为 **Heyao Rong** 为 SmartFoodie 开发 | 公司内部代码 |
| `firmware/` | 上游 **xiaozhi-esp32** 固件源码，未改动；设备只改了 NVS 里的服务端地址 | 上游许可 |

作者联系方式：Heyao Rong（rhythael@gmail.com）。

## 文件头标记

每个 Python 文件第一行有标记，方便 `grep` 统计：

```bash
grep -rl "SmartFoodie 041 语音助手 · 定制模块" --include='*.py' .       # 新写的模块
grep -rl "含 SmartFoodie 041 定制改动" --include='*.py' .                # 在上游文件上改的
```

## 在上游文件上改了什么（17 个文件）

| 文件 | 改动 |
|---|---|
| `core/connection.py` | 每轮入口：本地菜单资料直答 → 每轮刷新库存 → 本地直答路由 → 大模型；工具就绪竞态；每轮整形接入；TURN 计时 |
| `core/handle/receiveAudioHandle.py` | 抢话时保留本轮计时；听力测试模式 |
| `core/handle/abortHandle.py`、`helloHandle.py`、`textMessageProcessor.py` | 打断与握手时的计时、状态复位 |
| `core/providers/asr/base.py`、`asr/sherpa_onnx_local.py` | SenseVoice 优先 + Whisper 兜底的双模型路由；高频补偿；线程数按性能核；货道号归一 |
| `core/providers/tts/base.py`、`tts/edge.py` | 英文句号断句；首句本地合成；EdgeTTS 流式转码；按语言换音色；句内分语言；超长段切点；首尾静音裁剪 |
| `core/providers/llm/openai/openai.py` | 超时与重试参数化 |
| `core/providers/tools/server_mcp/mcp_manager.py`、`server_plugins/plugin_executor.py` | 桥不可达时的降级；只保留 MCP 工具 |
| `core/utils/context_provider.py`、`prompt_manager.py` | 库存快照与菜单资料注入提示词；失败标记 |
| `core/utils/textUtils.py` | 标点清理表；表情及附属码位 |
| `core/utils/util.py`、`audioRateController.py` | 音频发送恢复；工具函数 |

## 新写的模块（按链路顺序）

| 模块 | 作用 |
|---|---|
| `core/utils/asr_routing.py`、`audio_filters.py`、`slot_numbers.py` | 识别路由、麦克风高频补偿、货道号写法归一 |
| `core/utils/menu_knowledge.py`、`resources/smartfoodie/menu_catalog.json`、`launchers/import_menu_knowledge.py` | 220 条菜品资料（配料、过敏原、价格）与本地查询 |
| `core/utils/turn_context.py`、`context_provider.py` 改动 | 每轮向桥刷新库存并注入提示词 |
| `core/utils/local_answers.py` + `allergen_answer.py`、`diet_answer.py`、`template_answers.py`、`product_answer.py` | 不经大模型的本地直答：过敏原、素食/忌口/辣度、招呼、货单、货道、商品有无、菜单概括 |
| `core/utils/turn_shaping.py` | 送给大模型前的每轮整形：回答语言、指代背景、换语言确认、规则（所有 provider 共用） |
| `core/providers/llm/claudecli/` | 开发机用的 Claude Code CLI provider（公司部署不用） |
| `core/providers/tts/local_first_sentence.py`、`sherpa_onnx_local.py`、`core/utils/tts_lang_split.py` | 首句本机合成、离线 TTS、句内分语言 |
| `core/utils/turn_timing.py` | 每轮分阶段计时日志 |
| `agent-smartfoodie-prompt.txt` | 系统提示词模板 |
| `tests_smartfoodie/`（30 余个文件）、`tests_live/` | 离线回归与设备接口测试 |
| `bridge/` | 041 库存桥：`/context`、`/mcp`、中央厨房签名客户端 |
| `launchers/`、`scripts/`、`deploy/` | 启动、运维、容器与 systemd |
| `tools/nvs-tool/`、`tools/ota-alias/` | 设备 NVS 工具、开发机地址守护（设备 NVS 镜像含 WiFi 凭据，不入库，交接时单独提供） |

## 开发记录

- 提交历史：`git log`（主干）、`git log history/server`、`history/bridge`、`history/launchers`（合并前的三条历史）。
- 2026-10-05 四轮沙盒调试的问题与修法：`docs/debug-2026-10-05.md`。
- 设计与交接：`docs/HANDOFF-2026-09-17.md`、`docs/BASELINE-2026-09-22.md`、`docs/ARCHITECTURE.md`。
