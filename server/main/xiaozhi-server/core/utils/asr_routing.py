# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""SenseVoice + Whisper 双模型的识别路由。纯函数，不依赖模型库，测试可以直接导入。

原来每句都先让 Whisper 完整识别一遍，只为判断语种；中文和英语最后用的都是 SenseVoice
的结果，Whisper 那一遍白做。现在先跑 SenseVoice（约 0.05 秒），它认定是中文就直接用，
只有其余情况才请 Whisper。2026-09-23 用中德英各 16 句（含「你好」「Ja」「Hi」这类短词）
交替实测：

              语种判对   字错率   中文耗时   德语耗时   英语耗时
  原来          41/48    14.8%     0.59s      0.49s      0.56s
  现在          43/48     9.5%     0.05s      0.58s      0.54s

德语慢约 0.1 秒（先跑了一遍 SenseVoice），换中文每轮快约 0.55 秒。
"""

import re

_CJK = re.compile(r"[一-鿿]")
# SenseVoice 自动判语种，对德语短词会写出日文假名或韩文（「Ja」→「いや」、「Danke」→「땅케」）
_KANA_HANGUL = re.compile(r"[぀-ヿ가-힯]")

# SenseVoice 判为中文、且至少有这么多个汉字，才不必再问 Whisper。
# 更短的（「呀」「啊」）可能是德语「Ja」被听成了中文，实测真的发生过。
MIN_SURE_CJK = 3


def sensevoice_is_enough(sv_text, sv_lang):
    """只看 SenseVoice 的结果就能定下来吗。"""
    return sv_lang in ("zh", "yue") and len(_CJK.findall(sv_text or "")) >= MIN_SURE_CJK


def choose(sv_text, sv_lang, whisper_text, whisper_lang):
    """两个模型都跑过之后选哪个结果。返回 (text, lang, need_forced_german)。

    need_forced_german 为 True 时，调用方应当用固定德语的 Whisper 重识别一次：
    Whisper 判出了中德英以外的语言（「Ja」→ja、「Hallo」→tl、「Danke」→ko），
    门店里这几乎总是德国顾客说的短词被判错。
    """
    sv_text = (sv_text or "").strip()
    whisper_text = (whisper_text or "").strip()
    if whisper_lang == "de":
        return whisper_text, "de", False
    if sv_lang in ("zh", "yue") and sv_text:
        # 短中文且 Whisper 没说是德语：信 SenseVoice，它的中文远强于 Whisper
        return sv_text, "zh", False
    if whisper_lang in ("en", "zh", "yue"):
        if _KANA_HANGUL.search(sv_text) or sv_lang in ("ja", "ko") or not sv_text:
            return whisper_text, whisper_lang, False
        return sv_text, whisper_lang, False
    return whisper_text, whisper_lang or "", True
