# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""启动期与降级路径的三道锁。

1. `get_lunar` 不得回到必要函数表：桥挂掉时模型会病急乱投医去调农历工具，
   然后把「查的是农历」念给顾客听（HANDOFF §3.1）。上游曾把它写死为必要函数，
   合并上游时最容易悄悄回来，所以这里直接盯源码常量，不只看行为。
2. 本地桥端口不通时，MCP 初始化必须立刻放弃（<1 秒），不能干等 10 秒超时，
   否则顾客听到近二十秒的静默。这里用真实关闭的端口，不打补丁。
3. 服务启动期的 LLM 预热：走 LLMProviderBase.warmup 接口、不判 provider 类型，
   跑完要回收会话、失败不能让启动炸掉；基类默认实现必须是无副作用的空操作。
"""
import asyncio
import socket
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.providers.tools.server_mcp.mcp_manager import ServerMCPManager
from core.providers.tools.server_plugins import plugin_executor


def _closed_port():
    """拿一个刚释放、此刻没人监听的回环端口。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LunarStaysOutTests(unittest.TestCase):
    def test_necessary_functions_do_not_include_get_lunar(self):
        source = Path(plugin_executor.__file__).read_text(encoding="utf-8")
        line = next(l for l in source.splitlines() if "necessary_functions = [" in l)
        self.assertNotIn("get_lunar", line, "get_lunar 回到了必要函数表，桥挂掉时会把内部错误念给顾客")
        self.assertIn("handle_exit_intent", line)


class McpProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_local_port_returns_fast_without_raising(self):
        manager = ServerMCPManager(SimpleNamespace())
        port = _closed_port()
        started = time.monotonic()
        with patch("core.providers.tools.server_mcp.mcp_manager.ServerMCPClient") as client:
            await manager._init_server("inventory", {"url": f"http://127.0.0.1:{port}/mcp"})
        self.assertLess(time.monotonic() - started, 1.0, "端口不通应在探测超时（0.3s）内放弃，而不是等满 10s")
        client.assert_not_called()
        self.assertEqual(manager.tools, [])


class StartupWarmTests(unittest.IsolatedAsyncioTestCase):
    def _server(self, llm_type, llm):
        from core.websocket_server import WebSocketServer
        server = WebSocketServer.__new__(WebSocketServer)
        server.config = {"selected_module": {"LLM": "X"}, "LLM": {"X": {"type": llm_type}}}
        server.logger = MagicMock()
        server._llm = llm
        return server

    async def test_llm_is_warmed_and_session_closed(self):
        llm = MagicMock()
        server = self._server("claudecli", llm)
        await server._warm_llm_on_startup()
        # 启动期预热不带提示词：垫话由 provider 自己的 warm_text 决定
        llm.warmup.assert_called_once_with("startup-warm")
        llm.close_session.assert_called_once_with("startup-warm")

    async def test_base_provider_default_warmup_is_a_harmless_noop(self):
        from core.providers.llm.base import LLMProviderBase

        class Plain(LLMProviderBase):
            def response(self, session_id, dialogue):
                yield ""

        llm = Plain()
        server = self._server("openai", llm)
        await server._warm_llm_on_startup()  # 既不抛，也不需要 provider 认识 warmup
        self.assertIsNone(llm.warmup("x"))
        self.assertIsNone(llm.close_session("x"))
        server.logger.bind.return_value.warning.assert_not_called()

    async def test_warmup_failure_is_only_a_warning(self):
        llm = MagicMock()
        llm.warmup.side_effect = RuntimeError("claude 进程中断")
        server = self._server("claudecli", llm)
        await server._warm_llm_on_startup()  # 不能抛
        server.logger.bind.return_value.warning.assert_called()
        llm.close_session.assert_called_once_with("startup-warm")


if __name__ == "__main__":
    unittest.main()
