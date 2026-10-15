# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""识别前的音频滤波。单独成模块，不依赖任何模型库，测试可以直接导入。"""

import numpy as np


def highshelf_coeffs(gain_db, freq_hz, sample_rate=16000):
    """RBJ 高架滤波器系数 (b, a)。gain_db 为 0 时返回 None。"""
    if not gain_db:
        return None
    a_ = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * freq_hz / sample_rate
    alpha = np.sin(w0) / 2 * np.sqrt(2)
    c = np.cos(w0)
    sq = 2 * np.sqrt(a_) * alpha
    b = [a_ * ((a_ + 1) + (a_ - 1) * c + sq), -2 * a_ * ((a_ - 1) + (a_ + 1) * c),
         a_ * ((a_ + 1) + (a_ - 1) * c - sq)]
    a = [(a_ + 1) - (a_ - 1) * c + sq, 2 * ((a_ - 1) - (a_ + 1) * c), (a_ + 1) - (a_ - 1) * c - sq]
    return np.array(b) / a[0], np.array(a) / a[0]


def apply_filter(coeffs, samples):
    """coeffs 为 None 时原样返回。输出裁到 [-1, 1]。"""
    if coeffs is None:
        return samples
    from scipy.signal import lfilter

    b, a = coeffs
    return np.clip(lfilter(b, a, samples), -1.0, 1.0).astype(np.float32)
