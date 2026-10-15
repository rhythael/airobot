# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Inventory deployments must not advertise unrelated default tools."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.providers.tools.server_plugins.plugin_executor import ServerPluginExecutor
from plugins_func.register import all_function_registry, module_func_map


class PluginSelectionTests(unittest.TestCase):
    def setUp(self):
        registry = {
            name: SimpleNamespace(description={"type": "function", "function": {"name": name}})
            for name in ("handle_exit_intent", "get_lunar")
        }
        self.registry_patch = patch.dict(all_function_registry, registry, clear=True)
        self.module_patch = patch.dict(module_func_map, {"calendar": ["get_lunar"]}, clear=True)
        self.registry_patch.start()
        self.module_patch.start()
        self.addCleanup(self.registry_patch.stop)
        self.addCleanup(self.module_patch.stop)

    def tools(self, functions):
        conn = SimpleNamespace(config={
            "selected_module": {"Intent": "function_call"},
            "Intent": {"function_call": {"functions": functions}},
        })
        return ServerPluginExecutor(conn).get_tools()

    def test_inventory_only_keeps_exit(self):
        self.assertEqual(set(self.tools([])), {"handle_exit_intent"})

    def test_calendar_can_be_explicitly_enabled(self):
        self.assertEqual(set(self.tools(["get_lunar"])), {"handle_exit_intent", "get_lunar"})

    def test_calendar_module_can_be_explicitly_enabled(self):
        self.assertIn("get_lunar", self.tools(["calendar"]))


if __name__ == "__main__":
    unittest.main()
