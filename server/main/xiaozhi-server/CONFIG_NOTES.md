# 生产配置要点

`data/.config.yaml` 被 .gitignore 排除（含活凭据），所以它的内容不在版本控制内。
换机器或重建配置时照这份文档恢复，否则会悄悄退回上游默认值。

## 模块选择

```yaml
selected_module:
  VAD: SileroVAD
  ASR: WhisperASR
  LLM: CloudLLM       # 任一 type: openai 的条目；ClaudeCLI 仅开发机
  TTS: EdgeTTS
  Memory: nomem
  Intent: function_call
```

## VAD：静音阈值 600ms（2026-10-02 从 900 收紧）

值由 `launchers/start_server.py` 的 `apply_overrides` 注入（`min_silence_duration_ms = 600`），
`data/.config.yaml` 里不再写这个键：配置文件被 gitignore，换机器会丢，覆盖层是被跟踪的唯一真相。

上游默认 200ms。顾客句中略一停顿就被判定说完并打断，中文口语句中停顿常在 400-800ms，
2026-09 因此放宽到 900ms。2026-10-02 全链路优化时收到 600ms：真机每句话少等 0.3 秒，
这是首包里唯一一段纯等待。

风险：句中停顿超过 0.6 秒（想菜名、看屏幕）会被判定说完，后半句落到下一轮。
观察指标：实机日志里同一顾客连续两轮、第二轮是半句话的比例。
回退：改 `launchers/start_server.py` 里的 600 为 900 并重启服务端（`scripts/stop-all.sh && scripts/start-all.sh`）。

## ASR：必须用 whisper-small，不能用 base

```yaml
ASR:
  WhisperASR:
    model_dir: models/sherpa-onnx-whisper-small
    zh_model_dir: models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
```

base 的德语识别不可用，实测把 `hat 9 leere Fächer` 听成 `hat neuen Lehrefechern`，
中文货道号 `1-7道` 听成 `1港7道`。德语是门店顾客的主要语言，货道号是取餐依据。
small 单次识别约 0.96-1.29 秒（base 约 0.3-0.5 秒），这个代价是刻意付的。

推理线程数不再写死 2，默认取性能核数（本机 4）。实测 whisper-small 平均单次识别：

| 线程 | 平均 |
|---|---|
| 2 | 1.15 秒 |
| 4 | 0.76 秒 |
| 6 | 0.86 秒 |
| 8 | 1.03 秒 |

超过性能核数会把活派到能效核上，反而更慢。配置里给 `num_threads` 可覆盖。
CoreML 试过，int8 量化模型上比 CPU 慢 15 倍（13.24 秒 对 0.86 秒），不要用。

识别顺序（2026-09-23 起，见 core/utils/asr_routing.py）：先跑 SenseVoice，认定是中文且至少 3 个汉字就直接用（约 0.05 秒）；否则再跑 Whisper，德语用 Whisper 的结果，英语用 SenseVoice 的结果；Whisper 判出中德英以外的语言时按德语重识别。之前是每句都先让 Whisper 完整识别，中文要 0.6 秒。

## TTS：按语言换音色

```yaml
TTS:
  EdgeTTS:
    voice: de-DE-SeraphinaMultilingualNeural   # 认不出语言时的默认
    voices:
      zh: zh-CN-XiaoxiaoNeural
      de: de-DE-SeraphinaMultilingualNeural
      en: en-US-AvaMultilingualNeural
```

只配 voice 不配 voices 时，所有语言共用一个德语音色。多语音色能读别的语言但读不好：
同一句中文德语音色要 10.85 秒，中文音色 9.05 秒，慢 20%，听感含糊。

## LLM：ClaudeCLI

```yaml
LLM:
  ClaudeCLI:
    type: claudecli
    model_name: claude-haiku-4-5
    read_timeout: 25
```

实测 Haiku 首字中位 0.75 秒、最大 1.28 秒；Sonnet 5 中位 0.99 秒但「中文指代」场景
稳定在 3.6 秒以上，故选 Haiku。详见 obsidian session-log 的 A/B 记录。

`cli_path` 由 `launchers/start_server.py` 注入：`shutil.which("claude")`，找不到回落
`~/.local/bin/claude`（它是指向 `~/.local/share/claude/versions/<版本>` 的软链接，升级 Claude Code
后自动更新）。配置文件里显式写了 `cli_path` 则以配置为准。这样从 launchd 或非登录 shell 启动、
PATH 里没有 `~/.local/bin` 时也能找到。
日志里曾出现的「找不到 claude CLI: /nonexistent/claude」来自 `tests_smartfoodie/test_llm_session_cleanup.py`
的用例（它们和服务端共用同一个日志文件），不是生产配置的问题。

服务启动时会在后台用一次性会话 `startup-warm` 预热一次 LLM（`core/websocket_server.py`）：
走 `LLMProviderBase.warmup` 接口，不判 provider 类型，不需要预热的 provider 默认是空操作。
重启后第一个连接的握手期预热实测 3.69 秒，之后只要 1.3–1.7 秒，差的两秒是 claude
可执行文件冷启动，与连接无关，所以提前到启动期付掉。

## 由 start_server.py 在内存里注入的（不写进配置文件）

函数 `apply_overrides(config, key)`。这是被 git 跟踪的覆盖层：凡是我们有意改动、希望新机器也生效的
参数都放这里；`data/.config.yaml` 只放机器相关的东西（模型目录、音色、API 地址）。

- LLM_API_KEY / SPEECH_APPID / SPEECH_ACCESS_TOKEN：从 `.env` 或环境变量读（开发机无 `.env` 时退回 macOS 钥匙串）
- `local_menu_knowledge`：菜品目录路径与 concise_voice
- `menu_settings`：传给 ClaudeCLI provider，用于按对话内容补查菜品资料
- ClaudeCLI 的 `cli_path`（配置未写时按 `which claude` 注入）
- VAD `min_silence_duration_ms = 600`
- `turn_context_refresh`：每轮刷新与本地直答开关
- `context_providers` 的 refresh_params 与 structured_fields
- EdgeTTS：`cache_short_audio`、超时与重试、`tts_max_segment_chars`、
  `edge_stream_decode`、`first_sentence_local`、`first_sentence_models`（绝对路径）、`first_sentence_vocoder`

不起服务校验拼装结果：
```bash
cd <repo> && "${SERVER_PYTHON:-.venv/bin/python}" -c "
import sys, os, asyncio; r=os.path.abspath('.')
sys.path[:0]=[r+'/launchers', r+'/server/main/xiaozhi-server']; os.chdir('server/main/xiaozhi-server')
from config.config_loader import load_config; import start_server
c=start_server.apply_overrides(asyncio.run(load_config()),'x'); print(c['VAD'], c['TTS']['EdgeTTS'].get('first_sentence_models'))"
```

## 未启用但配置段存在

`voiceprint` 段存在而 url 为空。connection.py 判的是 url，所以不会启用，
日志记 info「声纹识别功能未启用」。不要在未评估合规前给它填 url。

## 收音：补高频 + 回答后提示音（2026-09-23 开启）

```yaml
listen_cue: true          # 顶层
ASR:
  WhisperASR:
    highshelf_db: 6       # 识别前 3.5kHz 以上 +6dB，0 为关闭
```

041 的设备是 NullLab ESP32-WROOM-32E + 板载 16kHz PDM 麦克风。普通 ESP32 跑不了乐鑫 AFE，
设备端没有降噪、没有回声消除、没有 VAD。2026-09-23 用 Mac 麦克风同步录音对照：
同一时间窗、同一 SenseVoice，Mac 基本全对，机器错约三成的句子。

- 音质：机器 4-8kHz 比 Mac 低约 7dB，底噪高 14dB，辅音被听混（顾客→姑、手机→肘机、机→器）。
  highshelf_db: 6 在真机录音上字错率 19.8% → 13.9%，中德英干净语音 12 句结果完全不变。
  只能部分改善；根治要换带 AFE 的 ESP32-S3 板和 I2S 麦克风。
- 丢句首：设备说话时不收音，播放队列清空后才重新打开麦克风。顾客在机器话音刚落时接话，
  开头几个字就丢了。服务端 VAD 本身正常（开口约 0.12 秒触发，0.6 秒缓冲够用），网络无丢包。
  listen_cue 在每次回答后响约 0.3 秒提示音，让顾客等它响完再开口。
- 提示词 `<speech_input>` 告诉模型顾客的话来自识别、常有同音错字，按读音和场景理解。

## 诊断开关（默认关闭，会录下说话人的声音，测完关掉并删除录音）

```yaml
asr_listen_test: true                  # 顶层：机器不回答，只复述听到的内容
audio_stream_capture_dir: tmp/audio_stream   # 顶层：设备传来的全部音频 + 包到达时间 + VAD 事件
ASR:
  WhisperASR:
    capture_dir: tmp/asr_capture       # 每句录音 + Whisper / SenseVoice 各自结果
```

## TTS：句内分语言合成（可选，默认关闭）

```yaml
TTS:
  EdgeTTS:
    split_languages: true   # 需同时配 voices
```

不开时整句只交给一个音色：句子里有一个汉字就全交给中文音色，所以德国顾客听到的
「Am Automaten 041 gibt es … 1-6 鸡肉蔬菜蒸饺」整句是中文音色在念德语；
中文句里的德语长菜名则是中文音色硬念。开了之后按书写体系切段，每段用对应音色，
并发合成、裁掉首尾静音再拼接。货道号跟随整句的主语言，「10粒」「2份」这种量词跟着中文。
实机日志 913 句里 130 句会被切开。

代价是延迟，只发生在被切开的句子上：缓存冷时实测多 0.7-2.1 秒（几个并发连接首次握手
互相拖慢），菜名进缓存后多约 0.1 秒（解码拼接）。

德英保持 Multilingual 音色，不要换成原生音色（Katja / Jenny 等）。2026-09-23 交替实测
10 轮，两类音色首包中位数都是 0.25-0.29 秒，原生音色并不更快（之前逐个测出的差距是
网络随时间波动造成的）；而短句的德英判断常常拿不准，判错时多语音色还念得下去，
原生音色就念坏了。过敏原词清晰度两类打平（Seraphina 34/40，Katja 36/40）。

本地离线模型也比过（Piper / Matcha / Kokoro / MeloTTS）：快，但中文和德语的发音都不如
EdgeTTS——Matcha 把「虾饺」念成「夹角」，Piper thorsten 把 Dampfnudel 念坏，
而 Piper thorsten-high 已经不比 EdgeTTS 快。

## 本地离线 TTS（可选，未默认启用）

`core/providers/tts/sherpa_onnx_local.py`，基于 sherpa-onnx 的 Piper(VITS) 模型，
完全离线。要启用改 `selected_module.TTS: SherpaLocalTTS` 并加：

```yaml
TTS:
  SherpaLocalTTS:
    type: sherpa_onnx_local
    default_language: de
    num_threads: 4
    models:
      de: models/tts/vits-piper-de_DE-thorsten-medium
      zh: models/tts/vits-piper-zh_CN-huayan-medium
      en: models/tts/vits-piper-en_US-amy-medium
    output_dir: tmp/
```

模型不入库（`.gitignore` 已排除 `models/tts/`），三语合计约 236MB，另行下载：

```bash
cd main/xiaozhi-server/models/tts
for m in vits-piper-de_DE-thorsten-medium vits-piper-zh_CN-huayan-medium vits-piper-en_US-amy-medium; do
  curl -L -o "$m.tar.bz2" "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/$m.tar.bz2"
  tar -xjf "$m.tar.bz2" && rm "$m.tar.bz2"
done
```

首包实测对照（同一句话，本机 8 核 / num_threads=4）：

| 语言 | EdgeTTS 首包 | Piper 首包 | 倍数 |
|---|---|---|---|
| 德语 | 1.415 秒 | 0.083 秒 | 17× |
| 中文 | 0.490 秒 | 0.195 秒 | 2.5× |
| 英语 | 0.908 秒 | 0.081 秒 | 11× |

模型加载约 0.4 秒，按需加载并缓存，只在首次用到该语言时付一次。
加载后纯合成 0.054-0.136 秒，实时率约 0.04。

离线还顺带解决两件事：不再依赖微软消费级端点（无 DPA，合规审计里标为面向公众前
必须更换），以及断网时语音仍可用。

**未默认启用的原因**：音质需要人工判断。EdgeTTS 的神经音色更自然，Piper medium
偏合成感。对照样本在 `/tmp/voicecmp/`（edge-*.mp3 与 piper-*.wav 是同一句话）。
云端双向流式 TTS 已否决：音色库里没有德语。

## 首包优化：EdgeTTS 流式转码 + 首句本地合成（2026-10-02）

两项都是 `TTS.EdgeTTS` 下的键，由 `launchers/start_server.py` 注入（模型路径按 SERVER_DIR 拼成绝对路径），
服务端重启生效。要关闭或换模型改那边，不要在 `.config.yaml` 里再写一份。provider 认的键：

```yaml
TTS:
  EdgeTTS:
    edge_stream_decode: true          # provider 默认开。mp3 分块一到就解码、编 Opus、推播放队列
    first_sentence_local: true        # provider 默认关，覆盖层打开。回答第一句用本机 sherpa-onnx 合成
    first_sentence_models:
      zh: models/tts/matcha-icefall-zh-baker        # Matcha：目录里有 model-steps-*.onnx 即按 Matcha 加载
      de: models/tts/vits-piper-de_DE-thorsten-high
      en: models/tts/vits-piper-en_US-lessac-high
    first_sentence_vocoder: models/tts/vocos-22khz-univ.onnx   # Matcha 的声码器，Piper 不需要
    # first_sentence_threads: 4       # 默认按性能核数
    # first_sentence_lazy: true       # 默认启动时后台预加载三个模型（约 2 秒），设 true 改为首次用到才加载
```

为什么：顾客盯着哑巴机器的时间由第一句决定。EdgeTTS 一句短首句要等 0.3-2.2 秒才有第一块
音频（看微软端点当时状态），而且原来的代码要整句下载完、解码完才开始编 Opus。
实现见 `core/providers/tts/edge.py` 的 `stream_segment` / `_stream_edge` / `_speak_first_locally`，
基类钩子在 `core/providers/tts/base.py` 的 `to_tts_stream`，本地引擎在 `core/providers/tts/local_first_sentence.py`。

同一句话，到第一个 Opus 帧的秒数（本机，三次交替实测，EdgeTTS 的波动来自网络）：

| 句子 | 整段路径（原来） | 流式路径 | 首句本地 |
|---|---|---|---|
| 现在有两种可买。 | 0.81 / 0.63 / 0.70 | 0.86 / 0.50 / 0.32 | 0.11 / 0.13 / 0.14（Matcha） |
| Es gibt zwei Gerichte. | 2.23 / 0.76 / 0.59 | 1.62 / 0.55 / 0.34 | 0.32 / 0.29 / 0.32（Piper high） |
| Two items are available. | 1.68 / 1.41 / 0.79 | 0.46 / 0.33 / 0.43 | 0.33 / 0.34 / 0.31（Piper high） |

规则与限制：
- 流式路径的静音裁剪与原来的 `trim_silence` 等价：开头静音在第一帧前跳过，尾部静音不发；
  句中停顿后面若还有语音，会在下一次解码时补发，不会把停顿吃掉。
- 缓存命中、`split_languages` 切成多段的句子仍走整段路径（多段要等最慢的一段，没有流式可言）。
- 首句本地只接管本轮回答的第一段（`first_segment_pending`），第二段起仍是 EdgeTTS；
  首句音色因此和后面略有不同。首句规则是「不含菜名」，所以首句基本是单语言短句，
  正是本地模型最拿手的。本地引擎失败（模型缺失、异常）自动退回 EdgeTTS。
- thorsten-high / lessac-high 比 medium 慢（0.3 s vs 0.08 s）但发音更好；嫌慢可换 medium 目录。
- 三个模型常驻约 350 MB 内存；这台 8 GB 机器已在重度换页，若发现服务进程被换出，
  改 `first_sentence_lazy: true` 或只保留顾客最多的语言。
- Matcha 加载时打印若干 `Unknown token: shei2`，是词典里缺「谁」的多音读法，无害。
