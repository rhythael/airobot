# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""每轮附给模型的两条目标语言规则（第二轮 debug，2026-10-05）。

1. 菜名照原样说：德语回答把「Plant-Based Fish-Style Penne」说成「Fischstäbchen-Penne」，
   给素食顾客推荐「鱼条意面」。提示词里的 <product_names> 规则写在很长的系统指令中段，压不住。
2. 没被问到不报过敏原：回答「Was ist in den Teigtaschen drin?」时模型顺带报过敏原，
   把韩式鸡肉面的腰果、芹菜串到了小笼包上。过敏原问法已由本地规则直答，模型不该主动提。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.providers.llm.claudecli import claudecli as cc


class _FakeSession:
    def __init__(self):
        self.system_prompt = "SYS"
        self.sent_turns = 0
        self.forced_language = None
        self.payload = None

    def is_alive(self):
        return True

    def ask(self, text):
        self.payload = text
        yield "ok"


def payload_for(text, system_prompt="SYS"):
    provider = cc.LLMProvider.__new__(cc.LLMProvider)
    provider.menu_settings = {}
    provider.fallback_text = "fallback"
    provider._warned_no_tools = False
    session = _FakeSession()
    provider._get_session = lambda session_id, prompt: session
    list(provider.response("s", [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]))
    return session.payload


class TurnRuleTests(unittest.TestCase):
    def test_rules_in_the_customers_language(self):
        de = payload_for("Welche Gerichte sind vegetarisch?")
        self.assertIn("nicht übersetzen", de)
        self.assertIn("Allergene nur", de)
        en = payload_for("What is vegetarian here?")
        self.assertIn("do not translate", en)
        self.assertIn("allergens only", en)
        zh = payload_for("有什么素的")
        self.assertIn("不要翻译", zh)
        self.assertIn("过敏原", zh)

    def test_no_invented_popularity_or_spiciness(self):
        # 第四轮：模型说某几款「besonders beliebt」，把调味猪肉末面说成辣的；没有销量数据，也没标辣
        de = payload_for("Was empfiehlst du mir?")
        self.assertIn("beliebt", de)
        self.assertIn("scharf", de)
        en = payload_for("What do you recommend?")
        self.assertIn("popular", en)
        self.assertIn("spicy", en)
        zh = payload_for("推荐一个")
        self.assertIn("受欢迎", zh)
        self.assertIn("辣", zh)

    def test_chinese_rule_keeps_foreign_names(self):
        # 中文回答把「Korean Spicy Chicken Noodles」译成「韩式辣鸡面」
        self.assertIn("英文、德文菜名也照原文念", payload_for("推荐一个"))

    def test_customer_words_are_labelled_and_kept(self):
        payload = payload_for("Welche Gerichte sind vegetarisch?")
        self.assertIn("Der Kunde sagt jetzt: Welche Gerichte sind vegetarisch?", payload)

    def test_label_survives_system_prompt_update(self):
        payload = payload_for("What is vegetarian here?", system_prompt="NEW SYSTEM PROMPT")
        self.assertIn("NEW SYSTEM PROMPT", payload)
        self.assertIn("The customer now says: What is vegetarian here?", payload)


if __name__ == "__main__":
    unittest.main()
