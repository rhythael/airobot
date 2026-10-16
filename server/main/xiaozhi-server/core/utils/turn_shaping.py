# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""每轮送给大模型之前的「整形」：回答语言、指代背景、换语言确认、每轮规则。

SmartFoodie 041 定制模块（作者：Heyao Rong，2026-09 至 2026-10），不属于上游 xiaozhi-esp32-server。

这些逻辑原来只写在 ClaudeCLI provider 里，换任何别的大模型就全部失效。这里是 provider 无关的版本：
- ClaudeCLI 调 build_payload()，把结果作为常驻进程的单轮输入（它要自己补回放块和系统指令更新）；
- OpenAI 兼容等其它 provider 不经手这些，由 connection.chat 调 shape_dialogue()，
  把送出去的消息列表里最后那条 user 消息改写成同样的形状。

每一条规则都对应一次实机或沙盒上真实出过的错，见各处注释里的日期。
"""
import re

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# 用目标语言本身下达语言指令，锚定效果远好于用英文说"reply in German"。
# 回放的历史是中文的，不这么做模型会跟着历史把德语提问答成中文。
LANGUAGE_DIRECTIVE = {
    'Chinese': '用中文回答。上面的背景不影响这一点。',
    'German': 'Antworte auf Deutsch. Der Hintergrund oben ist chinesisch, das ändert daran nichts.',
    'English': 'Reply in English. The background above is Chinese; that does not change this.',
}

# 连提问的标签也用目标语言写。用中文标签包住德语句子，
# 模型会把它当成被引用的内容，回答语言就跟着背景走了。
ASK_LABEL = {
    'Chinese': '顾客现在说',
    'German': 'Der Kunde sagt jetzt',
    'English': 'The customer now says',
}

# 服务端认定本轮是换语言请求时，用目标语言明说。提示词里另有一条「顾客问会说哪些语言，
# 就列出三种并问他要哪种」，模型会把「Sprich bitte Englisch」误当成那种问题，
# 用英语反问「Which would you like?」（2026-10-05 复测 5 次中 3 次）。
SWITCH_CONFIRM = {
    'Chinese': '顾客刚要求改用中文。用中文简短确认，不要再问他想用哪种语言。',
    'German': 'Der Kunde hat gerade gebeten, Deutsch zu sprechen. Bestätige kurz auf Deutsch; '
              'frag nicht, welche Sprache er möchte.',
    'English': 'The customer just asked you to speak English. Confirm briefly in English; '
               'do not ask which language they want.',
}

# 每轮附在末尾、用顾客的语言写的规则。系统指令里虽有同样的话，但埋在两万字中段，实测压不住：
#   德语回答把「Plant-Based Fish-Style Penne」意译成「Fischstäbchen-Penne」；
#   回答「里面有什么」时顺带报过敏原，把别的商品的腰果、芹菜串了过来；
#   说某几款「besonders beliebt」（没有销量数据）；把没标 🌶️ 的调味猪肉末面说成辣的；
#   中文回答把「Korean Spicy Chicken Noodles」译成「韩式辣鸡面」。
TURN_RULES = {
    'Chinese': '[提示，勿复述：回答简短，最多三句话，最多念三个商品名。商品名照数据原样说，不要翻译或改写{example}，'
               '英文、德文菜名也照原文念，不要译成中文。顾客没问过敏原时不要主动提过敏原。'
               '不要说哪款受欢迎或卖得好；菜名没标辣的不要说辣。]',
    'German': '[Hinweis, nicht vorlesen: Kurz antworten, höchstens drei Sätze und höchstens drei Produktnamen. '
              'Produktnamen genau so sagen, wie sie in den Daten stehen, nicht übersetzen{example}. '
              'Allergene nur nennen, wenn der Kunde danach fragt. Sag nicht, dass etwas beliebt ist oder sich gut '
              'verkauft, und nenne nichts scharf, was im Namen nicht als scharf markiert ist.]',
    'English': '[Note, do not read aloud: keep it short, at most three sentences and at most three product names. '
               'Say product names exactly as they appear in the data; do not translate them{example}. '
               'Mention allergens only if the customer asks about them. Do not call anything popular or a '
               'bestseller, and do not call anything spicy unless its name marks it as spicy.]',
}
# 示例用当前货架上的真名：中文名最容易被意译成「BBQ beef dumplings」，外文名会被意译成「鱼条意面」
RULE_EXAMPLE = {
    'Chinese': lambda names: '，比如' + '和'.join(f'“{n}”' for n in names) + '都照原样念',
    'German': lambda names: ' – z. B. bleiben ' + ' und '.join(f'„{n}“' for n in names) + ' genau so',
    'English': lambda names: ', e.g. ' + ' and '.join(f'"{n}"' for n in names) + ' stay exactly as they are',
}

LANGUAGES = ('Chinese', 'German', 'English')


def turn_rules(language, system_prompt):
    """每轮末尾附的规则，带上从系统指令货道段读出的一个中文名、一个外文名做示例。"""
    from core.utils.menu_knowledge import shelf_names_from_context
    from core.utils.textUtils import check_emoji
    names = [check_emoji(n).strip() for n in shelf_names_from_context(system_prompt or "")]
    cjk = next((n for n in names if re.search(r'[一-鿿]', n)), None)
    latin = next((n for n in names if n and not re.search(r'[一-鿿]', n)), None)
    picked = [n for n in (cjk, latin) if n]
    example = RULE_EXAMPLE[language](picked) if picked else ''
    return TURN_RULES[language].replace('{example}', example)


# ---------------------------------------------------------------- 语言判定

def has_strong_signal(text, lang):
    """这一句是不是真的在用该语言说话，而不是夹了一两个外来词。"""
    t = text or ''
    if lang == 'Chinese':
        return len(re.findall(r'[一-鿿]', t)) >= 3
    if lang == 'German':
        return bool(re.search(r'[äöüÄÖÜß]', t)) or len(re.findall(
            r'\b(?:der|die|das|und|ist|sind|nicht|haben|gibt|was|wie|ich|Sie)\b', t, re.I)) >= 2
    if lang == 'English':
        return len(re.findall(r'\b(?:the|is|are|what|how|do|does|you|have|available|please)\b',
                              t, re.I)) >= 2
    return False


def requested_language(text):
    """顾客是否显式要求了某种语言。没有则返回 None。

    漏认的代价很大：调用方会按这句话本身的语言下发回答语言指令，
    「Sprich bitte Englisch」就被配上「Antworte auf Deutsch」。两条指令打架时，
    模型实测会把纠结过程连同提示词原文念给顾客（2026-10-05 沙盒，7 次中 2 次）。
    """
    want = text or ''
    # 固定说法：出现即算请求
    if re.search(r'[说讲]德(语|文|語)|用德(语|文|語)|auf Deutsch|in German|德语回答|德文回答', want, re.I):
        return 'German'
    if re.search(r'[说讲]英(语|文)|用英(语|文)|in English|auf Englisch|英语回答|英文回答', want, re.I):
        return 'English'
    if re.search(r'[说讲]中(文|国话)|[说讲]汉语|[说讲]普通话|用中文|in Chinese|auf Chinesisch|中文回答', want, re.I):
        return 'Chinese'
    # 「说」类动词 + 语言名：Sprich bitte Englisch / Can you speak German / English, please。
    # 否定句（Ich spreche kein Englisch / I don't speak German）是在说自己，不是请求；
    # 「talk about the German dumplings」「über chinesisches Essen」是在聊话题。
    if not re.search(r"\b(?:kein|nicht|don'?t|do not|can'?t|cannot|about|über)\b|不会|不懂", want, re.I):
        for lang, names in (('German', r'deutsch|german'),
                            ('English', r'englisch|english'),
                            ('Chinese', r'chinesisch|chinese|mandarin')):
            if re.search(
                    r'\b(?:spr[ie]ch\w*|speak|talk)\b[^.?!]{0,20}?\b(?:' + names + r')\b'
                    r'|\b(?:' + names + r')\b[^.?!]{0,10}?\b(?:sprechen|bitte|please)\b',
                    want, re.I):
                return lang
    return requested_language_by_sound(want)


def requested_language_by_sound(text):
    """按读音兜底。语音识别常把「说德语」听成「朱德宇」「苏德宇」「说德宇」，
    实机上真的发生过，而且之后整轮卡住。

    锚在语言名本身（德语/英语/中文）而不是整句，因为动词最容易被听坏。
    只在短句上启用：顾客站在机器前说的语言切换指令都很短，
    长句里出现「德语」多半是在聊别的。
    """
    raw = (text or '').strip()
    if not raw or len(raw) > 12:
        return None
    try:
        from core.utils.menu_knowledge import _pinyin_key
    except Exception:
        return None
    key = _pinyin_key(raw)
    if len(key) < 4:
        return None
    import difflib
    targets = (
        ('German', ('deyu', 'deyv', 'dewen', 'deguohua')),
        ('English', ('yingyu', 'yingwen', 'yingguohua')),
        ('Chinese', ('zhongwen', 'zhongguohua', 'hanyu')),
    )
    best, best_score = None, 0.0
    for lang, forms in targets:
        for form in forms:
            folded = form
            for src, dst in (('zh', 'z'), ('ch', 'c'), ('sh', 's'),
                             ('ang', 'an'), ('eng', 'en'), ('ing', 'in')):
                folded = folded.replace(src, dst)
            if folded in key:
                return lang
            # 允许一个音节的偏差
            for start in range(0, max(1, len(key) - len(folded) + 2)):
                window = key[start:start + len(folded)]
                if not window:
                    continue
                score = difflib.SequenceMatcher(None, folded, window).ratio()
                if score > best_score:
                    best, best_score = lang, score
    return best if best_score >= 0.85 else None


def reply_language(text):
    """按顾客这一句判定回答语言。回放的历史是中文的，
    不加这条指令模型会跟着历史说中文，把英德顾客的提问答成中文。"""
    # 顾客可能用甲语言要求你用乙语言回答（「说德语」「speak English」）。
    # 必须听顾客的，否则会出现「说英文」→「我只能用中文回答」这种
    # 既不听话又说假话的回复。实机上真的发生过。
    requested = requested_language(text)
    if requested:
        return requested
    if re.search(r'[一-鿿]', text or ''):
        return 'Chinese'
    if re.search(r'[äöüÄÖÜß]', text or '') or re.search(
        r'\b(?:ist|sind|was|wie|wo|hast|haben|gibt|drin|nicht|kein|bitte|danke|'
        r'der|die|das|und|noch|wann|welche|ich|du|sie)\b', text or '', re.I):
        return 'German'
    return 'English'


def update_forced_language(forced, last_user):
    """语言粘性：顾客显式要求过某语言就一直用它，直到再次要求，
    或顾客真的改用另一种语言说话（此时按说话的语言走）。
    返回 (新的粘性语言或 None, 本轮显式请求的语言或 None, 本轮回答语言)。"""
    requested = requested_language(last_user)
    spoken = reply_language(last_user)
    if requested:
        forced = requested
    elif forced and spoken != forced:
        # 顾客这一句本身就是另一种语言，说明自然切换了，撤销粘性
        if spoken in LANGUAGES and has_strong_signal(last_user, spoken):
            forced = None
    return forced, requested, forced or spoken


# ---------------------------------------------------------------- 对话结构

def history_turns(dialogue):
    """取出对话里的用户/助手轮次，跳过系统消息和 few-shot 临时消息。

    few-shot 示例（「给我讲个故事吧」「拜拜」）进入 LLM 对话时 is_temporary 标记已经
    没有了，只能靠形状认：它们的下一条总是带 tool_calls 的 assistant 消息，
    而本链路的真实轮次永远不会有这种形状。"""
    messages = list(dialogue or [])
    turns = []
    for index, message in enumerate(messages):
        role = message.get('role')
        content = message.get('content')
        if role not in ('user', 'assistant') or not isinstance(content, str) or not content.strip():
            continue
        if role == 'user' and index + 1 < len(messages) and messages[index + 1].get('tool_calls'):
            continue
        turns.append((role, content.strip()))
    return turns


def split_dialogue(dialogue):
    """(最后一条 system 的内容, 最后一条 user 的内容)。"""
    system_prompt = ""
    last_user = ""
    for message in dialogue or []:
        if message.get("role") == "system" and message.get("content"):
            system_prompt = message["content"]
    for message in reversed(dialogue or []):
        if message.get("role") == "user":
            last_user = message.get("content") or ""
            break
    return system_prompt, last_user


def dish_facts(text, menu_settings):
    """把对话里提到的菜品资料补进背景。顾客用中文问过某款商品、
    再用英语德语追问时，该商品若不在货道上，模型手里就没有资料。"""
    if not menu_settings:
        return "", []  # 调用方按 (facts, names) 解包，空配置也得给二元组
    try:
        from core.utils.menu_knowledge import dishes_mentioned_context
        return dishes_mentioned_context(text, menu_settings)
    except Exception as e:
        logger.bind(tag=TAG).warning(f"补充菜品资料失败: {e}")
        return "", []


def _named_shelf_items(last_user, system_prompt):
    from core.utils.menu_knowledge import items_in_named_category, shelf_names_from_context
    return items_in_named_category(last_user, shelf_names_from_context(system_prompt or ""))


def referent_background(last_user, system_prompt, missed_turns, menu_settings, include_recap=True):
    """给模型的指代背景：前几轮提到的菜（可能不在货架上）的资料、点名类别对应的货架商品。
    missed_turns 是模型没见过的轮次（常驻进程式 provider）或最近几轮（无状态 provider，
    此时 include_recap=False：历史已在消息里，不必复述）。返回字符串，可能为空。"""
    recap = '\n'.join(('顾客：' if role == 'user' else '你的回答：') + text for role, text in missed_turns)
    facts, names = dish_facts(recap + '\n' + last_user, menu_settings)
    from core.utils.menu_knowledge import mentions_product_noun
    named_shelf = _named_shelf_items(last_user, system_prompt)
    if named_shelf:
        # 顾客点名的是一类商品（Teigtaschen / dumplings / 饺子），直接说清楚对应货架上哪几款。
        # 只说「按点名的回答」不够：背景里只有前几轮那道菜的资料，模型复测 3/3 仍把
        # 「Was ist in den Teigtaschen drin?」答成 Dampfnudel（2026-10-05）。
        return (f"[背景，勿复述。顾客这句话说的商品指货架上的：{'、'.join(named_shelf)}。"
                f"只按这几款回答，资料见系统指令里的货道商品"
                + (f"；不要套用前几轮提到的{'、'.join(names)}" if names else "") + "]")
    if names and mentions_product_noun(last_user):
        # 顾客这句话自己点名了商品，就不能再把指代绑到前几轮的菜上。
        return (f"[背景，勿复述。前几轮提到过：{'、'.join(names)}。"
                f"顾客这句话点名了商品，按他这句话点名的商品回答，不要套用前几轮的商品]\n{facts}")
    if names:
        # 点名比让模型从回放里自己推断可靠得多。前面几轮里夹着 few-shot 示例和货道清单，指代很容易被埋掉。
        return (f"[背景，勿复述。顾客这几轮说的商品是：{'、'.join(names)}。"
                f"顾客现在用「它/da drin/in it」这类说法时，指的就是它]\n{facts}")
    if not include_recap:
        return ""
    return ("[背景：本次对话中你尚未看到的几轮，仅供你判断顾客在说哪款商品。"
            f"不要复述这段话]\n{recap}")


def build_payload(last_user, system_prompt, *, missed_turns, forced_language, menu_settings,
                  always_directive=False, context_turns=()):
    """组装本轮送给模型的 user 文本。

    返回 dict：payload、language（本轮回答语言）、requested（本轮显式要求的语言或 None）、
    forced_language（更新后的粘性语言）。
    missed_turns：模型没见过的前几轮 [(role, text)]；常驻进程式 provider 传本地直答跳过的轮次，
    每次都送完整历史的 provider 传空列表。
    always_directive：无粘性语言时也附语言指令。常驻进程有上一轮的语境可依赖，可以不附；
    无状态 provider 每轮都是新请求，附上更稳。
    context_turns：模型已经见过、但其中提到的菜可能不在货架上的最近几轮。无状态 provider 传它，
    顾客问「Was ist da drin?」时才有 Dampfnudel 的配料可答（交付验证时云端模型答成了货单）。
    """
    forced, requested, language_now = update_forced_language(forced_language, last_user)
    payload = last_user
    if not missed_turns and (forced or always_directive):
        # 没有回放块时也要带上语言指令，否则切过去的语言下一轮就丢了
        payload = (f"{LANGUAGE_DIRECTIVE[language_now]}\n\n"
                   f"{ASK_LABEL[language_now]}: {last_user}\n\n{LANGUAGE_DIRECTIVE[language_now]}")
    if missed_turns:
        background = referent_background(last_user, system_prompt, missed_turns, menu_settings)
        directive = LANGUAGE_DIRECTIVE[language_now]
        # 背景资料是中文的，篇幅又比提问长得多，只在末尾说一次压不住，模型会跟着背景的语言走。首尾各放一次。
        payload = f"{directive}\n\n{background}\n\n{ASK_LABEL[language_now]}: {last_user}\n\n{directive}"
    if payload == last_user:
        # 原话也用目标语言的标签包起来，后面附的规则才不会和顾客原话混在一起
        payload = f"{ASK_LABEL[language_now]}: {last_user}"
    if not missed_turns and context_turns:
        background = referent_background(last_user, system_prompt, list(context_turns), menu_settings,
                                         include_recap=False)
        if background:
            payload = f"{background}\n{payload}"
    elif not missed_turns:
        # 没有前几轮可回放时（新连接第一句），点名一类商品也要写明对应货架上哪几款。
        # 2026-10-05 复测：「Was ist in den Teigtaschen drin?」被答成牛肉蒸饺、腊肠炒饭和 Penne。
        named_now = _named_shelf_items(last_user, system_prompt)
        if named_now:
            payload = (f"[背景，勿复述。顾客这句话说的商品指货架上的：{'、'.join(named_now)}。"
                       f"只按这几款回答]\n{payload}")
    if requested:
        payload = f"{payload}\n\n{SWITCH_CONFIRM[requested]}"
    payload = f"{payload}\n\n{turn_rules(language_now, system_prompt)}"
    return {"payload": payload, "language": language_now, "requested": requested, "forced_language": forced}


def shape_dialogue(dialogue, state, menu_settings):
    """给每次都送完整历史的 provider（OpenAI 兼容等）用：改写最后一条 user 消息，其余原样。

    state 是按连接保存的 dict（connection 持有），只放粘性语言。
    不改传入的消息对象，返回新列表。"""
    if not dialogue:
        return dialogue
    last_index = next((i for i in range(len(dialogue) - 1, -1, -1) if dialogue[i].get("role") == "user"), None)
    if last_index is None:
        return dialogue
    system_prompt, last_user = split_dialogue(dialogue)
    if not isinstance(last_user, str) or not last_user.strip():
        return dialogue
    recent = history_turns(dialogue[:last_index])[-6:]   # 最近三轮问答，够找回「它」指的是哪款
    shaped = build_payload(last_user, system_prompt, missed_turns=[], forced_language=state.get("forced_language"),
                           menu_settings=menu_settings, always_directive=True, context_turns=recent)
    state["forced_language"] = shaped["forced_language"]
    state["language"] = shaped["language"]
    message = dict(dialogue[last_index])
    message["content"] = shaped["payload"]
    return dialogue[:last_index] + [message] + dialogue[last_index + 1:]
