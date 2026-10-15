# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
import ast
import queue
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
from core.utils.menu_knowledge import local_menu_turn, DEFAULT_CATALOG

class ChainRecoveryTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).parents[1] / 'core/connection.py').read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'chat')
        ns = dict(uuid=uuid, Message=Message, TTSMessageDTO=TTSMessageDTO,
                  SentenceType=SentenceType, ContentType=ContentType, TAG='test',
                  get_system_error_response=lambda config: '暂时无法回答，请看机器屏幕。')
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<chat>', 'exec'), ns)
        self.chat = ns['chat']
        self.conn = SimpleNamespace(config={}, logger=Mock(), dialogue=Mock(),
            tts=SimpleNamespace(tts_text_queue=queue.Queue(), store_tts_text=Mock()),
            client_abort=False, intent_type='nointent', memory=None,
            current_speaker=None, system_introduced_speakers=set(), session_id='test', llm=Mock())
    def run_chat(self):
        with patch('core.utils.turn_context.refresh_turn_context', return_value=False):
            return self.chat(self.conn, '你好')
    def states(self):
        q=self.conn.tts.tts_text_queue
        return [q.get().sentence_type for _ in range(q.qsize())]
    def test_request_setup_failure_finishes_turn(self):
        self.conn.llm.response.side_effect=RuntimeError('unavailable')
        self.run_chat()
        self.assertEqual(self.states(), [SentenceType.FIRST, SentenceType.MIDDLE, SentenceType.LAST])
        self.assertEqual(self.conn.dialogue.put.call_args.args[0].role, 'assistant')
    def test_empty_stream_finishes_with_spoken_failure(self):
        self.conn.llm.response.return_value=iter(())
        self.run_chat()
        self.assertEqual(self.states(), [SentenceType.FIRST, SentenceType.MIDDLE, SentenceType.LAST])
    def test_old_stream_cannot_resume_when_abort_flag_cleared(self):
        def stream():
            self.conn.sentence_id='new-turn'
            self.conn.client_abort=False
            yield '过期的回答'
        self.conn.llm.response.return_value=stream()
        self.run_chat()
        self.assertEqual(self.states(), [SentenceType.FIRST])
        self.conn.tts.store_tts_text.assert_not_called()
        self.assertEqual(self.conn.dialogue.put.call_count, 1)
    def test_stream_exception_finishes_turn(self):
        def stream():
            raise RuntimeError('stream failed')
            yield ''
        self.conn.llm.response.return_value=stream()
        self.run_chat()
        self.assertEqual(self.states(), [SentenceType.FIRST, SentenceType.MIDDLE, SentenceType.LAST])
    def test_abort_during_inventory_refresh_does_not_start_old_audio(self):
        def refresh(conn):
            conn.sentence_id = 'replacement'
            return False
        with patch('core.utils.turn_context.refresh_turn_context', side_effect=refresh):
            self.chat(self.conn, '你好')
        self.assertEqual(self.states(), [])
        self.conn.llm.response.assert_not_called()

    def test_stock_question_binds_allergen_followup(self):
        conn=SimpleNamespace()
        settings={'path': str(DEFAULT_CATALOG)}
        self.assertIsNone(local_menu_turn(conn, '牛肉炒面还有吗？', settings))
        self.assertEqual(conn.last_local_menu_id, '537')
        self.assertIn('含有小麦、鸡蛋、大豆', local_menu_turn(conn, '过敏原呢？', settings))
        self.assertIsNone(local_menu_turn(conn, '咖啡还有吗？', settings))
        self.assertIsNone(conn.last_local_menu_id)
        # 换了个目录里没有的商品之后，绝不能把上一款的过敏原套过去。
        # 本地认不出对象时返回 None，交给模型用完整对话历史回答，
        # 而不是反问顾客「你说的是哪一款」。
        followup = local_menu_turn(conn, '过敏原呢？', settings)
        self.assertIsNone(followup)

if __name__ == '__main__':
    unittest.main()
