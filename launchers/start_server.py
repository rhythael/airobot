# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""启动 SmartFoodie 041 语音服务端，并把 SmartFoodie 的运行时覆盖层叠在上游配置上。

SmartFoodie 041 定制（作者：Heyao Rong，2026-09 至 2026-10）。

凭据只从环境变量 / 仓库根目录的 .env 读，注入内存后交给服务端，data/.config.yaml 里永远不放密钥：
  LLM_API_KEY            selected_module.LLM 所选大模型的 API Key（ClaudeCLI 不需要）

  cp launchers/config.example.yaml server/main/xiaozhi-server/data/.config.yaml   # 首次
  cp .env.example .env && 编辑 .env                                              # 首次
  python launchers/start_server.py                                               # 每次启动

兼容旧的开发机用法：环境变量里没有时，若装了 keyring，再去 macOS 钥匙串找一遍（服务名
smartfoodie-xiaozhi-server）。`--set-key` 仍可把 Key 存进钥匙串，仅 macOS 开发机使用。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

# 单仓库布局：本文件在 <repo>/launchers/，服务端在 <repo>/server/
REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server/main/xiaozhi-server"
EXAMPLE_CONFIG = REPO_ROOT / "launchers/config.example.yaml"
KEYCHAIN_SERVICE = "smartfoodie-xiaozhi-server"
KEYCHAIN_ACCOUNT = "LLM_API_KEY"  # provider-agnostic: whatever selected_module.LLM needs


def load_dotenv(path: Path) -> None:
    """最简 .env 读取：KEY=VALUE 一行一个，# 开头是注释，已有的环境变量不覆盖。不引入第三方包。"""
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


def credential(name: str, keychain_account: str | None = None) -> str:
    """环境变量优先；没有再试 macOS 钥匙串（开发机兼容）。找不到返回空串。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        import keyring  # 可选依赖，公司机器上通常没装
        return (keyring.get_password(KEYCHAIN_SERVICE, keychain_account or name) or "").strip()
    except Exception:
        return ""


def set_key() -> None:
    import getpass
    import keyring
    key = getpass.getpass("大模型 API Key（输入不会显示）: ").strip()
    if not key:
        raise SystemExit("未输入，钥匙串未改动。")
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, key)
    print("已保存到 macOS 钥匙串。")


def ensure_config_file() -> None:
    """data/.config.yaml 被 gitignore；新机器上没有就从示例复制一份，并提醒检查。"""
    target = SERVER_DIR / "data/.config.yaml"
    if target.exists():
        return
    if not EXAMPLE_CONFIG.exists():
        raise SystemExit(f"缺少 {target}，也找不到示例 {EXAMPLE_CONFIG}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(EXAMPLE_CONFIG, target)
    print(f"已从示例生成 {target}，请检查模型目录、端口和 selected_module 后再上线。")


def main() -> None:
    if "--set-key" in sys.argv[1:]:
        set_key()
        return

    load_dotenv(REPO_ROOT / ".env")
    ensure_config_file()
    os.chdir(SERVER_DIR)
    sys.path.insert(0, str(SERVER_DIR))

    from config.config_loader import load_config

    # load_config caches this dict with no expiry; later calls return the same object.
    config = asyncio.run(load_config())
    llm_name = config.get("selected_module", {}).get("LLM", "")
    llm_type = (config.get("LLM", {}).get(llm_name) or {}).get("type")
    key = credential("LLM_API_KEY")
    if not key and llm_type != "claudecli":
        raise SystemExit(
            f"没有大模型 API Key：请在 {REPO_ROOT / '.env'} 或环境变量里设置 LLM_API_KEY"
            f"（当前 selected_module.LLM = {llm_name!r}）。"
        )
    apply_overrides(config, key)

    import app

    try:
        asyncio.run(app.main())
    except KeyboardInterrupt:
        print("手动中断，程序终止。")


def apply_overrides(config: dict, key: str) -> dict:
    """SmartFoodie 的运行时覆盖层。

    这里是被 git 跟踪的唯一真相：data/.config.yaml 被 gitignore，换机器会丢；
    凡是我们有意改动、希望新机器也生效的参数都写在这里，配置文件只放机器相关的东西
    （模型目录、音色、API 地址）。单独成函数是为了能不起服务只校验拼装结果。"""
    def _selected(section):
        """selected_module 指向的那一节配置。写错名字要在启动时大声失败，
        而不是把覆盖值写进一个没人读的临时字典、VAD 悄悄退回上游默认 200 ms。"""
        name = config.get("selected_module", {}).get(section, "")
        block = config.get(section, {}).get(name)
        if not isinstance(block, dict):
            raise SystemExit(f"配置错误：selected_module.{section}={name!r} 在 {section} 下不存在")
        return name, block

    _, llm_config = _selected("LLM")
    llm_config["api_key"] = key

    from core.utils.menu_knowledge import load_catalog, DEFAULT_CATALOG
    load_catalog(str(DEFAULT_CATALOG))  # Load once locally; fail startup on corrupt data.
    config["local_menu_knowledge"] = {"path": str(DEFAULT_CATALOG), "concise_voice": True}

    # ClaudeCLI provider 用它按对话内容补查菜品配料与过敏原，
    # 顾客问一个不在货道上的商品时才有资料可依。
    llm_config["menu_settings"] = config["local_menu_knowledge"]
    llm_config["timeout"] = {"connect": 3, "read": 15, "write": 5, "pool": 2}
    llm_config["max_retries"] = 0
    if llm_config.get("type") == "claudecli":
        # 从 launchd / 非登录 shell 启动时 PATH 里未必有 ~/.local/bin。
        # 与 claudecli.py 自己的回退一致；配置里显式写了就尊重配置。
        llm_config.setdefault(
            "cli_path", shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        )

    # VAD 尾部静音：上游默认 200ms 会打断句中停顿，2026-09 放宽到 900，2026-10-02 收到 600
    # （每句少等 0.3 秒；句中停顿超过 0.6 秒会被当成说完）。实机抢话就改回 900。
    _, vad_config = _selected("VAD")
    vad_config["min_silence_duration_ms"] = 600

    # 每轮直接刷新库存，一次 LLM 往返即可回答；失败时不能沿用历史快照。
    config["system_error_response"] = "暂时无法回答，请看机器屏幕。"
    config["turn_context_refresh"] = {
        "tool_name": "machine_inventory_query",
        "local_count_answers": True,
        "local_product_answers": True,
        "report_unmatched_product": True,
        # 四类常见问题（有什么吃的 / 过期 / 空货道 / 某货道是什么）三语模板直答，不走 LLM
        "local_template_answers": True,
        # 过敏原筛查与「X 里有没有 Y」直接查原文，不交给模型（2026-10-05 沙盒：模型 4/4 答错花生）
        "local_allergen_answers": True,
        # 素食 / 不吃某种肉按配料原文直答（模型把腊肠炒饭说成素食，3/6）
        "local_diet_answers": True,
        # 辣度按菜名 🌶️ 直答（模型把没标辣的猪肉末面、黑椒牛肉炒饭说成辣的）
        "local_spicy_answers": True,
        "unavailable_context": (
            "本轮库存查询失败。库存暂不可用，不得使用历史对话或旧快照报库存。"
            "只告知顾客暂时查不到库存，请看机器屏幕；不得重试或调用其他工具查询库存。"
        ),
    }
    for provider in config.get("context_providers", []):
        provider["refresh_params"] = {"fresh": "1"}
        provider["structured_fields"] = ["inventory"]

    tts_name, tts_config = _selected("TTS")
    if tts_config.get("type") == "edge" or tts_name == "EdgeTTS":
        tts_config["cache_short_audio"] = True
        tts_config["tts_timeout"] = 8
        tts_config["tts_max_attempts"] = 2
        tts_config["tts_max_segment_chars"] = 60
        # 首包优化（2026-10-02）：mp3 边收边转 Opus；回答第一句用本机 sherpa-onnx 合成。
        # 模型路径按 SERVER_DIR 拼绝对路径，服务端不依赖进程 cwd。
        tts_config["edge_stream_decode"] = True
        tts_config["first_sentence_local"] = True
        tts_config["first_sentence_models"] = {
            "zh": str(SERVER_DIR / "models/tts/matcha-icefall-zh-baker"),
            "de": str(SERVER_DIR / "models/tts/vits-piper-de_DE-thorsten-high"),
            "en": str(SERVER_DIR / "models/tts/vits-piper-en_US-lessac-high"),
        }
        tts_config["first_sentence_vocoder"] = str(SERVER_DIR / "models/tts/vocos-22khz-univ.onnx")
    return config


if __name__ == "__main__":
    main()
