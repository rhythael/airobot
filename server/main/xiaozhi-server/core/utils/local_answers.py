# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""本地直答的统一入口：一次调用按固定顺序试四个回答器，命中就不走模型。

  0. local_allergen_answer  「我对花生过敏」「饺子里有芝麻吗」——查过敏原原文（2026-10-05 加）
  0a. local_diet_answer     「有什么素的」「我不吃鸡肉」——按菜名表情和配料原文（2026-10-05 加）
  0a'. local_spicy_answer   「有什么辣的」「我不吃辣」——按菜名 🌶️ 个数（2026-10-05 加）
  0b. local_greeting_answer 单独一句 Hallo / Hello / 你好——直接回应（2026-10-05 加）
  0c. local_menu_overview_answer「菜单上还有什么」——按目录主料分组概括（2026-10-05 加）

顺序和 2026-10-02 之前 connection.chat 里三段 `if answer is None` 完全一样：
  1. local_count_answer     「有几种商品」——数量从格式化上下文里读
  2. local_product_answer   「X 还有吗」——用 lookup_query（菜单追问解析后的那句）
  3. local_template_answer  「有什么吃的 / 哪些过期 / 几个空货道 / X 货道是什么」
为什么分开传 query 和 lookup_query：只有商品问法需要把「它还有吗」解析成上一轮的菜名，
数量和模板问法必须按顾客原话匹配，否则「它还有吗」会被解析后的菜名撞上别的模式。
"""
from core.utils.allergen_answer import local_allergen_answer
from core.utils.diet_answer import local_diet_answer, local_spicy_answer
from core.utils.product_answer import local_product_answer
from core.utils.template_answers import local_greeting_answer, local_menu_overview_answer, local_template_answer
from core.utils.turn_context import local_count_answer, normalize_query


def route(conn, query, lookup_query):
    """命中任一本地回答器则返回答案文本，否则 None（交给模型）。"""
    settings = conn.config["turn_context_refresh"]
    context = conn.prompt_manager.context_data
    data = conn.prompt_manager.context_provider.structured_data
    if not isinstance(query, str):
        return None
    # 归一化一次；各回答器内部再调 normalize_query 是幂等的，保留是为了能被单独调用和测试
    query = normalize_query(query)
    lookup_query = normalize_query(lookup_query) if isinstance(lookup_query, str) else lookup_query
    # 过敏原放最前：「有花生吗」不能被商品直答当成在问一个叫「花生」的商品
    answer = local_allergen_answer(query, context, data, settings, conn.config.get("local_menu_knowledge"))
    if answer is None:
        answer = local_diet_answer(query, context, data, settings, conn.config.get("local_menu_knowledge"))
    if answer is None:
        answer = local_spicy_answer(query, context, data, settings, conn.config.get("local_menu_knowledge"))
    if answer is None:
        answer = local_greeting_answer(query, settings)
    if answer is None:
        answer = local_menu_overview_answer(query, data, settings, conn.config.get("local_menu_knowledge"))
    if answer is None:
        answer = local_count_answer(query, context, settings)
    if answer is None:
        answer = local_product_answer(lookup_query, context, data, settings)
    if answer is None:
        answer = local_template_answer(query, context, data, settings)
    return answer
