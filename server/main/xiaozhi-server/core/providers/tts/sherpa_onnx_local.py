# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""本地离线 TTS，基于 sherpa-onnx 的 Piper(VITS) 模型。

为什么做这个：EdgeTTS 要整句合成完才返回，德语首包实测 1.415 秒，而德语是门店
顾客的主要语言。sherpa-onnx 已经在本环境跑 ASR，它的 OfflineTts 支持流式回调，
同一句德语首包 0.083 秒，快 17 倍，且完全离线。

实测（本机 8 核，num_threads=4）：
    语言    EdgeTTS首包   Piper首包   实时率
    德语      1.415s      0.083s     0.04
    中文      0.490s      0.195s     0.04
    英语      0.908s      0.081s     0.03

离线还顺带解决了两件事：不再依赖微软的消费级端点（无 DPA，合规审计里被标为
面向公众前必须更换），以及断网时语音仍然可用。

模型不随仓库分发，需另行下载到 models/ 下，见 CONFIG_NOTES.md。
"""
import os

from core.providers.tts.base import TTSProviderBase
from core.providers.tts.local_first_sentence import build_vits_tts, samples_to_pcm16
from core.utils.tts_lang_split import guess_language
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.audio_file_type = "wav"
        self.num_threads = int(config.get("num_threads") or 4)
        self.speed = float(config.get("speed") or 1.0)
        # 每种语言一个模型目录。德语顾客占多数，所以默认语言是德语。
        self.models = config.get("models") or {}
        self.default_lang = config.get("default_language") or "de"
        self._engines = {}

    def generate_filename(self, extension=".wav"):
        return os.path.join(
            self.output_file,
            f"tts-{__import__('uuid').uuid4()}{extension}",
        )

    def pick_language(self, text):
        """按这一句的语言挑模型。和 EdgeTTS 选音色用同一个判断函数。"""
        lang = guess_language(text, self.default_lang)
        return lang if lang in self.models else self.default_lang

    def _engine(self, lang):
        """按需加载并缓存模型。加载约 0.4 秒，只在首次用到该语言时付一次。"""
        if lang in self._engines:
            return self._engines[lang]
        model_dir = self.models.get(lang)
        if not model_dir or not os.path.isdir(model_dir):
            raise FileNotFoundError(f"TTS 模型目录不存在: {lang} -> {model_dir}")
        engine = build_vits_tts(model_dir, self.num_threads)
        self._engines[lang] = engine
        logger.bind(tag=TAG).info(f"本地 TTS 模型已加载: {lang} <- {model_dir}")
        return engine

    async def text_to_speak(self, text, output_file):
        lang = self.pick_language(text)
        engine = self._engine(lang)
        audio = engine.generate(text, sid=0, speed=self.speed)
        pcm = samples_to_pcm16(audio.samples)

        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.sample_rate)
            w.writeframes(pcm)
        data = buf.getvalue()

        if output_file:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "wb") as f:
                f.write(data)
            return
        return data
