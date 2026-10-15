# Provenance and authorship

<p><a href="CONTRIBUTIONS.en.md"><img alt="English" src="https://img.shields.io/badge/English-DBEDFA"></a> <a href="CONTRIBUTIONS.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DFE0E5"></a></p>

This repository contains all the code of the voice assistant for SmartFoodie vending machine 041. Three origins; please treat them separately at handover:

| Location | Origin | Licence / notes |
|---|---|---|
| Unmarked files under `server/` | the upstream open-source project **xiaozhi-esp32-server** (xinnan-tech); merge point = upstream commit `e4a7c18` | upstream LICENSE, see `server/LICENSE` |
| Files under `server/` whose first line says "SmartFoodie 041 … custom module" or "contains SmartFoodie 041 customisations" | written by **Heyao Rong** for SmartFoodie (2026-09 to 2026-10), partly with Codex / Claude Code as coding assistants | company-internal code |
| `bridge/`, `launchers/`, `scripts/`, `tools/`, `deploy/`, `docs/`, `tests/` | entirely written by **Heyao Rong** for SmartFoodie | company-internal code |
| `firmware/` | upstream **xiaozhi-esp32** firmware source, unmodified; only the server address in the device's NVS was changed | upstream licence |

Author contact: Heyao Rong (rhythael@gmail.com).

## File-header markers

The first line of every Python file identifies its origin (bilingual), so `grep` can count them:

```bash
grep -rl "SmartFoodie 041 语音助手 · 定制模块" --include='*.py' .       # new modules
grep -rl "含 SmartFoodie 041 定制改动" --include='*.py' .                # upstream files that were modified
```

## What was changed in upstream files (17 files)

| File | Change |
|---|---|
| `core/connection.py` | per-turn entry: menu-fact answers → inventory refresh → local answer router → LLM; tool-readiness race; turn shaping for every provider; TURN timing |
| `core/handle/receiveAudioHandle.py` | keep the turn timer when the customer interrupts; listening-test mode |
| `core/handle/abortHandle.py`, `helloHandle.py`, `textMessageProcessor.py` | timing and state reset on interrupt / handshake |
| `core/providers/asr/base.py`, `asr/sherpa_onnx_local.py` | SenseVoice-first / Whisper-fallback routing; treble boost; thread count from performance cores; slot-number normalisation |
| `core/providers/tts/base.py`, `tts/edge.py` | sentence splitting on Latin full stops; local first sentence; EdgeTTS streaming decode; voice per language; in-sentence language split; long-segment cut points; silence trimming |
| `core/providers/llm/openai/openai.py` | timeout and retry parameters |
| `core/providers/tools/server_mcp/mcp_manager.py`, `server_plugins/plugin_executor.py` | degraded mode when the bridge is unreachable; MCP tools only |
| `core/utils/context_provider.py`, `prompt_manager.py` | inventory snapshot and menu facts injected into the prompt; failure marker |
| `core/utils/textUtils.py` | punctuation table; emoji and their modifier code points |
| `core/utils/util.py`, `audioRateController.py` | audio send recovery; helpers |

## New modules (in chain order)

| Module | Purpose |
|---|---|
| `core/utils/asr_routing.py`, `audio_filters.py`, `slot_numbers.py` | recognition routing, microphone treble compensation, slot-number spelling |
| `core/utils/menu_knowledge.py`, `resources/smartfoodie/menu_catalog.json`, `launchers/import_menu_knowledge.py` | 220 dish records (ingredients, allergens, price) and local lookup |
| `core/utils/turn_context.py` + changes in `context_provider.py` | refresh the inventory from the bridge every turn and inject it |
| `core/utils/local_answers.py` + `allergen_answer.py`, `diet_answer.py`, `template_answers.py`, `product_answer.py` | answers without the LLM: allergens, vegetarian / avoid-meat / spiciness, greeting, what's available, slots, is-X-in-stock, menu overview |
| `core/utils/turn_shaping.py` | shaping before the LLM: reply language, referent background, language-switch confirmation, per-turn rules (shared by all providers) |
| `core/providers/llm/claudecli/` | Claude Code CLI provider for the dev machine (not for company deployment) |
| `core/providers/tts/local_first_sentence.py`, `sherpa_onnx_local.py`, `core/utils/tts_lang_split.py` | local first-sentence synthesis, offline TTS, in-sentence language split |
| `core/utils/turn_timing.py` | per-turn timing log |
| `agent-smartfoodie-prompt.txt` | system prompt template |
| `tests_smartfoodie/` (30+ files), `tests_live/` | offline regression and device-interface tests |
| `bridge/` | inventory bridge for 041: `/context`, `/mcp`, signed Central Kitchen client |
| `launchers/`, `scripts/`, `deploy/` | launch, operations, containers and systemd |
| `tools/nvs-tool/`, `tools/ota-alias/` | device NVS tools, dev-machine address daemon (device NVS images contain WiFi credentials, kept out of git, handed over separately) |

## Development record

- Commit history: `git log` (main), `git log history/server`, `history/bridge`, `history/launchers` (the three pre-merge histories).
- The four rounds of sandbox debugging on 2026-10-05: `docs/debug-2026-10-05.md`.
- Design and handoff: `docs/HANDOFF-2026-09-17.md`, `docs/BASELINE-2026-09-22.md`, `docs/ARCHITECTURE.en.md`.
