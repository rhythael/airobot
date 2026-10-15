# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""四类常见库存问题的三语模板直答：宁可漏命中，不能误命中；回答要守播报规则。"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.template_answers import local_template_answer, match_intent, detect_language, zh_number

SETTINGS = {"local_template_answers": True, "unavailable_context": "本轮库存查询失败"}


def inventory(items):
    return {"inventory": {"machine_number": "041", "items": items}}


# 2026-10-02 实机快照：2 种可买、9 个货道过期、7 个空货道
LIVE = inventory([
    {"slot": "1-2", "name": "红烧羊肉盖饭", "quantity": 3, "purchasable": False},
    {"slot": "1-3", "name": "梅菜扣肉盖饭", "quantity": 2, "purchasable": False},
    {"slot": "1-4", "name": "鸡肉蔬菜泰式绿咖喱饭", "quantity": 1, "purchasable": False},
    {"slot": "1-5", "name": "Gewürzte Schweinehackfleisch-Nudeln", "quantity": 1, "purchasable": False},
    {"slot": "1-7", "name": "黄油鸡咖喱配长粒米", "quantity": 1, "purchasable": False},
    {"slot": "1-9", "name": "Korean Spicy Chicken Noodles", "quantity": 2, "purchasable": False},
    {"slot": "2-2", "name": "尖椒牛肉盖饭", "quantity": 1, "purchasable": False},
    {"slot": "2-5", "name": "素炒面", "quantity": 2, "purchasable": True},
    {"slot": "2-6", "name": "印尼风味鸡肉蔬菜面", "quantity": 3, "purchasable": False},
    {"slot": "2-7", "name": "Geschmorte Rindfleischnudeln (ohne Suppe)", "quantity": 1, "purchasable": True},
    {"slot": "2-9", "name": "Korean Spicy Chicken Noodles", "quantity": 3, "purchasable": False},
])

# 24 句听力稿：只有 2/6/10/14/18/22 属于这四类，其余一句都不能命中
LISTENING_SCRIPT = {
    "你好": None,
    "现在有什么吃的": ("available", "zh"),
    "鸡肉蔬菜蒸饺还有吗": None,
    "鱼香茄子盖饭多少钱": None,
    "虾饺有什么过敏原": None,
    "一号七货道是什么": ("slot", "zh"),
    "我不吃鸡肉，有什么推荐": None,
    "说德语": None,
    "Hallo": None,
    "Was gibt es gerade?": ("available", "de"),
    "Welche Gerichte sind vegetarisch?": None,
    "Was kostet die Dampfnudel mit Vanillesauce?": None,
    "Ist in den Teigtaschen Sesam drin?": None,
    "Was liegt im Fach zwei sechs?": ("slot", "de"),
    "Ich möchte etwas ohne Fleisch.": None,
    "Sprich bitte Englisch.": None,
    "Hello": None,
    "What can I buy right now?": ("available", "en"),
    "Do you have Korean Spicy Chicken Noodles?": None,
    "Does the shrimp dumpling contain nuts?": None,
    "How much is the fried rice with beef?": None,
    "What is in slot one seven?": ("slot", "en"),
    "I'm allergic to peanuts.": None,
    "Speak Chinese, please.": None,
}


class IntentMatchingTests(unittest.TestCase):
    def test_listening_script_sentence_by_sentence(self):
        for sentence, expected in LISTENING_SCRIPT.items():
            with self.subTest(sentence=sentence):
                got = match_intent(sentence)
                if expected is None:
                    self.assertIsNone(got, f"误命中: {sentence} -> {got}")
                else:
                    self.assertIsNotNone(got, f"漏命中: {sentence}")
                    self.assertEqual(got[:2], expected)

    def test_slot_numbers_are_normalized_from_speech(self):
        self.assertEqual(match_intent("一号七货道是什么")[2], "1-7")
        self.assertEqual(match_intent("17货道有什么")[2], "1-7")
        self.assertEqual(match_intent("Was liegt im Fach zwei sechs?")[2], "2-6")
        self.assertEqual(match_intent("Was ist in Fach 1/7?")[2], "1-7")
        self.assertEqual(match_intent("What is in slot one seven?")[2], "1-7")
        self.assertEqual(match_intent("what's in slot 2-9")[2], "2-9")

    def test_more_positive_forms(self):
        for sentence, intent in [
            ("41号机器现在有什么吃的？", "available"), ("请问现在能买什么", "available"),
            ("有什么可以买的吗", "available"), ("Was gibt es gerade am Automaten 41?", "available"),
            ("Was kann ich jetzt kaufen?", "available"), ("What can I buy at machine 41 right now?", "available"),
            ("What do you have today?", "available"), ("What's available?", "available"),
            ("有过期的吗", "expired"), ("哪些过期了", "expired"), ("Was ist abgelaufen?", "expired"),
            ("Is anything expired?", "expired"), ("which items are expired", "expired"),
            ("有几个空货道", "empty"), ("哪些货道是空的", "empty"), ("Wie viele Fächer sind leer?", "empty"),
            ("Which slots are empty?", "empty"), ("are there any empty slots", "empty"),
            ("2-5货道是什么", "slot"), ("2-5号货道有什么", "slot"), ("Was ist im Fach 2-5?", "slot"),
            ("What's in slot 2-5 right now?", "slot"),
        ]:
            with self.subTest(sentence=sentence):
                got = match_intent(sentence)
                self.assertIsNotNone(got, sentence)
                self.assertEqual(got[0], intent)

    def test_never_matches_other_intents(self):
        for sentence in [
            "有什么推荐", "有什么选择", "不吃鸡肉有什么", "有什么素的", "有什么吃的多少钱",
            "有什么吃的，有过期的吗", "41号和42号机器有什么吃的",
            "Was gibt es Vegetarisches?", "Was gibt es für 5 Euro?", "Was liegt im Fach 3-1?",
            "What can I buy with 5 euros?", "What is in slot 1-7 and 1-8?", "what's expired and what's empty",
            "", "   ", None, 42,
        ]:
            with self.subTest(sentence=sentence):
                self.assertIsNone(match_intent(sentence))


class AnswerFormatTests(unittest.TestCase):
    def answer(self, query, data=LIVE, context="ok", settings=SETTINGS):
        return local_template_answer(query, context, data, settings)

    def first(self, answer):
        return re.split(r"(?<=[。！？])|(?<=[.!?])\s", answer, maxsplit=1)[0]

    def test_available_three_languages_on_live_snapshot(self):
        zh = self.answer("现在有什么吃的")
        de = self.answer("Was gibt es gerade?")
        en = self.answer("What can I buy right now?")
        self.assertEqual(self.first(zh), "现在有两种可买。")
        self.assertEqual(self.first(de), "Es gibt zwei Gerichte.")
        self.assertEqual(self.first(en), "Two items are available.")
        for text in (zh, de, en):
            self.assertIn("素炒面", text)
            self.assertIn("2-5", text)
            self.assertIn("Geschmorte Rindfleischnudeln (ohne Suppe)", text)
            self.assertIn("2-7", text)

    def test_first_sentence_is_short_and_has_no_product_name(self):
        names = {i["name"] for i in LIVE["inventory"]["items"]}
        for query in ["现在有什么吃的", "Was gibt es gerade?", "What can I buy right now?",
                      "有过期的吗", "Was ist abgelaufen?", "Is anything expired?",
                      "有几个空货道", "Wie viele Fächer sind leer?", "Which slots are empty?"]:
            with self.subTest(query=query):
                first = self.first(self.answer(query))
                self.assertLessEqual(len(first.split()) if " " in first else len(first), 10, first)
                for name in names:
                    self.assertNotIn(name, first)

    def test_chinese_numbers_are_characters_not_digits(self):
        for query in ["现在有什么吃的", "有过期的吗", "有几个空货道", "2-5货道是什么"]:
            first = self.first(self.answer(query))
            self.assertIsNone(re.search(r"(?<![\d-])\d+(?:种|个|份)", first), first)
        self.assertEqual(zh_number(2), "两")
        self.assertEqual(zh_number(11), "十一")
        self.assertEqual(zh_number(18), "十八")

    def test_at_most_three_products_then_count_the_rest(self):
        many = inventory([{"slot": f"1-{i}", "name": f"菜{i}", "quantity": 1, "purchasable": True} for i in range(1, 8)])
        zh = self.answer("现在有什么吃的", many)
        self.assertTrue(zh.startswith("现在有七种可买。"))
        self.assertEqual(len(re.findall(r"菜\d", zh)), 3)
        self.assertIn("还有四种。", zh)
        en = self.answer("What can I buy right now?", many)
        self.assertEqual(len(re.findall(r"菜\d", en)), 3)
        self.assertIn("Plus four more.", en)
        de = self.answer("Was gibt es gerade?", many)
        self.assertIn("Dazu vier weitere.", de)

    def test_same_product_in_two_slots_counts_once(self):
        two = inventory([
            {"slot": "1-1", "name": "素炒面", "quantity": 1, "purchasable": True},
            {"slot": "1-2", "name": "素炒面", "quantity": 2, "purchasable": True},
        ])
        self.assertEqual(self.answer("现在有什么吃的", two), "现在有一种可买。素炒面在1-1、1-2货道。")
        self.assertEqual(self.first(self.answer("What can I buy?", two)), "One item is available.")

    def test_nothing_available_and_nothing_expired(self):
        empty = inventory([])
        self.assertEqual(self.answer("现在有什么吃的", empty), "现在没有可买的。")
        self.assertEqual(self.answer("Was gibt es gerade?", empty), "Gerade ist nichts verfügbar.")
        self.assertEqual(self.answer("Is anything expired?", empty), "Nothing is expired.")
        self.assertEqual(self.answer("有过期的吗", empty), "没有过期的商品。")
        self.assertTrue(self.answer("有几个空货道", empty).startswith("有十八个空货道。"))

    def test_expired_and_empty_on_live_snapshot(self):
        self.assertTrue(self.answer("有过期的吗").startswith("有九个货道过期了。1-2的红烧羊肉盖饭"))
        self.assertIn("还有六个。", self.answer("有过期的吗"))
        self.assertEqual(self.answer("有几个空货道"), "有七个空货道。分别是1-1、1-6、1-8、2-1、2-3、2-4、2-8。")
        self.assertEqual(self.answer("Which slots are empty?"), "Seven slots are empty. Slot 1-1, 1-6, 1-8, 2-1, 2-3, 2-4, 2-8.")

    def test_slot_answers(self):
        self.assertEqual(self.answer("2-5货道是什么"), "2-5货道是素炒面，还有两份。")
        self.assertEqual(self.answer("1-7货道是什么"), "1-7货道是黄油鸡咖喱配长粒米，已经过期，不能买。")
        self.assertEqual(self.answer("1-1货道是什么"), "1-1货道是空的。")
        self.assertEqual(self.answer("Was liegt im Fach zwei sechs?"), "In Fach 2-6 liegt 印尼风味鸡肉蔬菜面, aber es ist abgelaufen und nicht kaufbar.")
        self.assertEqual(self.answer("Was liegt im Fach 2-5?"), "In Fach 2-5 liegt 素炒面, zwei Portionen.")
        self.assertEqual(self.answer("What is in slot one seven?"), "Slot 1-7 has 黄油鸡咖喱配长粒米, but it is expired and not for sale.")
        self.assertEqual(self.answer("What is in slot 1-1?"), "Slot 1-1 is empty.")

    def test_unavailable_inventory_is_left_to_the_original_path(self):
        self.assertIsNone(self.answer("现在有什么吃的", context=SETTINGS["unavailable_context"]))
        self.assertIsNone(self.answer("Was gibt es gerade?", data={}))
        self.assertIsNone(self.answer("现在有什么吃的", data={"inventory": {"machine_number": "042", "items": []}}))
        bad = inventory([{"slot": "3-1", "name": "x", "quantity": 1, "purchasable": True}])
        self.assertIsNone(self.answer("现在有什么吃的", bad))
        dup = inventory([{"slot": "1-1", "name": "a", "quantity": 1, "purchasable": True},
                         {"slot": "1-1", "name": "b", "quantity": 1, "purchasable": True}])
        self.assertIsNone(self.answer("现在有什么吃的", dup))

    def test_switch_off_disables_everything(self):
        self.assertIsNone(self.answer("现在有什么吃的", settings={"local_template_answers": False}))
        self.assertIsNone(self.answer("现在有什么吃的", settings={}))
        self.assertIsNone(self.answer("现在有什么吃的", settings=None))


class TimingLabelTests(unittest.TestCase):
    def test_language_detection_for_timing_log(self):
        self.assertEqual(detect_language("现在有什么吃的"), "zh")
        self.assertEqual(detect_language("Was gibt es gerade?"), "de")
        self.assertEqual(detect_language("What can I buy right now?"), "en")
        self.assertEqual(detect_language(None), "en")
        # 规则和 TTS 选音色的 guess_language 是同一份：德语词表里没有的问法会标成 en，只影响日志
        self.assertEqual(detect_language("Wie viele Fächer sind leer?"), "de")


if __name__ == "__main__":
    unittest.main()
