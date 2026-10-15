# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Per-turn refresh replaces stale facts, including when inventory fails."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.turn_context import refresh_turn_context, filter_turn_tools, local_count_answer, speak_local_answer, normalize_query, valid_inventory, UNAVAILABLE_ANSWER
from core.utils.local_answers import route
from core.utils.context_provider import ContextDataProvider
from core.providers.tools.server_mcp.mcp_manager import local_endpoint_available, ServerMCPManager
import asyncio


class TurnContextTests(unittest.TestCase):
    def conn(self):
        manager = SimpleNamespace(
            context_lock=threading.RLock(), context_data="old inventory",
            context_provider=SimpleNamespace(fetch_all=Mock(return_value="fresh inventory")),
        )
        manager.build_enhanced_prompt = lambda *args, **kwargs: manager.context_data
        return SimpleNamespace(
            config={"prompt": "base", "context_providers": [{"url": "http://127.0.0.1/context"}],
                    "turn_context_refresh": {"tool_name": "inventory", "unavailable_context": "unavailable"}},
            prompt_manager=manager, device_id="sim", client_ip="127.0.0.1", features={},
            change_system_prompt=Mock(),
        )

    def test_every_turn_fetches_and_replaces_the_snapshot(self):
        conn = self.conn()
        refresh_turn_context(conn)
        conn.prompt_manager.context_provider.fetch_all.return_value = "sold out"
        refresh_turn_context(conn)
        self.assertEqual(conn.prompt_manager.context_provider.fetch_all.call_count, 2)
        conn.change_system_prompt.assert_called_with("sold out")

    def test_failure_removes_old_inventory_and_recovery_replaces_failure(self):
        conn = self.conn()
        conn.prompt_manager.context_provider.fetch_all.return_value = ""
        self.assertTrue(refresh_turn_context(conn))
        conn.change_system_prompt.assert_called_with("unavailable")
        conn.prompt_manager.context_provider.fetch_all.return_value = "recovered inventory"
        refresh_turn_context(conn)
        conn.change_system_prompt.assert_called_with("recovered inventory")

    def test_unexpected_provider_error_is_safe(self):
        conn = self.conn()
        conn.prompt_manager.context_provider.fetch_all.side_effect = RuntimeError("internal secret")
        self.assertTrue(refresh_turn_context(conn))
        conn.change_system_prompt.assert_called_with("unavailable")

    def test_template_fallback_keeps_the_fresh_context(self):
        conn = self.conn()
        conn.prompt_manager.build_enhanced_prompt = Mock(return_value="base prompt")
        refresh_turn_context(conn)
        self.assertIn("fresh inventory", conn.change_system_prompt.call_args.args[0])

    def test_disabled_refresh_does_not_fetch(self):
        conn = self.conn()
        del conn.config["turn_context_refresh"]
        self.assertFalse(refresh_turn_context(conn))
        conn.prompt_manager.context_provider.fetch_all.assert_not_called()

    def test_refresh_removes_only_the_redundant_inventory_tool(self):
        functions = [{"function": {"name": name}} for name in ("inventory", "handle_exit_intent")]
        filtered = filter_turn_tools(functions, {"tool_name": "inventory"})
        self.assertEqual(filtered, [functions[1]])
        self.assertEqual(len(functions), 2)

    def test_refresh_query_parameters_are_opt_in(self):
        provider = ContextDataProvider({"context_providers": [{
            "url": "http://127.0.0.1/context", "refresh_params": {"fresh": "1"},
        }]})
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0, "data": {"stock": "fresh"}}
        with patch("core.utils.context_provider.httpx.get", return_value=response) as get:
            provider.fetch_all("sim")
            self.assertEqual(get.call_args.kwargs["params"], {})
            provider.fetch_all("sim", refresh=True)
            self.assertEqual(get.call_args.kwargs["params"], {"fresh": "1"})
            self.assertEqual(get.call_args.kwargs["headers"]["device-id"], "sim")


class LocalAnswerTests(unittest.TestCase):
    settings = {"local_count_answers": True, "unavailable_context": "unavailable"}

    def test_three_languages_use_current_purchase_count(self):
        questions = ("41号机器有几种商品？", "How many products does machine 41 have?", "Wie viele Produkte gibt es im Automaten 41?")
        for query in questions:
            self.assertIn("9", local_count_answer(query, "可购买9种商品", self.settings))
            self.assertIn("8", local_count_answer(query, "可购买8种商品", self.settings))

    def test_specific_products_and_multiple_requests_stay_with_llm(self):
        for query in ("鸡肉蔬菜蒸饺还有吗？", "41号机器有几种商品？都列出来", "How many products does machine 41 have and how much do they cost?", "41号机器有几种商品，牛肉炒面多少钱？"):
            self.assertIsNone(local_count_answer(query, "可购买9种商品", self.settings))

    def test_other_machine_is_never_answered_from_041(self):
        for query in ("42号机器有几种商品？", "How many products does machine 42 have?", "Wie viele Produkte gibt es im Automaten 42?"):
            self.assertIsNone(local_count_answer(query, "可购买9种商品", self.settings))

    def test_failed_refresh_never_returns_historical_count(self):
        answer = local_count_answer("41号机器有几种商品？", "unavailable", self.settings)
        self.assertEqual(answer, "暂时查不到库存，请看机器屏幕。")

    def test_old_snapshot_or_disabled_feature_does_not_use_local_path(self):
        self.assertIsNone(local_count_answer("41号机器有几种商品？", "在售12种", self.settings))
        self.assertIsNone(local_count_answer("41号机器有几种商品？", "可购买9种商品", {}))

    def test_zero_purchase_stock_is_a_valid_answer(self):
        self.assertEqual(local_count_answer("41号机器有几种商品？", "可购买0种商品", self.settings), "有0种可购买的商品。")

    def test_direct_answer_is_recorded_and_tts_is_finished(self):
        import queue
        conn = SimpleNamespace(tts=SimpleNamespace(tts_text_queue=queue.Queue(), store_tts_text=Mock()), dialogue=Mock())
        speak_local_answer(conn, "有9种可购买的商品。", "turn-1")
        first, last = conn.tts.tts_text_queue.get(), conn.tts.tts_text_queue.get()
        self.assertEqual(first.content_detail, "有9种可购买的商品。")
        self.assertEqual(first.sentence_id, "turn-1")
        self.assertEqual(last.sentence_type.name, "LAST")
        conn.tts.store_tts_text.assert_called_with("turn-1", "有9种可购买的商品。")
        self.assertEqual(conn.dialogue.put.call_args.args[0].role, "assistant")


class LocalAnswerRouteTests(unittest.TestCase):
    """三个本地回答器只在 route 里排一次序：数量 → 具体商品（用 lookup_query）→ 四类模板。"""
    inventory = {"inventory": {"machine_number": "041", "items": [
        {"slot": "2-5", "name": "素炒面", "quantity": 2, "purchasable": True},
        {"slot": "2-7", "name": "虾饺", "quantity": 1, "purchasable": False},
    ]}}

    def conn(self, context="可购买1种商品", data=None):
        settings = {"local_count_answers": True, "local_product_answers": True, "local_template_answers": True,
                    "report_unmatched_product": True, "unavailable_context": "unavailable"}
        provider = SimpleNamespace(structured_data=self.inventory if data is None else data)
        return SimpleNamespace(config={"turn_context_refresh": settings},
                               prompt_manager=SimpleNamespace(context_data=context, context_provider=provider))

    def test_each_answerer_is_reached_in_order(self):
        conn = self.conn()
        self.assertEqual(route(conn, "41号机器有几种商品？", "41号机器有几种商品？"), "有1种可购买的商品。")
        self.assertTrue(route(conn, "素炒面还有吗？", "素炒面还有吗？").startswith("还有2份"))
        self.assertEqual(route(conn, "现在有什么吃的？", "现在有什么吃的？"), "现在有一种可买。素炒面在2-5货道。")
        self.assertIsNone(route(conn, "有什么推荐？", "有什么推荐？"))

    def test_product_uses_the_resolved_lookup_query_and_templates_use_the_original(self):
        conn = self.conn()
        # 「它还有吗」靠上一轮解析出的菜名才能答；模板问法必须按原话匹配
        self.assertTrue(route(conn, "它还有吗？", "素炒面还有吗？").startswith("还有2份"))
        # 解析结果不是「还有吗」句式时商品回答器让路，模板按顾客原话答
        self.assertEqual(route(conn, "现在有什么吃的？", "素炒面"), "现在有一种可买。素炒面在2-5货道。")
        # 商品回答器排在模板前面（和改造前一样）：lookup 命中就由它答
        self.assertTrue(route(conn, "现在有什么吃的？", "素炒面还有吗？").startswith("还有2份"))

    def test_unavailable_inventory_keeps_each_answerer_s_own_behavior(self):
        conn = self.conn(context="unavailable")
        self.assertEqual(route(conn, "41号机器有几种商品？", "41号机器有几种商品？"), UNAVAILABLE_ANSWER["zh"])
        self.assertEqual(route(conn, "素炒面还有吗？", "素炒面还有吗？"), UNAVAILABLE_ANSWER["zh"])
        self.assertIsNone(route(conn, "现在有什么吃的？", "现在有什么吃的？"))

    def test_shared_helpers(self):
        self.assertEqual(normalize_query("  现在有什么吃的？， "), "现在有什么吃的")
        self.assertEqual(normalize_query("What  can I\tbuy?"), "What can I buy")
        self.assertEqual(normalize_query("鸡肉蔬菜蒸饺（10粒）还有吗？"), "鸡肉蔬菜蒸饺(10粒)还有吗")
        self.assertEqual(len(valid_inventory(self.inventory)), 2)
        self.assertIsNone(valid_inventory({"inventory": {"machine_number": "042", "items": []}}))
        self.assertIsNone(valid_inventory(None))


class LocalProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_local_port_is_unavailable(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        self.assertFalse(await local_endpoint_available({"url": f"http://127.0.0.1:{port}/mcp"}))

    async def test_listening_local_port_is_available(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            self.assertTrue(await local_endpoint_available({"url": f"http://127.0.0.1:{port}/mcp"}))
        finally:
            server.close()
            await server.wait_closed()

    async def test_unavailable_local_endpoint_skips_mcp_initialization(self):
        manager = ServerMCPManager.__new__(ServerMCPManager)
        with patch("core.providers.tools.server_mcp.mcp_manager.local_endpoint_available", new=AsyncMock(return_value=False)), patch("core.providers.tools.server_mcp.mcp_manager.ServerMCPClient") as client:
            await manager._init_server("inventory", {"url": "http://127.0.0.1:8766/mcp"})
            client.assert_not_called()

    async def test_available_endpoint_can_take_longer_than_probe_timeout_to_initialize(self):
        manager = ServerMCPManager.__new__(ServerMCPManager)
        manager._init_lock = asyncio.Lock()
        manager.clients = {}
        manager.tools = []
        client = Mock()
        client.initialize = AsyncMock(side_effect=lambda **kwargs: None)
        client.get_available_tools.return_value = [{"function": {"name": "inventory"}}]
        async def initialize(**kwargs):
            await asyncio.sleep(0.35)
        client.initialize.side_effect = initialize
        with patch("core.providers.tools.server_mcp.mcp_manager.local_endpoint_available", new=AsyncMock(return_value=True)), patch("core.providers.tools.server_mcp.mcp_manager.ServerMCPClient", return_value=client):
            await manager._init_server("inventory", {"url": "http://127.0.0.1:8766/mcp"})
        self.assertIs(manager.clients["inventory"], client)
        self.assertEqual(manager.tools, [{"function": {"name": "inventory"}}])

    async def test_remote_and_stdio_do_not_get_probed(self):
        with patch("asyncio.open_connection") as connect:
            self.assertTrue(await local_endpoint_available({"url": "https://example.com/mcp"}))
            self.assertTrue(await local_endpoint_available({"command": "worker"}))
            connect.assert_not_called()


class InventoryFailureSignalTests(unittest.TestCase):
    """库存失败必须走显式标记，不能靠上下文是否为空来推断。

    完整菜单目录是无条件注入的，所以桥挂掉时 context_data 依然有 3000+ 字符。
    旧实现 `context or unavailable_context` 会把这当成取数成功，
    顾客问库存时拿到的是基于菜单的回答，而不是「暂时查不到库存」。
    """

    def _provider(self, url, with_menu=True):
        from core.utils.context_provider import ContextDataProvider
        from core.utils.menu_knowledge import DEFAULT_CATALOG
        quiet = SimpleNamespace(bind=lambda **k: SimpleNamespace(
            info=lambda *a: None, debug=lambda *a: None,
            warning=lambda *a: None, error=lambda *a: None))
        config = {"context_providers": [{"url": url}]}
        if with_menu:
            config["local_menu_knowledge"] = {"path": str(DEFAULT_CATALOG)}
        return ContextDataProvider(config, quiet)

    def test_unreachable_bridge_marks_inventory_not_ok(self):
        provider = self._provider("http://127.0.0.1:59999/context")
        context = provider.fetch_all("device", refresh=True)
        # 上下文非空（菜单块仍在），正是旧逻辑误判的原因
        self.assertGreater(len(context), 0)
        self.assertFalse(provider.inventory_ok)

    def test_failure_marker_reaches_prompt_even_when_context_nonempty(self):
        from core.utils import turn_context as tc
        provider = self._provider("http://127.0.0.1:59999/context")
        manager = SimpleNamespace(
            context_provider=provider, context_lock=threading.Lock(),
            context_data="", build_enhanced_prompt=lambda *a, **k: "基础提示词")
        conn = SimpleNamespace(
            config={"turn_context_refresh": {"unavailable_context": "库存暂不可用标记"},
                    "context_providers": [{"url": "x"}], "prompt": "p"},
            prompt_manager=manager, device_id="d", client_ip="1.2.3.4", features={},
            change_system_prompt=lambda x: None)
        tc.refresh_turn_context(conn)
        self.assertIn("库存暂不可用标记", manager.context_data)


if __name__ == "__main__":
    unittest.main()
