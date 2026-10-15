# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""每轮整形对所有大模型一视同仁（交付整理，2026-10-09）。

语言指令、指代背景、换语言确认、每轮规则原来只在 ClaudeCLI 里；公司换成 OpenAI 兼容的
大模型后这些行为不能丢。shape_dialogue 改写送出去的最后一条 user 消息，和 ClaudeCLI 的 payload 同形。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils import turn_shaping as ts
from core.utils.menu_knowledge import DEFAULT_CATALOG, shelf_menu_context

MENU = {"path": str(DEFAULT_CATALOG), "concise_voice": True}
SHELF = "规则……\n" + shelf_menu_context(["BBQ牛肉蒸饺（6大粒）", "Fried Rice with Asian Sausage"], MENU)


def dialogue(*users, system=SHELF):
    msgs = [{"role": "system", "content": system}]
    for i, text in enumerate(users):
        msgs.append({"role": "user", "content": text})
        if i < len(users) - 1:
            msgs.append({"role": "assistant", "content": "ok"})
    return msgs


class ShapeDialogueTests(unittest.TestCase):
    def test_only_last_user_message_is_rewritten(self):
        original = dialogue("你好", "Was gibt es noch?")
        shaped = ts.shape_dialogue(original, {}, MENU)
        self.assertEqual(shaped[:-1], original[:-1])
        self.assertEqual(original[-1]["content"], "Was gibt es noch?")   # 原对象未被改
        self.assertIn("Der Kunde sagt jetzt: Was gibt es noch?", shaped[-1]["content"])
        self.assertIn("Antworte auf Deutsch", shaped[-1]["content"])
        self.assertIn("höchstens drei Sätze", shaped[-1]["content"])
        self.assertIn("„BBQ牛肉蒸饺（6大粒）“", shaped[-1]["content"])

    def test_language_stickiness_lives_in_state(self):
        state = {}
        ts.shape_dialogue(dialogue("Sprich bitte Englisch"), state, MENU)
        self.assertEqual(state["forced_language"], "English")
        shaped = ts.shape_dialogue(dialogue("Sprich bitte Englisch", "Fried Rice?"), state, MENU)
        self.assertIn("Reply in English", shaped[-1]["content"])      # 短句看不出语言，沿用要求的英语
        shaped = ts.shape_dialogue(dialogue("Sprich bitte Englisch", "Fried Rice?", "Welche Gerichte sind vegetarisch und ohne Fleisch?"), state, MENU)
        self.assertIsNone(state["forced_language"])                     # 整句德语，自然切回
        self.assertIn("Antworte auf Deutsch", shaped[-1]["content"])

    def test_switch_confirmation_and_category_mapping(self):
        shaped = ts.shape_dialogue(dialogue("Speak Chinese, please."), {}, MENU)
        self.assertIn("顾客刚要求改用中文", shaped[-1]["content"])
        shaped = ts.shape_dialogue(dialogue("Was ist in den Teigtaschen drin?"), {}, MENU)
        hint = shaped[-1]["content"].split("[背景")[1].split("]")[0]
        self.assertIn("BBQ牛肉蒸饺（6大粒）", hint)
        self.assertNotIn("Fried Rice", shaped[-1]["content"].split("[背景")[1].split("]")[0])

    def test_pronoun_followup_gets_facts_of_the_dish_from_history(self):
        # 上一轮本地直答了 Dampfnudel 的价格，这一轮「Was ist da drin?」：Dampfnudel 不在货架上，
        # 模型手里没有它的配料。交付验证时 Doubao 把这句答成了货单。
        shaped = ts.shape_dialogue(dialogue("Was kostet die Dampfnudel mit Vanillesauce?", "Was ist da drin?"), {}, MENU)
        content = shaped[-1]["content"]
        self.assertIn("指的就是它", content)
        self.assertIn("Dampfnudel mit Vanillesauce und Kirschen", content)
        self.assertIn("Milch", content)             # 配料原文随背景一起给
        self.assertNotIn("你尚未看到的几轮", content)  # 历史已在消息里，不复述

    def test_no_user_message_or_empty_dialogue_passthrough(self):
        self.assertEqual(ts.shape_dialogue([], {}, MENU), [])
        only_system = [{"role": "system", "content": "x"}]
        self.assertEqual(ts.shape_dialogue(only_system, {}, MENU), only_system)


class ClaudeCliParityTests(unittest.TestCase):
    """ClaudeCLI 走同一个 build_payload，静态方法仍可用（旧测试在用）。"""

    def test_static_helpers_delegate(self):
        from core.providers.llm.claudecli.claudecli import LLMProvider
        self.assertEqual(LLMProvider._requested_language("Sprich bitte Englisch"), "English")
        self.assertEqual(LLMProvider._reply_language("Was gibt es"), "German")
        self.assertTrue(LLMProvider.shapes_turns)

    def test_build_payload_with_missed_turns_replays_background(self):
        shaped = ts.build_payload("Ist da Sesam drin?", SHELF,
                                  missed_turns=[("user", "Was kostet die Dampfnudel mit Vanillesauce?"),
                                                ("assistant", "3,99 Euro")],
                                  forced_language=None, menu_settings=MENU)
        self.assertIn("指的就是它", shaped["payload"])
        self.assertIn("Dampfnudel", shaped["payload"])
        self.assertEqual(shaped["language"], "German")


if __name__ == "__main__":
    unittest.main()
