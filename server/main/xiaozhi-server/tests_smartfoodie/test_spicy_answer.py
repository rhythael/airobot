# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""辣度问法走本地规则（第四轮 debug，2026-10-05）。

模型把没标辣的 Gewürzte Schweinehackfleisch-Nudeln（调味猪肉末面）、黑椒牛肉炒饭、BBQ牛肉蒸饺
说成辣的。目录菜名里的 🌶️ 个数就是辣度：「虾仁云吞面（微辣）🌶️」「虾仁云吞面（辣）🌶️🌶️」
「湘味小炒黄牛肉盖饭🌶️🌶️🌶️」；少数菜名写了「辣 / Chili」但没标 🌶️。
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.utils.diet_answer import local_spicy_answer, spicy_level
from core.utils.menu_knowledge import DEFAULT_CATALOG
from test_diet_answer import SHELF, KOREAN, PORK_NOODLES, PENNE

MENU = {"path": str(DEFAULT_CATALOG)}
SETTINGS = {"local_spicy_answers": True, "unavailable_context": "unavailable"}


def ask(query, data=SHELF, context="fresh"):
    return local_spicy_answer(query, context, data, SETTINGS, MENU)


class SpicyLevelTests(unittest.TestCase):
    def test_levels_from_chili_markers_and_name_words(self):
        self.assertEqual(spicy_level({"name": "🦐虾仁云吞面（微辣）🌶️"}), 1)
        self.assertEqual(spicy_level({"name": "🐮湘味小炒黄牛肉盖饭🌶️🌶️🌶️"}), 3)
        self.assertEqual(spicy_level({"name": "🐮Chili con Carne Reis Bowl"}), 0)   # 写了辣但没标级别
        self.assertIsNone(spicy_level({"name": "🐷Gewürzte Schweinehackfleisch-Nudeln"}))


class WantSpicyTests(unittest.TestCase):
    def test_only_korean_noodles_are_spicy_in_three_languages(self):
        cases = (("我想吃点辣的", "有一款辣的。", "微辣"),
                 ("Welche Gerichte sind scharf?", "Es gibt ein scharfes Gericht. ", "leicht scharf"),
                 ("Do you have anything spicy?", "One item is spicy. ", "mildly spicy"))
        for query, lead, level in cases:
            answer = ask(query)
            self.assertIsNotNone(answer, query)
            self.assertTrue(answer.startswith(lead), answer)
            self.assertIn(KOREAN, answer)
            self.assertIn(level, answer)
            for name in (PORK_NOODLES, "BBQ牛肉蒸饺", "Black Pepper"):
                self.assertNotIn(name, answer, query)

    def test_nothing_spicy_on_shelf(self):
        data = copy.deepcopy(SHELF)
        for item in data["inventory"]["items"]:
            if item["name"] == KOREAN:
                item["purchasable"] = False
        self.assertTrue(ask("有什么辣的", data).startswith("货架上现在没有辣的"))


class AvoidSpicyTests(unittest.TestCase):
    def test_no_spicy(self):
        zh = ask("我不吃辣")
        self.assertTrue(zh.startswith("不吃辣的话，有六款可以选。"), zh)
        self.assertIn(KOREAN + "是辣的", zh)
        en = ask("Something not spicy please")
        self.assertTrue(en.startswith("Six items aren't spicy. "), en)
        de = ask("Ich möchte nichts Scharfes")
        self.assertTrue(de.startswith("Ohne Schärfe gibt es sechs Gerichte. "), de)


class NumberWordTests(unittest.TestCase):
    def test_remaining_count_is_spoken_as_a_word(self):
        self.assertIn("还有两款", ask("我不吃辣"))
        self.assertIn("two more", ask("Something not spicy please"))
        self.assertIn("zwei weitere", ask("Ich möchte nichts Scharfes"))


class NamedItemTests(unittest.TestCase):
    def test_bu_la_question(self):
        self.assertIn("特辣", ask("湘味小炒黄牛肉盖饭辣不辣"))

    def test_named_items(self):
        self.assertIn("mildly spicy", ask("Is the Korean Spicy Chicken Noodles spicy?"))
        self.assertIn("isn't marked spicy", ask("Is the Gewürzte Schweinehackfleisch-Nudeln spicy?"))
        self.assertIn("没标辣", ask("Plant-Based Fish-Style Penne辣吗"))


class SafeFallbackTests(unittest.TestCase):
    def test_names_containing_spicy_words_are_not_spicy_questions(self):
        for query in ("Do you have Korean Spicy Chicken Noodles?", "Korean Spicy Chicken Noodles还有吗",
                      "辣子鸡丁盖饭还有吗"):
            self.assertIsNone(ask(query), query)

    def test_unsure_goes_to_model(self):
        for query in ("Ist das scharf?", "Welche Gerichte sind scharf und vegetarisch?", "Was gibt es gerade?",
                      "Is the coffee spicy?"):
            self.assertIsNone(ask(query), query)
        self.assertIsNone(local_spicy_answer("有什么辣的", "fresh", SHELF, {}, MENU))
        self.assertIsNone(ask("有什么辣的", context="unavailable"))


if __name__ == "__main__":
    unittest.main()
