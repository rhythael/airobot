# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""回答后的提示音，与识别前的高频补偿。"""

import sys
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

import numpy as np
from scipy.signal import freqz

from core.utils.audio_filters import highshelf_coeffs
from core.providers.tts.edge import TTSProvider


def _tts(cue=True, abort=False):
    p = TTSProvider({"voice": "de-DE-SeraphinaMultilingualNeural", "output_dir": "tmp/"}, True)
    p.conn = SimpleNamespace(config={"listen_cue": cue}, sample_rate=16000, client_abort=abort)
    p.opus_encoder = None  # 走临时编码器
    return p


def test_cue_is_short_opus_after_the_reply():
    p = _tts()
    p._play_listen_cue()
    frames = []
    while not p.tts_audio_queue.empty():
        frames.append(p.tts_audio_queue.get())
    # 0.12s 间隔 + 两个短音共约 0.31 秒，60ms 一帧
    assert 5 <= len(frames) <= 7
    assert all(isinstance(f[1], bytes) and f[1] for f in frames)


def test_cue_off_by_default_and_skipped_after_abort():
    for p in (_tts(cue=False), _tts(abort=True)):
        p._play_listen_cue()
        assert p.tts_audio_queue.empty()


def test_highshelf_boosts_consonant_band_only():
    b, a = highshelf_coeffs(6, 3500)
    w, h = freqz(b, a, worN=[500, 1000, 6000, 7500], fs=16000)
    gain = 20 * np.log10(np.abs(h))
    assert abs(gain[0]) < 0.5 and abs(gain[1]) < 1.0  # 元音区基本不动
    assert 5.0 < gain[2] < 6.5 and 5.0 < gain[3] < 6.5  # 辅音区约 +6dB


def test_highshelf_off_when_zero():
    assert highshelf_coeffs(0, 3500) is None
