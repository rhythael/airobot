# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""2026-10-02 代码审查修掉的几处正确性问题，用例把它们钉住。

每个用例顶上写的是当时的失败场景，不是功能描述——这样以后有人想「简化」回去时知道会碰到什么。
"""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.providers.llm.claudecli import claudecli as cc
from core.utils import product_answer, template_answers, turn_timing
from core.utils.local_answers import route


def _session(events):
    """不起真进程的 _CliSession：事件由测试直接塞进队列。"""
    s = cc._CliSession.__new__(cc._CliSession)
    s.read_timeout = 5
    s.first_token_timeout = 5
    s.last_used = time.time()
    s.system_prompt = ""
    s.forced_language = None
    s.sent_turns = 0
    s._lock = threading.Lock()
    s._events = queue.Queue()
    s._closed = False
    s.stale = False
    # ask() 一进来会清空残留事件，所以事件要像真进程那样：收到 stdin 写入之后才出现
    def _write(_):
        for e in events:
            s._events.put(e)
    s.proc = SimpleNamespace(poll=lambda: None, stdin=SimpleNamespace(write=_write, flush=lambda: None, closed=False))
    return s


class ClaudeCliTests(unittest.TestCase):
    def test_dish_facts_returns_pair_when_menu_settings_missing(self):
        # 不经 start_server 启动时 menu_settings 为空，原来返回 "" 让 `facts, names = …` 直接抛 ValueError
        p = cc.LLMProvider.__new__(cc.LLMProvider)
        p.menu_settings = {}
        facts, names = p._dish_facts("随便什么")
        self.assertEqual((facts, names), ("", []))

    def test_history_skips_fewshot_user_turns(self):
        # few-shot 的「给我讲个故事吧」「拜拜」进入对话后没有 is_temporary 标记，
        # 原来会作为"顾客说过的话"回放给模型
        dialogue = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "给我讲个故事吧"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "fewshot_da_001"}]},
            {"role": "tool", "content": "已直接回复"},
            {"role": "user", "content": "拜拜"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "fewshot_exit_001"}]},
            {"role": "user", "content": "有什么吃的"},
            {"role": "assistant", "content": "现在有两种可买。"},
            {"role": "user", "content": "它有什么配料"},
        ]
        self.assertEqual(
            cc.LLMProvider._history_turns(dialogue),
            [("user", "有什么吃的"), ("assistant", "现在有两种可买。"), ("user", "它有什么配料")],
        )

    def test_interrupted_ask_marks_session_stale_when_tail_never_arrives(self):
        # 顾客打断：生成器提前关闭，进程还在吐上一轮。1 秒内收不到 done 就不能复用这个进程
        s = _session([("text", "现在有"), ("text", "两种")])
        gen = s.ask("hi")
        self.assertEqual(next(gen), "现在有")
        gen.close()
        self.assertTrue(s.stale)
        self.assertFalse(s.is_alive())

    def test_interrupted_ask_recovers_when_done_arrives_quickly(self):
        s = _session([("text", "现在有"), ("done", None)])
        gen = s.ask("hi")
        self.assertEqual(next(gen), "现在有")
        gen.close()
        self.assertFalse(s.stale)
        self.assertTrue(s.is_alive())
        self.assertTrue(s._events.empty())  # 尾巴已收干净，下一轮不会串


class ProductAnswerTests(unittest.TestCase):
    settings = {"local_product_answers": True, "report_unmatched_product": True, "unavailable_context": "X"}
    data = {"inventory": {"machine_number": "041", "items": [
        {"name": "素炒面", "slot": "1-7", "quantity": 3, "purchasable": True},
    ]}}

    def test_slot_and_generic_nouns_are_not_product_names(self):
        # 原来「1-7货道还有吗」答成「现在机器里没看到1-7货道。」——1-7 其实有 3 份素炒面
        for q in ("1-7货道还有吗", "吃的还有吗", "过期的还有吗", "空货道还有吗", "1-7货道里的素炒面还有吗",
                  "Is slot 1-7 still available", "Ist Fach 1-7 noch verfügbar"):
            self.assertIsNone(product_answer.local_product_answer(q, "ctx", self.data, self.settings), q)

    def test_real_product_still_answered(self):
        self.assertIsNotNone(product_answer.local_product_answer("素炒面还有吗", "ctx", self.data, self.settings))


class TemplateNumberTests(unittest.TestCase):
    def test_zh_number_never_raises_on_large_quantities(self):
        # 桥不给 quantity 上限；原来 n≥100 让 _answer_slot 抛 IndexError，而那时 FIRST 已入队、整轮挂死
        self.assertEqual(template_answers.zh_number(99), "九十九")
        self.assertEqual(template_answers.zh_number(100), "100")
        self.assertEqual(template_answers.zh_number(250), "250")
        self.assertEqual(template_answers.zh_number(0), "零")

    def test_number_words_cover_all_eighteen_slots(self):
        self.assertEqual(template_answers._de_number(18), "achtzehn")
        self.assertEqual(template_answers._en_number(13, True), "Thirteen")
        self.assertEqual(template_answers._en_number(19), "19")

    def test_slot_answer_with_huge_quantity_does_not_raise(self):
        data = {"inventory": {"machine_number": "041", "items": [
            {"name": "素炒面", "slot": "1-7", "quantity": 1234, "purchasable": True},
        ]}}
        settings = {"local_template_answers": True, "unavailable_context": "X"}
        answer = template_answers.local_template_answer("1-7货道是什么", "ctx", data, settings)
        self.assertIsNotNone(answer)
        self.assertIn("1234", answer)


class RouteTests(unittest.TestCase):
    def test_route_rejects_non_string_query(self):
        conn = SimpleNamespace(config={"turn_context_refresh": {}},
                               prompt_manager=SimpleNamespace(context_data="", context_provider=SimpleNamespace(structured_data={})))
        self.assertIsNone(route(conn, None, None))


class TurnTimingBargeInTests(unittest.TestCase):
    def test_first_audio_only_counted_for_current_sentence_with_route(self):
        # 抢话：上一轮残帧撞上新零点。发送端只认带 route 且 sentence_id 匹配的那一轮
        conn = SimpleNamespace(session_id="s", logger=SimpleNamespace(bind=lambda **k: SimpleNamespace(info=lambda m: None)))
        turn_timing.start_turn(conn)
        turn_timing.set_field(conn, "sentence_id", "new")
        timing = conn.turn_timing
        # 模拟 sendAudioHandle 的守卫
        def guard(flow_sentence_id):
            return bool(timing and timing.get("sentence_id") in (None, flow_sentence_id) and timing.get("route"))
        self.assertFalse(guard("old"))      # 旧句子的残帧
        self.assertFalse(guard("new"))      # 本轮还没进入回答（route 未设）
        turn_timing.set_field(conn, "route", "local")
        self.assertFalse(guard("old"))
        self.assertTrue(guard("new"))


if __name__ == "__main__":
    unittest.main()
