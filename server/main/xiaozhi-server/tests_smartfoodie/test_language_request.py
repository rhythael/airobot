# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""顾客要求换语言时必须认出来（2026-10-05 沙盒测试）。

漏认的后果不只是没切换：服务端会按这句话本身的语言下发「Antworte auf Deutsch」，
和顾客「Sprich bitte Englisch」的要求冲突，模型有时会把这段纠结连同提示词原文念出来。
验收稿 3 条换语言句子里有 2 条漏认。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.providers.llm.claudecli.claudecli import LLMProvider


class LanguageRequestTests(unittest.TestCase):
    def assertRequested(self, text, expected):
        self.assertEqual(LLMProvider._requested_language(text), expected, text)
        # 回答语言必须跟着请求走，而不是跟着这句话本身的语言
        self.assertEqual(LLMProvider._reply_language(text), expected, text)

    def test_acceptance_script_phrases(self):
        self.assertRequested("说德语", "German")
        self.assertRequested("Sprich bitte Englisch.", "English")
        self.assertRequested("Speak Chinese, please.", "Chinese")

    def test_german_phrasings(self):
        self.assertRequested("Sprich bitte Englisch", "English")
        self.assertRequested("Sprechen Sie Englisch?", "English")
        self.assertRequested("Kannst du Chinesisch sprechen?", "Chinese")
        self.assertRequested("Englisch bitte", "English")
        self.assertRequested("Bitte sprich Deutsch", "German")

    def test_english_phrasings(self):
        self.assertRequested("Speak English please", "English")
        self.assertRequested("Can you speak German?", "German")
        self.assertRequested("Do you speak German?", "German")
        self.assertRequested("English, please", "English")
        self.assertRequested("Could you talk in Chinese?", "Chinese")
        self.assertRequested("Mandarin please", "Chinese")

    def test_chinese_phrasings(self):
        self.assertRequested("讲英语", "English")
        self.assertRequested("请讲德语", "German")
        self.assertRequested("讲中文", "Chinese")
        self.assertRequested("说普通话", "Chinese")

    def test_ordinary_sentences_are_not_requests(self):
        for text in ("Was gibt es gerade?", "Fried Rice with Asian Sausage",
                     "Ist das deutsches Essen?", "Do you have an English menu?",
                     "Ich spreche kein Englisch", "I don't speak German",
                     "现在有什么吃的", "Was ist in den chinesischen Teigtaschen?",
                     "Can we talk about the German dumplings?", "Sprechen wir über chinesisches Essen"):
            self.assertIsNone(LLMProvider._requested_language(text), text)


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


def payload_for(text):
    from core.providers.llm.claudecli import claudecli as cc
    provider = cc.LLMProvider.__new__(cc.LLMProvider)
    provider.menu_settings = {}
    provider.fallback_text = "fallback"
    provider._warned_no_tools = False
    session = _FakeSession()
    provider._get_session = lambda session_id, system_prompt: session
    list(provider.response("s", [{"role": "system", "content": "SYS"}, {"role": "user", "content": text}]))
    return session.payload


class SwitchConfirmationTests(unittest.TestCase):
    """提示词里「问会说哪些语言就列出三种并反问」那条，会让模型把 Sprich bitte Englisch
    当成在问会什么语言（复测 5 次中 3 次反问「Which would you like?」）。
    服务端已经认定是换语言请求，就在本轮明说。"""

    def test_request_is_spelled_out_in_target_language(self):
        payload = payload_for("Sprich bitte Englisch")
        self.assertIn("asked you to speak English", payload)
        self.assertIn("do not ask which language", payload)
        self.assertIn("改用中文", payload_for("Speak Chinese, please."))

    def test_ordinary_turn_has_no_switch_note(self):
        self.assertNotIn("asked you to speak", payload_for("What can I buy right now?"))


if __name__ == "__main__":
    unittest.main()
