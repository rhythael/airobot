# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""过敏原问答的本地直答：直接查货架商品的过敏原原文，不经过大模型。

为什么要有这一层（2026-10-05 沙盒测试）：模型拿到的货架过敏原原文是完整的，
但「I'm allergic to peanuts」问 4 次错 4 次，错法各不相同，有一次把标注
「可能含花生痕量」的黑椒牛肉炒饭说成安全。关掉思考的小模型做不好跨商品的逐条筛查，
而这类答案完全由资料决定，没有理由交给模型。

两类问法：
  筛查  I'm allergic to peanuts / Ich bin allergisch gegen Sesam / 我对花生过敏
  含有  Do the dumplings contain sesame? / Ist in den Teigtaschen Sesam drin? / 饺子里有芝麻吗

边界（宁可漏命中，也不能误命中）：
- 必须认出具体过敏原（花生、芝麻……）。只说「过敏原」的，交给菜单资料链路；
- 商品范围必须完全认清：点名货架商品、一类商品（饺子 / Nudeln / fried rice）、
  目录里的菜名，或者干脆没提商品（= 货架上全部可购买商品）。
  句子里还剩认不出的实词（shrimp dumpling、coffee、vegetarian）就不答，交给模型；
- 用代词指前文（它 / da drin / it）不答，模型有对话历史；
- 库存不可用或快照不合法不答。
原文按「可能含有 / may contain / kann Spuren」切成含有与痕量两段，分开报。
"""
import re

from core.utils.menu_knowledge import (
    CATEGORY_PATTERNS as _CATEGORIES, DEFAULT_CATALOG, _PRODUCT_NOUN, _aliases, _mentions, load_catalog, normalize,
)
from core.utils.turn_context import normalize_query, valid_inventory

# key: (问句里的写法, 原文里的写法, 三语名称)
_ALLERGENS = {
    # 问句侧放宽拼写：Whisper 会写出 Erdnüße、säsam，还会把 Sesam 粘在前一个词上（Teigtaschensäsam）
    "peanut": (r"花生|peanuts?|erdn(?:uss|üss|üß|uess)\w*",
               r"花生|peanut|erdn(?:uss|üss)",
               {"zh": "花生", "de": "Erdnüsse", "en": "peanuts"}),
    "treenut": (r"腰果|杏仁|核桃|榛子|开心果|碧根果|夏威夷果|tree ?nuts?|cashew\w*|almonds?|walnuts?|hazelnuts?"
                r"|pistachios?|pecans?|macadamia\w*|schalenfr\w*|mandel\w*|walnüss\w*|walnuss\w*|haselnüss\w*"
                r"|haselnuss\w*|pistazie\w*",
                r"坚果|腰果|杏仁|核桃|榛子|开心果|碧根果|夏威夷果|tree ?nuts?|(?<!pea)nuts?\b|cashew|almond|walnut"
                r"|hazelnut|pistachio|pecan|macadamia|schalenfr|mandel|walnuss|walnüss|haselnuss|haselnüss|pistazie"
                r"|(?<!erd)nüsse",
                {"zh": "坚果", "de": "Schalenfrüchte", "en": "tree nuts"}),
    "sesame": (r"芝麻|s[eäa]sam\w*", r"芝麻|sesam", {"zh": "芝麻", "de": "Sesam", "en": "sesame"}),
    "gluten": (r"麸质|麦麸|小麦|面筋|gluten|wheat|weizen|dinkel",
               r"麸质|麦麸|小麦|大麦|黑麦|燕麦|面筋|gluten|wheat|barley|\brye\b|\boats?\b|weizen|gerste|roggen|hafer|dinkel",
               {"zh": "麸质", "de": "Gluten", "en": "gluten"}),
    "soy": (r"大豆|黄豆|\bsoy\w*|\bsoja\w*", r"大豆|黄豆|\bsoy|\bsoja", {"zh": "大豆", "de": "Soja", "en": "soy"}),
    "milk": (r"牛奶|乳制品|乳糖|奶|\bmilk\b|lactose|dairy|milch\w*|laktose",
             r"牛奶|乳制品|乳糖|乳清|奶|milk|lactose|milch|laktose|sahne",
             {"zh": "牛奶", "de": "Milch", "en": "milk"}),
    # 「鸡蛋白」是蛋清，要认；「大豆蛋白」是蛋白质，不能认成鸡蛋
    "egg": (r"鸡蛋|蛋|\beggs?\b|\beier\b|\bei\b",
            r"鸡蛋|蛋清|蛋黄|蛋类|(?<!白)蛋(?!白)|\beggs?\b|\beier\b|\bei\b|hühnerei|vollei|eigelb",
            {"zh": "鸡蛋", "de": "Eier", "en": "egg"}),
    "fish": (r"(?<![鱿章墨])鱼(?!香)|\bfish\b|(?<!tinten)fisch\w*",
             r"(?<![鱿章墨])鱼(?!香)|\bfish\b|(?<!tinten)fisch",
             {"zh": "鱼类", "de": "Fisch", "en": "fish"}),
    "crustacean": (r"甲壳|虾|蟹|crustaceans?|shellfish|shrimps?|prawns?|crabs?|lobsters?|krebstier\w*"
                   r"|schalentier\w*|garnele\w*|krabbe\w*|hummer",
                   r"甲壳|虾|蟹|crustacean|shellfish|shrimp|prawn|crab|lobster|krebstier|schalentier|garnele|krabbe|hummer",
                   {"zh": "甲壳类", "de": "Krebstiere", "en": "crustaceans"}),
    "mollusc": (r"软体动物|贝类|牡蛎|生蚝|鱿鱼|章鱼|mollus\w*|oysters?|squid|octopus|weichtier\w*|auster\w*"
                r"|tintenfisch\w*|muschel\w*",
                r"软体|贝类|牡蛎|生蚝|蚝|鱿鱼|章鱼|墨鱼|mollus|oyster|squid|octopus|weichtier|auster|tintenfisch|muschel",
                {"zh": "软体动物", "de": "Weichtiere", "en": "molluscs"}),
    "celery": (r"芹菜|celery|sellerie", r"芹菜|celery|sellerie", {"zh": "芹菜", "de": "Sellerie", "en": "celery"}),
    "mustard": (r"芥末|mustard|\bsenf\b", r"芥末|芥菜|mustard|\bsenf", {"zh": "芥末", "de": "Senf", "en": "mustard"}),
    "sulphite": (r"亚硫酸|sulph?ites?|sulfit\w*", r"亚硫酸|二氧化硫|sulph?it|sulfur dioxide|sulphur dioxide|schwefel",
                 {"zh": "亚硫酸盐", "de": "Sulfite", "en": "sulphites"}),
    "lupin": (r"羽扇豆|lupin\w*", r"羽扇豆|lupin", {"zh": "羽扇豆", "de": "Lupinen", "en": "lupin"}),
}
# 只说「坚果 / nuts / Nüsse」时，花生和树坚果都要报：对过敏的人宁可多报
_GENERIC_NUTS = r"坚果|\bnuts?\b|\bn(?:uss|üsse)(?:frei)?\b"

_TRACE_MARK = re.compile(
    r"可能含有|可能含|可能有|微量|痕量|may contain|might contain|can contain|traces? of"
    r"|kann\s+spuren|können\s+spuren|spuren\s+von|kann\b[^.。]{0,40}?enthalten",
    re.I,
)

_SCREEN = re.compile(r"allerg|过敏(?!原)|不含|不能吃|不吃|\bohne\b|\bwithout\b|\bfree\b|frei\b", re.I)
_PRESENCE = re.compile(
    r"contain|\bis there\b|\bare there\b|\bany\b|\bhave\b|\bhas\b|\bwith\b"
    r"|\bdrin\b|\bdarin\b|enthält|enthalten|\bgibt\b|\bist\b|\bsind\b|\bhaben\b|\bhat\b|\bmit\b"
    r"|有没有|有|含",
    re.I,
)
_PRONOUN = re.compile(
    r"\b(?:it|its|this|that|these|those|they|them|da|darin|es|dies|diese|dieser|dieses)\b"
    r"|它|这个|这款|那个|那款|这些|那些|这道|那道",
    re.I,
)
# 泛指「商品 / Gerichte / dishes」的词，不算点名
_GENERIC_NOUN = re.compile(r"\bdish(?:es)?\b|\bgerichte?\b|\bmeals?\b|菜品|菜", re.I)

_STOP_WORDS = frozenset("""
i im am is are was be a an the there theres any anything something some in on at of to for with without free from
contain contains containing contained have has had do does did dont doesnt which what whats can could would should
will eat eating buy safe allergic allergy allergies severe very please hi hello hey food foods item items product
products here machine vending now right today currently available shelf ok so and or but not no trace traces may
might inside also still too really sure everything all none other others like tell know check need want get one ones
kind kinds type types me my you your we us our
ich bin habe hab eine einen einer eines ein der die das den dem des ist sind gibt gibts es im am an auf gegen von vom
mit ohne frei drin darin drinnen enthält enthalten haben hat was welche welcher welches welchen kann können darf
dürfen essen kaufen sicher allergisch allergie allergien bitte hallo gerade jetzt heute hier automat automaten auch
noch etwas irgendwas kein keine keinen keiner nicht spuren und oder aber sehr alle alles andere anderen mir mich du
sie wir ihr man ja nein denn mal schon vielleicht produkt produkte sachen wo zu
""".split())
_STOP_ZH = sorted("""
我 你 您 对 有点 有些 严重 过敏 有没有 没有 含不含 含有 不含 不能吃 不吃 能吃 可以吃 吃 里面 里头 里边 里 中 吗 么 嘛 呢
啊 呀 吧 的 了 哪些 哪个 哪款 什么 东西 商品 食物 现在 目前 机器 这里 请问 一下 都 也 还 是 会 可能 微量 痕量 成分
任何 一点 所有 其他 别的 安全 帮我 看看 告诉我 买 能 可以 要 想 有 含 带 不 请 问
""".split(), key=len, reverse=True)

# 「Spuren von …」要与格：Erdnüssen、Eiern
_DE_DATIVE = {"Erdnüsse": "Erdnüssen", "Schalenfrüchte": "Schalenfrüchten", "Eier": "Eiern",
              "Krebstiere": "Krebstieren", "Weichtiere": "Weichtieren", "Sulfite": "Sulfiten"}


def _de_dative(names):
    return " oder ".join(_DE_DATIVE.get(name, name) for name in names.split(" oder "))


_TEXT = {
    "zh": {"sep": "。", "join": lambda xs: "、".join(xs), "or": "或",
           "contains": lambda n, k, x: f"{n}含{x}",
           "traces": lambda n, k, x: f"{n}可能含微量{x}",
           "nodata": lambda n, k, x: f"{n}没有过敏原资料",
           "clean": lambda n, k, x: f"{n}的资料里没提到{x}",
           "clean_rest": lambda x: f"其余几款资料里没提到{x}",
           "clean_all": lambda x: f"货架上的商品资料里都没提到{x}",
           "tail": "以包装标签为准。"},
    "de": {"sep": ". ", "join": lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " und " + xs[-1],
           "or": " oder ",
           "contains": lambda n, k, x: f"{n} {'enthält' if k == 1 else 'enthalten'} {x}",
           "traces": lambda n, k, x: f"{n} {'kann' if k == 1 else 'können'} Spuren von {_de_dative(x)} enthalten",
           "nodata": lambda n, k, x: f"Zu {n} gibt es keine Allergenangaben",
           "clean": lambda n, k, x: f"{n} {'hat' if k == 1 else 'haben'} keinen Hinweis auf {x}",
           "clean_rest": lambda x: f"Die übrigen Produkte haben keinen Hinweis auf {x}",
           "clean_all": lambda x: f"Kein Produkt im Automaten hat einen Hinweis auf {x}",
           "tail": "Bitte prüfe trotzdem das Etikett."},
    "en": {"sep": ". ", "join": lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1],
           "or": " or ",
           "contains": lambda n, k, x: f"{n} {'contains' if k == 1 else 'contain'} {x}",
           "traces": lambda n, k, x: f"{n} may contain traces of {x}",
           "nodata": lambda n, k, x: f"{n} {'has' if k == 1 else 'have'} no allergen information",
           "clean": lambda n, k, x: f"{n} {'doesn' if k == 1 else 'don'}'t list {x}",
           "clean_rest": lambda x: f"The other items don't list {x}",
           "clean_all": lambda x: f"None of the items on the shelf list {x}",
           "tail": "Please check the package label too."},
}


def split_allergen_text(text):
    """把过敏原原文切成（含有，可能含痕量）两段。"""
    text = text or ""
    mark = _TRACE_MARK.search(text)
    return (text[:mark.start()], text[mark.start():]) if mark else (text, "")


def allergen_status(text, keys):
    """contains / traces / clean / nodata。keys 里任一过敏原命中即算。"""
    if not (text or "").strip():
        return "nodata"
    contains, traces = split_allergen_text(text)
    if any(re.search(_ALLERGENS[key][1], contains, re.I) for key in keys):
        return "contains"
    if any(re.search(_ALLERGENS[key][1], traces, re.I) for key in keys):
        return "traces"
    return "clean"


def _blank(text, start, end):
    return text[:start] + " " * (end - start) + text[end:]


def _remove_alias(text, alias):
    boundary = r"(?<![a-z0-9])" if alias[0].isascii() and alias[0].isalnum() else ""
    ending = r"(?![a-z0-9])" if alias[-1].isascii() and alias[-1].isalnum() else ""
    return re.sub(boundary + re.escape(alias) + ending, " ", text)


def _is_dish_word(text, match):
    """「虾饺」「shrimp dumpling」「Fish-Style Penne」「蛋糕」里的过敏原字样是菜名的一部分。"""
    if _PRODUCT_NOUN.search(match.group(0)) or _PRODUCT_NOUN.match(text, match.start()):
        return True
    tail = text[match.end():].lstrip(" -")
    return bool(_PRODUCT_NOUN.match(tail) or re.match(r"(?:style|art)\b", tail, re.I))


def _find_allergens(text):
    keys, spans = [], []
    for key, (pattern, _, _) in _ALLERGENS.items():
        for match in re.finditer(pattern, text, re.I):
            if not _is_dish_word(text, match):
                keys.append(key)
                spans.append(match.span())
    for match in re.finditer(_GENERIC_NUTS, text, re.I):
        if not _is_dish_word(text, match):
            keys += ["peanut", "treenut"]
            spans.append(match.span())
    for start, end in spans:
        text = _blank(text, start, end)
    return list(dict.fromkeys(keys)), text


def _leftover(text, extra_words=frozenset(), extra_zh=()):
    """去掉虚词、泛指名词后还剩认不出的实词吗。素食直答复用它，带上自己的额外虚词。"""
    text = _GENERIC_NOUN.sub(" ", text)
    for phrase in sorted(set(_STOP_ZH) | set(extra_zh), key=len, reverse=True):
        text = text.replace(phrase, " ")
    if re.search(r"[\u4e00-\u9fff]", text):
        return True
    words = re.findall(r"[a-zäöüß]+", text)
    return any(word not in _STOP_WORDS and word not in extra_words for word in words)


def _language(text):
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[äöüß]", text) or re.search(
            r"\b(?:ich|bin|ist|sind|gibt|gegen|drin|enthält|enthalten|ohne|den|der|die|das|welche|habe|kann"
            r"|bitte|auch|mit)\b", text):
        return "de"
    return "en"


def _dish_for(name, dishes):
    """货架商品名 → 目录条目。同名多条时优先有过敏原原文的；原文互相矛盾就当没有资料。"""
    target = normalize(name)
    hits = [d for d in dishes if target in _aliases(d)]
    if not hits:
        hits = [d for d in dishes if _mentions(target, normalize(d["name"])) or _mentions(normalize(d["name"]), target)]
    with_text = [d for d in hits if (d.get("allergen_text") or "").strip()]
    if len({d["allergen_text"].strip() for d in with_text}) > 1:
        return None
    return (with_text or hits or [None])[0]


def _display(name):
    """菜名去掉 emoji 和末尾份量括号，用来念。"""
    name = "".join(c for c in name if c.isalnum() or c in " ()（）&-.,'").strip()
    return re.sub(r"\s*[(（][^()（）]*[)）]$", "", name).strip() or name


def _shelf_names(item, dish):
    names = {normalize(item["name"]), re.sub(r"\s*\([^()]*\)$", "", normalize(item["name"]))}
    if dish:
        names |= _aliases(dish)
    return {n for n in names if len(n) >= 2}


def local_allergen_answer(query, context, data, settings, menu_settings):
    """命中则返回答案文本，否则 None（交给原有路径）。"""
    if not settings.get("local_allergen_answers") or not isinstance(query, str):
        return None
    if context == settings.get("unavailable_context"):
        return None
    items = valid_inventory(data)
    if not items:
        return None
    shelf = [item for item in items if item["purchasable"]]
    if not shelf:
        return None
    try:
        dishes = load_catalog(str((menu_settings or {}).get("path") or DEFAULT_CATALOG))["dishes"]
    except (OSError, ValueError, TypeError):
        return None

    text = normalize(normalize_query(query))
    # 1. 点名的货架商品（先去掉商品名，免得「Fish-Style Penne」被当成在问鱼）
    shelf_dishes = [(item, _dish_for(item["name"], dishes)) for item in shelf]
    named = []
    for item, dish in shelf_dishes:
        hit = [alias for alias in _shelf_names(item, dish) if _mentions(text, alias)]
        if hit:
            named.append((item, dish))
            for alias in sorted(hit, key=len, reverse=True):
                text = _remove_alias(text, alias)

    keys, rest = _find_allergens(text)
    if not keys:
        return None
    original = normalize_query(query).casefold()
    if not (_SCREEN.search(original) or _PRESENCE.search(original)):
        return None
    language = _language(re.sub(r"\s+", " ", rest))

    scope, catalog_hits = None, None
    if named:
        if _leftover(rest):
            return None
        scope = named
    else:
        # 2. 一类商品：饺子 / Nudeln / fried rice
        cat_rest, cat_items = rest, []
        for query_pattern, item_pattern in _CATEGORIES:
            if re.search(query_pattern, cat_rest, re.I):
                cat_rest = re.sub(query_pattern, " ", cat_rest, flags=re.I)
                cat_items += [(item, dish) for item, dish in shelf_dishes
                              if re.search(item_pattern, item["name"] + " " + (dish or {}).get("name", ""), re.I)]
        if cat_items and not _leftover(cat_rest):
            scope = list({id(pair[0]): pair for pair in cat_items}.values())
        else:
            # 3. 目录里的菜名（不在货架上的菜也能答资料）
            hits, alias_rest = [], rest
            for dish in dishes:
                matched = [alias for alias in _aliases(dish) if len(alias) >= 2 and _mentions(rest, alias)]
                if matched:
                    hits.append(dish)
                    for alias in sorted(matched, key=len, reverse=True):
                        alias_rest = _remove_alias(alias_rest, alias)
            if hits and not _leftover(alias_rest):
                catalog_hits = hits
            elif _PRODUCT_NOUN.search(_GENERIC_NOUN.sub(" ", rest)) or _leftover(rest):
                return None
            elif _PRONOUN.search(re.sub(r"\bgibt\s+es\b", " ", original)):
                return None
            else:
                scope = None  # 4. 没提商品：货架上全部可购买商品

    words = _TEXT[language]
    allergen = words["or"].join(dict.fromkeys(_ALLERGENS[key][2][language] for key in keys))

    if catalog_hits is not None:
        statuses = {allergen_status(dish.get("allergen_text"), keys) for dish in catalog_hits}
        if len(statuses) != 1:
            return None
        status = statuses.pop()
        name = _display(catalog_hits[0]["name"])
        return words[status](name, 1, allergen) + words["sep"].rstrip() + " " * (language != "zh") + words["tail"]

    pairs = scope if scope is not None else shelf_dishes
    groups = {"contains": [], "traces": [], "nodata": [], "clean": []}
    for item, dish in pairs:
        status = allergen_status((dish or {}).get("allergen_text"), keys)
        name = item["name"].strip()
        if name not in groups[status]:
            groups[status].append(name)
    parts = []
    for status in ("contains", "traces", "nodata"):
        if groups[status]:
            parts.append(words[status](words["join"](groups[status]), len(groups[status]), allergen))
    if groups["clean"]:
        if scope is not None:
            parts.append(words["clean"](words["join"](groups["clean"]), len(groups["clean"]), allergen))
        else:
            parts.append(words["clean_rest"](allergen) if parts else words["clean_all"](allergen))
    sep = words["sep"]
    return sep.join(parts) + sep.rstrip() + (" " if language != "zh" else "") + words["tail"]
