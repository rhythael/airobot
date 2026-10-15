# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""四类最常见的库存问题走本地模板直答，不经过大模型。

为什么要有这一层：首包延迟里 LLM 首字 0.7–1.3 秒 + EdgeTTS 首句 0.5–2 秒，
而「有什么吃的」「哪些过期」「几个空货道」「X 货道是什么」四类问题的答案
完全由库存快照决定，模型只是在把 JSON 念成句子。模板直答把 LLM 那一段整个省掉，
首句又固定且很短，由 TTS 的首句本地引擎零点几秒念出。

边界（宁可漏命中，也不能误命中）：
- 全句 fullmatch，带了别的内容（推荐、过敏原、价格、换语言、复合句）就不匹配，交给模型；
- 库存不可用（context 是 unavailable_context）或快照结构不合法 → None，走原有逻辑；
- 回答遵守提示词的播报规则：首句 ≤10 词、不含菜名、中文数字用汉字；
  第二句最多 3 个商品名 + 货道号，再多只说「还有 N 种」。

曾经有过一套「按快照预热首句音频缓存」的逻辑，连同一份复制的 TTS 切句规则。
它在握手期拿到的快照永远是空的（库存在 chat 入口才刷新），所以从未生效；
首句改走本地引擎后 EdgeTTS 缓存预热也没有意义，2026-10-02 一并删除。
"""
import re

from core.providers.tts.local_first_sentence import guess_language
from core.utils.slot_numbers import normalize_slot_numbers
from core.utils.turn_context import normalize_query, valid_inventory

_ALL_SLOTS = tuple(f"{row}-{col}" for row in (1, 2) for col in range(1, 10))
_SLOT = r"([12]-[1-9])"

_ZH_HEAD = r"(?:请问)?(?:0?41号?(?:机器|售货机)(?:里|的)?)?(?:现在|目前|今天)?"
_ZH_TAIL = r"(?:呢|呀|啊|吗)?"
_DE_HEAD = r"(?:hallo,?\s*)?(?:bitte\s+)?"
_DE_PLACE = r"(?:\s+(?:am|im)\s+automaten(?:\s+0?41)?|\s+hier)?"
_DE_TIME = r"(?:\s+(?:gerade|jetzt|heute|aktuell|momentan))?"
_EN_PLACE = r"(?:\s+(?:at|in|from)\s+(?:the\s+)?(?:vending\s+)?machine(?:\s+0?41)?|\s+here)?"
_EN_TIME = r"(?:\s+(?:right\s+now|now|today|at\s+the\s+moment|currently))?"

# 每类意图：语言 → 正则。顺序决定优先级，只有 slot 带一个捕获组。
_PATTERNS = {
    "available": (
        ("zh", re.compile(
            _ZH_HEAD + r"(?:"
            r"有(?:什么|啥|哪些)(?:(?:可以|能)?(?:吃|买)的(?:东西)?|吃的东西|卖的|商品|吃的)"
            r"|(?:能|可以)买(?:到)?(?:什么|啥|点什么|些什么|哪些)"
            r"|卖(?:什么|啥)"
            r"|都有(?:什么|啥)"
            r")" + _ZH_TAIL)),
        ("de", re.compile(
            _DE_HEAD + r"(?:"
            r"was gibt es" + _DE_TIME + _DE_PLACE + r"(?:\s+zu\s+(?:essen|kaufen))?"
            r"|was gibt'?s" + _DE_TIME + _DE_PLACE +
            r"|was kann ich" + _DE_TIME + _DE_PLACE + r"\s+(?:kaufen|essen|bekommen)"
            r"|was habt ihr" + _DE_TIME + _DE_PLACE +
            r"|was hast du" + _DE_TIME + _DE_PLACE +
            r"|was ist" + _DE_TIME + r"\s+(?:verfügbar|da|im angebot)" + _DE_PLACE +
            r"|welche gerichte gibt es" + _DE_TIME + _DE_PLACE +
            r")", re.I)),
        ("en", re.compile(
            r"(?:hello,?\s*)?(?:"
            r"what can i (?:buy|get|eat|order|have)" + _EN_TIME + _EN_PLACE + _EN_TIME +
            r"|what(?:'s| is) (?:available|there|on offer|in stock)" + _EN_TIME + _EN_PLACE + _EN_TIME +
            r"|what do you have" + _EN_TIME + _EN_PLACE + _EN_TIME +
            r"|what(?:'s| is) (?:there )?to eat" + _EN_TIME + _EN_PLACE +
            r"|what (?:food|items|dishes) (?:are|is) (?:available|there)" + _EN_TIME + _EN_PLACE +
            r")", re.I)),
    ),
    "expired": (
        ("zh", re.compile(
            _ZH_HEAD + r"(?:"
            r"有(?:没有|什么|哪些)?过期(?:的|了的)?(?:商品|东西|的)?"
            r"|哪些(?:商品|东西|货道)?(?:是)?过期(?:的|了)?"
            r"|什么(?:东西|商品)?过期了"
            r"|过期的有(?:哪些|什么)"
            r")" + _ZH_TAIL)),
        ("de", re.compile(
            _DE_HEAD + r"(?:"
            r"was ist abgelaufen|ist (?:etwas|was|irgendwas) abgelaufen|gibt es (?:etwas |was )?abgelaufenes"
            r"|welche (?:gerichte|produkte|speisen) sind abgelaufen|gibt es abgelaufene (?:gerichte|produkte|ware)"
            r")" + _DE_PLACE, re.I)),
        ("en", re.compile(
            r"(?:"
            r"what(?:'s| is) expired|is anything expired|anything expired"
            r"|which (?:items|products|dishes|slots) are expired|are there (?:any )?expired (?:items|products|dishes)"
            r"|do you have (?:any )?expired (?:items|products|food)"
            r")" + _EN_PLACE + _EN_TIME, re.I)),
    ),
    "empty": (
        ("zh", re.compile(
            _ZH_HEAD + r"(?:"
            r"有?(?:几个|多少个?|哪些)空(?:的)?(?:货道|货到)"
            r"|空(?:货道|货到)有(?:几个|多少|哪些)"
            r"|哪些(?:货道|货到)(?:是)?空(?:的|了)?"
            r"|有(?:没有)?空(?:的)?(?:货道|货到)"
            r")" + _ZH_TAIL)),
        ("de", re.compile(
            _DE_HEAD + r"(?:"
            r"wie viele f[äa]cher sind leer|welche f[äa]cher sind leer|gibt es leere f[äa]cher"
            r"|wie viele leere f[äa]cher(?: gibt es)?|sind f[äa]cher leer"
            r")" + _DE_PLACE, re.I)),
        ("en", re.compile(
            r"(?:"
            r"how many (?:slots|compartments) are empty|which (?:slots|compartments) are empty"
            r"|are there (?:any )?empty (?:slots|compartments)|how many empty (?:slots|compartments)(?: are there)?"
            r"|any empty slots"
            r")" + _EN_PLACE + _EN_TIME, re.I)),
    ),
    "slot": (
        ("zh", re.compile(
            _ZH_HEAD + _SLOT + r"(?:号)?(?:货道|货到)(?:里|上)?"
            r"(?:是什么|有什么|放的是什么|放的什么|是啥|有啥|卖的是什么|是什么东西|是什么商品)?" + _ZH_TAIL)),
        ("de", re.compile(
            _DE_HEAD + r"was (?:liegt|ist|gibt es|befindet sich) (?:im|in) fach " + _SLOT + _DE_TIME, re.I)),
        ("en", re.compile(
            r"what(?:'s| is| do you have)(?: in)? slot " + _SLOT + _EN_TIME, re.I)),
    ),
}

_ZH_NUMS = "零一二三四五六七八九"
# 机器最多 18 个货道，数词表覆盖到 18；再大（商品份数）回退阿拉伯数字，TTS 念数字没问题
_DE_WORDS = ["null", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
             "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn"]
_EN_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen"]


def zh_number(n):
    """汉字数字：提示词要求「两种」不是「2种」。只处理 0–99，货道份数再大就按数字念——
    越界曾让 _answer_slot 抛 IndexError，而那时 FIRST 已入队，整轮会静默挂死。"""
    if not isinstance(n, int) or n < 0 or n >= 100:
        return str(n)
    if n == 2:
        return "两"
    if n < 10:
        return _ZH_NUMS[n]
    if n < 20:
        return "十" + ("" if n == 10 else _ZH_NUMS[n - 10])
    tens, ones = divmod(n, 10)
    return _ZH_NUMS[tens] + "十" + ("" if ones == 0 else _ZH_NUMS[ones])


def _de_number(n):
    return _DE_WORDS[n] if n < len(_DE_WORDS) else str(n)


def _en_number(n, capital=False):
    word = _EN_WORDS[n] if n < len(_EN_WORDS) else str(n)
    return word.capitalize() if capital else word


def detect_language(text):
    """只给 TURN 计时日志标 lang 用。规则与 TTS 选音色的 guess_language 同一份，认不出算英语。"""
    return guess_language(text if isinstance(text, str) else "", "en")


# 单独一句招呼。德国顾客说「Hallo」，Whisper 会识别成「Hello」并判成英语（2026-10-05 音频复测），
# 单个词在声学上分不出德英，就不猜：德英各说一句。明确是德语或英语的招呼只用那一种。
_GREETING_BOTH = re.compile(r"(?:hallo|hello|hi|hey)(?: there| zusammen)?", re.I)
_GREETING_DE = re.compile(r"guten (?:tag|morgen|abend)|servus|moin|gr[üu](?:ß|ss|e)?(?: dich)? gott|grüß dich", re.I)
_GREETING_EN = re.compile(r"good (?:morning|afternoon|evening)|hi there|hello there", re.I)
# 中文招呼原来交给模型，会把整张货单念一遍（17 秒）
_GREETING_ZH = re.compile(r"(?:你好|您好|哈喽|嗨)(?:啊|呀|哇)?|(?:早上|中午|下午|晚上)好")
_GREETING_ANSWER = {
    "zh": "你好！有什么可以帮你？",
    "both": "Hallo! Wie kann ich helfen? Hello! How can I help?",
    "de": "Hallo! Wie kann ich helfen?",
    "en": "Hello! How can I help?",
}


def local_greeting_answer(query, settings):
    """整句只是一句招呼时直接回应；带了别的内容（「Hallo, was gibt es?」）一律不接。"""
    if not settings.get("local_template_answers") or not isinstance(query, str):
        return None
    text = normalize_query(query)
    if _GREETING_ZH.fullmatch(text):
        return _GREETING_ANSWER["zh"]
    if _GREETING_EN.fullmatch(text):
        return _GREETING_ANSWER["en"]
    if _GREETING_DE.fullmatch(text):
        return _GREETING_ANSWER["de"]
    if _GREETING_BOTH.fullmatch(text):
        return _GREETING_ANSWER["both"]
    return None


def match_intent(query):
    """返回 (intent, language, slot) 或 None。"""
    if not isinstance(query, str) or not query.strip():
        return None
    # 货道号（含「一号七」「Fach zwei sechs」这类念法）先统一成 1-7，正则只认这一种写法
    text = normalize_query(normalize_slot_numbers(normalize_query(query)))
    # 复合句（逗号、分号、问号在中间）一律不接，顾客一句话问了两件事时让模型答
    if re.search(r"[,，;；?？]", text):
        return None
    for intent, patterns in _PATTERNS.items():
        for language, pattern in patterns:
            m = pattern.fullmatch(text)
            if m:
                return intent, language, (m.group(1) if m.groups() else None)
    return None


def _grouped(items):
    """同名商品按货道合并：[(name, [slots...], total_qty)]，按首个货道排序。"""
    order, groups = [], {}
    for item in sorted(items, key=lambda i: i["slot"]):
        if item["name"] not in groups:
            groups[item["name"]] = {"slots": [], "qty": 0}
            order.append(item["name"])
        groups[item["name"]]["slots"].append(item["slot"])
        groups[item["name"]]["qty"] += item["quantity"]
    return [(name, groups[name]["slots"], groups[name]["qty"]) for name in order]


def _join(parts, language):
    if language == "zh":
        return "、".join(parts)
    return ", ".join(parts)


def _compose(language, first, body, more=""):
    """首句 + 正文 + 尾句的拼法：中文无空格、正文以「。」收；德英首句后空格、正文以「.」收。
    德英的尾句（Dazu … / Plus …）自带前导空格，中文的没有——照搬各语言原来的写法。"""
    if language == "zh":
        return f"{first}{body}。{more}"
    return f"{first} {body}.{more}"


# 可买 / 过期 两类是同一种形状：零条一句话；否则 首句(n) + 最多 limit 条 + 尾句(剩余数)。
# 德英第二句刻意以 Fach / Slot 开头：TTS 只把后面跟大写字母的英文句号当句尾，
# 若以中文菜名开头，首句会和第二句粘成一段，首包白等。
_LISTINGS = {
    "available": {
        "zh": dict(zero="现在没有可买的。", first=lambda n: f"现在有{zh_number(n)}种可买。", sep="，",
                   item=lambda name, slots: f"{name}在{_join(slots, 'zh')}货道", more=lambda k: f"还有{zh_number(k)}种。"),
        "de": dict(zero="Gerade ist nichts verfügbar.", sep=", ",
                   first=lambda n: "Es gibt ein Gericht." if n == 1 else f"Es gibt {_de_number(n)} Gerichte.",
                   item=lambda name, slots: f"Fach {_join(slots, 'de')} {name}", more=lambda k: f" Dazu {_de_number(k)} weitere."),
        "en": dict(zero="Nothing is available.", sep=", ",
                   first=lambda n: "One item is available." if n == 1 else f"{_en_number(n, True)} items are available.",
                   item=lambda name, slots: f"Slot {_join(slots, 'en')} {name}", more=lambda k: f" Plus {_en_number(k)} more."),
    },
    "expired": {
        "zh": dict(zero="没有过期的商品。", first=lambda n: f"有{zh_number(n)}个货道过期了。", sep="、",
                   item=lambda name, slots: f"{slots[0]}的{name}", more=lambda k: f"还有{zh_number(k)}个。"),
        "de": dict(zero="Nichts ist abgelaufen.", sep=", ",
                   first=lambda n: "Ein Fach ist abgelaufen." if n == 1 else f"{_de_number(n).capitalize()} Fächer sind abgelaufen.",
                   item=lambda name, slots: f"Fach {slots[0]} {name}", more=lambda k: f" Dazu {_de_number(k)} weitere."),
        "en": dict(zero="Nothing is expired.", sep=", ",
                   first=lambda n: "One slot is expired." if n == 1 else f"{_en_number(n, True)} slots are expired.",
                   item=lambda name, slots: f"Slot {slots[0]} {name}", more=lambda k: f" Plus {_en_number(k)} more."),
    },
}


def _listing(intent, language, entries, limit=3):
    """entries: [(name, [slots])]；按 _LISTINGS 的字符串表拼成回答。"""
    t = _LISTINGS[intent][language]
    n = len(entries)
    if n == 0:
        return t["zero"]
    body = t["sep"].join(t["item"](name, slots) for name, slots in entries[:limit])
    return _compose(language, t["first"](n), body, t["more"](n - limit) if n > limit else "")


def _answer_available(items, language):
    groups = _grouped([i for i in items if i["purchasable"]])
    return _listing("available", language, [(name, slots) for name, slots, _ in groups])


def _answer_expired(items, language):
    expired = sorted([i for i in items if not i["purchasable"]], key=lambda i: i["slot"])
    return _listing("expired", language, [(i["name"], [i["slot"]]) for i in expired])


def _answer_empty(items, language, limit=10):
    taken = {i["slot"] for i in items}
    empty = [s for s in _ALL_SLOTS if s not in taken]
    n = len(empty)
    if n == 0:
        return {"zh": "没有空货道。", "de": "Kein Fach ist leer.", "en": "No slot is empty."}[language]
    listed = _join(empty[:limit], language)
    if language == "zh":
        return _compose("zh", f"有{zh_number(n)}个空货道。", f"分别是{listed}{'等' if n > limit else ''}")
    if language == "de":
        first = "Ein Fach ist leer." if n == 1 else f"{_de_number(n).capitalize()} Fächer sind leer."
        return _compose("de", first, f"Fach {listed}{' und weitere' if n > limit else ''}")
    first = "One slot is empty." if n == 1 else f"{_en_number(n, True)} slots are empty."
    return _compose("en", first, f"Slot {listed}{' and more' if n > limit else ''}")


def _answer_slot(items, language, slot):
    item = next((i for i in items if i["slot"] == slot), None)
    if language == "zh":
        if item is None:
            return f"{slot}货道是空的。"
        if item["purchasable"]:
            return f"{slot}货道是{item['name']}，还有{zh_number(item['quantity'])}份。"
        return f"{slot}货道是{item['name']}，已经过期，不能买。"
    if language == "de":
        if item is None:
            return f"Fach {slot} ist leer."
        if item["purchasable"]:
            portion = "eine Portion" if item["quantity"] == 1 else f"{_de_number(item['quantity'])} Portionen"
            return f"In Fach {slot} liegt {item['name']}, {portion}."
        return f"In Fach {slot} liegt {item['name']}, aber es ist abgelaufen und nicht kaufbar."
    if item is None:
        return f"Slot {slot} is empty."
    if item["purchasable"]:
        portion = "one portion" if item["quantity"] == 1 else f"{_en_number(item['quantity'])} portions"
        return f"Slot {slot} has {item['name']}, {portion}."
    return f"Slot {slot} has {item['name']}, but it is expired and not for sale."


def local_template_answer(query, context, data, settings):
    """命中四类意图且库存可用时返回答案文本，否则 None（交回原有逻辑）。"""
    if not settings or not settings.get("local_template_answers"):
        return None
    matched = match_intent(query)
    if matched is None:
        return None
    intent, language, slot = matched
    # 库存不可用时不直答：原有逻辑会按 unavailable_context 让模型只说「查不到」，
    # 在这里抢答反而绕开了那条已验证的降级路径。
    if context == settings.get("unavailable_context"):
        return None
    items = valid_inventory(data)
    if items is None:
        return None
    if intent == "available":
        return _answer_available(items, language)
    if intent == "expired":
        return _answer_expired(items, language)
    if intent == "empty":
        return _answer_empty(items, language)
    return _answer_slot(items, language, slot)


# ---------------------------------------------------------------------------
# 菜单概括（第四轮 debug，2026-10-05）
# 「What else is on the menu?」交给模型时，它会把货架上七款商品逐个念一遍。
# 改成按目录里在售菜品的主料分组说一句，再报机器上有几种可买，顾客想听哪一类再追问。

_MENU_PATTERNS = (
    ("zh", re.compile(r"(?:请问)?菜单(?:上|里)?(?:还|都)?有(?:什么|哪些|啥)(?:菜|吃的|东西)?(?:呢)?")),
    ("de", re.compile(r"(?:was|welche gerichte) (?:gibt es|steht|stehen|habt ihr|hast du) (?:noch |sonst )?(?:alles )?"
                      r"auf der (?:speise)?karte|was ist (?:noch )?auf der (?:speise)?karte", re.I)),
    ("en", re.compile(r"what(?:'s| is| else is|'s else) on (?:the|your) menu|what (?:else )?do you have on the menu", re.I)),
)
# 目录菜名开头的表情 → 三语主料名，按播报顺序
_MENU_GROUPS = (
    ("🐔", {"zh": "鸡肉", "de": "Huhn", "en": "chicken"}),
    ("🐮", {"zh": "牛肉", "de": "Rind", "en": "beef"}),
    ("🐷", {"zh": "猪肉", "de": "Schwein", "en": "pork"}),
    ("🐑", {"zh": "羊肉", "de": "Lamm", "en": "lamb"}),
    ("🦐", {"zh": "虾", "de": "Garnelen", "en": "shrimp"}),
    ("🐟", {"zh": "鱼", "de": "Fisch", "en": "fish"}),
)


def local_menu_overview_answer(query, data, settings, menu_settings):
    """只认整句问菜单的说法；带了具体菜名（「菜单上有虾饺吗」）不接。"""
    if not settings.get("local_template_answers") or not isinstance(query, str):
        return None
    text = normalize_query(query)
    language = next((lang for lang, pattern in _MENU_PATTERNS if pattern.fullmatch(text)), None)
    items = valid_inventory(data) if language else None
    if not items:
        return None
    try:
        from core.utils.menu_knowledge import DEFAULT_CATALOG, load_catalog
        dishes = load_catalog(str((menu_settings or {}).get("path") or DEFAULT_CATALOG))["dishes"]
    except (OSError, ValueError, TypeError):
        return None
    active = [d["name"] for d in dishes if d.get("global_status") != "全局下架"]
    meats = [names[language] for emoji, names in _MENU_GROUPS if any(emoji in name for name in active)]
    vegetarian = any("🌱" in name for name in active)
    dessert = any("🍬" in name for name in active)
    count = len({i["name"] for i in items if i["purchasable"]})
    if language == "zh":
        extra = "和".join([w for w, ok in (("素食", vegetarian), ("甜点", dessert)) if ok])
        return ("菜单上的菜分好几类。"
                f"有{'、'.join(meats[:-1])}和{meats[-1]}" + (f"，还有{extra}" if extra else "") + "。"
                f"这台机器现在有{zh_number(count)}种可买。想听哪一类？")
    if language == "de":
        extra = " und ".join([w for w, ok in (("Vegetarisches", vegetarian), ("Desserts", dessert)) if ok])
        return ("Auf der Karte gibt es mehrere Sorten. "
                f"Gerichte mit {', '.join(meats[:-1])} und {meats[-1]}"
                + (f", dazu {extra}" if extra else "") + ". "
                f"Im Automaten gibt es gerade {_de_number(count)} Gerichte. Welche Richtung interessiert dich?")
    extra = " and ".join([w for w, ok in (("vegetarian food", vegetarian), ("desserts", dessert)) if ok])
    return ("The menu has several kinds of dishes. "
            f"There are {', '.join(meats[:-1])} and {meats[-1]} dishes" + (f", plus {extra}" if extra else "") + ". "
            f"The machine has {_en_number(count)} items right now. Which kind would you like to hear about?")
