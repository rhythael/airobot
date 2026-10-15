# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""过敏原问答走本地规则，直接查货架商品的过敏原原文（2026-10-05 沙盒测试）。

模型拿到的过敏原原文是完整的，但「I'm allergic to peanuts」4 次答错 4 次、错法各不相同，
有一次把标注「可能含花生痕量」的黑椒牛肉炒饭说成安全。这类答案完全由资料决定，不该交给模型。
货架数据取自当天快照；菜单目录用仓库里的真实文件。
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.allergen_answer import local_allergen_answer, split_allergen_text, allergen_status
from core.utils.menu_knowledge import DEFAULT_CATALOG

MENU = {"path": str(DEFAULT_CATALOG)}
SETTINGS = {"local_allergen_answers": True, "unavailable_context": "unavailable"}
SHELF = {"inventory": {"machine_number": "041", "items": [
    {"slot": "1-6", "name": "BBQ牛肉蒸饺（6大粒）", "quantity": 3, "purchasable": True},
    {"slot": "1-7", "name": "Fried Rice with Asian Sausage", "quantity": 3, "purchasable": True},
    {"slot": "1-8", "name": "Plant-Based Fish-Style Penne", "quantity": 2, "purchasable": True},
    {"slot": "1-9", "name": "Korean Spicy Chicken Noodles", "quantity": 3, "purchasable": True},
    {"slot": "2-6", "name": "Fried Rice with Beef in Black Pepper Sauce", "quantity": 3, "purchasable": True},
    {"slot": "2-7", "name": "鸡肉蔬菜小笼包（6个）", "quantity": 3, "purchasable": True},
    {"slot": "2-8", "name": "Gewürzte Schweinehackfleisch-Nudeln", "quantity": 3, "purchasable": True},
    {"slot": "2-9", "name": "Korean Spicy Chicken Noodles", "quantity": 3, "purchasable": True},
]}}
SAUSAGE, BEEF = "Fried Rice with Asian Sausage", "Fried Rice with Beef in Black Pepper Sauce"
DUMPLINGS = ("BBQ牛肉蒸饺（6大粒）", "鸡肉蔬菜小笼包（6个）")


def ask(query, data=SHELF, context="fresh"):
    return local_allergen_answer(query, context, data, SETTINGS, MENU)


def sentence_with(answer, name):
    return next(s for s in answer.replace("!", ".").split(".") if name in s) if "." in answer else \
        next(s for s in answer.split("。") if name in s)


class PeanutScreeningTests(unittest.TestCase):
    def test_english_lists_both_fried_rices_as_traces(self):
        answer = ask("I'm allergic to peanuts.")
        self.assertIsNotNone(answer)
        traces = sentence_with(answer, SAUSAGE)
        self.assertIn(BEEF, traces)
        self.assertIn("traces", traces)
        # 韩式鸡肉面标的是腰果（tree nuts），不是花生，不能出现在花生那句里
        self.assertNotIn("Korean Spicy Chicken Noodles", traces)
        self.assertIn("Plant-Based Fish-Style Penne", answer)  # 没有过敏原资料，要单独说出来

    def test_german_and_chinese(self):
        de = ask("Ich bin allergisch gegen Erdnüsse")
        self.assertIn("Spuren von Erdnüssen", sentence_with(de, SAUSAGE))
        self.assertIn(BEEF, sentence_with(de, SAUSAGE))
        zh = ask("我对花生过敏")
        self.assertIn("可能含微量花生", sentence_with(zh, SAUSAGE))
        self.assertIn(BEEF, sentence_with(zh, SAUSAGE))

    def test_expired_items_are_not_part_of_the_answer(self):
        data = copy.deepcopy(SHELF)
        data["inventory"]["items"][1]["purchasable"] = False
        self.assertNotIn(SAUSAGE, ask("I'm allergic to peanuts.", data))

    def test_generic_nuts_cover_peanuts_and_tree_nuts(self):
        answer = ask("Are there any nuts?")
        self.assertIn("Korean Spicy Chicken Noodles", answer)  # 腰果
        self.assertIn(SAUSAGE, answer)                          # 花生


class PresenceTests(unittest.TestCase):
    def test_sesame_in_dumplings_three_languages(self):
        for query in ("Ist in den Teigtaschen Sesam drin?", "Do the dumplings contain sesame?", "饺子里有芝麻吗"):
            answer = ask(query)
            self.assertIsNotNone(answer, query)
            for name in DUMPLINGS:
                self.assertIn(name, answer, query)
            self.assertNotIn(SAUSAGE, answer, query)
        self.assertIn("enthalten Sesam", ask("Ist in den Teigtaschen Sesam drin?"))
        self.assertIn("含芝麻", ask("饺子里有芝麻吗"))

    def test_asr_spelling_variants(self):
        # 音频复测：Whisper 把「Teigtaschen Sesam」识别成「Teigtaschensäsam」
        answer = ask("ist in den Teigtaschensäsam drin")
        self.assertIsNotNone(answer)
        self.assertIn("enthalten Sesam", answer)
        self.assertIn(SAUSAGE, ask("Ich bin allergisch gegen Erdnüße"))

    def test_named_shelf_item(self):
        answer = ask("Does the Korean Spicy Chicken Noodles contain sesame?")
        self.assertIn("contains sesame", answer)
        self.assertNotIn(SAUSAGE, answer)

    def test_category_without_the_allergen(self):
        answer = ask("Is there egg in the fried rice?")
        self.assertIn(SAUSAGE, answer)
        self.assertIn(BEEF, answer)
        self.assertIn("don't list egg", answer)

    def test_dish_not_on_shelf_answers_from_catalog(self):
        # 不声称「货架上没有」：目录里同一道菜可能有另一种语言的名字正在货架上
        answer = ask("虾饺有芝麻吗")
        self.assertIn("虾饺含芝麻", answer)
        self.assertNotIn(DUMPLINGS[0], answer)


class SafeFallbackTests(unittest.TestCase):
    def test_unrelated_questions(self):
        for query in ("Was gibt es gerade?", "现在有什么吃的", "虾饺有什么过敏原", "Ich möchte etwas ohne Fleisch",
                      "Which dishes are vegetarian and without peanuts?", "How much is the fried rice with beef?"):
            self.assertIsNone(ask(query), query)

    def test_unresolvable_product_goes_to_model(self):
        # shrimp 是修饰 dumpling 的菜名，不是过敏原；货架上也没有虾饺的英文名可认
        self.assertIsNone(ask("Does the shrimp dumpling contain nuts?"))
        self.assertIsNone(ask("Is there sesame in the coffee?"))

    def test_pronoun_followups_go_to_model(self):
        for query in ("Ist da Sesam drin?", "Does it contain nuts?", "它里面有芝麻吗"):
            self.assertIsNone(ask(query), query)

    def test_unavailable_or_invalid_inventory(self):
        self.assertIsNone(ask("I'm allergic to peanuts.", context="unavailable"))
        self.assertIsNone(ask("I'm allergic to peanuts.", data={"inventory": {"machine_number": "042", "items": []}}))
        self.assertIsNone(local_allergen_answer("I'm allergic to peanuts.", "fresh", SHELF, {}, MENU))


class AllergenTextTests(unittest.TestCase):
    def test_contains_and_traces_are_separated(self):
        text = "Allergen information:Contains gluten (wheat) and soy.May contain traces of peanuts and sesame."
        self.assertEqual(allergen_status(text, ["peanut"]), "traces")
        self.assertEqual(allergen_status(text, ["soy"]), "contains")
        self.assertEqual(allergen_status(text, ["egg"]), "clean")
        self.assertEqual(allergen_status("", ["egg"]), "nodata")
        contains, traces = split_allergen_text("过敏提示： 含有小麦、大豆、芝麻。可能含有牛奶、鸡蛋、芥末和甲壳类制品的痕量。")
        self.assertIn("芝麻", contains)
        self.assertIn("牛奶", traces)

    def test_egg_white_counts_but_soy_protein_does_not(self):
        self.assertEqual(allergen_status("过敏提示：含猪肉、小麦、麸质、大豆、芝麻和鸡蛋白。", ["egg"]), "contains")
        self.assertEqual(allergen_status("过敏提示：含组织化大豆蛋白、小麦。", ["egg"]), "clean")

    def test_german_traces(self):
        text = "Allergenhinweis:Enthält Gluten (Weizen) und Soja.Kann Spuren von Krebstieren und Weichtieren enthalten."
        self.assertEqual(allergen_status(text, ["crustacean"]), "traces")
        self.assertEqual(allergen_status(text, ["gluten"]), "contains")


if __name__ == "__main__":
    unittest.main()
