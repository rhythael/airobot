# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""每轮一行 TURN 计时日志：字段齐全、只打一次、本地直答没有 llm_first、对缺字段免疫。"""
import asyncio
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils import turn_timing

LINE = re.compile(
    r"^TURN session=(\S*) lang=(zh|de|en|-) asr=(\d+\.\d\ds|-) llm_first=(\d+\.\d\ds|-) "
    r"tts_first=(\d+\.\d\ds|-) first_audio=(\d+\.\d\ds|-) route=(llm|local|-)$"
)


def logger_spy():
    logger = Mock()
    logger.bind.return_value = logger
    return logger


class TurnTimingTests(unittest.TestCase):
    def test_llm_turn_has_every_field(self):
        conn = SimpleNamespace(session_id="s1")
        turn_timing.start_turn(conn)
        turn_timing.set_field(conn, "lang", "zh")
        for field in ("asr", "llm_first", "tts_first", "first_audio"):
            turn_timing.mark(conn, field)
        turn_timing.set_field(conn, "route", "llm")
        logger = logger_spy()
        line = turn_timing.emit(conn, logger)
        self.assertRegex(line, LINE)
        self.assertIn("lang=zh", line)
        self.assertIn("route=llm", line)
        self.assertNotIn("=-", line)
        logger.info.assert_called_once_with(line)

    def test_local_turn_has_no_llm_first(self):
        conn = SimpleNamespace(session_id="s2")
        turn_timing.start_turn(conn, lang="de")
        turn_timing.mark(conn, "asr")
        turn_timing.set_field(conn, "route", "local")
        turn_timing.mark(conn, "tts_first")
        turn_timing.mark(conn, "first_audio")
        line = turn_timing.emit(conn, logger_spy())
        self.assertRegex(line, LINE)
        self.assertIn("llm_first=-", line)
        self.assertIn("route=local", line)
        self.assertIn("lang=de", line)

    def test_first_mark_wins_and_emit_happens_once(self):
        conn = SimpleNamespace(session_id="s3")
        turn_timing.start_turn(conn)
        turn_timing.mark(conn, "asr")
        first = conn.turn_timing["asr"]
        turn_timing.mark(conn, "asr")
        self.assertEqual(conn.turn_timing["asr"], first)
        logger = logger_spy()
        self.assertIsNotNone(turn_timing.emit(conn, logger))
        self.assertIsNone(turn_timing.emit(conn, logger))
        self.assertEqual(logger.info.call_count, 1)

    def test_new_turn_discards_old_fields(self):
        conn = SimpleNamespace(session_id="s4")
        turn_timing.start_turn(conn)
        turn_timing.mark(conn, "llm_first")
        turn_timing.start_turn(conn)
        self.assertNotIn("llm_first", conn.turn_timing)

    def test_connection_without_timing_is_harmless(self):
        conn = SimpleNamespace()
        turn_timing.mark(conn, "asr")
        turn_timing.set_field(conn, "route", "llm")
        self.assertIsNone(turn_timing.emit(conn, logger_spy()))
        self.assertFalse(hasattr(conn, "turn_timing"))

    def test_first_packet_sent_emits_the_line(self):
        from core.handle.sendAudioHandle import _do_send_audio
        conn = SimpleNamespace(session_id="s5", conn_from_mqtt_gateway=False,
                               websocket=SimpleNamespace(send=AsyncMock()), logger=logger_spy())
        turn_timing.start_turn(conn, lang="en")
        turn_timing.mark(conn, "asr")
        turn_timing.set_field(conn, "route", "llm")
        turn_timing.mark(conn, "llm_first")
        turn_timing.mark(conn, "tts_first")
        flow = {"packet_count": 0, "sequence": 0}
        asyncio.run(_do_send_audio(conn, b"\x00", flow))
        asyncio.run(_do_send_audio(conn, b"\x00", flow))
        self.assertEqual(conn.logger.info.call_count, 1)
        self.assertRegex(conn.logger.info.call_args.args[0], LINE)
        self.assertEqual(flow["packet_count"], 2)

    def test_abort_discards_the_turn(self):
        from core.handle.abortHandle import handleAbortMessage
        from core.handle.sendAudioHandle import _do_send_audio
        conn = SimpleNamespace(session_id="s6", conn_from_mqtt_gateway=False,
                               websocket=SimpleNamespace(send=AsyncMock()), logger=logger_spy(),
                               clear_queues=Mock(), clearSpeakStatus=Mock())
        turn_timing.start_turn(conn, lang="zh")
        turn_timing.mark(conn, "asr")
        asyncio.run(handleAbortMessage(conn))
        self.assertIsNone(conn.turn_timing)
        # 打断后设备收到的下一帧（例如提示音）不能用旧零点打出 TURN 行
        asyncio.run(_do_send_audio(conn, b"\x00", {"packet_count": 0, "sequence": 0}))
        self.assertFalse(any(str(c.args[0]).startswith("TURN ") for c in conn.logger.info.call_args_list))

    def test_asr_language_from_provider_lands_in_the_line(self):
        conn = SimpleNamespace(session_id="s7")
        turn_timing.start_turn(conn)
        turn_timing.set_field(conn, "lang", "de")
        turn_timing.mark(conn, "asr")
        turn_timing.mark(conn, "first_audio")
        self.assertIn("lang=de", turn_timing.emit(conn, logger_spy()))


if __name__ == "__main__":
    unittest.main()
