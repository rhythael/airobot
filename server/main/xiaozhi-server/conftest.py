"""pytest 根配置：在任何测试导入项目模块之前生效。

测试进程和线上服务读的是同一份配置，日志原本都写 tmp/server.log；故障注入用例的报错
会混进线上日志（2026-10-05 沙盒测试时被误读过）。这里把测试的日志改写到 tmp/pytest.log。
"""
import os

os.environ.setdefault("XIAOZHI_LOG_FILE", "pytest.log")
