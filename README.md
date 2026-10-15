<h1 align="center">airobot — trilingual voice assistant for a vending machine</h1>
<p align="center"><b>Portfolio copy of the code I wrote for SmartFoodie GmbH</b> · published with the company's agreement · internal details removed</p>
<p align="center">
  <a href="README.md"><img alt="English" src="https://img.shields.io/badge/English-DBEDFA"></a>
  <a href="README.zh.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DFE0E5"></a>
  <a href="https://github.com/rhythael/airobot-case-study"><img alt="case study" src="https://img.shields.io/badge/case%20study-read%20first-blue"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="lines" src="https://img.shields.io/badge/my%20code-%E2%89%887.5k%20lines%20%2B%205k%20tests-brightgreen">
</p>

> **What this is.** Everything I wrote for the project, in its original structure, plus one patch file holding my changes to the upstream server. Read the [case study](https://github.com/rhythael/airobot-case-study) first for the problem, the design decisions and the measured results.
> **What it is not.** A runnable product. The upstream server (3,800 commits by other people), the 1.9 GB of speech models and the company's inventory API are not included, and internal hosts, device identifiers and credentials were replaced with placeholders.

## How a question flows through it

```
ESP32 → voice server (VAD → SenseVoice/Whisper routing → local answers → turn shaping → any OpenAI-compatible LLM → local first sentence + streamed TTS) → inventory bridge → inventory API
```

| Stage | My code |
|---|---|
| Recognition | `server/…/core/utils/asr_routing.py`, `audio_filters.py`, `slot_numbers.py` — SenseVoice first (0.05 s), Whisper when unsure; treble compensation; slot-number mis-hearings |
| Inventory every turn | `core/utils/turn_context.py` + patch to `context_provider.py` — fetch from the bridge at the start of every turn, inject into the prompt |
| Local answers (no LLM) | `core/utils/local_answers.py` → `allergen_answer.py`, `diet_answer.py`, `template_answers.py`, `product_answer.py` — allergens, vegetarian / avoid-meat / spiciness, what's available, slots, prices, greeting, menu overview, in zh / de / en |
| Turn shaping (LLM-agnostic) | `core/utils/turn_shaping.py` — reply language and stickiness, language-switch requests, referent mapping across turns, per-turn rules |
| Menu knowledge | `core/utils/menu_knowledge.py` + `resources/smartfoodie/menu_catalog.json` — 220 dish records, fuzzy / pinyin matching |
| Speech | `core/providers/tts/local_first_sentence.py`, `sherpa_onnx_local.py`, `core/utils/tts_lang_split.py` + patches to `tts/base.py`, `tts/edge.py` — first sentence locally in 0.1 s, streamed Opus, voice per language |
| Inventory bridge | `bridge/` — separate process, signed upstream calls, `/context` snapshot + structured list, read-only MCP tool |
| Operations | `launchers/`, `scripts/`, `deploy/` (Docker Compose, systemd), `tools/` |
| Tests | `server/…/tests_smartfoodie/` (30+ files), `tests_live/`, `bridge/tests/` — 334 + 29 + 37 passing at handover |

Measured on the real machine and the simulator: first audio 0.4–1.1 s for locally answered questions (was 1.9–4.1 s), 1.4–2.5 s through the LLM; Chinese ASR 0.59 → 0.05 s; trilingual WER 14.8 % → 9.5 %.

## Layout

```
server/main/xiaozhi-server/   my modules in their upstream paths (overlay)
server/patches/               smartfoodie-changes-to-upstream.patch — my edits to 17 upstream files
bridge/  launchers/  scripts/  deploy/  tools/  docs/  tests/
```

To reconstruct a working tree: clone [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) at commit `e4a7c18`, copy this `server/main/xiaozhi-server/` over it, apply the patch, add the models and an inventory API.

## What was removed or replaced

Internal API host, router and device MAC addresses, store name and device serial, device NVS images (contain WiFi credentials), audio samples, the company PDF. Keys were never in the repository. Machine number `041` is an internal index and was left as is.

## Authorship

All files here were written by Heyao Rong (rhythael@gmail.com) between 2026-09-11 and 2026-10-15; each Python file says so in its first line. The original repository is company-internal; its history, signed tag and handover receipt are the primary evidence. Codex and Claude Code were used as coding assistants; the architecture and every design decision are mine. See `CONTRIBUTIONS.en.md` for the per-module list and `LICENSE` for terms.
