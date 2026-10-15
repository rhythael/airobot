<h1 align="center">airobot — 售货机三语语音助手</h1>
<p align="center"><b>我为 SmartFoodie GmbH 编写的代码的作品集副本</b> · 经公司同意公开 · 已去除内部信息</p>
<p align="center">
  <a href="README.md"><img alt="English" src="https://img.shields.io/badge/English-DFE0E5"></a>
  <a href="README.zh.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-DBEDFA"></a>
  <a href="https://github.com/rhythael/airobot-case-study"><img alt="案例说明" src="https://img.shields.io/badge/案例说明-先读这个-blue"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="lines" src="https://img.shields.io/badge/我的代码-%E2%89%887500%20行%20%2B%205000%20行测试-brightgreen">
</p>

> **这是什么。** 我在这个项目里写的全部代码，保持原有目录结构，外加一个补丁文件，装着我对上游服务端的改动。问题、设计决策和实测结果请先看[案例说明](https://github.com/rhythael/airobot-case-study)。
> **这不是什么。** 不是可直接运行的产品。上游服务端（3800 个别人的提交）、1.9 GB 语音模型、公司库存接口都不在这里；内部主机名、设备标识和凭据已替换为占位符。

## 一句话怎么走完整条链路

```
ESP32 → 语音服务端（VAD → SenseVoice/Whisper 路由 → 本地直答 → 每轮整形 → 任一 OpenAI 兼容大模型 → 首句本机合成 + 流式 TTS）→ 库存桥 → 库存接口
```

| 环节 | 我的代码 |
|---|---|
| 识别 | `server/…/core/utils/asr_routing.py`、`audio_filters.py`、`slot_numbers.py` — SenseVoice 先判（0.05 s），拿不准再 Whisper；高频补偿；货道号听错写法 |
| 每轮库存 | `core/utils/turn_context.py` + 对 `context_provider.py` 的补丁 — 每轮入口向桥取库存并注入提示词 |
| 本地直答（不经大模型） | `core/utils/local_answers.py` → `allergen_answer.py`、`diet_answer.py`、`template_answers.py`、`product_answer.py` — 过敏原、素食/忌口/辣度、货单、货道、价格、招呼、菜单概括，中德英 |
| 整形（与模型无关） | `core/utils/turn_shaping.py` — 回答语言与粘性、换语言请求、多轮指代映射、每轮规则 |
| 菜单知识 | `core/utils/menu_knowledge.py` + `resources/smartfoodie/menu_catalog.json` — 220 条菜品资料，拼音模糊匹配 |
| 语音 | `core/providers/tts/local_first_sentence.py`、`sherpa_onnx_local.py`、`core/utils/tts_lang_split.py` + 对 `tts/base.py`、`tts/edge.py` 的补丁 — 首句本机 0.1 s 出声、流式 Opus、按语言换音色 |
| 库存桥 | `bridge/` — 独立进程，签名调用上游，`/context` 快照 + 结构化清单，只读 MCP 工具 |
| 运维 | `launchers/`、`scripts/`、`deploy/`（Docker Compose、systemd）、`tools/` |
| 测试 | `server/…/tests_smartfoodie/`（30 余个文件）、`tests_live/`、`bridge/tests/` — 交付时 334 + 29 + 37 条通过 |

真机与仿真器实测：本地直答类首包 0.4–1.1 s（原 1.9–4.1 s），走大模型 1.4–2.5 s；中文识别 0.59 → 0.05 s；三语字错率 14.8 % → 9.5 %。

## 目录

```
server/main/xiaozhi-server/   我的模块，保持上游路径（覆盖层）
server/patches/               smartfoodie-changes-to-upstream.patch — 我对 17 个上游文件的改动
bridge/  launchers/  scripts/  deploy/  tools/  docs/  tests/
```

要还原成可运行的工作区：克隆 [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) 到提交 `e4a7c18`，把这里的 `server/main/xiaozhi-server/` 覆盖上去，打补丁，再放入模型和一个库存接口。

## 去掉或替换了什么

内部接口主机名、路由器与设备 MAC、门店名与设备序列号、设备 NVS 镜像（含 WiFi 凭据）、音频样本、公司 PDF。密钥从未进过仓库。机器编号 `041` 只是内部序号，保持原样。

## 作者

这里所有文件由 Heyao Rong（rhythael@gmail.com）在 2026-09-11 至 2026-10-15 期间编写，每个 Python 文件首行都有署名。原仓库属公司内部，其提交历史、签名标签和交接签收单是第一手证据。开发中使用 Codex 与 Claude Code 作为编码辅助，架构与所有设计决策由本人做出。逐模块清单见 `CONTRIBUTIONS.md`，条款见 `LICENSE`。
