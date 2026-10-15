# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""测试不能写进线上服务的日志（第四轮 debug，2026-10-05）。

沙盒测试时发现：pytest 里故障注入用例的「找不到 claude CLI」「edge down」「model missing」
都写进了正在运行的服务端的 tmp/server.log，排查真机问题时会被误读。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.logger import log_file_name


class LogIsolationTests(unittest.TestCase):
    def test_pytest_runs_log_to_their_own_file(self):
        self.assertEqual(os.environ.get("XIAOZHI_LOG_FILE"), "pytest.log")
        self.assertEqual(log_file_name({"log_file": "server.log"}), "pytest.log")

    def test_service_keeps_configured_file_without_override(self):
        saved = os.environ.pop("XIAOZHI_LOG_FILE")
        try:
            self.assertEqual(log_file_name({"log_file": "server.log"}), "server.log")
            self.assertEqual(log_file_name({}), "server.log")
        finally:
            os.environ["XIAOZHI_LOG_FILE"] = saved


if __name__ == "__main__":
    unittest.main()
