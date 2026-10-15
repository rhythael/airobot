# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""第三轮 debug（2026-10-05）：播报文本与切段。

1. 菜名里的 🌶️ 去掉后残留 U+FE0F（变体选择符），字幕显示「鱼香茄子盖饭️」。
2. 本地直答整段一次交给 TTS，超过 60 字时按最后一个空格硬切：
   「Fried Rice with Asian | Sausage」「Dazu vier | weitere」，菜名中间停顿；
   中文「现在有七种可买。」也被并进中英混排段，用不上首句本地合成。
3. 中文「你好」仍交给模型，会念完整张货单（17 秒）。
4. 每轮提示补「回答简短」，并用当前货架上的中文菜名举例「照原样说」。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.utils.textUtils import check_emoji, is_punctuation_or_emoji
from core.utils.template_answers import local_greeting_answer
from core.utils.menu_knowledge import DEFAULT_CATALOG, shelf_menu_context
from test_tts_first_packet import _Recorder
from test_turn_rules import payload_for

ZH_LISTING = ("现在有七种可买。BBQ牛肉蒸饺（6大粒）在1-6货道，Fried Rice with Asian Sausage在1-7货道，"
              "Plant-Based Fish-Style Penne在1-8货道。还有四种。")
DE_LISTING = ("Fach 1-6 BBQ牛肉蒸饺（6大粒）, Fach 1-7 Fried Rice with Asian Sausage, "
              "Fach 1-8 Plant-Based Fish-Style Penne. Dazu vier weitere.")


class EmojiTests(unittest.TestCase):
    def test_variation_selector_is_removed_with_the_emoji(self):
        self.assertEqual(check_emoji("🌱鱼香茄子盖饭🌶️。"), "鱼香茄子盖饭。")
        self.assertTrue(is_punctuation_or_emoji("️"))


class ChunkingTests(unittest.TestCase):
    def chunks(self, text):
        provider = _Recorder()
        provider.tts_max_segment_chars = 60
        provider.to_tts_stream(text, opus_handler=lambda f: None, is_first_segment=True)
        return [t for t, _ in provider.seen]

    def test_short_chinese_first_sentence_is_its_own_chunk(self):
        chunks = self.chunks(ZH_LISTING)
        self.assertEqual(chunks[0].rstrip("。"), "现在有七种可买")

    def test_names_are_never_cut_in_the_middle(self):
        for text in (ZH_LISTING, DE_LISTING):
            chunks = self.chunks(text)
            self.assertEqual("".join(chunks).replace(" ", ""), text.replace(" ", ""))
            self.assertTrue(all(len(c) <= 60 for c in chunks))
            joined = " | ".join(chunks)
            self.assertNotIn("Asian |", joined)
            self.assertNotIn("Asian  |", joined)
            self.assertNotIn("vier |", joined)


class LocalAnswerSentenceTests(unittest.TestCase):
    """本地直答按句入队：整段一次交给 TTS 时，60 字以内的回答会整段合成，
    开头的短句跟着后面的中英混排一起慢（「有什么素的」首包 2.4 秒）。"""

    def queued(self, answer):
        import queue
        from types import SimpleNamespace
        from unittest.mock import Mock
        from core.utils.turn_context import speak_local_answer
        conn = SimpleNamespace(tts=SimpleNamespace(tts_text_queue=queue.Queue(), store_tts_text=Mock()), dialogue=Mock())
        speak_local_answer(conn, answer, "turn-1")
        items = []
        while not conn.tts.tts_text_queue.empty():
            items.append(conn.tts.tts_text_queue.get())
        conn.tts.store_tts_text.assert_called_with("turn-1", answer)
        return [m.content_detail for m in items if m.sentence_type.name != "LAST"], items[-1].sentence_type.name

    def test_chinese_and_latin_sentences_are_queued_one_by_one(self):
        texts, last = self.queued("有一款素食为主。1-8货道的Plant-Based Fish-Style Penne。以包装配料为准。")
        self.assertEqual(texts, ["有一款素食为主。", "1-8货道的Plant-Based Fish-Style Penne。", "以包装配料为准。"])
        self.assertEqual(last, "LAST")
        texts, _ = self.queued("One item is vegetarian. Plant-Based Fish-Style Penne in slot 1-8. Please check the package.")
        self.assertEqual(len(texts), 3)
        self.assertEqual("".join(texts), "One item is vegetarian. Plant-Based Fish-Style Penne in slot 1-8. Please check the package.")

    def test_decimal_points_and_slot_numbers_do_not_split(self):
        texts, _ = self.queued("It costs 7.49 euros. Slot 1-7 has it.")
        self.assertEqual(texts, ["It costs 7.49 euros. ", "Slot 1-7 has it."])


class MenuOverviewTests(unittest.TestCase):
    """「What else is on the menu?」模型会把七款货架商品全念一遍。改成按目录主料分组概括。"""

    def answer(self, query):
        from core.utils.template_answers import local_menu_overview_answer
        from test_diet_answer import SHELF
        return local_menu_overview_answer(query, SHELF, {"local_template_answers": True}, {"path": str(DEFAULT_CATALOG)})

    def test_three_languages(self):
        zh = self.answer("菜单上还有什么")
        # 先说一句不带列举的短句，首段不会在顿号中间被切开
        self.assertTrue(zh.startswith("菜单上的菜分好几类。有鸡肉"), zh)
        self.assertIn("七种可买", zh)
        de = self.answer("Was gibt es noch auf der Karte?")
        self.assertIn("Auf der Karte", de)
        self.assertIn("sieben", de)
        en = self.answer("What else is on the menu?")
        self.assertTrue(en.startswith("The menu has several kinds of dishes. "), en)
        self.assertTrue(de.startswith("Auf der Karte gibt es mehrere Sorten. "), de)
        self.assertIn("seven", en)
        for answer in (zh, de, en):
            self.assertNotIn("Fried Rice", answer)   # 不念货架菜名

    def test_other_questions_are_not_menu_overview(self):
        for query in ("现在有什么吃的", "What can I buy right now?", "菜单上有虾饺吗", "Is the menu in English?"):
            self.assertIsNone(self.answer(query), query)


class ChineseGreetingTests(unittest.TestCase):
    def test_chinese_greeting_is_answered_locally_and_briefly(self):
        settings = {"local_template_answers": True}
        for query in ("你好", "您好", "你好呀", "哈喽"):
            answer = local_greeting_answer(query, settings)
            self.assertIsNotNone(answer, query)
            self.assertLess(len(answer), 20)
        self.assertIsNone(local_greeting_answer("你好，有什么吃的", settings))


class TurnRuleExtrasTests(unittest.TestCase):
    def test_brevity_and_live_name_example(self):
        shelf = shelf_menu_context(["BBQ牛肉蒸饺（6大粒）", "Fried Rice with Asian Sausage"], {"path": str(DEFAULT_CATALOG)})
        system = "规则……\n" + shelf
        de = payload_for("Was gibt es noch?", system_prompt=system)
        self.assertIn("höchstens drei Sätze", de)
        self.assertIn("„BBQ牛肉蒸饺（6大粒）“", de)
        en = payload_for("What else do you have?", system_prompt=system)
        self.assertIn("at most three sentences", en)
        self.assertIn('"BBQ牛肉蒸饺（6大粒）"', en)
        zh = payload_for("还有什么", system_prompt=system)
        self.assertIn("最多三句话", zh)
        self.assertIn("Fried Rice with Asian Sausage", zh.split("[提示")[1])

    def test_no_example_without_shelf_data(self):
        self.assertIn("höchstens drei Sätze", payload_for("Was gibt es noch?"))


if __name__ == "__main__":
    unittest.main()
