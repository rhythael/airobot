# 链路与模块说明

<p><a href="ARCHITECTURE.en.md"><img alt="English" src="https://img.shields.io/badge/English-DFE0E5"></a> <a href="ARCHITECTURE.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DBEDFA"></a></p>

顾客站在 041 号售货机前用中文 / 德语 / 英语提问，设备把语音送到自建服务端，服务端结合实时库存回答并播报。
不依赖涂鸦平台和小智官方云。本文按一句话经过的顺序讲每个模块是什么、接口是什么、怎么换。

```
ESP32 设备（固件 firmware/，未改动）
   │ ① HTTP  POST /xiaozhi/ota/           :8003   开机取 websocket 地址
   │ ② WS    /xiaozhi/v1/                 :8000   hello 握手后收发 Opus 音频与 JSON 事件
   ▼
语音服务端 server/main/xiaozhi-server（上游 xiaozhi-esp32-server + SmartFoodie 定制）
   ├ 收音   core/providers/vad/silero.py            静音 600 ms 判一句说完（launchers/start_server.py 注入）
   ├ 识别   core/providers/asr/sherpa_onnx_local.py  SenseVoice 先，拿不准再 Whisper（core/utils/asr_routing.py）
   │        core/utils/slot_numbers.py               「一号期火道」→「1-7货道」
   ├ 分流   core/connection.py chat()
   │        ├ core/utils/menu_knowledge.py           菜单资料直答（配料 / 过敏原 / 价格），不查库存
   │        ├ core/utils/turn_context.py             ③ 每轮 GET /context?fresh=1 刷新库存，注入提示词
   │        ├ core/utils/local_answers.py            本地直答路由（下列模块按序尝试）
   │        │   allergen_answer.py  diet_answer.py(素食/忌口/辣度)  template_answers.py(招呼/货单/货道/菜单概括)
   │        │   product_answer.py(商品有无)  turn_context.py(种数)
   │        └ core/utils/turn_shaping.py             都没命中才走大模型：回答语言、指代背景、每轮规则
   ├ 模型   core/providers/llm/*                     任何 OpenAI 兼容接口（默认）；claudecli/ 仅开发机
   ├ 合成   core/providers/tts/base.py + edge.py     首句本机 sherpa-onnx（local_first_sentence.py），其余 EdgeTTS 流式
   └ 回传   core/handle/sendAudioHandle.py           Opus 帧 + tts/stt/llm 事件；说完响提示音
                 │ ③ HTTP GET /context    ④ MCP /mcp（当前模型不用工具调用，保留）
                 ▼
库存桥 bridge/（tuya_enterprise_bridge.machine_mcp_server，127.0.0.1:8766）
   ├ inventory.py          按门店名定位 041，读 18 个货道，拼可购买清单 / 过期 / 空货道
   └ central_kitchen.py    ⑤ 签名 GET getStoreList / getStoreGoodsShelvesList
                 ▼
中央厨房 API  https://inventory-api.example.com/api（SF_APP_KEY 签名）
```

## 接口契约

| 边界 | 协议 | 要点 |
|---|---|---|
| ① 设备 → 服务端 OTA | HTTP POST，头 `device-id` / `client-id` | 回包 `websocket.url` 由服务端按本机局域网 IP 生成（`core/utils/util.get_local_ip`，可用配置 `server.websocket` 固定） |
| ② 设备 ↔ 服务端 | WebSocket，小智协议 | 二进制帧 = Opus 16 kHz；JSON：`hello` / `listen` / `tts`(start, sentence_start, stop) / `stt` / `llm` |
| ③ 服务端 → 桥 | `GET /context[?fresh=1]`，回 `{code, data}` | `code≠0` 表示上游失败，服务端改说「暂时查不到库存」。**`data` 里的键名就是给模型的指令**；`data.inventory` 是本地直答用的结构化清单（`machine_number`, `items[{slot,name,quantity,purchasable}]`） |
| ④ 服务端 → 桥 | MCP over HTTP `/mcp`，只读工具 `machine_inventory_query` | 现在的模型不调工具，保留给支持 function call 的模型 |
| ⑤ 桥 → 中央厨房 | GET + `app_key/ts/sign`（sha256） | 5 秒超时；门店名以 `041` 结尾且 不在排除名单内 才算 041 |

## 怎么换

| 想换 | 改哪里 |
|---|---|
| 大模型 | `data/.config.yaml` 的 `selected_module.LLM` 指向任一 `type: openai` 的条目（火山方舟、DeepSeek、OpenAI、本地 vLLM …），Key 放 `.env` 的 `LLM_API_KEY`。整形逻辑（`turn_shaping.py`）对所有 provider 生效 |
| 语音合成 | `selected_module.TTS`；首句本地合成需要 `models/tts/` 下的 Piper / Matcha 模型，没有就自动退回云端合成 |
| 识别模型 | `ASR.WhisperASR.model_dir` / `zh_model_dir`；必须 whisper-small（见 CONFIG_NOTES） |
| 库存来源 | 换 `bridge/src/tuya_enterprise_bridge/central_kitchen.py` 的两个请求，保持 `inventory.py` 的输出结构 |
| 服务多台机器 | 桥的 `ALLOWED_MACHINE_NUMBERS`、`machine_mcp_server.py` 里写死的 `041`，以及提示词中的机器号 |
| 关掉某个本地直答 | `launchers/start_server.py` 的 `turn_context_refresh` 开关：`local_allergen_answers` / `local_diet_answers` / `local_spicy_answers` / `local_template_answers` / … |

## 三个隐性耦合（改动时两边一起改）

1. 桥 `/context` 的键名含「库存快照」字样，服务端 `core/connection.py` 用 `"库存快照" in prompt` 判断是否跳过等待工具。
2. TTS 切句（`core/providers/tts/base.py`）与标点清理表（`core/utils/textUtils.py`）共享分号等符号，改一处必须跑 `tests_smartfoodie` 全部。
3. 本地直答与提示词里的「首句不带菜名、单一语言」约定：首句本地合成只接得住这种首句。

## 配置分层

- `server/main/xiaozhi-server/config.yaml`：上游默认，不改。
- `server/main/xiaozhi-server/data/.config.yaml`：机器相关（模型目录、音色、端口），不入库；示例在 `launchers/config.example.yaml`。
- `launchers/start_server.py` 的 `apply_overrides`：SmartFoodie 有意的参数（VAD 600 ms、本地直答开关、首句合成模型路径），入库，是「唯一真相」。
- `.env`：密钥，不入库。
