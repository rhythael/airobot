# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""素食 / 不吃某种肉的问法走本地规则（第三轮 debug，2026-10-05）。

模型把 Fried Rice with Asian Sausage、Gewürzte Schweinehackfleisch-Nudeln、Korean Spicy Chicken
Noodles 说成素食，或虚报「另外两款素食」；对照实验有无每轮提示分别 3/6、2/6 出错，是模型原有问题。
菜名开头的表情（🌱🐔🐮🐷…）只是按主料粗分，不是素食保证：🌱 组里有用蚝油、鸡精的菜，
标「素」的金汤酸菜火锅配料里有虾仁和炸鸡肉。所以要结合配料原文判断。
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.diet_answer import animal_terms, local_diet_answer
from core.utils.menu_knowledge import DEFAULT_CATALOG

MENU = {"path": str(DEFAULT_CATALOG)}
SETTINGS = {"local_diet_answers": True, "unavailable_context": "unavailable"}
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
PENNE, SAUSAGE, KOREAN = "Plant-Based Fish-Style Penne", "Fried Rice with Asian Sausage", "Korean Spicy Chicken Noodles"
PORK_NOODLES, XLB = "Gewürzte Schweinehackfleisch-Nudeln", "鸡肉蔬菜小笼包（6个）"


def ask(query, data=SHELF, context="fresh"):
    return local_diet_answer(query, context, data, SETTINGS, MENU)


def first_sentence(answer):
    """名单那一句。全货架回答先有一句不带菜名的引导句，名单在第二句。"""
    parts = answer.split("。") if "。" in answer else answer.split(". ")
    lead = parts[0]
    if re.fullmatch(r"有.款素食为主|货架上现在没有素食|不吃.+的话，有.款可以选|Es gibt .+|Gerade gibt es .+|Ohne .+ gibt es .+"
                    r"|\w+ items? (?:is|are) vegetarian|Nothing on the shelf .+|\w+ items? ha(?:s|ve) no .+|Everything .+|Alle .+", lead):
        return parts[1] if len(parts) > 1 else lead
    return lead


class VegetarianTests(unittest.TestCase):
    def test_only_the_penne_is_vegetarian_in_three_languages(self):
        for query in ("Welche Gerichte sind vegetarisch?", "Ich möchte etwas ohne Fleisch.", "有什么素的",
                      "我吃素", "Do you have anything vegetarian?", "Is there something without meat?"):
            answer = ask(query)
            self.assertIsNotNone(answer, query)
            head = first_sentence(answer)
            self.assertIn(PENNE, head, query)
            for name in (SAUSAGE, KOREAN, PORK_NOODLES):
                self.assertNotIn(name, head, query)
        self.assertIn("1-8", ask("Welche Gerichte sind vegetarisch?"))

    def test_named_item(self):
        self.assertIn("vegetarian", ask("Is the Plant-Based Fish-Style Penne vegetarian?"))
        self.assertNotIn("is vegetarian", ask("Is the Korean Spicy Chicken Noodles vegetarian?"))
        self.assertIn("chicken", ask("Is the Korean Spicy Chicken Noodles vegetarian?"))

    def test_no_vegetarian_item_on_shelf(self):
        data = copy.deepcopy(SHELF)
        data["inventory"]["items"][2]["purchasable"] = False
        answer = ask("有什么素的", data)
        self.assertTrue(answer.startswith("货架上现在没有素食"))
        self.assertNotIn(PENNE, answer)
        # 一款素食都没有时不能说「其余几款」；按菜单优先的规矩补一句菜单上有素食
        self.assertNotIn("其余", answer)
        self.assertIn("菜单上有素食", answer)
        de = ask("Welche Gerichte sind vegetarisch?", data)
        self.assertNotIn("übrigen", de)
        self.assertIn("Auf der Karte", de)


class AvoidMeatTests(unittest.TestCase):
    def test_no_chicken(self):
        answer = ask("我不吃鸡肉，有什么推荐")
        ok = first_sentence(answer)
        self.assertNotIn(KOREAN, ok)
        self.assertNotIn(XLB, ok)
        self.assertIn(PENNE, answer)
        # 不能吃的超过两款就不逐个点名（回答太长，25 秒），只说其余几款含鸡肉成分
        self.assertNotIn(KOREAN, answer)
        self.assertIn("其余几款含鸡肉成分", answer)

    def test_no_pork_in_english_and_german(self):
        for query in ("I don't eat pork", "Ich esse kein Schweinefleisch"):
            answer = ask(query)
            ok = first_sentence(answer)
            self.assertNotIn(SAUSAGE, ok, query)
            self.assertNotIn(PORK_NOODLES, ok, query)
            self.assertRegex(answer, r"other|übrigen", query)


class LeadSentenceTests(unittest.TestCase):
    """首句不带菜名、单一语言：首句本地合成才接得住（模板直答同一条规则）。"""

    def test_vegetarian_lead(self):
        self.assertTrue(ask("有什么素的").startswith("有一款素食为主。"))
        self.assertTrue(ask("Welche Gerichte sind vegetarisch?").startswith("Es gibt ein vegetarisches Gericht. "))
        self.assertTrue(ask("Do you have anything vegetarian?").startswith("One item is vegetarian. "))

    def test_avoid_lead(self):
        self.assertTrue(ask("我不吃鸡肉，有什么推荐").startswith("不吃鸡肉的话，有三款可以选。"))
        self.assertTrue(ask("I don't eat pork").startswith("Four items have no pork. "))
        self.assertTrue(ask("Ich esse kein Schweinefleisch").startswith("Ohne Schweinefleisch gibt es vier Gerichte. "))


class WordingTests(unittest.TestCase):
    def test_hidden_ingredients_are_called_ingredients(self):
        # 两款炒饭含 chicken stock granules，鸡肉小笼包含猪肉明胶：要说「成分」，不能说成整块肉
        zh = ask("我不吃鸡肉，有什么推荐")
        self.assertNotIn("Fried Rice with Asian Sausage", zh.split("。")[1])  # 含鸡精颗粒，不在可选名单里
        self.assertIn("含鸡肉成分", zh)
        self.assertIn("pork ingredients", ask("I don't eat pork"))
        # 只有一两款不能吃时照样点名
        data = copy.deepcopy(SHELF)
        for item in data["inventory"]["items"]:
            if item["name"] in (SAUSAGE, "Fried Rice with Beef in Black Pepper Sauce", KOREAN):
                item["purchasable"] = False
        self.assertIn(XLB, ask("我不吃鸡肉", data))

    def test_category_question_does_not_talk_about_the_whole_shelf(self):
        answer = ask("Are the noodles vegetarian?")
        self.assertNotIn("Nothing on the shelf", answer)
        self.assertNotIn("other items", answer)
        self.assertIn(KOREAN, answer)
        self.assertIn(PORK_NOODLES, answer)

    def test_generic_meat_is_not_repeated_next_to_specific_kind(self):
        self.assertNotIn("and meat", ask("Is the Korean Spicy Chicken Noodles vegetarian?"))

    def test_english_question_about_a_chinese_dish_name_is_answered_in_english(self):
        answer = ask("Is 金汤酸菜味迷你火锅 vegetarian?")
        self.assertIn("contains", answer)
        self.assertIn("seafood", answer)


class SafeFallbackTests(unittest.TestCase):
    def test_goes_to_model_when_unsure(self):
        for query in ("Ist das vegetarisch?", "Welche Gerichte sind vegetarisch und scharf?", "Was gibt es gerade?",
                      "Is the coffee vegetarian?", "我对花生过敏", "现在有什么吃的"):
            self.assertIsNone(ask(query), query)

    def test_unavailable_inventory_or_switched_off(self):
        self.assertIsNone(ask("有什么素的", context="unavailable"))
        self.assertIsNone(ask("有什么素的", data={"inventory": {"machine_number": "042", "items": []}}))
        self.assertIsNone(local_diet_answer("有什么素的", "fresh", SHELF, {}, MENU))


class AnimalTermTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dishes = json.loads(Path(DEFAULT_CATALOG).read_text(encoding="utf-8"))["dishes"]
        cls.by_name = lambda self, part: next(d for d in dishes if part in d["name"])

    def kinds(self, part):
        return set(animal_terms(self.by_name(part)))

    def test_vegetarian_look_alikes_are_not_meat(self):
        self.assertEqual(self.kinds("素叉烧包"), set())          # 素蚝油
        self.assertEqual(self.kinds("森林蘑菇烩饭"), set())       # 牛肝菌、鸡油菌
        self.assertEqual(self.kinds("辣味番茄酱配意大利波浪宽面"), set())  # 鸡蛋面
        self.assertEqual(self.kinds("Fish-Style Penne"), set())
        self.assertEqual(self.kinds("Falafel Couscous"), set())   # fermented 里藏着 ente
        self.assertEqual(self.kinds("黄油素鸡饭"), set())

    def test_hidden_animal_ingredients(self):
        self.assertIn("seafood", self.kinds("地三鲜盖饭"))       # 蚝油
        self.assertIn("chicken", self.kinds("干煸四季豆"))        # 鸡精
        kinds = self.kinds("金汤酸菜味迷你火锅（素）")             # 标「素」但有虾仁、炸鸡肉
        self.assertIn("seafood", kinds)
        self.assertIn("chicken", kinds)

    def test_main_ingredient_emoji(self):
        self.assertIn("chicken", self.kinds("Korean Spicy Chicken Noodles"))
        self.assertIn("pork", self.kinds("Gewürzte Schweinehackfleisch-Nudeln"))


if __name__ == "__main__":
    unittest.main()
