# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""第二轮 debug（2026-10-05）：招呼语与价格口径。

招呼：德国顾客说「Hallo」，Whisper 识别成「Hello」、判成英语，模型就用英语回答。
单个词的招呼在声学上分不出德英，不去猜：德英两种都说一句。
价格：9-17 按用户菜单资料导入了目录价，中文/德语本地报价，英语「How much」没被认成问价，
落到模型说「看标签」；德英报价还把「2026-09-17」和 snapshot 这类内部用语念给顾客。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.menu_knowledge import DEFAULT_CATALOG, local_menu_answer
from core.utils.template_answers import local_greeting_answer

MENU = {"path": str(DEFAULT_CATALOG), "concise_voice": True}
SHELF_STOCK = {"fried rice with asian sausage", "fried rice with beef in black pepper sauce", "bbq牛肉蒸饺(6大粒)"}


class GreetingTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"local_template_answers": True}

    def test_ambiguous_greeting_answers_in_german_and_english(self):
        for query in ("Hallo", "Hello", "hello!", "Hi", "Hey"):
            answer = local_greeting_answer(query, self.settings)
            self.assertIn("Wie kann ich helfen", answer, query)
            self.assertIn("How can I help", answer, query)

    def test_unambiguous_greetings_stay_in_their_language(self):
        self.assertNotIn("How can I help", local_greeting_answer("Guten Tag", self.settings))
        self.assertNotIn("Wie kann ich", local_greeting_answer("Good morning", self.settings))

    def test_greeting_with_a_question_is_not_a_greeting(self):
        # 「你好」第三轮起也由本地回应（见 test_speech_polish），这里只留带了别的内容的句子
        for query in ("Hallo, was gibt es?", "Hello, what can I buy", "你好，有什么吃的", "Hallo Sesam"):
            self.assertIsNone(local_greeting_answer(query, self.settings), query)
        self.assertIsNone(local_greeting_answer("Hallo", {}))


class PriceTests(unittest.TestCase):
    def test_english_how_much_is_a_price_question(self):
        answer, _ = local_menu_answer("How much is the fried rice with beef?", MENU, stock=SHELF_STOCK)
        self.assertIsNotNone(answer)
        self.assertIn("euros", answer)
        self.assertIn("Beef", answer)
        self.assertNotIn("Sausage", answer)

    def test_spoken_price_has_no_internal_date_or_jargon(self):
        de, _ = local_menu_answer("Was kostet die Dampfnudel mit Vanillesauce?", MENU)
        en, _ = local_menu_answer("How much is the Dampfnudel mit Vanillesauce?", MENU)
        for answer in (de, en):
            self.assertNotRegex(answer, r"20\d\d-\d\d-\d\d")
            self.assertNotIn("snapshot", answer)
        self.assertIn("3,99 Euro", de)
        self.assertIn("Preis am Automaten", de)
        self.assertIn("price on the machine", en)

    def test_stock_question_with_how_much_is_not_price(self):
        answer, _ = local_menu_answer("How much is left of the fried rice?", MENU, stock=SHELF_STOCK)
        self.assertIsNone(answer)

    def test_full_detail_request_keeps_the_long_form(self):
        zh, _ = local_menu_answer("鱼香茄子盖饭的完整价格", MENU)
        self.assertIn("欧元", zh)


if __name__ == "__main__":
    unittest.main()
