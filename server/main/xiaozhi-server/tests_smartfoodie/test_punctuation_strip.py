# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""验证送进 TTS 的文本清理：分号要被清掉，货道号的连字符不能被误伤。

只测 textUtils，不启服务端、不联网、不合成语音。
"""

import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent  # main/xiaozhi-server
sys.path.insert(0, str(SERVER))

from core.utils.textUtils import get_string_no_punctuation_or_emoji as clean

CASES = [
    # (说明, 输入, 期望输出)
    ("句尾中文分号被清掉", "可以试试尖椒牛肉盖饭，分量足味道香；", "可以试试尖椒牛肉盖饭，分量足味道香"),
    ("句尾英文分号被清掉", "Three items are available;", "Three items are available"),
    ("句首分号被清掉", "；现在有三种", "现在有三种"),
    ("句中分号保留", "有牛肉炒面；还有虾饺", "有牛肉炒面；还有虾饺"),
    ("句尾句号照常清掉", "现在有三种。", "现在有三种"),
    ("德语句尾句号照常清掉", "Es gibt drei Gerichte.", "Es gibt drei Gerichte"),
    ("句中货道号连字符不受影响", "它在1-7货道", "它在1-7货道"),
    ("句中德语商品名不受影响", "有Wiesnschmaus Bowl mit Kartoffelsalat", "有Wiesnschmaus Bowl mit Kartoffelsalat"),
    ("emoji 商品名前缀被清掉", "🐮牛肉炒面", "牛肉炒面"),
    ("混合语种句子整体保留", "有牛肉炒面、Creamy Mac & Cheese，还有两种德餐。",
     "有牛肉炒面、Creamy Mac & Cheese，还有两种德餐"),
]


def main():
    bad = 0
    for label, src, want in CASES:
        got = clean(src)
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            print(f"       输入: {src!r}")
            print(f"       期望: {want!r}")
            print(f"       实际: {got!r}")
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
