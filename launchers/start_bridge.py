# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""启动 041 库存桥（/context 与 /mcp，监听 127.0.0.1:8766）。

SmartFoodie 041 定制（作者：Heyao Rong，2026-09）。

凭据只从环境变量 / 仓库根目录的 .env 读，传给桥进程的环境，不落盘、不打印：
  SF_APP_KEY                    Central Kitchen App Key（必填）
  ALLOWED_MACHINE_NUMBERS       默认 041
  CENTRAL_KITCHEN_BASE_URL      默认 https://inventory-api.example.com/api
  BRIDGE_PYTHON                 桥用的 Python（可选；不给则依次找 <repo>/bridge/.venv、
                                ~/.venvs/tuya-enterprise-bridge，最后用当前解释器）

  python launchers/start_bridge.py

兼容旧的开发机用法：环境变量里没有 SF_APP_KEY 时，若装了 keyring，再去 macOS 钥匙串找
（服务名 smartfoodie-041-bridge）；`--set-keys` 仍可写入钥匙串，仅 macOS 开发机使用。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_CWD = REPO_ROOT / "bridge"            # 单仓库布局：<repo>/bridge
BRIDGE_SCRIPT = Path(__file__).with_name("serve_inventory_bridge.py")
KEYCHAIN_SERVICE = "smartfoodie-041-bridge"

# (环境变量名, 提示语, 是否机密)
REQUIRED = [
    ("SF_APP_KEY", "Central Kitchen App Key", True),
]
# 有默认值，通常不必单独给
OPTIONAL_DEFAULTS = {
    "ALLOWED_MACHINE_NUMBERS": "041",
    "CENTRAL_KITCHEN_BASE_URL": "https://inventory-api.example.com/api",
}


def load_dotenv(path: Path) -> None:
    """最简 .env 读取：KEY=VALUE 一行一个，# 开头是注释，已有的环境变量不覆盖。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def credential(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        import keyring  # 可选依赖
        return (keyring.get_password(KEYCHAIN_SERVICE, name) or "").strip()
    except Exception:
        return ""


def bridge_python() -> Path:
    candidates = [
        os.environ.get("BRIDGE_PYTHON", ""),
        str(BRIDGE_CWD / ".venv/bin/python"),
        str(Path.home() / ".venvs/tuya-enterprise-bridge/bin/python"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return Path(sys.executable)


def set_keys() -> None:
    import getpass
    import keyring
    print(f"凭据将存入 macOS 钥匙串服务 {KEYCHAIN_SERVICE}，留空表示跳过该项。\n")
    for name, label, secret in REQUIRED:
        prompt = f"{label} ({name}): "
        value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        if not value:
            print(f"  跳过 {name}，保留原值")
            continue
        keyring.set_password(KEYCHAIN_SERVICE, name, value)
        print(f"  已保存 {name}")
    print("\n完成。")


def main() -> None:
    if "--set-keys" in sys.argv[1:]:
        set_keys()
        return

    load_dotenv(REPO_ROOT / ".env")
    env = os.environ.copy()
    for name, value in OPTIONAL_DEFAULTS.items():
        env.setdefault(name, value)

    missing = []
    for name, label, _ in REQUIRED:
        value = credential(name)
        if not value:
            missing.append(f"{name}（{label}）")
            continue
        env[name] = value
    if missing:
        raise SystemExit("缺少以下凭据，请写进 .env 或环境变量：\n  " + "\n  ".join(missing))
    if not BRIDGE_CWD.is_dir():
        raise SystemExit(f"找不到桥的目录：{BRIDGE_CWD}（单仓库布局应为 <repo>/bridge）")

    python = bridge_python()
    print(f"启动 041 桥（Python: {python}；凭据来自环境，不落盘）…")
    # exec 语义：让桥顶替当前进程，Ctrl-C 和信号直达它，也不会多出一层看不出状态的父进程。
    os.chdir(BRIDGE_CWD)
    os.execve(str(python), [str(python), str(BRIDGE_SCRIPT)], env)


if __name__ == "__main__":
    main()
