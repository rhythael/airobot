# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""连接关闭时必须回收 LLM 的常驻子进程。

claudecli provider 每条 WebSocket 连接 Popen 一个 claude 进程。此前 connection.close()
从不回收，只靠 provider 内 600 秒的惰性回收兜底，而那个回收只在 _get_session 里顺带
触发——没有新连接时永远不跑。实测 0 条连接时仍挂着 3 个子进程共 194MB。
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.providers.llm.claudecli.claudecli import LLMProvider


class _FakeProviderWithClose:
    def __init__(self):
        self.closed = []

    def close_session(self, session_id):
        self.closed.append(session_id)


class _FakeProviderWithoutClose:
    """模拟 openai/豆包 这类 provider，没有 close_session。"""


class _FakeSession:
    def __init__(self):
        self.close_calls = 0
        self.last_used = 0.0

    def is_alive(self):
        return True

    def close(self):
        self.close_calls += 1


class LlmSessionCleanupTests(unittest.TestCase):
    def _close_path(self, llm):
        """复刻 connection.close() 里那段回收逻辑，避免构造完整 ConnectionHandler。"""
        errors = []
        obj = SimpleNamespace(llm=llm, session_id="sess-1")
        provider = getattr(obj, "llm", None)
        if provider is not None and hasattr(provider, "close_session"):
            try:
                provider.close_session(obj.session_id)
            except Exception as e:   # pragma: no cover - 守住不抛出
                errors.append(e)
        return errors

    def test_close_releases_llm_session(self):
        llm = _FakeProviderWithClose()
        self.assertEqual(self._close_path(llm), [])
        self.assertEqual(llm.closed, ["sess-1"])

    def test_provider_without_close_session_is_untouched(self):
        """不改变既有正确行为：没有 close_session 的 provider 一行都不该跑到。"""
        self.assertEqual(self._close_path(_FakeProviderWithoutClose()), [])

    def test_close_session_terminates_and_is_idempotent(self):
        provider = LLMProvider({"cli_path": "/nonexistent/claude"})
        session = _FakeSession()
        provider._sessions["sess-1"] = session

        provider.close_session("sess-1")
        self.assertEqual(session.close_calls, 1)
        self.assertNotIn("sess-1", provider._sessions)

        # 幂等：重复回收不应抛异常，也不该重复 close
        provider.close_session("sess-1")
        self.assertEqual(session.close_calls, 1)

    def test_close_session_on_unknown_id_is_safe(self):
        provider = LLMProvider({"cli_path": "/nonexistent/claude"})
        provider.close_session("never-existed")   # 不抛异常即通过


if __name__ == "__main__":
    unittest.main()


class LanguageSwitchTests(unittest.TestCase):
    """顾客用甲语言要求乙语言时必须听话。

    实机上真的发生过：顾客说「说英文」，系统答「我只能用中文回答」——
    既不听话，而且是假话，它三语都会。
    """

    def test_explicit_request_wins_over_utterance_language(self):
        self.assertEqual(LLMProvider._reply_language('说德语'), 'German')
        self.assertEqual(LLMProvider._reply_language('说英文'), 'English')
        self.assertEqual(LLMProvider._reply_language('请用德语回答'), 'German')
        self.assertEqual(LLMProvider._reply_language('speak English please'), 'English')
        self.assertEqual(LLMProvider._reply_language('bitte auf Deutsch'), 'German')

    def test_plain_utterance_still_follows_its_own_language(self):
        self.assertEqual(LLMProvider._reply_language('现在有什么吃的'), 'Chinese')
        self.assertEqual(LLMProvider._reply_language('Was gibt es zu essen'), 'German')
        self.assertEqual(LLMProvider._reply_language('What is available now'), 'English')

    def test_requested_language_detection_is_separable(self):
        self.assertEqual(LLMProvider._requested_language('说德语'), 'German')
        self.assertIsNone(LLMProvider._requested_language('现在有什么吃的'))
        self.assertIsNone(LLMProvider._requested_language('Was gibt es'))


class LanguageSwitchBySoundTests(unittest.TestCase):
    """语音识别把「说德语」听坏时仍要认出来。

    实机原样：说德语 -> 朱德宇 / 苏德宇，之后整轮卡住 25 秒才出兜底话术。
    「说德语」与「说德宇」拼音完全相同，「苏德宇」只差一个音节。
    """

    def test_misheard_switch_commands_still_recognised(self):
        for text in ('说德语', '朱德宇', '苏德宇', '说德宇', '水德语'):
            self.assertEqual(LLMProvider._requested_language(text), 'German', text)
        for text in ('说英文', '说英语'):
            self.assertEqual(LLMProvider._requested_language(text), 'English', text)
        self.assertEqual(LLMProvider._requested_language('说中文'), 'Chinese')

    def test_no_false_positive_on_normal_questions(self):
        for text in ('现在有什么吃的', '鸡肉蔬菜蒸饺', '这个多少钱',
                     '我想知道德语菜单上都有什么好吃的东西', 'Was gibt es'):
            self.assertIsNone(LLMProvider._requested_language(text), text)

    def test_long_utterance_with_language_word_is_not_a_switch(self):
        """长句里提到「德语」多半是在聊别的，不能当成切换指令。"""
        self.assertIsNone(LLMProvider._requested_language(
            '你们的菜单有没有德语版本的说明书可以给我看一下'))
