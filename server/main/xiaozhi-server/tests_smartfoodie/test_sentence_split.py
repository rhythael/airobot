# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""离线验证 _get_segment_text 的切句行为，不启服务器、不联网、不碰 TTS。

模拟 LLM 流式输出：把整段文本一个字符一个字符喂进 tts_text_buff，
每喂一个就问一次 _get_segment_text，记录它吐出的每一段。
关心的是第一段——用户听到声音的时间由它决定。
"""

import re
import sys
import textwrap
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent  # main/xiaozhi-server
sys.path.insert(0, str(SERVER))

from core.utils import textUtils


class Fake:
    """只带上切句需要的那几个字段，绕开 TTSProviderBase 的完整构造。"""

    def __init__(self):
        src = (SERVER / "core/providers/tts/base.py").read_text()
        # 从真实源码里抓这三处定义，避免测试和实现各写一份而悄悄分叉
        body = src[src.index("self.punctuations = ("):src.index("self.tts_stop_request = False")]
        # 截取点落在首行的 token 上，首行没带缩进，后续行带着类里的 8 空格
        body = textwrap.dedent(" " * 8 + body)
        exec(compile(body, "base.py", "exec"), {"re": re}, {"self": self})
        self.tts_text_buff = []
        self.processed_chars = 0
        self.is_first_sentence = True
        self.tts_stop_request = False

    _get_segment_text = None  # 下面绑定真实实现


# 把真实的 _get_segment_text 绑到 Fake 上，测的是线上那份代码
import core.providers.tts.base as base_mod

Fake._get_segment_text = base_mod.TTSProviderBase._get_segment_text


def segments(text):
    f = Fake()
    out = []
    for ch in text:
        f.tts_text_buff.append(ch)
        seg = f._get_segment_text()
        if seg:
            out.append(seg)
    f.tts_stop_request = True
    tail = f._get_segment_text()
    if tail:
        out.append(tail)
    return out


CASES = [
    # (说明, 输入, 第一段必须等于)
    ("德语两句", "Es gibt drei Gerichte zur Auswahl. Du bekommst 鸡肉蔬菜蒸饺.",
     "Es gibt drei Gerichte zur Auswahl"),
    ("德语无空格", "Es gibt drei Gerichte.Du bekommst Nudeln.",
     "Es gibt drei Gerichte"),
    ("英语两句", "Three items are available. You can get dumplings.",
     "Three items are available"),
    ("中文", "现在有三种吃的。分别是饺子、面和米饭。", "现在有三种吃的"),
    ("德语缩写 z.B. 不切", "Es gibt z.B. Nudeln und Reis. Alles frisch.",
     "Es gibt z.B. Nudeln und Reis"),
    ("Dr. 不切", "Dr. Meier hat bestellt. Es ist fertig.",
     "Dr. Meier hat bestellt"),
    ("小数不切", "Es kostet 2.50 Euro. Viel Spaß.", "Es kostet 2.50 Euro"),
    ("货道号不切", "Es liegt in 1-7. Guten Appetit.", "Es liegt in 1-7"),
    # 首句仍从逗号切，但切出来够长才切
    ("首句长逗号照切", "Wir haben heute drei Gerichte, alle frisch.",
     "Wir haben heute drei Gerichte"),
    ("中文首句逗号照切", "现在有三种吃的，分别是饺子和面。", "现在有三种吃的"),
    # 太短的开头并进后面，不单独念 0.3 秒就停下等下一段（实机 16:38 的「Ja」「gerne」）。
    # 德英末句由收尾冲刷吐出，带句末标点，这是原有行为
    ("Ja 不单独成段", "Ja, es gibt drei Gerichte.", "Ja, es gibt drei Gerichte."),
    ("Ja gerne 不拆", "Ja, gerne. Wie kann ich dir helfen?",
     "Ja, gerne. Wie kann ich dir helfen?"),
    ("Sure 不单独成段", "Sure, what would you like to know?",
     "Sure, what would you like to know?"),
    ("你好不单独成段", "你好，欢迎来到041号机器。", "你好，欢迎来到041号机器"),
    ("整段就一个短词照样念出", "Gerne.", "Gerne."),
]


def test_short_opening_waits_for_more_text():
    """短开头之后如果文字还没到，不能先把短开头吐出去。"""
    f = Fake()
    for ch in "Sure, ":
        f.tts_text_buff.append(ch)
        assert f._get_segment_text() is None


def main():
    bad = 0
    for label, text, want_first in CASES:
        got = segments(text)
        first = got[0] if got else ""
        ok = first == want_first
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            print(f"       期望首段: {want_first!r}")
            print(f"       实际首段: {first!r}")
            print(f"       全部分段: {got!r}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} 通过")
    return 1 if bad else 0


def test_all_cases():
    """让 pytest 能收集到本文件。

    原来断言全封在 main() 里、只由 __main__ 触发，pytest 按 python_functions
    规则收集不到任何东西，于是这个文件在 pytest 下静默通过——断言一条都没跑。
    断言逻辑一个字没改，这里只是加一个 pytest 可见的入口。
    """
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
