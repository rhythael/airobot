# Architecture and modules

<p><a href="ARCHITECTURE.en.md"><img alt="English" src="https://img.shields.io/badge/English-DBEDFA"></a> <a href="ARCHITECTURE.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DFE0E5"></a></p>

A customer in front of vending machine 041 asks a question in Chinese, German or English. The device streams the audio to a self-hosted server, which answers from the live inventory and speaks the reply. No dependency on the Tuya platform or the Xiaozhi public cloud. This document follows one utterance through the chain and explains, for every module, what it is, what its interface is and how to replace it.

```
ESP32 device (firmware/, unmodified upstream)
   │ ① HTTP  POST /xiaozhi/ota/           :8003   on boot: obtain the websocket address
   │ ② WS    /xiaozhi/v1/                 :8000   hello handshake, then Opus audio + JSON events
   ▼
Voice server server/main/xiaozhi-server (upstream xiaozhi-esp32-server + SmartFoodie customisations)
   ├ capture   core/providers/vad/silero.py            600 ms of silence ends an utterance (injected by launchers/start_server.py)
   ├ recognise core/providers/asr/sherpa_onnx_local.py  SenseVoice first, Whisper when unsure (core/utils/asr_routing.py)
   │           core/utils/slot_numbers.py               "一号期火道" → "1-7货道"
   ├ dispatch  core/connection.py chat()
   │           ├ core/utils/menu_knowledge.py           menu-fact answers (ingredients / allergens / price), no inventory lookup
   │           ├ core/utils/turn_context.py             ③ GET /context?fresh=1 every turn, inventory injected into the prompt
   │           ├ core/utils/local_answers.py            local answer router (modules tried in order)
   │           │   allergen_answer.py  diet_answer.py (vegetarian / avoid-meat / spiciness)
   │           │   template_answers.py (greeting / what's available / slot / menu overview)
   │           │   product_answer.py (is X in stock)  turn_context.py (how many kinds)
   │           └ core/utils/turn_shaping.py             only if nothing matched: reply language, referent background, per-turn rules
   ├ model     core/providers/llm/*                     any OpenAI-compatible endpoint (default); claudecli/ dev machine only
   ├ speak     core/providers/tts/base.py + edge.py     first sentence via local sherpa-onnx (local_first_sentence.py), rest streamed from EdgeTTS
   └ return    core/handle/sendAudioHandle.py           Opus frames + tts/stt/llm events; a short tone when done speaking
                 │ ③ HTTP GET /context    ④ MCP /mcp (kept for tool-capable models; the current model does not use tools)
                 ▼
Inventory bridge bridge/ (tuya_enterprise_bridge.machine_mcp_server, 127.0.0.1:8766)
   ├ inventory.py          locate machine 041 by store name, read 18 slots, build purchasable / expired / empty lists
   └ central_kitchen.py    ⑤ signed GET getStoreList / getStoreGoodsShelvesList
                 ▼
Central Kitchen API  https://inventory-api.example.com/prod-api (signed with SF_APP_KEY)
```

## Interface contracts

| Boundary | Protocol | Essentials |
|---|---|---|
| ① device → server OTA | HTTP POST, headers `device-id` / `client-id` | the reply's `websocket.url` is built from the host's LAN IP (`core/utils/util.get_local_ip`); pin it with `server.websocket` in the config if needed |
| ② device ↔ server | WebSocket, Xiaozhi protocol | binary frames = Opus 16 kHz; JSON: `hello` / `listen` / `tts` (start, sentence_start, stop) / `stt` / `llm` |
| ③ server → bridge | `GET /context[?fresh=1]`, returns `{code, data}` | `code≠0` means the upstream failed and the server says "inventory temporarily unavailable". **The keys of `data` are literally the instructions given to the model**; `data.inventory` is the structured list for local answers (`machine_number`, `items[{slot,name,quantity,purchasable}]`) |
| ④ server → bridge | MCP over HTTP `/mcp`, read-only tool `machine_inventory_query` | not used by the current model; kept for models with function calling |
| ⑤ bridge → Central Kitchen | GET + `appKey/timeStamp/sign` (sha256) | 5 s timeout; a store counts as 041 when its name ends in `041` and storeId ≠ 61 |

## How to replace a part

| To change | Edit |
|---|---|
| the LLM | `selected_module.LLM` in `data/.config.yaml` → any entry with `type: openai` (Volcengine, DeepSeek, OpenAI, local vLLM …); the key goes into `.env` as `LLM_API_KEY`. Turn shaping (`turn_shaping.py`) applies to every provider |
| speech synthesis | `selected_module.TTS`; local first-sentence synthesis needs the Piper / Matcha models under `models/tts/`, otherwise it falls back to the cloud voice automatically |
| the ASR models | `ASR.WhisperASR.model_dir` / `zh_model_dir`; must be whisper-small (see CONFIG_NOTES) |
| the inventory source | the two requests in `bridge/src/tuya_enterprise_bridge/central_kitchen.py`; keep the output structure of `inventory.py` |
| serving several machines | the bridge's `ALLOWED_MACHINE_NUMBERS`, the hard-coded `041` in `machine_mcp_server.py`, and the machine number in the prompt |
| switching a local answer off | the `turn_context_refresh` flags in `launchers/start_server.py`: `local_allergen_answers` / `local_diet_answers` / `local_spicy_answers` / `local_template_answers` / … |

## Three hidden couplings (change both sides together)

1. The `/context` key of the bridge contains the words "库存快照" (inventory snapshot); `core/connection.py` tests `"库存快照" in prompt` to decide whether to wait for tools.
2. TTS sentence splitting (`core/providers/tts/base.py`) and the punctuation table (`core/utils/textUtils.py`) share characters such as the semicolon; after touching either, run all of `tests_smartfoodie`.
3. Local answers and the prompt agree that the first sentence of a reply carries no product name and is in a single language; only such a first sentence can be synthesised locally.

## Configuration layers

- `server/main/xiaozhi-server/config.yaml`: upstream defaults, never edited.
- `server/main/xiaozhi-server/data/.config.yaml`: machine-specific (model directories, voices, ports), not in git; example in `launchers/config.example.yaml`.
- `apply_overrides` in `launchers/start_server.py`: the parameters SmartFoodie chose on purpose (VAD 600 ms, local-answer switches, first-sentence model paths); in git, the single source of truth.
- `.env`: secrets, not in git.
