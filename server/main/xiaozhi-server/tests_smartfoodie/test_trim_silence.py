# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""合成音频首尾静音裁剪。EdgeTTS 给短句补了一秒多的尾部静音，逐句拼接时句间断档。"""

import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

from pydub import AudioSegment
from pydub.generators import Sine

from core.utils.util import trim_silence


def _clip(lead_ms, speech_ms, tail_ms):
    tone = Sine(440).to_audio_segment(duration=speech_ms).apply_gain(-10)
    return (AudioSegment.silent(duration=lead_ms, frame_rate=16000)
            + tone.set_frame_rate(16000)
            + AudioSegment.silent(duration=tail_ms, frame_rate=16000))


def test_edge_like_padding_is_trimmed():
    # 形状照「gerne」的实测：开头 210ms、发音 440ms、尾部 1210ms
    out = trim_silence(_clip(210, 440, 1210))
    assert 440 <= len(out) <= 440 + 30 + 100 + 20


def test_keeps_a_little_head_and_tail():
    out = trim_silence(_clip(300, 500, 500))
    assert len(out) >= 500 + 30 + 100 - 20


def test_clip_without_padding_is_unchanged():
    clip = _clip(0, 800, 0)
    assert abs(len(trim_silence(clip)) - len(clip)) <= 10


def test_all_silence_is_left_alone():
    silent = AudioSegment.silent(duration=600, frame_rate=16000)
    assert len(trim_silence(silent)) == 600


def test_empty_audio():
    assert len(trim_silence(AudioSegment.empty())) == 0
