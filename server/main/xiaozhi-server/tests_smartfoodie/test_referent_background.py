# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""多轮对话的指代背景不能压过顾客这句话里点名的商品（2026-10-05 沙盒测试）。

复现：先问 Dampfnudel（本地直答，不经过模型），再问「Ist in den Teigtaschen Sesam drin?」。
旧背景写「顾客现在用 它/da drin/in it 时指的就是 Dampfnudel」，只附 Dampfnudel 的资料，
还贴着「在售及货道上商品」的标签。模型 3/3 回答「没有芝麻，只含牛奶和麸质」，
而货架上两款饺子都含芝麻。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.providers.llm.claudecli import claudecli as cc
from core.utils.menu_knowledge import (
    DEFAULT_CATALOG, SHELF_CONTEXT_LABEL, dishes_mentioned_context, mentions_product_noun,
    shelf_menu_context, shelf_names_from_context,
)

DAMPFNUDEL_ANSWER = ("Dampfnudel mit Vanillesauce und Kirschen. Der Standardpreis beträgt 3.99 Euro "
                     "pro Portion. Es gilt der aktuelle Preis am Automaten.")


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


def payload_for(followup, system_prompt="SYS"):
    provider = cc.LLMProvider.__new__(cc.LLMProvider)
    provider.menu_settings = {"path": str(DEFAULT_CATALOG), "concise_voice": True}
    provider.fallback_text = "fallback"
    provider._warned_no_tools = False
    session = _FakeSession()
    provider._get_session = lambda session_id, system_prompt: session
    dialogue = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Was kostet die Dampfnudel mit Vanillesauce?"},
        {"role": "assistant", "content": DAMPFNUDEL_ANSWER},
        {"role": "user", "content": followup},
    ]
    list(provider.response("s", dialogue))
    return session.payload


class ReferentBackgroundTests(unittest.TestCase):
    def test_named_product_overrides_previous_dish(self):
        payload = payload_for("Ist in den Teigtaschen Sesam drin?")
        self.assertNotIn("指的就是它", payload)
        self.assertIn("点名", payload)

    def test_pronoun_followup_still_points_to_previous_dish(self):
        payload = payload_for("Ist da Sesam drin?")
        self.assertIn("指的就是它", payload)
        self.assertIn("Dampfnudel", payload)

    def test_named_category_is_mapped_to_shelf_items(self):
        # 第一次修复只改了措辞，背景里仍只有 Dampfnudel 的资料，复测 3/3 仍答成 Dampfnudel。
        # 要把「Teigtaschen」直接对应到货架上的饺子。
        shelf = shelf_menu_context(["BBQ牛肉蒸饺（6大粒）", "Fried Rice with Asian Sausage", "鸡肉蔬菜小笼包（6个）"],
                                   {"path": str(DEFAULT_CATALOG)})
        payload = payload_for("Was ist in den Teigtaschen drin?", system_prompt="规则……\n<context>\n" + shelf + "\n</context>")
        self.assertIn("BBQ牛肉蒸饺", payload.split("[背景")[1].split("]")[0])
        self.assertIn("鸡肉蔬菜小笼包", payload.split("[背景")[1].split("]")[0])
        self.assertNotIn("Fried Rice", payload.split("[背景")[1].split("]")[0])
        self.assertIn("不要套用", payload)

    def test_named_category_is_mapped_even_on_the_first_turn(self):
        # 第三轮复测：新连接第一句就问「Was ist in den Teigtaschen drin?」，没有前几轮记录，
        # 映射提示没加，模型把腊肠炒饭和 Penne 也当成了 Teigtaschen
        shelf = shelf_menu_context(["BBQ牛肉蒸饺（6大粒）", "Fried Rice with Asian Sausage", "鸡肉蔬菜小笼包（6个）"],
                                   {"path": str(DEFAULT_CATALOG)})
        provider = cc.LLMProvider.__new__(cc.LLMProvider)
        provider.menu_settings = {"path": str(DEFAULT_CATALOG), "concise_voice": True}
        provider.fallback_text = "fallback"
        provider._warned_no_tools = False
        session = _FakeSession()
        provider._get_session = lambda session_id, system_prompt: session
        list(provider.response("s", [{"role": "system", "content": "规则……\n" + shelf},
                                     {"role": "user", "content": "Was ist in den Teigtaschen drin?"}]))
        hint = session.payload.split("[背景")[1].split("]")[0]
        self.assertIn("BBQ牛肉蒸饺", hint)
        self.assertIn("鸡肉蔬菜小笼包", hint)
        self.assertNotIn("Fried Rice", hint)

    def test_named_category_is_mapped_when_only_fewshot_turns_precede(self):
        # 真实首轮前面有示例对话（直接回答类 few-shot），它们也算「没回放过的轮次」，
        # 走回放分支；那个分支原来只在认出前几轮菜名时才加映射
        shelf = shelf_menu_context(["BBQ牛肉蒸饺（6大粒）", "Fried Rice with Asian Sausage", "鸡肉蔬菜小笼包（6个）"],
                                   {"path": str(DEFAULT_CATALOG)})
        provider = cc.LLMProvider.__new__(cc.LLMProvider)
        provider.menu_settings = {"path": str(DEFAULT_CATALOG), "concise_voice": True}
        provider.fallback_text = "fallback"
        provider._warned_no_tools = False
        session = _FakeSession()
        provider._get_session = lambda session_id, system_prompt: session
        list(provider.response("s", [{"role": "system", "content": "规则……\n" + shelf},
                                     {"role": "user", "content": "你好"},
                                     {"role": "assistant", "content": "你好，有什么可以帮你？"},
                                     {"role": "user", "content": "Was ist in den Teigtaschen drin?"}]))
        hint = session.payload.split("[背景")[1].split("]")[0]
        self.assertIn("鸡肉蔬菜小笼包", hint)
        self.assertNotIn("Fried Rice", hint)

    def test_shelf_names_round_trip_through_context(self):
        names = ["BBQ牛肉蒸饺（6大粒）", "Korean Spicy Chicken Noodles"]
        block = shelf_menu_context(names, {"path": str(DEFAULT_CATALOG)})
        parsed = shelf_names_from_context("前文\n" + block + "\n- **完整菜单：** ……")
        self.assertEqual(len(parsed), 2)
        self.assertTrue(any("BBQ牛肉蒸饺" in name for name in parsed))

    def test_mentioned_dish_is_not_labelled_as_on_shelf(self):
        facts, names = dishes_mentioned_context("Dampfnudel mit Vanillesauce", {"path": str(DEFAULT_CATALOG)})
        self.assertTrue(names)
        self.assertNotIn(SHELF_CONTEXT_LABEL, facts)
        self.assertIn("不代表本机有货", facts)

    def test_product_nouns_in_three_languages(self):
        for text in ("Ist in den Teigtaschen Sesam drin?", "Do the dumplings contain sesame?",
                     "饺子里有芝麻吗", "Sind in den Nudeln Erdnüsse?", "Is there egg in the fried rice?"):
            self.assertTrue(mentions_product_noun(text), text)
        # 「Preis」「price」里藏着 reis/rice，「里面」里藏着「面」，都不能算点名商品
        for text in ("Ist da Sesam drin?", "What's the price?", "Wie ist der Preis?", "它里面有什么", "Does it contain nuts?"):
            self.assertFalse(mentions_product_noun(text), text)


if __name__ == "__main__":
    unittest.main()
