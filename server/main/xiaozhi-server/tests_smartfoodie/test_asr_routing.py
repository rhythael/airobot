# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""SenseVoice + Whisper 路由。样例取自 2026-09-23 的实测输出。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.utils.asr_routing import choose, sensevoice_is_enough


def test_clear_chinese_skips_whisper():
    assert sensevoice_is_enough("现在有什么吃的。", "zh")
    assert sensevoice_is_enough("鸡肉蔬菜蒸饺还有吗？", "yue")


def test_short_chinese_asks_whisper():
    # 德语「Ja」被 SenseVoice 听成「呀」，实测发生过
    assert not sensevoice_is_enough("呀。", "zh")
    assert not sensevoice_is_enough("你好。", "zh")
    assert not sensevoice_is_enough("Hello.", "en")


def test_short_chinese_confirmed_by_whisper():
    assert choose("你好。", "zh", "Не волк!", "ru") == ("你好。", "zh", False)  # 实机：Whisper 把「你好」判成俄语
    assert choose("呀。", "zh", "Ja.", "de") == ("Ja.", "de", False)


def test_german_uses_whisper():
    assert choose("Fiagarriss and Carradofa.", "en", "Vier Gerichte sind gerade verfügbar.", "de") == (
        "Vier Gerichte sind gerade verfügbar.", "de", False)


def test_english_uses_sensevoice_unless_it_writes_kana():
    assert choose("What can I buy right now?", "en", "What can I buy right now?", "en")[0] == "What can I buy right now?"
    assert choose("いや.", "ja", "Yeah.", "en")[0] == "Yeah."
    assert choose("하ello.", "ko", "Hello.", "en")[0] == "Hello."


def test_other_languages_fall_back_to_german():
    for whisper in (("いや", "ja"), ("Hallo", "tl"), ("땅케", "ko")):
        assert choose("いや.", "ja", *whisper)[2] is True
