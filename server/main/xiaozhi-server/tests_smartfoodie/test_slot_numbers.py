# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""识别结果里的货道号规范化。正例取自 2026-09-23 的识别输出，反例是不能误改的常见说法。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.utils.slot_numbers import normalize_slot_numbers as n


def test_chinese_slots():
    assert n("17货道是什么") == "1-7货道是什么"
    assert n("1号7货道有什么") == "1-7货道有什么"
    assert n("一号七货道是什么") == "1-7货道是什么"
    assert n("一号期货到是什么") == "1-7货道是什么"   # SenseVoice 实际输出
    assert n("在2-6号货道") == "在2-6号货道"
    assert n("1-7货到") == "1-7货道"
    # 2026-10-05 音频复测：「一号七货道」识别成「一号期火道」，模型据此猜成了 1-6
    assert n("一号期火道是什么？") == "1-7货道是什么？"
    assert n("一号七火道是什么") == "1-7货道是什么"
    assert n("二号六获到有什么") == "2-6货道有什么"


def test_german_and_english_slots():
    assert n("Was liegt im Fach 2/6?") == "Was liegt im Fach 2-6?"   # Whisper 实际输出
    assert n("Fach 1.7 bitte") == "Fach 1-7 bitte"
    assert n("What is in slot 17?") == "What is in slot 1-7?"
    assert n("slot number 2 6") == "slot number 2-6"
    assert n("Fach Nr. 13") == "Fach Nr. 1-3"


def test_german_and_english_number_words():
    # 识别模型把货道号念成数词时常原样写出来；以前只有模板直答自己补这一刀，ASR 层看不到
    assert n("Was liegt im Fach zwei sechs?") == "Was liegt im Fach 2-6?"
    assert n("What is in slot one seven?") == "What is in slot 1-7?"
    assert n("Fach fuenf-sieben") == "Fach 5-7"
    assert n("slot Three Nine") == "slot 3-9"
    for text in ("zwei Gerichte sind da", "Es gibt zwei sechs Euro", "one seven"):   # 没有货道关键词
        assert n(text) == text, text


def test_things_that_must_not_change():
    for text in (
        "12 Fächer sind leer",          # 数字在关键词前面，是数量
        "现在有14个空货道",
        "有过期货吗",                    # 「过期货」不是「七货道」
        "过期火腿还有吗",                  # 前面不是数字，「期火」不是「七货」
        "有没有防火道具",
        "鱼香茄子盖饭7.99欧元",
        "Das kostet 17 Euro.",
        "Fach 10",                       # 没有第 0 格
        "slot 1.50",
        "041号机器现在有9个空货道",
        "What is in 17?",               # 没有关键词，交给大模型
    ):
        assert n(text) == text, text


def test_non_text_passthrough():
    assert n("") == ""
    assert n(None) is None
