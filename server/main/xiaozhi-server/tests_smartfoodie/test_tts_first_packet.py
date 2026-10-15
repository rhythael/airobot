# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""首包优化：EdgeTTS 边收边转 Opus，以及回答首句改用本地引擎。

守着三件事：
- 流式路径发出的音频和整段路径等价（帧数、时长一致，首尾静音同样被裁掉）；
- 只有本轮第一段走本地引擎，第二段仍走 EdgeTTS；两个开关关掉时行为等于现状；
- 缓存命中、分语言拼接这两种情况流式钩子让路（返回 False）。
"""
import asyncio
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydub import AudioSegment
from pydub.generators import Sine

from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType
from core.providers.tts.edge import TTSProvider, _SHORT_AUDIO_CACHE
from core.utils import opus_encoder_utils
from core.utils.util import audio_bytes_to_data_stream, opus_datas_to_wav_bytes

SR = 16000


def _mp3(lead_ms, speech_ms, tail_ms):
    tone = Sine(440).to_audio_segment(duration=speech_ms).apply_gain(-10)
    clip = (AudioSegment.silent(duration=lead_ms, frame_rate=24000)
            + tone.set_frame_rate(24000)
            + AudioSegment.silent(duration=tail_ms, frame_rate=24000))
    buf = BytesIO()
    clip.set_channels(1).export(buf, format="mp3", bitrate="48k")
    return buf.getvalue()


def _chunks(data, size=720):
    return [data[i:i + size] for i in range(0, len(data), size)]


def _provider(**extra):
    config = {"voice": "test-voice", "cache_short_audio": False}
    config.update(extra)
    provider = TTSProvider(config, True)
    provider.conn = SimpleNamespace(sample_rate=SR)
    provider.opus_encoder = opus_encoder_utils.OpusEncoderUtils(sample_rate=SR, channels=1, frame_size_ms=60)
    provider.current_sentence_id = "sid"
    return provider


def _patch_edge(mp3_bytes):
    async def stream():
        yield {"type": "WordBoundary", "text": "ignored"}
        for piece in _chunks(mp3_bytes):
            yield {"type": "audio", "data": piece}
    communicate = Mock()
    communicate.return_value.stream = stream
    return patch("core.providers.tts.edge.edge_tts.Communicate", communicate), communicate


def _duration_ms(frames):
    wav = opus_datas_to_wav_bytes(frames, sample_rate=SR)
    return len(AudioSegment.from_file(BytesIO(wav), format="wav"))


class StreamDecodeTests(unittest.TestCase):
    def setUp(self):
        _SHORT_AUDIO_CACHE.clear()
        self.addCleanup(_SHORT_AUDIO_CACHE.clear)

    def test_streamed_audio_matches_whole_clip_path(self):
        mp3 = _mp3(200, 900, 1200)
        provider = _provider()
        patcher, communicate = _patch_edge(mp3)
        streamed = []
        with patcher:
            handled = provider.stream_segment("Es gibt zwei Gerichte.", "Es gibt zwei Gerichte.", streamed.append)
        self.assertTrue(handled)
        self.assertEqual(communicate.call_count, 1)
        # FIRST 标记先于任何帧进入播放队列
        kind, _, text, sid = provider.tts_audio_queue.get_nowait()
        self.assertEqual((kind, text, sid), (SentenceType.FIRST, "Es gibt zwei Gerichte.", "sid"))

        whole = []
        encoder = opus_encoder_utils.OpusEncoderUtils(sample_rate=SR, channels=1, frame_size_ms=60)
        audio_bytes_to_data_stream(mp3, "mp3", True, whole.append, SR, encoder)
        self.assertAlmostEqual(len(streamed), len(whole), delta=1)
        self.assertAlmostEqual(_duration_ms(streamed), _duration_ms(whole), delta=70)

    def test_head_and_tail_silence_are_not_sent(self):
        provider = _provider()
        patcher, _ = _patch_edge(_mp3(250, 600, 1300))
        frames = []
        with patcher:
            provider.stream_segment("hello there", "hello there", frames.append)
        # 发音 600ms + 头 30ms + 尾 100ms，再加最后一帧补零，不应带上 1.3 秒尾部静音
        self.assertLess(_duration_ms(frames), 600 + 30 + 100 + 120)
        self.assertGreater(_duration_ms(frames), 600)

    def test_short_clip_is_cached_after_streaming(self):
        provider = _provider(cache_short_audio=True)
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            provider.stream_segment("12 items", "12 items", lambda f: None)
            self.assertEqual(len(_SHORT_AUDIO_CACHE), 1)
            # 第二次命中缓存：流式钩子让路，基类走整段路径
            self.assertFalse(provider.stream_segment("12 items", "12 items", lambda f: None))
        self.assertEqual(communicate.call_count, 1)

    def test_switch_off_restores_whole_clip_path(self):
        provider = _provider(edge_stream_decode=False)
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            self.assertFalse(provider.stream_segment("hello", "hello", lambda f: None))
        self.assertEqual(communicate.call_count, 0)

    def test_split_languages_keeps_whole_clip_path(self):
        provider = _provider(split_languages=True, voices={"zh": "zh-v", "de": "de-v", "en": "en-v"})
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            self.assertFalse(provider.stream_segment("Es gibt 素炒面 im Fach 2-5.", "x", lambda f: None))
        self.assertEqual(communicate.call_count, 0)

    def test_failure_before_first_frame_falls_back(self):
        provider = _provider()
        async def broken():
            raise RuntimeError("edge down")
            yield  # pragma: no cover
        communicate = Mock()
        communicate.return_value.stream = broken
        with patch("core.providers.tts.edge.edge_tts.Communicate", communicate):
            self.assertFalse(provider.stream_segment("hello", "hello", lambda f: None))
        self.assertTrue(provider.tts_audio_queue.empty())


class FakeEngine:
    def __init__(self):
        self.calls = []

    def supports(self, lang):
        return lang in ("zh", "de", "en")

    def synthesize(self, text, lang):
        self.calls.append((text, lang))
        tone = Sine(330).to_audio_segment(duration=500).apply_gain(-10).set_frame_rate(22050).set_channels(1)
        return tone.raw_data, 22050


class FirstSentenceLocalTests(unittest.TestCase):
    def setUp(self):
        _SHORT_AUDIO_CACHE.clear()
        self.addCleanup(_SHORT_AUDIO_CACHE.clear)

    def test_first_segment_uses_local_engine_and_second_uses_edge(self):
        provider = _provider()
        provider.first_sentence_engine = FakeEngine()
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        first, second = [], []
        with patcher:
            self.assertTrue(provider.speak_segment("现在有两种可买。", "现在有两种可买。", first.append, True))
            self.assertTrue(provider.speak_segment("素炒面在2-5货道。", "素炒面在2-5货道。", second.append, False))
        self.assertEqual(provider.first_sentence_engine.calls, [("现在有两种可买。", "zh")])
        self.assertEqual(communicate.call_count, 1)
        self.assertGreater(len(first), 0)
        self.assertGreater(_duration_ms(first), 450)  # 22050 → 16000 重采样后时长不变
        kind, _, text, _ = provider.tts_audio_queue.get_nowait()
        self.assertEqual((kind, text), (SentenceType.FIRST, "现在有两种可买。"))

    def test_language_without_local_model_goes_to_edge(self):
        provider = _provider()
        engine = FakeEngine()
        engine.supports = lambda lang: lang == "de"
        provider.first_sentence_engine = engine
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            self.assertTrue(provider.speak_segment("Two items available.", "Two items available.", lambda f: None, True))
        self.assertEqual(engine.calls, [])
        self.assertEqual(communicate.call_count, 1)

    def test_mixed_script_first_sentence_goes_to_edge(self):
        # 实机日志：「You can eat素炒面 in slot 2-5 or …」被判成中文、用 Matcha 念英文。
        # 含汉字又含拉丁词的首句不能交给单语本地引擎。
        provider = _provider()
        engine = FakeEngine()
        provider.first_sentence_engine = engine
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            self.assertTrue(provider.speak_segment(
                "You can eat素炒面 in slot 2-5.", "You can eat素炒面 in slot 2-5.", lambda f: None, True))
            self.assertTrue(provider.speak_segment(
                "Fach 2-5 素炒面, Fach 2-7 Nudeln.", "Fach 2-5 素炒面, Fach 2-7 Nudeln.", lambda f: None, True))
        self.assertEqual(engine.calls, [])
        self.assertEqual(communicate.call_count, 2)
        # 纯中文句里出现货道号、单个字母缩写不算混合，仍走本地
        with patcher:
            provider.speak_segment("现在有两种可买，2-5货道。", "现在有两种可买，2-5货道。", lambda f: None, True)
        self.assertEqual(engine.calls, [("现在有两种可买，2-5货道。", "zh")])

    def test_local_engine_error_falls_back_to_edge(self):
        provider = _provider()
        engine = FakeEngine()
        engine.synthesize = Mock(side_effect=RuntimeError("model missing"))
        provider.first_sentence_engine = engine
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            self.assertTrue(provider.speak_segment("Es gibt zwei.", "Es gibt zwei.", lambda f: None, True))
        self.assertEqual(communicate.call_count, 1)

    def test_switch_off_never_touches_local_engine(self):
        provider = _provider()  # first_sentence_local 默认关
        self.assertIsNone(provider.first_sentence_engine)
        patcher, communicate = _patch_edge(_mp3(100, 400, 300))
        with patcher:
            provider.speak_segment("Es gibt zwei.", "Es gibt zwei.", lambda f: None, True)
        self.assertEqual(communicate.call_count, 1)


class _Recorder(TTSProviderBase):
    """只记录基类传进来的 is_first_segment，不做任何合成。"""

    def __init__(self):
        super().__init__({"output_dir": "tmp/"}, True)
        self.seen = []
        self.conn = SimpleNamespace(sample_rate=SR)

    async def text_to_speak(self, text, output_file):
        return b""

    def speak_segment(self, text, original_text, opus_handler, is_first_segment):
        self.seen.append((text, is_first_segment))
        return True


class BaseFirstSegmentFlagTests(unittest.TestCase):
    """首段判据来自合成线程切段前的 is_first_sentence，不再有单独的实例标志。"""

    def _feed(self, provider, text):
        provider.tts_text_buff.append(text)
        provider._speak_pending_segment(opus_handler=lambda f: None)

    def test_only_first_cut_of_a_turn_is_marked_first(self):
        provider = _Recorder()
        provider.tts_text_buff, provider.processed_chars, provider.is_first_sentence = [], 0, True
        self._feed(provider, "第一句话够长了。")
        self._feed(provider, "第二句话也够长。")
        self.assertEqual(provider.seen, [("第一句话够长了", True), ("第二句话也够长", False)])
        # 新一轮回答（FIRST 消息）重置后重新标记
        provider.tts_text_buff, provider.processed_chars, provider.is_first_sentence = [], 0, True
        self._feed(provider, "第三句话也够长。")
        self.assertEqual(provider.seen[-1], ("第三句话也够长", True))

    def test_unpunctuated_answer_flushed_at_end_is_first(self):
        provider = _Recorder()
        provider.tts_text_buff, provider.processed_chars, provider.is_first_sentence = [], 0, True
        self._feed(provider, "你好")  # 没有标点，切不出段
        self.assertEqual(provider.seen, [])
        provider._process_remaining_text_stream(opus_handler=lambda f: None)
        self.assertEqual(provider.seen, [("你好", True)])

    def test_long_segment_split_marks_only_the_first_piece(self):
        provider = _Recorder()
        provider.tts_max_segment_chars = 8
        provider.to_tts_stream("第一句很长，第二句也长，第三句。", opus_handler=lambda f: None, is_first_segment=True)
        flags = [f for _, f in provider.seen]
        self.assertEqual(flags[0], True)
        self.assertTrue(all(f is False for f in flags[1:]))
        self.assertGreater(len(flags), 1)


if __name__ == "__main__":
    unittest.main()
