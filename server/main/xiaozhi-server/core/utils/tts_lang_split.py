# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""把一句话按语言切成几段，每段交给该语言的音色念。

为什么不按顾客语言切整条链路：菜单本身是双语的（220 个菜名里 36 个是纯德语/英语），
实机回答里约 19% 同一句同时有汉字和拉丁字母。「现在还有鸡肉蔬菜蒸饺，还有一份
Tagliatelle mit Kalbsgeschnetzeltem」无论交给哪一种音色，另一半都会被念坏。
所以切分必须发生在句子内部。

德语和英语都是拉丁字母，靠书写体系分不开。回答里的德英混杂基本都是菜名，
所以用菜单目录里的菜名精确认出来，其余部分按这一段的用词判断。
"""

import re

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")

# 德英常用词，按命中数打分。刻意不收两种语言通用的词（was、also、so、in、an、will），
# 否则英语里的 was 会被当成德语证据。短句也要认得出：「Ja, gerne」「Sure」。
_DE_WORDS = re.compile(
    r"\b(?:der|die|das|den|dem|des|und|ist|sind|nicht|kein|keine|keinen|auch|noch|mit|für|"
    r"von|zum|zur|im|ich|du|dir|dich|mir|wir|ihr|sie|es|ein|eine|einen|gibt|gerne|gern|ja|"
    r"nein|kann|können|möchtest|möchten|wie|wo|wann|welche|welcher|hallo|danke|bitte|leider|"
    r"gerade|heute|jetzt|hier|schon|sehr|gut|aber|oder|nur|alle|fach|fächer|automat|preis|"
    r"stück|verfügbar|enthält|enthalten|spuren)\b",
    re.I,
)
_EN_WORDS = re.compile(
    r"\b(?:the|and|is|are|were|with|of|there|you|your|what|how|can|could|would|like|sure|"
    r"yes|no|hello|hi|here|now|today|it's|i'm|i'll|got|speaking|help|welcome|thanks|thank|"
    r"please|available|contains|slot|slots|item|items|left|some|any|this|that|these|those|"
    r"may|traces|machine|products?|expired)\b",
    re.I,
)
_UMLAUT = re.compile(r"[äöüÄÖÜß]")


def latin_scores(text):
    """(德语分, 英语分)。变音字母很少出现在英语里，给 2 分。"""
    de = len(_DE_WORDS.findall(text)) + 2 * len(_UMLAUT.findall(text))
    en = len(_EN_WORDS.findall(text))
    return de, en


def detect_latin(text):
    """德语 / 英语 / None（拿不准）。短句经常拿不准，所以德英要用多语音色兜底。"""
    de, en = latin_scores(text or "")
    if de == en:
        return None
    return "de" if de > en else "en"


# 整句粗判语言用的德语线索词。比上面的 _DE_WORDS 短，是 EdgeTTS 选音色一直在用的那份；
# 两份词表职责不同（这份只回答「整句算哪种语言」，那份给句内切分打分），不合并。
_DE_HINT = re.compile(
    r"\b(?:der|die|das|und|ist|sind|nicht|kein|auch|noch|mit|für|"
    r"Sie|wir|haben|gibt|bitte|danke|Preis|Fach|Automat)\b"
)
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}")


def guess_language(text, default="de"):
    """整句粗判：zh / de / en，认不出返回 default。

    EdgeTTS 选音色、本地 TTS 选模型、首句本地引擎选模型三处用的是同一个函数——
    同一句话三处必须得出同一个答案，否则首句本地引擎和后续 EdgeTTS 会一句德语
    一句英语地换来换去。以前是三份逐字相同的正则，现在只此一处。"""
    text = text or ""
    if _CJK.search(text):
        return "zh"
    if _UMLAUT.search(text) or _DE_HINT.search(text):
        return "de"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return default


def is_mixed_script(text):
    """既有汉字又有拉丁词（「You can eat素炒面 in slot 2-5」）。这种句子交给任何单语
    引擎都会念坏一半，调用方据此退回多语音色或句内切分。"""
    text = text or ""
    return bool(_CJK.search(text)) and bool(_LATIN_WORD.search(text))


# 菜名是德语还是英语。只用来给目录里的纯拉丁菜名定语言，拿不准就不定。
_DISH_DE = re.compile(
    r"[äöüßÄÖÜ]|\b(?:mit|und|Stk|Reis|ohne|Suppe)\b|"
    r"(?:fleisch|nudeln|soße|gulasch|kuchen|bällchen|füllung|geschnetzelt|bolognese|rahm)",
    re.I,
)
_DISH_EN = re.compile(
    r"\b(?:with|and|of|Fried|Rice|Beef|Chicken|Noodles?|Soup|Cheese|Style|Plant|Based|"
    r"Creamy|Vegetable|Braised|Shredded|Spicy|Sausage|Sauce|pcs)\b"
)

# 拉丁字母少于这个数的片段（「A区」「OK」）不单独切，中文音色念单个字母没问题
_MIN_LATIN_LETTERS = 3


def _clean_dish_name(name):
    name = re.sub(r"\([^)]*\)", "", name or "")
    name = re.sub(r"[^\wÀ-ÿ&' .,-]", " ", name)  # 去掉 emoji 和 ? ❄ 之类的前缀符号
    return re.sub(r"\s+", " ", name).strip(" -.,")


def dish_languages(names):
    """给菜名定语言。返回 [(name, lang)]，长的在前。

    中文菜名也收进来（lang 为 zh），只用于判断句子骨架是哪种语言；
    纯拉丁菜名按用词分德语、英语，拿不准的不收。"""
    out = {}
    for raw in names or []:
        if not raw:
            continue
        if _CJK.search(raw):
            name = re.sub(r"[（(][^）)]*[）)]", "", raw)
            name = "".join(ch for ch in name if _CJK.match(ch) or _LATIN.match(ch) or ch.isdigit())
            if len(name) >= 2 and not _LATIN.search(name):
                out[name] = "zh"
            continue
        name = _clean_dish_name(raw)
        if len(name) < 8:
            continue
        de = len(_DISH_DE.findall(name))
        en = len(_DISH_EN.findall(name))
        if de != en:
            out[name] = "de" if de > en else "en"
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


_NUM = re.compile(r"\d+(?:[\-–./:]\d+)*")


def _script_runs(text, dishes=()):
    """按书写体系切：汉字一段、拉丁字母一段。标点空格跟着前一段走。"""
    # 以中文为主的句子里，单个英文词（「我是 Smartfoodie 的小助手」）留给中文音色，
    # 为一个词换音色反而突兀。多词的德语菜名才是中文音色真念不好的东西。
    # 主语言看句子骨架，不看菜名：「Right now you can get four items: 鸡肉蔬菜蒸饺, 虾饺
    # and 红烧牛肉面」按字数中文占一半，但它是英文句。菜名剔掉后再数。
    # 一个汉字的读音时长约等于 3 个拉丁字母。
    cjk = len(_CJK.findall(text))
    frame = _without_dishes(text, dishes)
    frame_cjk, frame_latin = len(_CJK.findall(frame)), len(_LATIN.findall(frame))
    if not frame_cjk and not frame_latin:
        frame_cjk, frame_latin = cjk, len(_LATIN.findall(text))
    zh_dominant = cjk > 0 and frame_cjk >= frame_latin / 3
    dominant = "zh" if zh_dominant else "lat"
    dish_names = [name.lower() for name, lang in dishes if lang != "zh"]

    # 数字单独归属。后面紧跟汉字的（10粒、2份、1号）是中文量词，按中文念；
    # 其余跟着整句的主语言。德语句「1-6 鸡肉蔬菜蒸饺，2-6 虾饺 und 2-9 …」里
    # 夹在两个中文菜名之间的 2-6 是货道号，是取餐依据，必须用德语念，
    # 不能因为挨着中文就被念成「二杠六」。
    tokens = []
    i = 0
    while i < len(text):
        m = _NUM.match(text, i)
        if m:
            nxt = text[m.end():m.end() + 1]
            if nxt and _CJK.match(nxt):
                kind = "zh"
            else:
                kind = dominant if cjk else None
            tokens.append((kind, m.group()))
            i = m.end()
            continue
        ch = text[i]
        kind = "zh" if _CJK.match(ch) else "lat" if _LATIN.match(ch) else None
        tokens.append((kind, ch))
        i += 1

    runs = []  # [kind, text]，kind 为 zh / lat / None（还没遇到文字）
    for kind, tok in tokens:
        if runs and (kind is None or runs[-1][0] in (kind, None)):
            if runs[-1][0] is None and kind is not None:
                runs[-1][0] = kind
            runs[-1][1] += tok
        else:
            runs.append([kind, tok])

    def stays_chinese(part):
        letters = len(_LATIN.findall(part))
        if letters < _MIN_LATIN_LETTERS:
            return not re.search(r"\d", part) or zh_dominant
        if not zh_dominant:
            return False
        words = re.findall(r"[A-Za-zÀ-ÿ]+", part)
        return len(words) < 2 and not any(n in part.lower() for n in dish_names)

    # 太短的拉丁片段并回汉字里
    merged = []
    for kind, part in runs:
        if kind == "lat" and cjk and stays_chinese(part):
            kind = "zh"
        if merged and merged[-1][0] == kind:
            merged[-1][1] += part
        else:
            merged.append([kind, part])
    return merged


def _without_dishes(text, dishes):
    """菜名不参与判断句子语言：「We have Wiesnschmaus Bowl mit ... and ...」里的
    mit / und 属于菜名，不能让整句被判成德语。"""
    rest = text
    for name, _ in dishes:
        rest = re.sub(re.escape(name), " ", rest, flags=re.I)
    return rest if rest.strip() else text


def _latin_language(part, context, default, dishes=()):
    for sample in (_without_dishes(part, dishes), _without_dishes(context, dishes)):
        lang = detect_latin(sample)
        if lang:
            return lang
    return default


def _split_latin(part, lang, dishes):
    """在一段拉丁文字里找出目录菜名，菜名按它自己的语言念，其余按 lang。"""
    pieces = []
    lower = part.lower()
    taken = [False] * len(part)
    spans = []
    for name, dish_lang in dishes:
        start = 0
        key = name.lower()
        while True:
            i = lower.find(key, start)
            if i < 0:
                break
            if not any(taken[i:i + len(key)]):
                spans.append((i, i + len(key), dish_lang))
                for j in range(i, i + len(key)):
                    taken[j] = True
            start = i + len(key)
    spans.sort()
    pos = 0
    for s, e, dish_lang in spans:
        if s > pos:
            pieces.append((lang, part[pos:s]))
        pieces.append((dish_lang, part[s:e]))
        pos = e
    if pos < len(part):
        pieces.append((lang, part[pos:]))
    return pieces


def split_by_language(text, dishes=(), default_latin="de"):
    """把一句话切成 [(lang, text)]，lang 为 zh / de / en。相邻同语言的段会合并。

    dishes: dish_languages() 的返回值。
    default_latin: 拉丁文字认不出德英时用哪种。
    """
    if not text:
        return []
    runs = _script_runs(text, dishes)
    latin_context = " ".join(p for k, p in runs if k == "lat")
    pieces = []
    for kind, part in runs:
        if kind == "lat":
            lang = _latin_language(part, latin_context, default_latin, dishes)
            pieces.extend(_split_latin(part, lang, dishes))
        elif kind == "zh":
            pieces.append(("zh", part))
        else:
            pieces.append((None, part))

    out = []
    for lang, part in pieces:
        # 只有标点空格的碎片（菜名前后的逗号、空格）挂到前一段上
        if not _CJK.search(part) and not _LATIN.search(part) and not re.search(r"\d", part):
            if out:
                out[-1] = (out[-1][0], out[-1][1] + part)
                continue
        if out and (out[-1][0] == lang or lang is None):
            out[-1] = (out[-1][0], out[-1][1] + part)
        elif out and out[-1][0] is None:
            out[-1] = (lang, out[-1][1] + part)
        else:
            out.append((lang, part))
    out = [(lang or default_latin, part) for lang, part in out if part.strip()]
    return out
