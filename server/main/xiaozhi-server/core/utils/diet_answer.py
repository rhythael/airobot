# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""素食 / 不吃某种肉的问法走本地规则，不经过大模型（第三轮 debug，2026-10-05）。

为什么：模型把 Fried Rice with Asian Sausage、Gewürzte Schweinehackfleisch-Nudeln、
Korean Spicy Chicken Noodles 说成素食，或虚报「另外两款素食」，有无每轮提示分别 3/6、2/6 出错。
这类答案由资料决定，和过敏原一样不该交给模型。

怎么判断：菜名开头的表情（🌱🐔🐮🐷🐑🦐🐟）是按主料粗分，不是素食保证——🌱 组里有用蚝油、
鸡精的菜，标「素」的金汤酸菜火锅配料里有虾仁和炸鸡肉。所以「表情 + 菜名和配料原文」一起看；
配料原文里的「素鸡、素蚝油、鸡蛋、牛奶、牛肝菌、鸡油菌、鱼香、Fish-Style」这类写法不算肉。
不看过敏原原文：那里的「可能含微量鱼类」是交叉污染提示，不是配料。

边界和过敏原直答一样：商品范围认不清（剩下认不出的实词、代词指前文、点名了货架外又对不上的菜）
就不答，交回模型；库存不可用不答。
"""
import json
import re

from core.utils.allergen_answer import (
    _CATEGORIES, _PRONOUN, _dish_for, _language, _leftover, _remove_alias, _shelf_names,
)
from core.utils.menu_knowledge import DEFAULT_CATALOG, _aliases, _mentions, load_catalog, normalize
from core.utils.template_answers import _de_number, _en_number, zh_number
from core.utils.turn_context import normalize_query, valid_inventory

# 动物性成分。排除项都来自目录里真实出现的写法
_ANIMAL = {
    "chicken": r"(?<!素)鸡(?!蛋|油菌|枞|腿菇|头米)|chicken(?![- ]?(?:style|free))|hähnchen|hühnchen|hühner(?!ei)"
               r"|\bhuhn\b|geflügel|poultry",
    "pork": r"猪|(?<!素)叉烧|火腿|培根|腊肉|腊肠|(?<!素)香肠|\bpork\b|bacon|\bham\b|\blard\b|salami|schwein|\bspeck\b"
            r"|schinken|schmalz",
    "beef": r"牛(?!奶|肝菌|蒡|油果|角椒|乳)|\bbeef\b|\brind(?!e\b)\w*",
    "lamb": r"羊(?!奶|肚菌|乳)|\blamb\b|mutton|\blamm\w*",
    "duck": r"鸭|\bduck\b|\bente\b",
    "fish": r"(?<![素鱿章墨])鱼(?!香)|\bfish\b(?![- ]?(?:style|art|free))|\btuna\b|salmon|anchov"
            r"|(?<!tinten)fisch(?![- ]?(?:art|style))|thunfisch|lachs|sardelle",
    "seafood": r"虾|蟹|(?<!素)蚝|(?<!干)贝(?!果)|干贝|鱿鱼|章鱼|墨鱼|海鲜|\bshrimps?\b|\bprawns?\b|\bcrabs?\b"
               r"|oyster(?![- ]?mushroom)|squid|octopus|mussel|garnele|krabbe|auster(?!npilz|nseitling)"
               r"|tintenfisch|muschel|meeresfrücht|seafood",
    "meat": r"(?<![素果椰蟹蛋])肉(?!桂|豆蔻|松)|\bmeat\b(?![- ]?(?:free|style|alternative|substitute))"
            r"|(?<!ohne )fleisch(?!ersatz|los|frei)|\bwurst\b|gelatin|明胶|骨汤",
}
_EMOJI_KIND = {"🐔": "chicken", "🐮": "beef", "🐷": "pork", "🐑": "lamb", "🦐": "seafood", "🍤": "seafood",
               "🐟": "fish", "🦆": "duck"}

_KIND_NAMES = {
    "zh": {"chicken": "鸡肉", "pork": "猪肉", "beef": "牛肉", "lamb": "羊肉", "duck": "鸭肉", "fish": "鱼",
           "seafood": "海鲜", "meat": "肉"},
    "de": {"chicken": "Hähnchen", "pork": "Schweinefleisch", "beef": "Rindfleisch", "lamb": "Lammfleisch",
           "duck": "Ente", "fish": "Fisch", "seafood": "Meeresfrüchte", "meat": "Fleisch"},
    "en": {"chicken": "chicken", "pork": "pork", "beef": "beef", "lamb": "lamb", "duck": "duck", "fish": "fish",
           "seafood": "seafood", "meat": "meat"},
}

# 「enthalten Bestandteile von …」用来源名：鸡精、明胶不是整块肉
_DE_SOURCE = {"Hähnchen": "Huhn", "Schweinefleisch": "Schwein", "Rindfleisch": "Rind", "Lammfleisch": "Lamm",
              "Meeresfrüchte": "Meeresfrüchten"}

_VEG_TRIGGER = (r"素食|素菜|素的|吃素|全素|纯素|不吃肉|不要肉|没有肉|不含肉|无肉|vegetari\w*|vegan\w*|veggie"
                r"|meat[- ]?free|meatless|without meat|no meat|(?:dont|do not) eat meat|ohne fleisch"
                r"|kein\w* fleisch|fleischlos|fleischfrei")
_AVOID = {
    "chicken": r"不吃鸡肉?|不要鸡肉|不含鸡肉|没有鸡肉|(?:no|without|dont eat|do not eat) chicken"
               r"|(?:ohne|kein\w*) (?:hähnchen|huhn|hühnchen|hühnerfleisch|geflügel)",
    "pork": r"不吃猪肉?|不要猪肉|不含猪肉|没有猪肉|(?:no|without|dont eat|do not eat) pork|(?:ohne|kein\w*) schwein\w*",
    "beef": r"不吃牛肉?|不要牛肉|不含牛肉|没有牛肉|(?:no|without|dont eat|do not eat) beef|(?:ohne|kein\w*) rind\w*",
    "lamb": r"不吃羊肉?|不要羊肉|(?:no|without|dont eat|do not eat) (?:lamb|mutton)|(?:ohne|kein\w*) lamm\w*",
}
_DIET_STOP = frozenset("""
vegetarisch vegetarische vegetarischen vegetarisches vegetarian vegan vegane veganes veggie recommend recommendation
suggest suggestion empfehlen empfiehlst empfehlung möchte mag gern gerne suche option options meat fleisch esse iss
gibts eat
""".split())
_DIET_STOP_ZH = ("推荐", "有什么", "给我", "想要", "想吃", "来点", "一些", "素", "肉", "可以选", "选")
_DIET_PRONOUN = re.compile(_PRONOUN.pattern + r"|\bdas\b|这道", re.I)

_TEXT = {
    "zh": {"join": "、".join, "slot": lambda name, slots: f"{'和'.join(slots)}货道的{name}",
           "veg": lambda names, n: f"素食为主的有{names}",
           "veg_lead": lambda n: f"有{zh_number(n)}款素食为主",
           "avoid_lead": lambda kind, n: f"不吃{kind}的话，有{zh_number(n)}款可以选",
           "veg_none": "货架上现在没有素食",
           "veg_but": lambda names, n, kinds: f"{names}标的是素食，但配料里有{kinds}",
           "meat_rest": "其余几款含肉或海鲜",
           "all_meat": "这几款都含肉或海鲜",
           "menu_veg": "菜单上有素食为主的菜，这台机器现在没有货",
           "item_veg": lambda name: f"{name}是素食为主",
           "item_has": lambda name, kinds: f"{name}含{kinds}",
           "avoid_ok": lambda kind, names: f"不吃{kind}的话，可以选{names}",
           "avoid_none": lambda kind: f"货架上几款都含{kind}",
           "avoid_has": lambda names, n, kind: f"{names}含{kind}成分",
           "avoid_rest": lambda kind: f"其余几款含{kind}成分",
           "group_meat": lambda names, n: f"{names}含肉或海鲜",
           "unknown": lambda names, n: f"{names}资料不足",
           "more": lambda k: f"，还有{zh_number(k)}款",
           "sep": "。", "tail": "以包装配料为准。"},
    "de": {"join": lambda xs: "" if not xs else xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " und " + xs[-1],
           "slot": lambda name, slots: f"{name} in Fach {' und '.join(slots)}",
           "veg": lambda names, n: f"Vegetarisch {'ist' if n == 1 else 'sind'} {names}",
           "veg_lead": lambda n: "Es gibt ein vegetarisches Gericht" if n == 1 else f"Es gibt {_de_number(n)} vegetarische Gerichte",
           "avoid_lead": lambda kind, n: f"Ohne {kind} gibt es {'ein Gericht' if n == 1 else _de_number(n) + ' Gerichte'}",
           "veg_none": "Gerade gibt es hier nichts Vegetarisches",
           "veg_but": lambda names, n, kinds: f"{names} {'ist' if n == 1 else 'sind'} als vegetarisch markiert, "
                                              f"laut Zutaten aber mit {kinds}",
           "meat_rest": "Die übrigen Produkte enthalten Fleisch oder Fisch",
           "all_meat": "Alle Produkte im Automaten enthalten Fleisch oder Fisch",
           "menu_veg": "Auf der Karte gibt es vegetarische Gerichte, aber gerade nicht im Automaten",
           "item_veg": lambda name: f"{name} ist vegetarisch",
           "item_has": lambda name, kinds: f"{name} enthält {kinds}",
           "avoid_ok": lambda kind, names: f"Ohne {kind}: {names}",
           "avoid_none": lambda kind: f"Alle Produkte im Automaten enthalten {kind}",
           "avoid_has": lambda names, n, kind: f"{names} {'enthält' if n == 1 else 'enthalten'} Bestandteile von {_DE_SOURCE.get(kind, kind)}",
           "avoid_rest": lambda kind: f"Die übrigen Produkte enthalten Bestandteile von {_DE_SOURCE.get(kind, kind)}",
           "group_meat": lambda names, n: f"{names} {'enthält' if n == 1 else 'enthalten'} Fleisch oder Fisch",
           "unknown": lambda names, n: f"Zu {names} fehlen Angaben",
           "more": lambda k: f" und {_de_number(k)} weitere",
           "sep": ". ", "tail": "Bitte prüfe die Zutaten auf der Verpackung."},
    "en": {"join": lambda xs: "" if not xs else xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1],
           "slot": lambda name, slots: f"{name} in slot {' and '.join(slots)}",
           "veg": lambda names, n: f"{names} {'is' if n == 1 else 'are'} vegetarian",
           "veg_lead": lambda n: "One item is vegetarian" if n == 1 else f"{_en_number(n, True)} items are vegetarian",
           "avoid_lead": lambda kind, n: f"One item has no {kind}" if n == 1 else f"{_en_number(n, True)} items have no {kind}",
           "veg_none": "Nothing on the shelf is vegetarian right now",
           "veg_but": lambda names, n, kinds: f"{names} {'is' if n == 1 else 'are'} marked vegetarian, "
                                              f"but the ingredients include {kinds}",
           "meat_rest": "The other items contain meat or fish",
           "all_meat": "Everything in the machine contains meat or fish",
           "menu_veg": "The menu has vegetarian dishes, but none are in the machine right now",
           "item_veg": lambda name: f"{name} is vegetarian",
           "item_has": lambda name, kinds: f"{name} contains {kinds}",
           "avoid_ok": lambda kind, names: f"Without {kind}: {names}",
           "avoid_none": lambda kind: f"Everything on the shelf contains {kind}",
           "avoid_has": lambda names, n, kind: f"{names} {'contains' if n == 1 else 'contain'} {kind} ingredients",
           "avoid_rest": lambda kind: f"The other items contain {kind} ingredients",
           "group_meat": lambda names, n: f"{names} {'contains' if n == 1 else 'contain'} meat or fish",
           "unknown": lambda names, n: f"{names} {'has' if n == 1 else 'have'} no ingredient information",
           "more": lambda k: f" and {_en_number(k)} more",
           "sep": ". ", "tail": "Please check the ingredients on the package."},
}
_MAX_NAMES = 4


def _ingredients_text(dish):
    value = dish.get("ingredients") or ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def animal_terms(dish):
    """{kind: [原文写法…]}：菜名表情 + 菜名和配料原文里的动物性成分。"""
    found = {}
    for char, kind in _EMOJI_KIND.items():
        if char in dish.get("name", ""):
            found.setdefault(kind, []).append(char)
    text = dish.get("name", "") + " " + _ingredients_text(dish)
    for kind, pattern in _ANIMAL.items():
        hits = sorted({m.group(0) for m in re.finditer(pattern, text, re.I)})
        if hits:
            found.setdefault(kind, []).extend(hits)
    return found


def _specific(kinds):
    """有具体肉类时去掉泛指的 meat，免得念成「含鸡肉和肉」。"""
    kinds = list(kinds)
    return [k for k in kinds if k != "meat"] if len(kinds) > 1 else kinds


def _has_data(dish):
    return bool(dish) and (bool(_ingredients_text(dish).strip()) or any(c in dish["name"] for c in "🌱" + "".join(_EMOJI_KIND)))


def _veg_status(dish):
    if not _has_data(dish):
        return "unknown", []
    kinds = _specific(animal_terms(dish))
    if not kinds:
        return "veg", []
    return ("veg_but" if "🌱" in dish["name"] else "meat"), kinds


def _avoid_status(dish, kind):
    if not _has_data(dish):
        return "unknown"
    kinds = animal_terms(dish)
    if kind in kinds:
        return "has"
    # 只写了「肉」「Fleisch」没说是什么肉，又没有主料表情，不能替顾客打包票
    if "meat" in kinds and not any(c in dish["name"] for c in _EMOJI_KIND):
        return "unknown"
    return "ok"


def _cap(words, names):
    shown = words["join"](names[:_MAX_NAMES])
    return shown + (words["more"](len(names) - _MAX_NAMES) if len(names) > _MAX_NAMES else "")


def _load(query, context, data, settings, flag, menu_settings):
    """开关、库存、目录都就绪才答。返回 (归一化问句, [(货架商品, 目录条目)], 目录) 或 None。"""
    if not settings.get(flag) or not isinstance(query, str):
        return None
    if context == settings.get("unavailable_context"):
        return None
    items = valid_inventory(data)
    if not items:
        return None
    shelf = [item for item in items if item["purchasable"]]
    try:
        dishes = load_catalog(str((menu_settings or {}).get("path") or DEFAULT_CATALOG))["dishes"]
    except (OSError, ValueError, TypeError):
        return None
    text = normalize(normalize_query(query)).replace("'", "")
    return text, [(item, _dish_for(item["name"], dishes)) for item in shelf], dishes


def _named_shelf(text, shelf_dishes):
    """点名的货架商品，以及去掉这些菜名后的问句。先去菜名：「Korean Spicy Chicken Noodles」里的
    Spicy、「Plant-Based Fish-Style Penne」里的 Fish 都不是顾客在问的东西。"""
    named, rest = [], text
    for item, dish in shelf_dishes:
        hit = [alias for alias in _shelf_names(item, dish) if _mentions(rest, alias)]
        if hit:
            named.append((item, dish))
            for alias in sorted(hit, key=len, reverse=True):
                rest = _remove_alias(rest, alias)
    return named, rest


def _resolve_scope(named, rest, shelf_dishes, dishes, stop_words, stop_zh):
    """问的是哪几款：点名的货架商品 / 一类商品 / 目录里的菜 / 整个货架。
    返回 (scope, catalog_hits, 判语言用的残句)；scope 为 None 表示整个货架。认不清返回 None。"""
    if named:
        return (None if _leftover(rest, stop_words, stop_zh) else (named, None, rest))
    cat_rest, cat_items = rest, []
    for query_pattern, item_pattern in _CATEGORIES:
        if re.search(query_pattern, cat_rest, re.I):
            cat_rest = re.sub(query_pattern, " ", cat_rest, flags=re.I)
            cat_items += [(item, dish) for item, dish in shelf_dishes
                          if re.search(item_pattern, item["name"] + " " + (dish or {}).get("name", ""), re.I)]
    if cat_items and not _leftover(cat_rest, stop_words, stop_zh):
        return list({id(pair[0]): pair for pair in cat_items}.values()), None, rest
    matched_by_dish = []
    for dish in dishes:
        matched = [alias for alias in _aliases(dish) if len(alias) >= 2 and _mentions(rest, alias)]
        if matched:
            matched_by_dish.append((dish, max(matched, key=len), matched))
    # 只留最具体的菜名：「湘味小炒黄牛肉盖饭」不能同时算成另一道「小炒黄牛肉盖饭」
    longest = [best for _, best, _ in matched_by_dish]
    hits, alias_rest = [], rest
    for dish, best, matched in matched_by_dish:
        if any(best != other and best in other for other in longest):
            continue
        hits.append(dish)
        for alias in sorted(matched, key=len, reverse=True):
            alias_rest = _remove_alias(alias_rest, alias)
    if hits and not _leftover(alias_rest, stop_words, stop_zh):
        # 「Is 金汤酸菜味迷你火锅 vegetarian?」：中文菜名不能把答话语言带成中文
        return None, hits, alias_rest
    if _leftover(rest, stop_words, stop_zh) or _DIET_PRONOUN.search(rest):
        return None
    return None, None, rest


def _language_of(rest_with_trigger, catalog_hits):
    """判答话语言：去掉菜名、保留问法关键词。「Penne辣吗」去掉「辣吗」就只剩空串，会误判成英语。"""
    text = rest_with_trigger
    for dish in catalog_hits or []:
        for alias in sorted(_aliases(dish), key=len, reverse=True):
            if len(alias) >= 2:
                text = _remove_alias(text, alias)
    return _language(re.sub(r"\s+", " ", text))


def local_diet_answer(query, context, data, settings, menu_settings):
    """命中则返回答案文本，否则 None（交给原有路径）。"""
    loaded = _load(query, context, data, settings, "local_diet_answers", menu_settings)
    if loaded is None:
        return None
    text, shelf_dishes, dishes = loaded
    avoid = next((kind for kind, pattern in _AVOID.items() if re.search(pattern, text, re.I)), None)
    vegetarian = avoid is None and re.search(_VEG_TRIGGER, text, re.I) is not None
    if not (avoid or vegetarian):
        return None

    named, with_trigger = _named_shelf(text, shelf_dishes)
    rest = re.sub(_AVOID[avoid] if avoid else _VEG_TRIGGER, " ", with_trigger, flags=re.I)
    resolved = _resolve_scope(named, rest, shelf_dishes, dishes, _DIET_STOP, _DIET_STOP_ZH)
    if resolved is None:
        return None
    scope, catalog_hits, _ = resolved
    language = _language_of(with_trigger, catalog_hits)
    words = _TEXT[language]

    sep = words["sep"]
    if catalog_hits is not None:
        # 目录里的菜（不一定在货架上）：几条同名记录结论一致才答
        if vegetarian:
            results = {(_veg_status(d)[0], tuple(_veg_status(d)[1])) for d in catalog_hits}
        else:
            results = {(_avoid_status(d, avoid), ()) for d in catalog_hits}
        if len(results) != 1:
            return None
        status, kinds = results.pop()
        name = re.sub(r"\s*[(（][^()（）]*[)）]$", "", "".join(
            c for c in catalog_hits[0]["name"] if c.isalnum() or c in " ()（）&-.,'").strip())
        kind_names = words["join"]([_KIND_NAMES[language][k] for k in kinds])
        if vegetarian:
            sentence = words["item_veg"](name) if status == "veg" else (
                words["unknown"](name, 1) if status == "unknown" else words["item_has"](name, kind_names))
        else:
            kind_name = _KIND_NAMES[language][avoid]
            sentence = words["avoid_has"](name, 1, kind_name) if status == "has" else (
                words["unknown"](name, 1) if status == "unknown" else words["avoid_ok"](kind_name, name))
        return sentence + sep.rstrip() + (" " if language != "zh" else "") + words["tail"]

    pairs = scope if scope is not None else shelf_dishes
    # 同名商品合并货道：Korean Spicy Chicken Noodles 在 1-9 和 2-9
    merged = {}
    for item, dish in sorted(pairs, key=lambda p: p[0]["slot"]):
        merged.setdefault(item["name"].strip(), {"dish": dish, "slots": []})["slots"].append(item["slot"])

    parts = []
    if vegetarian:
        groups = {"veg": [], "veg_but": [], "meat": [], "unknown": []}
        but_kinds = []
        for name, entry in merged.items():
            status, kinds = _veg_status(entry["dish"])
            groups[status].append((name, entry["slots"]))
            if status == "veg_but":
                but_kinds += [k for k in kinds if k not in but_kinds]
        if scope is not None and len(merged) == 1:
            name, entry = next(iter(merged.items()))
            status, kinds = _veg_status(entry["dish"])
            kind_names = words["join"]([_KIND_NAMES[language][k] for k in kinds])
            parts.append(words["item_veg"](name) if status == "veg" else (
                words["unknown"](name, 1) if status == "unknown" else words["item_has"](name, kind_names)))
        elif scope is not None:
            # 点名或按类别问了几款：逐组说，不扯整个货架
            if groups["veg"]:
                names = [name for name, _ in groups["veg"]]
                parts.append(words["veg"](words["join"](names), len(names)))
            if groups["veg_but"]:
                names = [name for name, _ in groups["veg_but"]]
                parts.append(words["veg_but"](words["join"](names), len(names),
                                              words["join"]([_KIND_NAMES[language][k] for k in but_kinds])))
            if groups["meat"]:
                names = [name for name, _ in groups["meat"]]
                parts.append(words["group_meat"](words["join"](names), len(names)))
            if groups["unknown"]:
                names = [name for name, _ in groups["unknown"]]
                parts.append(words["unknown"](words["join"](names), len(names)))
        else:
            # 先说一句不带菜名的短句，首句本地合成接得住；名单放第二句
            if groups["veg"]:
                listed = [words["slot"](name, slots) for name, slots in groups["veg"]]
                parts.append(words["veg_lead"](len(listed)))
                parts.append(_cap(words, listed))
            else:
                parts.append(words["veg_none"])
            if groups["veg_but"]:
                names = [name for name, _ in groups["veg_but"]]
                parts.append(words["veg_but"](words["join"](names), len(names),
                                              words["join"]([_KIND_NAMES[language][k] for k in but_kinds])))
            if groups["unknown"]:
                names = [name for name, _ in groups["unknown"]]
                parts.append(words["unknown"](words["join"](names), len(names)))
            if groups["meat"]:
                # 一款素食都没有时不能说「其余几款」
                parts.append(words["meat_rest"] if groups["veg"] else words["all_meat"])
            if not groups["veg"] and any("🌱" in d["name"] and d.get("global_status") != "全局下架" for d in dishes):
                # 提示词 <menu_vs_stock>：货架上没有时，也要告诉顾客菜单上有
                parts.append(words["menu_veg"])
    else:
        kind_name = _KIND_NAMES[language][avoid]
        groups = {"ok": [], "has": [], "unknown": []}
        for name, entry in merged.items():
            groups[_avoid_status(entry["dish"], avoid)].append((name, entry["slots"]))
        if groups["ok"]:
            listed = [words["slot"](name, slots) for name, slots in groups["ok"]]
            parts.append(words["avoid_lead"](kind_name, len(listed)))
            parts.append(_cap(words, listed))
        else:
            parts.append(words["avoid_none"](kind_name))
        if groups["has"] and groups["ok"]:
            names = [name for name, _ in groups["has"]]
            # 顾客要的是能吃的那几款；不能吃的超过两款就不逐个点名，免得回答拖到 25 秒
            parts.append(words["avoid_has"](words["join"](names), len(names), kind_name) if len(names) <= 2
                         else words["avoid_rest"](kind_name))
        if groups["unknown"]:
            names = [name for name, _ in groups["unknown"]]
            parts.append(words["unknown"](words["join"](names), len(names)))
    return sep.join(parts) + sep.rstrip() + (" " if language != "zh" else "") + words["tail"]


# ---------------------------------------------------------------------------
# 辣度（第四轮 debug，2026-10-05）
# 模型把没标辣的调味猪肉末面、黑椒牛肉炒饭、BBQ牛肉蒸饺说成辣的。目录菜名里 🌶️ 的个数就是辣度：
# 「虾仁云吞面（微辣）🌶️」「虾仁云吞面（辣）🌶️🌶️」「湘味小炒黄牛肉盖饭🌶️🌶️🌶️」。
# 少数菜名写了「辣 / Chili」却没标 🌶️，算辣但不报级别。

_NAME_SPICY = re.compile(r"辣|spicy|scharf|chili|chilli|arrabbiata", re.I)
# 「辣不辣」是在问辣不辣，不是「不辣」
_NO_SPICY = (r"不吃辣|不要辣|不能吃辣|吃不了辣|(?<!辣)不辣|怕辣|nicht\w* scharf\w*|nichts scharf\w*|ohne schärfe"
             r"|keine schärfe|kein\w* scharf\w*|not spicy|non[- ]?spicy|nothing spicy|no spicy"
             r"|(?:dont|do not|cant|cannot) (?:eat|handle|like|have) spicy|\bmild\b")
_SPICY = r"辣不辣|辣吗|辣|scharf\w*|schärfe|spicy|spiciness"
_SPICY_STOP = frozenset("""
möchte mag gern gerne bitte suche nichts etwas something please option options recommend empfehlen essen eat food
""".split())
_SPICY_STOP_ZH = ("想吃点", "吃点", "一点", "点", "不吃", "不要", "怕", "推荐", "有什么", "给我", "想要", "想吃", "来点")

_SPICY_TEXT = {
    "zh": {"join": "、".join, "level": {1: "微辣", 2: "辣", 3: "特辣", 0: "辣"},
           "slot": lambda name, slots: f"{'和'.join(slots)}货道的{name}",
           "want_lead": lambda n: f"有{zh_number(n)}款辣的",
           "want_none": "货架上现在没有辣的",
           "item_in_list": lambda slot, level: f"{slot}，{level}",
           "list_sep": "；",
           "rest_mild": "其余几款没标辣",
           "avoid_lead": lambda n: f"不吃辣的话，有{zh_number(n)}款可以选",
           "avoid_none": "货架上几款都是辣的",
           "spicy_named": lambda names, n: f"{names}是辣的",
           "spicy_rest": "其余几款是辣的",
           "item_spicy": lambda name, level: f"{name}{level}",
           "item_mild": lambda name: f"{name}没标辣",
           "unknown": lambda names, n: f"{names}资料不足",
           "more": lambda k: f"，还有{zh_number(k)}款",
           "sep": "。"},
    "de": {"join": lambda xs: "" if not xs else xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " und " + xs[-1],
           "level": {1: "leicht scharf", 2: "scharf", 3: "sehr scharf", 0: "scharf"},
           "slot": lambda name, slots: f"{name} in Fach {' und '.join(slots)}",
           "want_lead": lambda n: "Es gibt ein scharfes Gericht" if n == 1 else f"Es gibt {_de_number(n)} scharfe Gerichte",
           "want_none": "Gerade ist nichts Scharfes im Automaten",
           "item_in_list": lambda slot, level: f"{slot}, {level}",
           "list_sep": "; ",
           "rest_mild": "Die übrigen sind nicht als scharf markiert",
           "avoid_lead": lambda n: f"Ohne Schärfe gibt es {'ein Gericht' if n == 1 else _de_number(n) + ' Gerichte'}",
           "avoid_none": "Alle Produkte im Automaten sind scharf",
           "spicy_named": lambda names, n: f"{names} {'ist' if n == 1 else 'sind'} scharf",
           "spicy_rest": "Die übrigen sind scharf",
           "item_spicy": lambda name, level: f"{name} ist {level}",
           "item_mild": lambda name: f"{name} ist nicht als scharf markiert",
           "unknown": lambda names, n: f"Zu {names} fehlen Angaben",
           "more": lambda k: f" und {_de_number(k)} weitere",
           "sep": ". "},
    "en": {"join": lambda xs: "" if not xs else xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1],
           "level": {1: "mildly spicy", 2: "spicy", 3: "very spicy", 0: "spicy"},
           "slot": lambda name, slots: f"{name} in slot {' and '.join(slots)}",
           "want_lead": lambda n: "One item is spicy" if n == 1 else f"{_en_number(n, True)} items are spicy",
           "want_none": "Nothing on the shelf is spicy right now",
           "item_in_list": lambda slot, level: f"{slot}, {level}",
           "list_sep": "; ",
           "rest_mild": "The others aren't marked spicy",
           "avoid_lead": lambda n: "One item isn't spicy" if n == 1 else f"{_en_number(n, True)} items aren't spicy",
           "avoid_none": "Everything on the shelf is spicy",
           "spicy_named": lambda names, n: f"{names} {'is' if n == 1 else 'are'} spicy",
           "spicy_rest": "The others are spicy",
           "item_spicy": lambda name, level: f"{name} is {level}",
           "item_mild": lambda name: f"{name} isn't marked spicy",
           "unknown": lambda names, n: f"{names} {'has' if n == 1 else 'have'} no information",
           "more": lambda k: f" and {_en_number(k)} more",
           "sep": ". "},
}


def spicy_level(dish):
    """🌶️ 个数（1–3）；菜名写了辣却没标 🌶️ 返回 0；没标辣返回 None。"""
    name = (dish or {}).get("name", "")
    count = name.count("🌶")
    if count:
        return min(count, 3)
    return 0 if _NAME_SPICY.search(name) else None


def local_spicy_answer(query, context, data, settings, menu_settings):
    """「有什么辣的」「我不吃辣」「X 辣吗」。命中返回答案文本，否则 None。"""
    loaded = _load(query, context, data, settings, "local_spicy_answers", menu_settings)
    if loaded is None:
        return None
    text, shelf_dishes, dishes = loaded
    # 先去掉点名的货架菜名再判断是不是在问辣：「Do you have Korean Spicy Chicken Noodles?」是问有没有货
    named, with_trigger = _named_shelf(text, shelf_dishes)
    avoid = re.search(_NO_SPICY, with_trigger, re.I) is not None
    if not avoid and not re.search(_SPICY, with_trigger, re.I):
        return None
    rest = re.sub(_NO_SPICY if avoid else _SPICY, " ", with_trigger, flags=re.I)
    resolved = _resolve_scope(named, rest, shelf_dishes, dishes, _SPICY_STOP, _SPICY_STOP_ZH)
    if resolved is None:
        return None
    scope, catalog_hits, _ = resolved
    language = _language_of(with_trigger, catalog_hits)
    words = _SPICY_TEXT[language]
    sep = words["sep"]

    def item_sentence(name, dish):
        if not dish:
            return words["unknown"](name, 1)
        level = spicy_level(dish)
        return words["item_mild"](name) if level is None else words["item_spicy"](name, words["level"][level])

    if catalog_hits is not None:
        levels = {spicy_level(d) for d in catalog_hits}
        if len(levels) != 1:
            return None
        name = re.sub(r"\s*[(（][^()（）]*[)）]$", "", "".join(
            c for c in catalog_hits[0]["name"] if c.isalnum() or c in " ()（）&-.,'").strip())
        return item_sentence(name, catalog_hits[0]) + sep.rstrip()

    merged = {}
    for item, dish in sorted(scope if scope is not None else shelf_dishes, key=lambda p: p[0]["slot"]):
        merged.setdefault(item["name"].strip(), {"dish": dish, "slots": []})["slots"].append(item["slot"])

    if scope is not None:
        # 点名或按类别问：逐款说
        return sep.join(item_sentence(name, entry["dish"]) for name, entry in merged.items()) + sep.rstrip()

    spicy, mild, unknown = [], [], []
    for name, entry in merged.items():
        if not entry["dish"]:
            unknown.append(name)
            continue
        level = spicy_level(entry["dish"])
        (mild if level is None else spicy).append((name, entry["slots"], level))
    parts = []
    if not avoid:
        if spicy:
            parts.append(words["want_lead"](len(spicy)))
            listed = [words["item_in_list"](words["slot"](name, slots), words["level"][level])
                      for name, slots, level in spicy]
            parts.append(words["list_sep"].join(listed[:_MAX_NAMES]) + (
                words["more"](len(listed) - _MAX_NAMES) if len(listed) > _MAX_NAMES else ""))
            if mild:
                parts.append(words["rest_mild"])
        else:
            parts.append(words["want_none"])
    else:
        if mild:
            listed = [words["slot"](name, slots) for name, slots, _ in mild]
            parts.append(words["avoid_lead"](len(listed)))
            parts.append(_cap(words, listed))
            if spicy:
                names = [name for name, _, _ in spicy]
                parts.append(words["spicy_named"](words["join"](names), len(names)) if len(names) <= 2
                             else words["spicy_rest"])
        else:
            parts.append(words["avoid_none"])
    if unknown:
        parts.append(words["unknown"](words["join"](unknown), len(unknown)))
    return sep.join(parts) + sep.rstrip()
