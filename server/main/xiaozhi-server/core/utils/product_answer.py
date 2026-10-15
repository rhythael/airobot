# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Direct stock answers from validated per-turn structured inventory."""
import re
import unicodedata

from core.utils.turn_context import UNAVAILABLE_ANSWER, normalize_query, valid_inventory

_PATTERNS = (
    ("zh", re.compile(r"(?:(?:请问)?(?:0?41号(?:机器|售货机)的?)?)?(?:那个|那份)?(.+?)(?:还有吗|还有货吗|还有没有|是不是还有|有没有货)")),
    ("en", re.compile(r"(?:is (.+?) still (?:in stock|available)|do you still have (.+?))", re.I)),
    ("de", re.compile(r"(?:ist (.+?) noch (?:verfügbar|vorrätig)|hast du (.+?) (?:wirklich )?noch)", re.I)),
)


def _normalize(name):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip().casefold()


def _aliases(name):
    full = _normalize(name)
    short = re.sub(r"\s*\(\d+\s*(?:粒|个|份|pcs|pieces)\)$", "", full)
    return {full, short}


def local_product_answer(query, context, data, settings):
    if not settings.get("local_product_answers") or not isinstance(query, str):
        return None
    query = normalize_query(query)
    match = next(((language, pattern.fullmatch(query)) for language, pattern in _PATTERNS if pattern.fullmatch(query)), None)
    if not match:
        return None
    language, groups = match
    requested = next(group for group in groups.groups() if group is not None)
    # Reject compounds and requests for prices or another machine before any direct answer.
    # 「1-7货道还有吗」「吃的还有吗」「过期的还有吗」抓到的不是商品名，直答会说出
    # 「没看到1-7货道」这种错话；这些让给模板回答器（货道/过期/空货道）或模型。
    if re.search(r"[?？,，;；]|多少钱|价格|以及|[0-9]+号(?:机器|售货机)|还有.*(?:吗|货)|\b(?:price|cost|preis)\b|\b(?:machine|automat(?:en)?)\s+0*([0-9]+)"
                 r"|货道|货到|\b(?:slot|fach|platz)\b|^(?:吃的|东西|商品|食物|餐食|过期的?|空的?)$", requested, re.I):
        return None
    if context == settings.get("unavailable_context"):
        return UNAVAILABLE_ANSWER[language]
    items = valid_inventory(data)
    if items is None:
        return None
    requested = _normalize(requested)
    names = {item["name"] for item in items if requested == _normalize(item["name"])}
    if not names:
        names = {item["name"] for item in items if requested in _aliases(item["name"])}
    if not names and settings.get("report_unmatched_product") and language == "zh":
        if requested in ("它", "这个", "这款", "那款", "那个"):
            return "你说的是哪款商品？"
        if re.search(r"和|以及|还有|[与、]", requested):
            return None
        # 名称没匹配上时不能断言售罄，但也不必每次都加一句让顾客看屏幕。
        return f"现在机器里没看到{requested}。"
    if len(names) != 1:
        # Unknown names and ambiguous aliases cannot be reported as sold out.
        return None
    name = next(iter(names))
    available = [item for item in items if item["name"] == name and item["purchasable"]]
    quantity = sum(item["quantity"] for item in available)
    if quantity == 0:
        return {
            "zh": f"没有可购买的{name}。",
            "en": f"There is no {name} available for purchase.",
            "de": f"{name} ist nicht zum Kauf verfügbar.",
        }[language]
    slots = ", ".join(item["slot"] for item in available)
    return {
        "zh": f"还有{quantity}份可以购买。{name}在{slots}货道。",
        "en": ("One portion is available." if quantity == 1 else f"{quantity} portions are available.") + f" {name} is in slots {slots}.",
        "de": ("Eine Portion ist verfügbar." if quantity == 1 else f"{quantity} Portionen sind verfügbar.") + f" {name} liegt in den Fächern {slots}.",
    }[language]
