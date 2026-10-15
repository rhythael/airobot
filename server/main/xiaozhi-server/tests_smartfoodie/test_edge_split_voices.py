# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""EdgeTTS 句内分语言合成：每段用对应音色、并发合成、裁静音后拼接。不联网。"""

import asyncio
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

from pydub import AudioSegment
from pydub.generators import Sine

from core.providers.tts.edge import TTSProvider

VOICES = {"zh": "zh-voice", "de": "de-voice", "en": "en-voice"}


def _mp3(speech_ms, tail_ms=1200):
    """模仿 EdgeTTS：一段发音后面跟一秒多静音。"""
    tone = Sine(440).to_audio_segment(duration=speech_ms).apply_gain(-10).set_frame_rate(24000)
    clip = tone + AudioSegment.silent(duration=tail_ms, frame_rate=24000)
    buf = BytesIO()
    clip.set_channels(1).export(buf, format="mp3")
    return buf.getvalue()


class EdgeSplitTests(unittest.TestCase):
    def _provider(self, split=True):
        return TTSProvider({"voice": "de-voice", "voices": VOICES, "split_languages": split,
                            "output_dir": "tmp/"}, True)

    def _run(self, provider, text):
        calls = []

        async def fake(part, output_file, voice=None):
            calls.append((voice, part))
            return _mp3(500)

        with patch.object(provider, "_synthesize", side_effect=fake):
            data = asyncio.run(provider.text_to_speak(text, None))
        return calls, data

    def test_mixed_sentence_uses_one_voice_per_language(self):
        calls, data = self._run(self._provider(),
                                "Es gibt noch 牛肉炒面 und Dampfnudel mit Vanillesauce und Kirschen.")
        self.assertEqual([v for v, _ in calls], ["de-voice", "zh-voice", "de-voice"])
        self.assertEqual(calls[1][1], "牛肉炒面")
        self.assertEqual(data[:4], b"RIFF")

    def test_padding_between_pieces_is_trimmed(self):
        _, data = self._run(self._provider(), "Es gibt noch 牛肉炒面 und Dampfnudel mit Vanillesauce.")
        audio = AudioSegment.from_file(BytesIO(data), format="wav")
        # 三段各 0.5 秒发音，每段原本还拖 1.2 秒静音。不裁的话超过 5 秒
        self.assertLess(len(audio), 2000)

    def test_trailing_commas_are_stripped_for_cache_hits(self):
        calls, _ = self._run(self._provider(), "有鸡肉蔬菜蒸饺、Tagliatelle mit Kalbsgeschnetzeltem in Champignon-Rahmsauce、虾饺")
        self.assertEqual(calls[0][1], "有鸡肉蔬菜蒸饺")
        self.assertEqual(calls[1][1], "Tagliatelle mit Kalbsgeschnetzeltem in Champignon-Rahmsauce")

    def test_single_language_sentence_is_one_call(self):
        calls, data = self._run(self._provider(), "现在有三种吃的，分别是饺子和面。")
        self.assertEqual(calls, [("zh-voice", "现在有三种吃的，分别是饺子和面。")])
        self.assertNotEqual(data[:4], b"RIFF")  # 单段原样返回 mp3，不多一次转码

    def test_switch_off_keeps_old_behaviour(self):
        calls, _ = self._run(self._provider(split=False), "Es gibt noch 牛肉炒面 und Dampfnudel.")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][0])  # 走原来的 pick_voice

    def test_unrecognised_latin_follows_previous_sentence(self):
        provider = self._provider()
        self._run(provider, "There are twelve products available right now.")
        calls, _ = self._run(provider, "Shrimp")
        self.assertEqual(calls[0][0], "en-voice")


if __name__ == "__main__":
    unittest.main()
