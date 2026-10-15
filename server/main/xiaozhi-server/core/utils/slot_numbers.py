# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""把识别结果里的货道号统一写成「1-7」。货道号是取餐依据，库存快照里就是这种写法。

识别模型对货道号的写法五花八门（2026-09-23 实测）：
  SenseVoice  「slot one seven」→「17」，「一号七货道」→「一号期货到」
  Whisper     「Fach eins sieben」→「Fach 1/7」或「Fach 1.7」
只在货道关键词旁边才改，「17 Euro」「12 Fächer sind leer」「14个空货道」都不动。
"""

import re

_ZH_DIGIT = "一二三四五六七八九"
_ZH_TO_DIGIT = {c: str(i + 1) for i, c in enumerate(_ZH_DIGIT)}
_SEP = r"\s*(?:[-–/.、,，]|号|杠|减)?\s*"

# 「货道」的听错写法：货→火/获/或，道→到/倒（2026-10-05 音频复测：「一号期火道」）。
# 只在前面紧跟货道号时才认，「防火道具」「过期火腿」不受影响
_HUODAO = r"[货火获或][道到倒]"
# 中文：数字紧跟「货道」（中间最多一个「号」）
_ZH_SLOT = re.compile(
    rf"(?<![\d.])([1-9{_ZH_DIGIT}]){_SEP}([1-9{_ZH_DIGIT}])(?![\d.])\s*(号?\s*){_HUODAO}"
)
# 「七货道」常被听成「期货到」「期火道」。前面必须是数字或「号」，「有过期货吗」不受影响
_ZH_QI = re.compile(rf"([1-9{_ZH_DIGIT}])\s*号?\s*期{_HUODAO}")
# 德英：关键词在前，数字在后。「12 Fächer」数字在前，不受影响
_LATIN_SLOT = re.compile(
    r"\b(Fach|Slot|slot|Platz|Regal|Regalfach|shelf|compartment)"
    r"(\s*(?:Nummer|Nr\.?|number|no\.?)?\s*)"
    r"([1-9])\s*[-–/.,]?\s*([1-9])(?![\d])(?![.,]\d)",
    re.I,
)
# 德英数词：「Fach zwei sechs」「slot one seven」。识别模型把货道号念成单个数词时
# 常常原样写出来，和数字写法一样只在货道关键词后面才改，「zwei Gerichte」不动
_LATIN_WORD = {"eins": "1", "zwei": "2", "drei": "3", "vier": "4", "fünf": "5", "fuenf": "5",
               "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
               "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
               "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_WORD = r"(eins|zwei|drei|vier|f[üu]e?nf|sechs|sieben|acht|neun|one|two|three|four|five|six|seven|eight|nine)"
_LATIN_WORD_SLOT = re.compile(rf"\b(Fach|Slot|Platz)\s+{_WORD}[\s\-]+{_WORD}\b", re.I)


def _digit(ch):
    return _ZH_TO_DIGIT.get(ch, ch)


def _word_digit(word):
    return _LATIN_WORD.get(word.lower(), word)


def normalize_slot_numbers(text):
    if not text or not isinstance(text, str):
        return text
    text = _ZH_QI.sub(lambda m: f"{_digit(m.group(1))}-7货道", text)
    text = _ZH_SLOT.sub(lambda m: f"{_digit(m.group(1))}-{_digit(m.group(2))}{m.group(3)}货道", text)
    text = _LATIN_SLOT.sub(lambda m: f"{m.group(1)}{m.group(2) or ' '}{m.group(3)}-{m.group(4)}", text)
    text = _LATIN_WORD_SLOT.sub(lambda m: f"{m.group(1)} {_word_digit(m.group(2))}-{_word_digit(m.group(3))}", text)
    return text
