# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Short audio reuse must follow text and speech settings, not inventory state."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.providers.tts.edge import TTSProvider, _SHORT_AUDIO_CACHE


class EdgeCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _SHORT_AUDIO_CACHE.clear()
        self.provider = TTSProvider({"voice": "test-voice", "cache_short_audio": True}, True)
        self.audio = b"mp3-audio"
        async def stream():
            yield {"type": "WordBoundary", "text": "ignored"}
            yield {"type": "audio", "data": self.audio}
        self.communicate = Mock()
        self.communicate.return_value.stream = stream
        self.patcher = patch("core.providers.tts.edge.edge_tts.Communicate", self.communicate)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(_SHORT_AUDIO_CACHE.clear)

    async def test_same_short_sentence_reuses_audio(self):
        first = await self.provider.text_to_speak("12 items", None)
        second = await self.provider.text_to_speak("12 items", None)
        self.assertEqual(first, second)
        self.assertEqual(self.communicate.call_count, 1)

    async def test_inventory_text_change_requires_new_audio(self):
        await self.provider.text_to_speak("12 items", None)
        await self.provider.text_to_speak("11 items", None)
        self.assertEqual(self.communicate.call_count, 2)

    async def test_voice_and_rate_changes_require_new_audio(self):
        await self.provider.text_to_speak("12 items", None)
        self.provider.voice = "other-voice"
        await self.provider.text_to_speak("12 items", None)
        self.provider.edge_rate = "+20%"
        await self.provider.text_to_speak("12 items", None)
        self.assertEqual(self.communicate.call_count, 3)

    async def test_cached_audio_can_be_written_to_a_new_output_file(self):
        await self.provider.text_to_speak("12 items", None)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "clip.mp3"
            await self.provider.text_to_speak("12 items", str(output))
            self.assertEqual(output.read_bytes(), self.audio)
        self.assertEqual(self.communicate.call_count, 1)

    async def test_disabled_cache_preserves_network_calls(self):
        self.provider.cache_short_audio = False
        await self.provider.text_to_speak("12 items", None)
        await self.provider.text_to_speak("12 items", None)
        self.assertEqual(self.communicate.call_count, 2)

    async def test_large_audio_is_not_cached(self):
        self.audio = b"x" * (65 * 1024)
        await self.provider.text_to_speak("12 items", None)
        await self.provider.text_to_speak("12 items", None)
        self.assertEqual(self.communicate.call_count, 2)

    async def test_failed_synthesis_is_not_cached(self):
        self.communicate.side_effect = RuntimeError("unavailable")
        with self.assertRaises(Exception):
            await self.provider.text_to_speak("12 items", None)
        self.communicate.side_effect = None
        self.assertEqual(await self.provider.text_to_speak("12 items", None), self.audio)
        self.assertEqual(self.communicate.call_count, 2)

    async def test_stalled_stream_is_cancelled_without_caching_partial_audio(self):
        self.provider.tts_timeout = 0.03
        cancelled = asyncio.Event()
        async def stalled():
            try:
                yield {"type": "audio", "data": b"partial"}
                await asyncio.sleep(1)
            finally:
                cancelled.set()
        self.communicate.return_value.stream = stalled
        with self.assertRaises(Exception):
            await self.provider.text_to_speak("stalled", None)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(_SHORT_AUDIO_CACHE), 0)

    async def test_long_stream_text_is_split_without_losing_content(self):
        self.provider.tts_max_segment_chars = 60
        self.provider.conn = Mock(sample_rate=16000)
        self.provider.opus_encoder = Mock()
        text = "推荐你试试牛肉炒面，Wiesnschmaus Bowl mit Kartoffelsalat und Leberkäswürfeln，还有Dampfnudel mit Vanillesauce und Kirschen，剩下还有6种不同的餐食可以挑"
        captured = []
        async def record(part, output):
            captured.append(part)
            return b"audio"
        with patch.object(self.provider, "text_to_speak", side_effect=record), patch("core.providers.tts.base.audio_bytes_to_data_stream"):
            await asyncio.to_thread(self.provider.to_tts_stream, text)
        self.assertEqual("".join(captured).replace(" ", ""), text.replace(" ", ""))
        self.assertTrue(all(len(part) <= 60 for part in captured))
        self.assertGreater(len(captured), 1)

    async def test_failed_stream_stops_at_configured_attempt_limit(self):
        self.provider.tts_max_attempts = 2
        self.communicate.side_effect = RuntimeError("service unavailable")
        await asyncio.to_thread(self.provider.to_tts_stream, "retry bounded")
        self.assertEqual(self.communicate.call_count, 2)
        self.assertEqual(len(_SHORT_AUDIO_CACHE), 0)

    async def test_cache_has_a_capacity_limit(self):
        for index in range(129):
            await self.provider.text_to_speak(str(index), None)
        await self.provider.text_to_speak("0", None)
        self.assertEqual(self.communicate.call_count, 130)


if __name__ == "__main__":
    unittest.main()


class VoicePerLanguageTests(unittest.TestCase):
    """按语言选音色。德语音色念中文实测慢 20%，听感含糊。"""

    def _provider(self, with_voices=True):
        from core.providers.tts.edge import TTSProvider
        config = {'voice': 'de-DE-SeraphinaMultilingualNeural', 'output_dir': 'tmp/'}
        if with_voices:
            config['voices'] = {
                'zh': 'zh-CN-XiaoxiaoNeural',
                'de': 'de-DE-SeraphinaMultilingualNeural',
                'en': 'en-US-AvaMultilingualNeural',
            }
        return TTSProvider(config, True)

    def test_picks_voice_by_language(self):
        p = self._provider()
        self.assertEqual(p.pick_voice('现在有意大利细面'), 'zh-CN-XiaoxiaoNeural')
        self.assertEqual(p.pick_voice('Es gibt heute zwei Gerichte'),
                         'de-DE-SeraphinaMultilingualNeural')
        self.assertEqual(p.pick_voice('Two dishes are available now'),
                         'en-US-AvaMultilingualNeural')

    def test_mixed_text_follows_chinese(self):
        """菜名夹英文或货道号时仍按中文念，否则一句话中途换音色。"""
        p = self._provider()
        self.assertEqual(p.pick_voice('鸡肉蔬菜蒸饺(10粒）在 1-5 货道'), 'zh-CN-XiaoxiaoNeural')

    def test_without_voices_config_behaviour_unchanged(self):
        """不配 voices 时与现状完全一致，只用默认音色。"""
        p = self._provider(with_voices=False)
        for text in ('现在有什么吃的', 'What is available', 'Was gibt es'):
            self.assertEqual(p.pick_voice(text), 'de-DE-SeraphinaMultilingualNeural')

    def test_unrecognisable_text_falls_back(self):
        p = self._provider()
        self.assertEqual(p.pick_voice('1-5'), 'de-DE-SeraphinaMultilingualNeural')
        self.assertEqual(p.pick_voice(''), 'de-DE-SeraphinaMultilingualNeural')
