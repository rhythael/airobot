# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Audio transport failure must release completion waiters and allow reset."""
import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.audioRateController import AudioRateController


class AudioRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_send_releases_waiters_and_discards_remaining_packets(self):
        controller = AudioRateController(1)
        async def failed(packet):
            raise OSError("disconnected")
        controller.add_audio(b"first")
        controller.add_audio(b"second")
        await controller.start_sending(failed)
        self.assertTrue(controller.queue_empty_event.is_set())
        self.assertFalse(controller.queue)

    async def test_stop_before_sender_starts_releases_waiters(self):
        controller = AudioRateController(1)
        controller.add_audio(b"queued")
        task = controller.start_sending(AsyncMock())
        controller.stop_sending()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(controller.queue_empty_event.is_set())
        self.assertFalse(controller.queue)

    async def test_cancelled_send_releases_waiters(self):
        controller = AudioRateController(1)
        started = asyncio.Event()
        async def blocked(packet):
            started.set()
            await asyncio.Event().wait()
        controller.add_audio(b"first")
        task = controller.start_sending(blocked)
        await started.wait()
        controller.stop_sending()
        await task
        self.assertTrue(controller.queue_empty_event.is_set())

    async def test_reset_can_start_a_new_generation_without_old_task_clearing_it(self):
        controller = AudioRateController(1)
        entered = asyncio.Event()
        async def blocked(packet):
            entered.set()
            await asyncio.Event().wait()
        controller.add_audio(b"old")
        old = controller.start_sending(blocked)
        await entered.wait()
        controller.reset()
        received = []
        async def send(packet):
            received.append(packet)
        controller.add_audio(b"new")
        new = controller.start_sending(send)
        await old
        await asyncio.wait_for(controller.queue_empty_event.wait(), .2)
        self.assertEqual(received, [b"new"])
        controller.stop_sending()
        await new

    async def test_failed_message_also_releases_waiters(self):
        controller = AudioRateController(1)
        async def failed():
            raise OSError("message failed")
        controller.add_message(failed)
        await controller.start_sending(AsyncMock())
        self.assertTrue(controller.queue_empty_event.is_set())
        self.assertFalse(controller.queue)

    async def test_stop_message_completes_after_audio_sender_failure(self):
        from core.handle.sendAudioHandle import send_tts_message
        controller = AudioRateController(1)
        async def failed(packet):
            raise OSError("temporary transport failure")
        controller.add_audio(b"first")
        await controller.start_sending(failed)
        conn = SimpleNamespace(audio_rate_controller=controller, config={},
            logger=Mock(), sentence_id="current", session_id="session",
            clearSpeakStatus=Mock(), websocket=SimpleNamespace(send=AsyncMock()))
        await asyncio.wait_for(send_tts_message(conn, "stop"), .2)
        conn.clearSpeakStatus.assert_called_once()
        conn.websocket.send.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
