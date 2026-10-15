# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""回答的第一句用本机 sherpa-onnx 合成，后面的句子仍交给 EdgeTTS。

为什么只做首句：顾客盯着哑巴机器的时间由第一句决定。EdgeTTS 一句短首句的首块
要等 0.4-1.8 秒（看微软端点当时的状态），而本机 Matcha / Piper 合成同一句只要
0.06-0.1 秒。后面的句子在第一句播放期间就能合成完，用不用网络都来得及，
所以仍用音质更好的 EdgeTTS。代价是首句音色和后面略有不同。

模型按语言各一个目录，首次用到才加载（Matcha 约 0.9 秒、Piper 约 0.4 秒）；
preload() 在后台线程把三种语言都提前加载好，第一位顾客不用付这笔时间。
中文目录里有 model-steps-*.onnx 的按 Matcha 处理（需要 vocos 声码器），
其余按 Piper(VITS) 处理，和 sherpa_onnx_local.py 共用同一个构建函数。

首句该不该走本地、怎么退回 EdgeTTS，由 TTSProviderBase.speak_segment 决定，
任何 provider 都能用；这里只负责模型加载和合成。
"""
import glob
import os
import threading
import time

import numpy as np

from config.logger import setup_logging
# 语言判断已合并到 tts_lang_split；这里保留名字，老的导入路径不用改。
from core.utils.tts_lang_split import guess_language  # noqa: F401

TAG = __name__
logger = setup_logging()


def build_vits_tts(model_dir, num_threads):
    """按 Piper(VITS) 目录建 sherpa-onnx OfflineTts。SherpaLocalTTS 和首句引擎共用。"""
    import sherpa_onnx

    onnx = sorted(glob.glob(os.path.join(model_dir, "*.onnx")))
    if not onnx:
        raise FileNotFoundError(f"TTS 模型目录里没有 .onnx: {model_dir}")
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=onnx[0],
                tokens=os.path.join(model_dir, "tokens.txt"),
                data_dir=os.path.join(model_dir, "espeak-ng-data"),
            ),
            num_threads=num_threads,
            provider="cpu",
        )
    )
    return sherpa_onnx.OfflineTts(config)


def build_matcha_tts(model_dir, acoustic_model, vocoder, num_threads):
    """按 Matcha 目录建引擎。中文 Matcha 带数字/日期/多音字规则：不挂上 fst，
    「2-5」「两份」会念错。"""
    import sherpa_onnx

    if not vocoder or not os.path.isfile(vocoder):
        raise FileNotFoundError(f"Matcha 需要声码器 first_sentence_vocoder: {vocoder}")
    fsts = [p for p in (os.path.join(model_dir, f) for f in ("phone.fst", "date.fst", "number.fst"))
            if os.path.isfile(p)]
    model = sherpa_onnx.OfflineTtsModelConfig(
        matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
            acoustic_model=acoustic_model,
            vocoder=vocoder,
            lexicon=os.path.join(model_dir, "lexicon.txt"),
            tokens=os.path.join(model_dir, "tokens.txt"),
            dict_dir=os.path.join(model_dir, "dict"),
        ),
        num_threads=num_threads,
        provider="cpu",
    )
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=model, rule_fsts=",".join(fsts)))


def samples_to_pcm16(samples):
    """sherpa 输出的 float32 [-1, 1] → 16bit 单声道 PCM bytes。"""
    arr = np.asarray(samples, dtype=np.float32)
    return (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_engine(models, vocoder=None, num_threads=None, speed=1.0):
    """同一份配置全进程只建一个引擎。TTS provider 是每个连接新建一个的
    （connection.py 的 _initialize_tts），模型不能跟着每个连接重新加载：
    三个模型约 350 MB、2 秒，第二位顾客连上来就会重复付一次。"""
    key = (tuple(sorted((models or {}).items())), vocoder, num_threads, float(speed or 1.0))
    with _SHARED_LOCK:
        engine = _SHARED.get(key)
        if engine is None:
            engine = LocalFirstSentenceEngine(models, vocoder=vocoder, num_threads=num_threads, speed=speed)
            _SHARED[key] = engine
        return engine


class LocalFirstSentenceEngine:
    def __init__(self, models, vocoder=None, num_threads=None, speed=1.0):
        # {lang: model_dir}
        self.models = {k: v for k, v in (models or {}).items() if v}
        self.vocoder = vocoder
        self.num_threads = int(num_threads or _performance_cores())
        self.speed = float(speed or 1.0)
        self._engines = {}
        # 每种语言一把加载锁：预加载线程正在装 de/en 时，第一位中文顾客不该等它
        # 装完（Matcha 0.9 秒 + Piper 0.4 秒×2）才能用早已装好的 zh。
        self._load_locks = {lang: threading.Lock() for lang in self.models}
        self._gen_lock = threading.Lock()
        self._preload_started = False
        # 加载过但失败的语言（缺 tokens / 缺声码器）。不记下来的话每一轮首句都会
        # 重新 glob + 抛 FileNotFoundError 再退回 EdgeTTS，日志一行 warning 一轮
        self._failed = set()

    def supports(self, lang):
        model_dir = self.models.get(lang)
        return bool(model_dir) and lang not in self._failed and os.path.isdir(model_dir)

    def preload(self):
        """后台把所有配置的语言都加载好。失败只记日志：首句会退回 EdgeTTS，不影响服务。"""
        if self._preload_started:
            return
        self._preload_started = True

        def _load_all():
            for lang in list(self.models):
                try:
                    self._engine(lang)
                except Exception as e:
                    logger.bind(tag=TAG).warning(f"首句本地 TTS 预加载失败 {lang}: {e}")
        threading.Thread(target=_load_all, name="tts-first-sentence-preload", daemon=True).start()

    def _engine(self, lang):
        # 无锁快路径：dict 读在 GIL 下是原子的，已加载的语言不必排队
        engine = self._engines.get(lang)
        if engine is not None:
            return engine
        if not self.supports(lang):
            raise FileNotFoundError(f"首句 TTS 模型目录不存在: {lang} -> {self.models.get(lang)}")
        with self._load_locks[lang]:
            engine = self._engines.get(lang)
            if engine is not None:
                return engine
            model_dir = self.models[lang]
            started = time.perf_counter()
            matcha = sorted(glob.glob(os.path.join(model_dir, "model-steps-*.onnx")))
            try:
                if matcha:
                    engine = build_matcha_tts(model_dir, matcha[0], self.vocoder, self.num_threads)
                else:
                    engine = build_vits_tts(model_dir, self.num_threads)
            except Exception:
                self._failed.add(lang)
                raise
            self._engines[lang] = engine
            logger.bind(tag=TAG).info(
                f"首句本地 TTS 模型已加载: {lang} <- {model_dir}（{time.perf_counter() - started:.2f}s）")
            return engine

    def synthesize(self, text, lang):
        """返回 (16bit 单声道 PCM bytes, 采样率)。"""
        engine = self._engine(lang)
        # sherpa 的 OfflineTts 没有承诺并发 generate 安全；两台设备同时开口时串行化，
        # 一句只要 0.1-0.3 秒，排队代价远小于崩一次
        with self._gen_lock:
            audio = engine.generate(text, sid=0, speed=self.speed)
        return samples_to_pcm16(audio.samples), int(audio.sample_rate)


def _performance_cores():
    """推理线程数按性能核数来：能效核拖慢 onnxruntime 的并行算子（见 f672a52）。
    和 asr/sherpa_onnx_local.py 的同名逻辑故意不同：那边取逻辑核、上限 8，是给
    一个常驻的大模型用的；TTS 首句引擎按需短跑，取物理核、上限 4 就够，再多线程
    只会和 ASR 抢核。"""
    try:
        import subprocess
        out = subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
        if out.isdigit() and int(out) > 0:
            return int(out)
    except Exception:
        pass
    return max(1, min(4, os.cpu_count() or 1))
