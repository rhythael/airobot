# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Deterministic local menu lookup. No network requests or model calls."""
import difflib
import json
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "resources/smartfoodie/menu_catalog.json"


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", ''.join(c for c in text if c.isalnum() or c in " ()&-.,")).strip()


@lru_cache(maxsize=4)
def load_catalog(path):
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("dishes"), list):
        raise ValueError("Invalid local menu catalog")
    return catalog


def _aliases(dish):
    name = normalize(dish['name'])
    short = re.sub(r"\s*\([^()]*\)$", "", name)
    return {name, short, dish['code'].casefold()}


def _stock_names(conn):
    """当前这台机器实际上了哪些商品。用来在同名多份量时收敛到顾客买得到的那一款。
    拿不到就返回空集合，调用方退回原有的澄清逻辑。"""
    try:
        data = conn.prompt_manager.context_provider.structured_data
        items = (data or {}).get('inventory', {}).get('items') or []
        return {normalize(i['name']) for i in items if isinstance(i, dict) and isinstance(i.get('name'), str)}
    except Exception:
        return set()


def _narrow_by_stock(candidates, stock):
    """同名多款时，只保留机器里真有的那些。"""
    if not stock or len(candidates) < 2:
        return candidates
    hit = [d for d in candidates if normalize(d['name']) in stock]
    return hit if hit else candidates


def _head_alias(dish):
    """顾客口语里的简称：菜名中"配 / mit / with"之前的部分。
    例如「意大利细面配培根奶油酱」→「意大利细面」。"""
    name = normalize(dish['name'])
    head = re.split(r"配|\s+mit\s+|\s+with\s+|\s+in\s+|\s+auf\s+", name)[0].strip()
    return head if len(head) >= 3 and head != name else ""


def _tail_alias(dish):
    """区分同名菜的部分：菜名中"配 / mit / with"之后的内容。
    例如「意大利细面配培根奶油酱」→「培根奶油酱」。顾客回答澄清时常只说这一段。"""
    name = normalize(dish['name'])
    parts = re.split(r"配|\s+mit\s+|\s+with\s+|\s+in\s+|\s+auf\s+", name, maxsplit=1)
    tail = parts[1].strip() if len(parts) > 1 else ""
    return tail if len(tail) >= 2 else ""


def _match_by_head(dishes, normalized_query):
    """按简称匹配，歧义时返回全部命中，由调用方决定怎么处理。
    问答路径会把它们按菜名列给顾客；存指代对象的路径只认唯一命中。"""
    return [d for d in dishes if _mentions(normalized_query, _head_alias(d))]


def _mentions(query, alias):
    if not alias:
        return False
    # Latin names/codes must not match inside an unrelated word.
    boundary = r"(?<![a-z0-9])" if alias[0].isascii() and alias[0].isalnum() else ""
    ending = r"(?![a-z0-9])" if alias[-1].isascii() and alias[-1].isalnum() else ""
    return re.search(boundary + re.escape(alias) + ending, query) is not None


def _allergen_tags_covered(dish):
    """Only suppress repeated labels; retain any additional or unfamiliar tag."""
    statement = dish['allergen_text']
    if not statement or re.search(r'不含|无过敏|没有', statement):
        return False
    for tag in re.split(r'[；;]', dish['allergen_tags']):
        label = re.split(r'[（(]', tag)[0].strip()
        if not label:
            continue
        if label == '含麸质谷物':
            if not re.search(r'麸质|小麦|大麦|黑麦|燕麦', statement):
                return False
            continue
        if label in statement:
            continue
        # 标签和正文常差一个后缀：标签写「甲壳类动物」，正文写「甲壳类」。
        # 去掉后缀再比一次，核心词仍要真实出现才算覆盖，不放宽判定。
        core = re.sub(r'(?:动物|谷物|制品|类)$', '', label)
        if len(core) < 2 or core not in statement:
            return False
    return True


# 问价。英语「How much is …」原来没认，落到模型说「看标签」，和中德的目录价口径不一致；
# 「how much is left / available」是问库存，不算。
PRICE_PATTERN = (r"售价|价格|多少钱|几欧|price|cost|preis|kostet"
                 r"|\bhow much (?:is|are|does|do|for)\b(?!.*\b(?:left|remaining|available|in stock)\b)")


_NAME_FILLER = frozenset({"with", "from", "mit", "und", "oder", "style", "sauce", "soße", "sosse"})


def _narrow_by_words(candidates, normalized_query):
    """同一简称下几款都对得上时（fried rice → 腊肠 / 黑椒牛肉），
    用菜名里其余的拉丁词再收一次：顾客说了「with beef」就是牛肉那款。只在收成唯一时生效。"""
    if len(candidates) < 2:
        return candidates
    def content_words(text):
        return set(re.findall(r"[a-zäöüß]{4,}", text)) - _NAME_FILLER
    words = content_words(normalized_query)
    hit = [d for d in candidates
           if words & (content_words(normalize(d['name'])) - content_words(_head_alias(d)))]
    return hit if len(hit) == 1 else candidates


def local_menu_answer(query, settings, previous_id=None, previous_options=None, stock=None, out=None):
    """Return (answer, resolved ID); None answer means unrelated request."""
    if not settings or not isinstance(query, str):
        return None, previous_id
    topics = []
    for topic, pattern in (("ingredients", r"成[分份]|配料|食材|原料|配方|用什么做|里面有什么|ingredients?|zutaten"),
                           ("allergens", r"过敏|allerg"),
                           ("price", PRICE_PATTERN)):
        if re.search(pattern, query, re.I):
            topics.append(topic)
    if not topics:
        return None, previous_id
    language = 'zh' if re.search(r'成[分份]|配料|食材|原料|配方|用什么做|里面有什么|过敏|售价|价格|多少钱|几欧', query) else ('de' if re.search(r'zutaten|allergene|preis|kostet', query, re.I) else 'en')
    labels = {
        'zh': ('你说的是哪一款？', '有几款都对得上，你说的是哪一款：', '资料暂时读不到，你看一下商品包装。'),
        'en': ('Which dish do you mean?', 'A few match. Which one do you mean: ', 'The local record is unavailable. Please check the packaging.'),
        'de': ('Welches Gericht meinst du?', 'Mehrere passen. Welches meinst du: ', 'Die lokalen Angaben sind nicht verfügbar. Bitte die Verpackung prüfen.'),
    }[language]
    try:
        catalog = load_catalog(str(settings.get('path') or DEFAULT_CATALOG))
    except (OSError, ValueError, TypeError):
        return labels[2], None
    normalized = normalize(query)
    dishes = catalog['dishes']
    exact = [d for d in dishes if _mentions(normalized, normalize(d['name'])) or _mentions(normalized, d['code'].casefold())]
    # Prefer the most specific full name if one name is contained in another.
    if exact:
        candidates = [d for d in exact if not any(d is not other and normalize(d['name']) != normalize(other['name']) and normalize(d['name']) in normalize(other['name']) for other in exact)]
    else:
        candidates = [d for d in dishes if any(_mentions(normalized, alias) for alias in _aliases(d))]
        if not candidates:
            # 顾客常说简称（「意大利细面」而非全名），唯一命中才认。
            candidates = _match_by_head(dishes, normalized)
        if not candidates:
            # 最后再按读音找一次：语音识别常把蒸饺听成针饺、虾仁听成虾人。
            candidates = fuzzy_match_dish(query, dishes)
    if not candidates:
        # Only explicit pronoun/field-only follow-ups reuse the last local lookup.
        query = re.sub(r"^(?:那么|那|然后)[，, ]*", "", query.strip())
        followup = re.fullmatch(r"(?:具体)?(?:有哪些)?(?:成分|配料|过敏原|价格|售价|多少钱)(?:表|信息)?(?:呢|有吗|是什么|有哪些|是多少)?[?？。！!]*", query.strip()) or re.fullmatch(r"(?:它|这款|这个|那款)(?:的)?(?:有没有|有哪些|有|具体有哪些)?(?:成分|配料|过敏原|价格|售价|多少钱)(?:表|信息)?(?:呢|有吗|是什么|有哪些|是多少)?[?？。！!]*", query.strip())
        if not followup:
            followup = re.fullmatch(r"(?:what (?:are|is) (?:its|the)|how much is it|(?:its|the))?\s*(?:ingredients?|allergens?|price)?[?.!]*", query.strip(), re.I) or re.fullmatch(r"(?:welche|was sind die|und die)?\s*(?:zutaten|allergene|preis)[?.!]*", query.strip(), re.I)
        if not followup:
            # 上面几条正则只能穷举固定说法，「有什么过敏原」这类就漏了。
            # 兜底规则：把虚词和字段词都剥掉，如果一个字都不剩，
            # 说明顾客确实没提新对象，是在追问上一款菜。
            # 「这个咖啡的过敏原是什么」会剩下「咖啡」，因此不算追问。
            residue = normalize(query)
            residue = re.sub(r"成[分份]|配料|食材|原料|过敏原|过敏|售价|价格|多少钱|几欧|ingredients?|allergens?|price|cost|zutaten|allergene|preis", "", residue, flags=re.I)
            residue = re.sub(r"它|这款|那款|这个|那个|请问|具体|我|你|想|要|了解|知道|告诉|听|看|一下|完整|详细|全部|原文|资料|表|的|呢|吗|啊|呀|是什么|是多少|有哪些|有什么|有没有|多少|什么|是|有|和|table|info|full|detail|what|are|is|its|the|and|of|welche|sind|die|und", "", residue, flags=re.I)
            if not re.sub(r"[\s?？.。!！,，、]", "", residue):
                followup = True
        if followup and previous_id:
            candidates = [d for d in dishes if d['id'] == previous_id]
        elif previous_options:
            options = [d for d in dishes if d['id'] in previous_options]
            # 顾客回答澄清时往往只说区分的那一段（「配培根奶油酱的」）。
            narrowed = [d for d in options if _mentions(normalized, _tail_alias(d))]
            if len(narrowed) == 1:
                candidates = narrowed
            elif followup:
                # 没说清楚，就把这几款按菜名列出来，
                # 而不是空问一句「你说的是哪一款」。
                candidates = options
    candidates = _narrow_by_words(_narrow_by_stock(candidates, stock), normalized)
    if len(candidates) != 1:
        if not candidates:
            if isinstance(out, dict):
                out['unresolved'] = True
            return labels[0], None
        # 顾客已经报过菜名了，不能再把问题抛回去。几款都答，
        # 用区分的那一段（份量或酱料）标出来，让顾客自己对号入座。
        if isinstance(out, dict):
            out['options'] = [d['id'] for d in candidates]
        if len(candidates) <= 4:
            common = candidates[0]['name'][:_common_prefix_len(candidates)].strip(' （(')
            if len(common) < 2:
                # 名字开头带不同 emoji 时逐字比对得不到共同部分，
                # 退回用简称（「配」之前那段）。
                heads = {_head_alias(d) for d in candidates}
                common = heads.pop() if len(heads) == 1 else ''
            candidates = sorted(candidates, key=_portion_key)
            marks = _distinguishing_labels(candidates)
            bodies = [' '.join(_describe(dish, topics, language, query, settings, catalog))
                      for dish in candidates]
            if len(set(bodies)) == 1:
                # 几款资料完全相同，就没必要分开念。
                return (common + '。' if common else '') + bodies[0], None
            if topics == ['price'] and language == 'zh':
                # 只问价格时把模板提出来说一次，后面只报份量和数字。
                pairs = '，'.join(
                    f"{mark}{_price_value(dish, settings)}欧元"
                    for dish, mark in zip(candidates, marks)
                )
                head = (common + '：') if common else ''
                return f"{head}{pairs}。以机器标价为准。", None
            # 资料相同的份量合并成一条，避免同一段话念两遍。
            grouped = {}
            for mark, body in zip(marks, bodies):
                grouped.setdefault(body, []).append(mark)
            parts = [common + '。'] if common else []
            for body, group in grouped.items():
                parts.append(f"{'和'.join(group)}：{body}")
            return '\n'.join(parts), None
        return labels[1] + '；'.join(d['name'] for d in candidates[:6]), None
    dish = candidates[0]
    name = dish['name']
    answer = [name + '。'] + _describe(dish, topics, language, query, settings, catalog)
    return '\n'.join(answer), dish['id']


def _strip_parens(text):
    """去掉所有括号内容，含嵌套。配料表里括号装的是百分比和子成分，
    口语播报时是噪音；需要原文的顾客可以说「详细说说」。"""
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"[（(][^（()）]*[）)]", "", text)
    return text


def _concise_ingredients(text, limit=6):
    """只念前几样主要配料。绝不改写原文用词，只做截取。"""
    body = re.sub(r"^\s*配料\s*[：:]\s*", "", text.strip())
    items = [i.strip(" 、，,。.") for i in re.split(r"[、,，]", _strip_parens(body))]
    items = [i for i in items if i]
    if not items:
        return None
    head = "、".join(items[:limit])
    more = "等" if len(items) > limit else ""
    return f"主要配料是{head}{more}。完整配料表可以说详细说说。"


def _portion_key(dish):
    """按份量数字排序（6粒 < 10粒 < 12粒），没有数字的排后面。"""
    found = re.search(r"(\d+)\s*(?:粒|个|份|pcs|pieces)", dish['name'])
    return (0, int(found.group(1))) if found else (1, 0)


# 门店价与总部默认价偏离超过这个比例，或低于这个绝对值，就当数据有问题。
# 实测依据：菜品目录里 DEMO-041 的「鱼香茄子盖饭」门店价 0.11 欧元，
# 而默认价 7.99 欧元。041 目前只有这一条门店价，恰好就是坏的那条。
# 对顾客报 0.11 欧元是会出实际问题的，所以宁可回落默认价。
PRICE_MIN_EUR = 1.0
PRICE_MAX_DEVIATION = 0.5


def _price_is_sane(store_price, default_price):
    """门店价是否可信。拿不准一律判为不可信，回落默认价。"""
    try:
        sp = float(store_price)
        dp = float(default_price)
    except (TypeError, ValueError):
        return False
    if sp < PRICE_MIN_EUR:
        return False
    if dp > 0 and abs(sp - dp) / dp > PRICE_MAX_DEVIATION:
        return False
    return True


def _resolve_price(dish, settings):
    """返回 (报给顾客的价格, 是否用的门店价)。门店价异常时静默回落默认价。"""
    store_price = dish['store_price_eur'].get(settings.get('store_name', ''))
    if store_price and _price_is_sane(store_price, dish['default_price_eur']):
        return store_price, True
    return dish['default_price_eur'], False


def _price_value(dish, settings):
    return _resolve_price(dish, settings)[0]


def _common_prefix_len(dishes):
    names = [d['name'] for d in dishes]
    i = 0
    while i < min(len(n) for n in names) and len({n[i] for n in names}) == 1:
        i += 1
    return i


def _distinguishing_labels(dishes):
    """同一系列多款菜，去掉共同前缀，只留区分的那一段做标签。
    「鸡肉蔬菜蒸饺(6粒）/(10粒）/(12粒）」→「6粒 / 10粒 / 12粒」。"""
    names = [d['name'] for d in dishes]
    prefix = 0
    while prefix < min(len(n) for n in names) and len({n[prefix] for n in names}) == 1:
        prefix += 1
    labels = []
    for name in names:
        tail = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", name[prefix:])
        tail = tail.strip(' （()）「」【】·、,，').strip()
        labels.append(tail or name)
    return labels if len(set(labels)) == len(labels) else names


def _describe(dish, topics, language, query, settings, catalog):
    answer = []
    concise = settings.get('concise_voice', False) and language == 'zh' and not re.search(r'完整|详细|全部|原文', query)
    if 'ingredients' in topics:
        raw = dish['ingredients']
        short = _concise_ingredients(raw) if (concise and raw) else None
        answer.append(short or raw or {'zh': '资料未提供配料表。', 'en': 'Ingredients are not provided.', 'de': 'Die Zutaten sind nicht angegeben.'}[language])
    if 'allergens' in topics:
        # Preserve the supplier's "contains" vs "may contain" distinctions verbatim.
        if dish['allergen_text']:
            answer.append(dish['allergen_text'])
        else:
            answer.append({'zh': '原文未提供单独的过敏提示。', 'en': 'No separate allergen statement is provided.', 'de': 'Keine separate Allergenangabe vorhanden.'}[language])
        if concise and _allergen_tags_covered(dish):
            answer.append('请再核对包装。')
        else:
            answer.append({'zh': '结构化过敏原标签：', 'en': 'Recorded allergen tags: ', 'de': 'Erfasste Allergen-Tags: '}[language] + dish['allergen_tags'] + '。')
            answer.append({'zh': '标签不区分含有与可能含微量；未标注不代表没有过敏原，请核对包装。', 'en': 'Tags do not distinguish contains from may contain. Missing tags do not mean allergen-free. Check the packaging.', 'de': 'Tags unterscheiden nicht zwischen enthalten und möglichen Spuren. Fehlende Angaben bedeuten nicht allergenfrei. Bitte die Verpackung prüfen.'}[language])
    if _catalog_is_stale(catalog, settings) and ('allergens' in topics or 'ingredients' in topics):
        answer.append(STALE_NOTICE[language].format(date=catalog.get('snapshot_date', '?')))
    if 'price' in topics:
        value, store_price = _resolve_price(dish, settings)
        date = catalog['snapshot_date']
        zh_price = (f"资料上是{value}欧元，以机器标价为准。" if concise
                    else f"{date}资料中的{'门店' if store_price else '总部默认'}标价为每份{value}欧元，实际以机器有效标价为准。")
        # 口播不念「2026-09-17」「snapshot」：顾客听不懂，德语 TTS 还会把日期逐位念出来
        spoken = settings.get('concise_voice', False) and not re.search(r'完整|详细|全部|原文|full|vollständig', query, re.I)
        en_price = (f"According to our records it costs {value} euros. The price on the machine applies." if spoken
                    else f"The {date} snapshot {'store' if store_price else 'default'} price is {value} euros per portion. The machine's effective price applies.")
        de_price = (f"Laut unseren Unterlagen kostet es {str(value).replace('.', ',')} Euro. Es gilt der Preis am Automaten." if spoken
                    else f"Der {'Filialpreis' if store_price else 'Standardpreis'} im Stand vom {date} beträgt {value} Euro pro Portion. Es gilt der aktuelle Preis am Automaten.")
        answer.append({'zh': zh_price, 'en': en_price, 'de': de_price}[language])
    return answer


def local_menu_turn(conn, query, settings):
    """Remember requested fields across clarification and product-name-only turns."""
    if not settings or not isinstance(query, str):
        return None
    if re.fullmatch(r'(?:再)?(?:详细说说|说详细点|完整资料|完整的|详细的)[。.!！?？]*', query.strip()) and getattr(conn, 'last_local_menu_id', None):
        fields = getattr(conn, 'last_local_menu_fields', '成分和过敏原')
        try:
            catalog = load_catalog(str(settings.get('path') or DEFAULT_CATALOG))
        except (OSError, ValueError, TypeError):
            return '资料暂时无法读取，请查看商品包装。'
        dish = next((d for d in catalog['dishes'] if d['id'] == conn.last_local_menu_id), None)
        if dish:
            return local_menu_answer(dish['code'] + '的完整' + fields, settings)[0]
    options = getattr(conn, 'last_local_menu_options', None)
    if re.fullmatch(r'(?:再)?(?:详细说说|说详细点|完整资料|完整的|详细的)[。.!！?？]*', query.strip()) and options:
        # 上一轮是多款一起答的，用同一条查询重跑，只是这次不走简洁模式。
        last_query = getattr(conn, 'last_local_menu_query', '') or ''
        if last_query:
            return local_menu_answer(
                last_query + '的完整资料', settings, None, options, _stock_names(conn),
            )[0]
    pending = getattr(conn, 'pending_local_menu_fields', '')
    last_id = getattr(conn, 'last_local_menu_id', None)
    fields = []
    for name, pattern in [('成分', r'成[分份]|配料|食材|原料|配方|用什么做|里面有什么|ingredients?|zutaten'),
                          ('过敏原', r'过敏|allerg'),
                          ('价格', PRICE_PATTERN)]:
        if re.search(pattern, query, re.I):
            fields.append(name)
    if fields:
        pending = '和'.join(fields)
        conn.pending_local_menu_fields = pending
        effective_query = query
    else:
        # Reuse a pending question only for a standalone name/code clarification.
        normalized = normalize(query).rstrip('. ')
        normalized = re.sub(r'^(?:我说的是|我指的是|就是|是|那个)', '', normalized)
        normalized = re.sub(r'(?:啊|呀|呢|这款|这个)$', '', normalized).strip()
        try:
            dishes = load_catalog(str(settings.get('path') or DEFAULT_CATALOG))['dishes']
        except (OSError, ValueError, TypeError):
            dishes = []
        matching = [d for d in dishes if normalized in _aliases(d)]
        if matching:
            if pending:
                effective_query = query.rstrip('。.!！?？') + '的' + pending
            else:
                # 顾客只报了菜名、没说想知道什么。不要反问「你想了解成分、
                # 过敏原还是价格」——记住指代对象，让库存/模型自然回答
                # 「有没有货」，顾客下一句问成分或价格时才有对象可查。
                matching = _narrow_by_stock(matching, _stock_names(conn))
                conn.last_local_menu_id = matching[0]['id'] if len(matching) == 1 else None
                conn.last_local_menu_options = [d['id'] for d in matching] if len(matching) > 1 else []
                conn.pending_local_menu_fields = ''
                return None
        elif pending and normalized in ('牛肉面', '肉场面', '牛肉场面'):
            conn.last_local_menu_id = None
            return '你指牛肉炒面，还是红烧牛肉面？请说一下具体是哪款。'
        else:
            conn.pending_local_menu_fields = ''
            normalized_query = normalize(query)
            # 顾客很少报全名：可能省掉份量括号（「鸡肉蔬菜蒸饺」），
            # 也可能只说「配」之前那半截（「意大利细面」）。两种都要认，
            # 否则这一轮存不住指代对象，下一轮问成分就只能反问。
            mentioned = [d for d in dishes if any(_mentions(normalized_query, a) for a in _aliases(d))]
            if not mentioned:
                mentioned = _match_by_head(dishes, normalized_query)
            if not mentioned:
                mentioned = fuzzy_match_dish(query, dishes)
            mentioned = _narrow_by_stock(mentioned, _stock_names(conn))
            conn.last_local_menu_id = mentioned[0]['id'] if len(mentioned) == 1 else None
            conn.last_local_menu_options = [d['id'] for d in mentioned] if len(mentioned) > 1 else []
            return None
    out = {}
    answer, resolved_id = local_menu_answer(
        effective_query, settings, last_id,
        getattr(conn, 'last_local_menu_options', None),
        _stock_names(conn),
        out,
    )
    unresolved = bool(out.get('unresolved'))
    conn.last_local_menu_id = resolved_id
    # 多款一起作答时也要记住是哪几款，否则下一轮「多少钱」又没了对象。
    conn.last_local_menu_options = [] if resolved_id else out.get('options', [])
    if answer is not None:
        conn.last_local_menu_query = effective_query
    if resolved_id:
        conn.last_local_menu_fields = pending
        conn.pending_local_menu_fields = ''
    elif answer is not None:
        # Offer meaningful choices for real observed abbreviations/ASR errors;
        # never silently map one product's allergens to another product.
        if re.search(r'牛肉面|肉场面|牛肉场面', query) and not re.search(r'红烧牛肉面|牛肉炒面', query):
            answer = '你指牛肉炒面，还是红烧牛肉面？请说一下具体是哪款。'
            unresolved = False
    if unresolved:
        # 本地规则完全认不出顾客说的是哪款，而且没有具体候选可列。
        # 绝不能反问「你说的是哪一款」——顾客问「这个成分是什么」时，
        # 对象一定在前面几轮里。返回 None 交给模型：它有完整对话历史，
        # 也有货道商品资料和菜单目录，答得比规则准。
        conn.pending_local_menu_fields = pending
        return None
    return answer


def resolve_stock_followup(conn, query, settings):
    """Expand only an explicit single-product pronoun, keeping the user's history intact."""
    if not settings or not isinstance(query, str):
        return query
    match = re.fullmatch(r'(?:那)?(?:它|这款|这个|那款)(还有吗|还有货吗|还有没有|有没有货)[？?。.!！]*', query.strip())
    if not match or not getattr(conn, 'last_local_menu_id', None):
        return query
    try:
        dishes = load_catalog(str(settings.get('path') or DEFAULT_CATALOG))['dishes']
    except (OSError, ValueError, TypeError):
        return query
    dish = next((d for d in dishes if d['id'] == conn.last_local_menu_id), None)
    return normalize(dish['name']) + match.group(1) + '？' if dish else query

SHELF_CONTEXT_LABEL = (
    "在售及货道上商品的配料与过敏原原文（本机已存有这份资料，"
    "任何语言的顾客问到配料、成分或过敏原，都必须依据下列内容回答，"
    "不得回答查不到或系统里没有）"
)

# 对话里提到、但不一定在货道上的商品。曾经和货道资料共用上面那个「在售及货道上」标签，
# 模型据此把顾客上一轮问的 Dampfnudel 当成在售商品、当成这一轮的指代对象。
MENTIONED_CONTEXT_LABEL = (
    "对话中提到的商品的配料与过敏原原文（只说明这些商品本身，不代表本机有货；"
    "顾客问到它们时依据下列内容回答）"
)

# 顾客这句话里有没有点名一类商品。用来判断「它 / da drin / in it」该不该绑到前几轮的菜上：
# 「Ist in den Teigtaschen Sesam drin?」点名了 Teigtaschen，就不能再套用上一轮的 Dampfnudel。
# 短词必须带词界：Preis/price 里藏着 reis/rice；中文只收复合词，「里面」里藏着「面」。
_PRODUCT_NOUN = re.compile(
    r'饺|包子|小笼包|炒饭|盖饭|米饭|拌面|炒面|汤面|拉面|面条|意面|意大利面|粉丝|云吞|馄饨|甜点|蛋糕|面包'
    r'|teigtasche|maultasche|dampfnudel|nudel|knödel|suppe|pasta|penne|dessert|kuchen|gericht'
    r'|dumpling|noodle|xiaolongbao|\breis\b|\brice\b|\bsoups?\b|\bbuns?\b|\bbaos?\b|\bcakes?\b|\bdish',
    re.I,
)


def mentions_product_noun(text):
    """这句话是否点名了一类商品（饺子 / Nudeln / fried rice ……）。"""
    return isinstance(text, str) and bool(_PRODUCT_NOUN.search(text))


# 问句里的一类商品 → 货架商品名里的写法。修饰词（fried / gebratene）一起吃掉，
# 过敏原直答用它判断有没有剩下认不出的实词。过敏原直答和模型的指代背景共用这一份。
CATEGORY_PATTERNS = (
    (r"饺子|蒸饺|饺|小笼包|包子|teigtasche\w*|maultasche\w*|(?:\b(?:steamed|soup)\s+)?dumplings?|xiaolongbao"
     r"|\bbaos?\b|\bbuns?\b",
     r"饺|小笼包|包子|dumpling|xiaolongbao|teigtasche"),
    (r"面条|拌面|炒面|汤面|拉面|(?:\b(?:fried|spicy)\s+)?noodles?|nudel\w*", r"面|noodle|nudel"),
    (r"炒饭|盖饭|米饭|(?:\bfried\s+)?\brice\b|(?:\bgebratene[rn]?\s+)?\breis\w*", r"饭|\brice\b|\breis"),
    (r"意面|意大利面|pasta|penne", r"意面|意大利面|pasta|penne"),
)


def items_in_named_category(text, item_names):
    """顾客这句话点名的一类商品，对应到给定商品名里的哪几款（保持顺序、去重）。"""
    if not isinstance(text, str):
        return []
    hits = []
    for query_pattern, item_pattern in CATEGORY_PATTERNS:
        if re.search(query_pattern, text, re.I):
            hits += [name for name in item_names if re.search(item_pattern, name, re.I)]
    return list(dict.fromkeys(hits))


def shelf_names_from_context(text):
    """从提示词里 shelf_menu_context 生成的那一段读回货道商品名。
    格式由本模块自己生成：标签行之后每行两个空格缩进、菜名在「｜」之前。"""
    if not isinstance(text, str):
        return []
    marker = f"- **{SHELF_CONTEXT_LABEL}：**"
    start = text.find(marker)
    if start < 0:
        return []
    names = []
    for line in text[start + len(marker):].split("\n")[1:]:
        if not line.startswith("  "):
            break
        name = line.strip().split("｜")[0].strip()
        if name:
            names.append(name)
    return names


def _flatten(text):
    """折掉换行，避免破坏上下文的逐行结构。"""
    return re.sub(r'\s+', ' ', (text or '')).strip()


def shelf_menu_context(item_names, settings, max_items=8, max_ingredients=300, label=None):
    """把货道上这几件商品的配料与过敏原原文整理成一段上下文。

    模型拿到它之后，英语德语顾客问「what's inside」也能照实回答，
    不必依赖只认中文菜名的本地规则链路。
    过敏原原文逐字保留，配料过长时截断并标注，避免提示词无限膨胀。
    """
    if not settings or not item_names:
        return ""
    try:
        dishes = load_catalog(str(settings.get('path') or DEFAULT_CATALOG))['dishes']
    except (OSError, ValueError, TypeError):
        return ""
    lines, seen = [], set()
    for raw in item_names:
        if not isinstance(raw, str):
            continue
        target = normalize(raw)
        if not target or target in seen:
            continue
        seen.add(target)
        hit = next((d for d in dishes if target in _aliases(d)), None)
        if hit is None:
            hit = next((d for d in dishes if _mentions(target, normalize(d['name']))
                        or _mentions(normalize(d['name']), target)), None)
        if hit is None:
            continue
        ingredients = _flatten(hit['ingredients'])
        ingredients = re.sub(r'^(?:配料|成分|Zutaten|Ingredients)\s*[：:]\s*', '', ingredients, flags=re.I)
        if len(ingredients) > max_ingredients:
            ingredients = ingredients[:max_ingredients] + '…（原文更长，顾客要完整配料表时可逐条念）'
        allergens = _flatten(hit['allergen_text']) or '原文未提供单独的过敏提示。'
        lines.append(f"{hit['name']}｜配料：{ingredients or '资料未提供配料表。'}｜过敏原：{allergens}")
        if len(lines) >= max_items:
            break
    if not lines:
        return ""
    return f"- **{label or SHELF_CONTEXT_LABEL}：**\n" + "\n".join('  ' + line for line in lines)

_CATEGORY_LABELS = (
    ('\U0001F331', '素食为主'),
    ('\U0001F414', '鸡肉'),
    ('\U0001F42E', '牛肉'),
    ('\U0001F437', '猪肉'),
    ('\U0001F411', '羊肉'),
    ('\U0001F990', '虾'),
    ('\U0001F364', '虾'),
    ('\U0001F41F', '鱼'),
    ('\U0001F95A', '蛋类'),
    ('\U0001F36C', '甜点点心'),
    ('\u2744', '西式冷藏'),
)

MENU_CONTEXT_LABEL = (
    "完整菜单（这是菜单全目录，不代表本机当前有货。"
    "顾客问「有什么选择」「不吃某种肉能吃什么」「有没有素的」这类问题时，"
    "用这份目录回答，再说明具体哪几样此刻能买要看货道库存。"
    "分组只是按主料粗分，不是饮食或过敏保证；"
    "顾客明确忌口时，以商品的配料原文为准，必要时说明需要核对包装）"
)



# 过敏原与配料资料的时效闸。中央厨房换配方或换供应商后，如果目录没有重新导入，
# 这份资料会继续被当权威念给顾客听——而顾客可能正是因为过敏才问的。
# 默认关闭（max_age_days 不配就等于现状），打开后只追加一句提示，不删任何既有内容。
STALE_NOTICE = {
    'zh': '这份资料是{date}的，可能已经更新，请以包装标签为准。',
    'en': 'This record is from {date} and may be out of date. The packaging label applies.',
    'de': 'Diese Angaben stammen vom {date} und sind möglicherweise veraltet. Es gilt das Etikett.',
}


def _catalog_is_stale(catalog, settings):
    """目录是否已过时。配置里没给 max_age_days 就永远返回 False，行为与现状一致。"""
    max_age = settings.get('max_age_days') if settings else None
    if not max_age:
        return False
    snapshot = catalog.get('snapshot_date')
    if not snapshot:
        return True          # 没有快照日期本身就不可信
    try:
        taken = date.fromisoformat(str(snapshot))
    except (TypeError, ValueError):
        return True
    today = settings.get('today') or date.today()
    return (today - taken).days > int(max_age)

def _category_of(name):
    for mark, label in _CATEGORY_LABELS:
        if mark in name:
            return label
    return '其他'


@lru_cache(maxsize=4)
def full_menu_context(path):
    """把全部菜名按主料分组，供模型回答「有什么选择」这类菜单问题。

    只放菜名，不放配料，整块约 3 KB。货道上那几件的配料与过敏原
    由 shelf_menu_context 单独提供。
    """
    try:
        dishes = load_catalog(str(path or DEFAULT_CATALOG))['dishes']
    except (OSError, ValueError, TypeError):
        return ""
    groups = {}
    for dish in dishes:
        # 全局下架的商品不能进推荐面。顾客问「有什么选择」时，模型会照着这份目录
        # 报菜名，报出连锁已永久下架的商品等于让顾客白等。
        # 注意只过滤推荐面：顾客主动点名问下架商品的配料时，仍应照实回答。
        if dish.get('global_status') == '全局下架':
            continue
        clean = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", dish['name']).strip()
        if clean:
            groups.setdefault(_category_of(dish['name']), []).append(clean)
    if not groups:
        return ""
    order = [label for _, label in _CATEGORY_LABELS]
    ordered = sorted(groups, key=lambda g: (order.index(g) if g in order else len(order), g))
    lines = [f"  {group}（{len(groups[group])}）：" + '、'.join(groups[group]) for group in ordered]
    return f"- **{MENU_CONTEXT_LABEL}：**\n" + "\n".join(lines)

def dishes_mentioned_context(text, settings, max_items=3):
    """从一段对话文本里找出提到的菜品，返回它们的配料与过敏原资料。

    货道上的商品由 shelf_menu_context 覆盖；顾客问一个不在架上的商品时，
    模型手里没有资料，只能回答"我不知道"。这个函数按对话内容补上。
    """
    if not settings or not isinstance(text, str) or not text.strip():
        return "", []
    try:
        dishes = load_catalog(str(settings.get('path') or DEFAULT_CATALOG))['dishes']
    except (OSError, ValueError, TypeError):
        return "", []
    target = normalize(text)
    hits = [d for d in dishes if any(_mentions(target, a) for a in _aliases(d))]
    if not hits:
        hits = _match_by_head(dishes, target)
    if not hits:
        return "", []
    names = [d['name'] for d in hits[:max_items]]
    return shelf_menu_context(names, settings, max_items=max_items, label=MENTIONED_CONTEXT_LABEL), names

# 语音识别把菜名听错时的拼音归一。实测偏差集中在两类：
#   翘舌/平舌  蒸饺 zheng → 针饺 zhen
#   前后鼻音   炒面 chao → 场面 chang
# 另有纯同音字：虾仁/虾人、鸡肉/肌肉。
_PINYIN_FOLD = (
    ('zh', 'z'), ('ch', 'c'), ('sh', 's'),
    ('ang', 'an'), ('eng', 'en'), ('ing', 'in'),
)


@lru_cache(maxsize=2048)
def _pinyin_key(text):
    """把一段中文转成归一化拼音串，用于模糊比对。非中文原样保留。"""
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return ""
    try:
        joined = ''.join(lazy_pinyin(text or ''))
    except Exception:
        return ""
    key = re.sub(r'[^a-z]', '', joined.lower())
    for src, dst in _PINYIN_FOLD:
        key = key.replace(src, dst)
    return key


def _pinyin_similarity(needle, haystack):
    """菜名(needle)在顾客这句话(haystack)里的最佳匹配度。

    顾客说的话通常比菜名长（还夹着「的成分是什么」），所以按菜名长度
    在句子上滑窗逐一比对，取最高分；窗口略放宽以容纳多一两个音节的偏差。
    """
    if not needle or not haystack:
        return 0.0
    if needle in haystack or haystack in needle:
        return 1.0
    # 顾客可能说全名也可能说简称，所以拿短的那个在长的上面滑窗，
    # 两个方向都要覆盖，否则「牛肉面」配不上「红烧牛肉面」。
    if len(haystack) < len(needle):
        needle, haystack = haystack, needle
    best = 0.0
    span = len(needle)
    for width in (span, span + 2):
        for start in range(0, len(haystack) - width + 1):
            ratio = difflib.SequenceMatcher(None, needle, haystack[start:start + width]).ratio()
            if ratio > best:
                best = ratio
                if best == 1.0:
                    return best
    return best


def fuzzy_match_dish(query, dishes, threshold=0.90, margin=0.06):
    """语音听错时按读音找菜。只在唯一且明显领先时才认。

    过敏原会依据匹配结果作答，认错商品是安全问题，
    所以宁可返回空让模型处理，也不猜。
    """
    target = _pinyin_key(query)
    if len(target) < 4:
        return []
    scored = []
    for dish in dishes:
        code = dish['code'].casefold()
        alias_texts = [a for a in _aliases(dish) if a and a != code]
        pairs = [(a, _pinyin_key(a)) for a in alias_texts]
        # 编码（YZ005N）和过短的串会和任何句子都沾边，排除掉。
        pairs = [(a, k) for a, k in pairs if len(k) >= 6]
        if not pairs:
            continue
        alias_texts = [a for a, _ in pairs]
        keys = [k for _, k in pairs]
        best, best_alias = max(
            (( _pinyin_similarity(k, target), a)
             for k, a in zip(keys, alias_texts)),
        )
        if best >= threshold:
            scored.append((best, dish, re.sub(r"\s*\([^()]*\)$", "", best_alias)))
    if not scored:
        return []
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[0][0]
    close = [(dish, family) for score, dish, family in scored if top - score < margin]
    # 份量和辣度不同但同属一个系列，不算歧义（「虾仁云吞面」「虾仁云吞面(辣)」），
    # 一并返回交给上层按库存收敛或逐款作答。
    # 读音撞车的是两道不同的菜（「虾仁蒸饺」和「虾仁云吞面」）才算歧义，不猜。
    if len({family for _, family in close}) > 1:
        return []
    return [dish for dish, _ in close]
