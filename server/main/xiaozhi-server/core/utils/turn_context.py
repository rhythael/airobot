# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Opt-in per-turn context refresh, independent of LLM tool decisions.

这里还放着三个本地直答模块（count / product / template）共用的小件：
「库存不可用」三语文案、查询归一化、库存快照校验。它们以前各自抄了一份，
桥的快照结构一变就得改三处，而且已经改得不一样了（见 normalize_query 的注释）。
"""
import re
import unicodedata


def refresh_turn_context(conn):
    settings = conn.config.get("turn_context_refresh", {})
    if not settings or not conn.config.get("context_providers"):
        return False
    manager = conn.prompt_manager
    # Serialize with handshake enhancement so an older fetch cannot overwrite this turn.
    with manager.context_lock:
        try:
            context = manager.context_provider.fetch_all(conn.device_id, refresh=True)
        except Exception:
            # The caller must still get a safe answer if a provider unexpectedly fails.
            context = ""
        # 原本靠 context 是否为空串推断库存失败。自从完整菜单目录无条件注入后，
        # context 永远非空，失败标记再也装不进提示词——桥挂掉时顾客会拿到
        # 基于菜单的回答而不是「暂时查不到库存」。改为读 provider 的显式标记。
        provider = manager.context_provider
        inventory_ok = getattr(provider, "inventory_ok", bool(context))
        if inventory_ok and context:
            manager.context_data = context
        else:
            manager.context_data = settings["unavailable_context"]
        prompt = manager.build_enhanced_prompt(
            conn.config["prompt"], conn.device_id, conn.client_ip,
            emoji_enabled=(conn.features or {}).get("emoji", True),
        )
        if manager.context_data not in prompt:
            # Template fallback must not discard the refreshed inventory or failure marker.
            prompt += "\n<context>\n" + manager.context_data + "\n</context>"
        conn.change_system_prompt(prompt)
    return True


def filter_turn_tools(functions, settings):
    """A refreshed context already supplies the tool's answer, including failure."""
    return [
        function for function in functions
        if function.get("function", {}).get("name") != settings.get("tool_name")
    ]


# 刷新失败时三个本地直答模块对顾客说的同一句话。只此一份。
UNAVAILABLE_ANSWER = {
    "zh": "暂时查不到库存，请看机器屏幕。",
    "en": "Inventory is temporarily unavailable. Please check the machine display.",
    "de": "Der Bestand ist gerade nicht abrufbar. Bitte schau auf das Display.",
}


def normalize_query(query):
    """三个本地直答模块共用的查询归一化：NFKC、去掉句尾标点、空白合并。

    取的是三处旧正则的并集（count 只去 ?.! 并合并空白；product 只去 ?.!；
    template 还去句尾逗号分号并做 NFKC），所以每个模块原来能命中的句子现在仍能命中，
    多出来的只是「句尾带逗号」这类识别尾巴。"""
    text = unicodedata.normalize("NFKC", query).strip()
    text = re.sub(r"[?？.!。！,，;；]+$", "", text).strip()
    return re.sub(r"\s+", " ", text)


def valid_inventory(data):
    """桥快照里的 inventory 合法则返回 items，否则 None。

    只认 041、最多 18 个货道、每行 name/slot/quantity/purchasable 类型严格、货道不重复。
    直答绕过了模型的常识兜底，所以结构稍有不对就不答，交回原路径。"""
    inventory = data.get("inventory") if isinstance(data, dict) else None
    if not isinstance(inventory, dict) or inventory.get("machine_number") != "041":
        return None
    items = inventory.get("items")
    if not isinstance(items, list) or len(items) > 18:
        return None
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not item["name"].strip() or not isinstance(item.get("slot"), str)
                or not re.fullmatch(r"[12]-[1-9]", item["slot"])
                or type(item.get("quantity")) is not int or item["quantity"] <= 0
                or type(item.get("purchasable")) is not bool):
            return None
    if len({item["slot"] for item in items}) != len(items):
        return None
    return items


_COUNT_PATTERNS = (
    ("zh", re.compile(r"(?:(?:请问)?(?:0?41号(?:机器|售货机))?)?(?:现在|目前)?有?(?:几种|多少种)(?:商品|食物|吃的|餐食)(?:可购买)?")),
    ("en", re.compile(r"how many (?:products|items|dishes|kinds of food|types of food) (?:does (?:machine|the machine|vending machine) 0?41 have|are available(?: in (?:machine|the machine) 0?41)?)", re.I)),
    ("de", re.compile(r"wie viele (?:produkte|gerichte|speisen) (?:gibt es(?: im automaten 0?41)?|sind verfügbar)", re.I)),
)


def local_count_answer(query, context, settings):
    """Only full, unambiguous kind-count questions use the local path."""
    if not settings.get("local_count_answers") or not isinstance(query, str):
        return None
    normalized = normalize_query(query)
    language = next((name for name, pattern in _COUNT_PATTERNS if pattern.fullmatch(normalized)), None)
    if language is None:
        return None
    if context == settings.get("unavailable_context"):
        return UNAVAILABLE_ANSWER[language]
    match = re.search(r"可购买(\d+)种商品", context)
    if not match:
        return None
    count = int(match.group(1))
    # 注意：这里仍用阿拉伯数字（「有3种」），和 template_answers 的汉字数字规则不一致。
    # 属于对客话术，本次清理不改；统一时连同 tests 一起改。
    return {
        "zh": f"有{count}种可购买的商品。",
        "en": "One kind of food is available." if count == 1 else f"{count} kinds of food are available.",
        "de": "Es gibt ein verfügbares Produkt." if count == 1 else f"Es gibt {count} verfügbare Produkte.",
    }[language]


# 句末：中文全角标点；英文句号只认「后面隔空格接大写字母、汉字或数字」的，「7.49」「1-7」不切
_LOCAL_SENTENCE_END = re.compile(r"[。！？!?]+\s*|\.\s+(?=[A-ZÄÖÜ0-9\u4e00-\u9fff])")


def split_local_sentences(answer):
    """把本地直答切成句子，拼回去和原文一字不差。"""
    parts, start = [], 0
    for match in _LOCAL_SENTENCE_END.finditer(answer):
        parts.append(answer[start:match.end()])
        start = match.end()
    if start < len(answer):
        parts.append(answer[start:])
    return [part for part in parts if part]


def speak_local_answer(conn, answer, sentence_id):
    from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
    from core.utils.dialogue import Message
    # 按句入队。整段一次交过去时，合成线程每条消息只切一段：60 字以内的回答整段合成，
    # 开头不带菜名的短句跟着后面的中英混排一起走慢路径（「有什么素的」首包 2.4 秒）。
    for sentence in split_local_sentences(answer):
        conn.tts.tts_text_queue.put(TTSMessageDTO(
            sentence_id=sentence_id, sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT, content_detail=sentence,
        ))
    conn.tts.store_tts_text(sentence_id, answer)
    conn.dialogue.put(Message(role="assistant", content=answer))
    conn.tts.tts_text_queue.put(TTSMessageDTO(
        sentence_id=sentence_id, sentence_type=SentenceType.LAST,
        content_type=ContentType.ACTION,
    ))
