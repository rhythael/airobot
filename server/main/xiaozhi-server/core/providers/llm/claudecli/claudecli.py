# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Claude Code CLI 作为 LLM provider。

复用本机已登录的 Claude Code 账户，不需要 API Key。

延迟策略（实测，Haiku）：
  每轮新起进程        首字 3.0-5.4 秒   不可用
  常驻进程第一轮      首字 3.0-3.8 秒   仍偏慢
  常驻进程第二轮起    首字 1.8-2.0 秒   可用

所以每个连接一个常驻进程，并在握手期由 warmup() 先喂一句垫话。
用户真正开口时走的已经是"第二轮"，首字约 1.8 秒。垫话发生在
线程池里，不占用户时间，和库存预取是同一个套路。

已知限制：CLI 无头模式不对外暴露 OpenAI 式的 function call 增量，
因此本 provider 不支持工具调用，response_with_functions 退化为纯文本。
当前链路的库存问答走握手期预取和本地直答，不依赖工具调用。
"""

import json
import os
import re
import queue
import shutil
import subprocess
import threading
import time

from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()

# 语言指令、换语言确认、每轮规则等「整形」逻辑在 core/utils/turn_shaping.py，
# 其它 provider 共用；这里只保留常驻进程特有的部分（回放块、系统指令更新）。
from core.utils import turn_shaping as _shaping

_LANGUAGE_DIRECTIVE = _shaping.LANGUAGE_DIRECTIVE
_ASK_LABEL = _shaping.ASK_LABEL
_SWITCH_CONFIRM = _shaping.SWITCH_CONFIRM
_TURN_RULES = _shaping.TURN_RULES
_turn_rules = _shaping.turn_rules

# 语音助手不需要任何开发工具，全部禁用以缩短启动和推理时间
DISALLOWED_TOOLS = [
    "Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Glob", "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite",
]

# 空闲超过这个秒数的会话进程会被回收
IDLE_REAP_SECONDS = 600


class _CliSession:
    """包一个常驻的 claude 进程，串行处理该连接的每一轮。"""

    def __init__(self, cli_path, model, system_prompt, cwd, extra_args, read_timeout,
                 env=None, first_token_timeout=8.0):
        self.read_timeout = read_timeout
        # 首字单独设一个更短的闸。顾客站在机器前，超过几秒没出声就等于坏了；
        # 而整轮超时 25 秒意味着干等 25 秒再听到兜底话术，实机上出现过一次。
        self.first_token_timeout = first_token_timeout
        self.last_used = time.time()
        self.system_prompt = system_prompt or ""
        # 顾客显式要求过的回答语言。一旦要求就粘住，直到再次要求、
        # 或顾客真的改用另一种语言说话为止。否则切成德语后下一轮又回中文。
        self.forced_language = None
        # 已经喂给 claude 进程的对话条数。本地直答的轮次不会经过这里，
        # 进程内部的历史会断层，所以要把漏掉的补上。
        self.sent_turns = 0
        self._lock = threading.Lock()
        self._events = queue.Queue()
        self._closed = False
        # 上一轮被打断（生成器提前关闭）且进程里的尾巴没收干净时置位。
        # 这种进程不能复用：残留的 text/done 事件会串进下一轮，
        # 新一轮会先吐出旧回答的尾巴、再被旧的 done 提前截断。
        self.stale = False

        cmd = [
            cli_path, "-p",
            "--model", model,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--mcp-config", '{"mcpServers":{}}',
            "--strict-mcp-config",
            "--exclude-dynamic-system-prompt-sections",
            # 关掉 skills，否则会加载本机 ~/.claude/skills，
            # 模型会当自己是 Claude Code，开口就说"我需要调用 MCP 工具"。
            "--disable-slash-commands",
            "--no-session-persistence",
            "--disallowed-tools", ",".join(DISALLOWED_TOOLS),
        ]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        cmd += list(extra_args or [])

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(os.path.expanduser("~/.cache/smartfoodie-claude-jail/cli-stderr.log"), "a"),
            text=True,
            bufsize=1,
            cwd=cwd,
            env=env,
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                etype = event.get("type")
                if etype == "stream_event":
                    text = event.get("event", {}).get("delta", {}).get("text", "")
                    if text:
                        self._events.put(("text", text))
                elif etype == "result":
                    self._events.put(("done", None))
        except Exception:
            pass
        finally:
            self._closed = True
            self._events.put(("closed", None))

    def is_alive(self):
        return not self._closed and not self.stale and self.proc.poll() is None

    def ask(self, text):
        """发一轮，流式产出文本片段。同一会话串行。"""
        self._lock.acquire()
        finished = False
        try:
            if not self.is_alive():
                raise RuntimeError("claude 进程已退出")
            self.last_used = time.time()
            # 丢弃上一轮可能残留的事件，避免串轮
            while True:
                try:
                    self._events.get_nowait()
                except queue.Empty:
                    break
            message = {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            }
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

            started = time.time()
            deadline = started + self.read_timeout
            first_deadline = started + self.first_token_timeout
            produced_any = False
            while True:
                limit = deadline if produced_any else min(deadline, first_deadline)
                remaining = limit - time.time()
                if remaining <= 0:
                    if not produced_any:
                        raise TimeoutError(
                            f"claude {self.first_token_timeout:.0f} 秒内没有首字")
                    raise TimeoutError("claude 响应超时")
                try:
                    kind, value = self._events.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue
                if kind == "text":
                    self.last_used = time.time()
                    produced_any = True
                    yield value
                elif kind == "done":
                    finished = True
                    return
                else:
                    finished = True  # 进程已死，无尾巴可收
                    raise RuntimeError("claude 进程中断")
        finally:
            if not finished and not self._closed:
                # 调用方提前关闭了生成器（顾客打断）。给进程 1 秒把这轮说完；
                # 收不到 done 就标记为脏，下一轮由 _get_session 重建，宁可付一次冷启动。
                end = time.time() + 1.0
                while time.time() < end:
                    try:
                        kind, _ = self._events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if kind != "text":
                        finished = True
                        break
                if not finished:
                    self.stale = True
            self._lock.release()

    def close(self):
        self._closed = True
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.cli_path = (
            config.get("cli_path")
            or shutil.which("claude")
            or os.path.expanduser("~/.local/bin/claude")
        )
        self.model_name = config.get("model_name") or "claude-haiku-4-5"
        self.read_timeout = float(config.get("read_timeout") or 25)
        self.first_token_timeout = float(config.get("first_token_timeout") or 8)
        self.warm_text = config.get("warm_text") or "只回复 ok 两个字母，不要其他内容。"
        # 独立的空工作目录：避免 CLAUDE.md、项目设置、skills 污染语音回答。
        # 注意不能用 --bare，它会连 OAuth 登录凭据一起跳过，导致 Not logged in。
        self.cwd = config.get("cwd") or os.path.expanduser("~/.cache/smartfoodie-claude-jail")
        os.makedirs(self.cwd, exist_ok=True)
        self.extra_args = config.get("extra_args") or []
        self.fallback_text = (
            config.get("fallback_text")
            or "抱歉，我暂时无法回答，你看一下机器屏幕。"
        )
        self._sessions = {}
        self._sessions_lock = threading.Lock()
        self._warned_no_tools = False
        self.menu_settings = config.get('menu_settings') or {}

        # 关掉扩展思考。实测同一条 8909 字符的真实提示词：
        # 开思考首字 5.9-9.4 秒，关思考首字 0.8-1.1 秒。
        # 语音问答不需要推理深度，这是本 provider 最大的一处优化。
        # 剥掉父进程可能带的 Claude Code 会话变量。若服务端是从某个
        # Claude Code 会话里启动的，这些变量会让子进程被当成嵌套子会话，
        # 导致行为与从普通终端启动时不一致。
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("CLAUDE_") and k != "CLAUDECODE"
        }
        self.env["MAX_THINKING_TOKENS"] = str(config.get("max_thinking_tokens", 0))

        if not os.path.exists(self.cli_path):
            logger.bind(tag=TAG).error(
                f"找不到 claude CLI: {self.cli_path}，请在配置里指定 cli_path"
            )

    # --- 会话管理 ---

    def _reap_idle(self):
        now = time.time()
        for sid in list(self._sessions.keys()):
            session = self._sessions.get(sid)
            if session is None:
                continue
            if not session.is_alive() or now - session.last_used > IDLE_REAP_SECONDS:
                session.close()
                self._sessions.pop(sid, None)

    def _get_session(self, session_id, system_prompt):
        with self._sessions_lock:
            self._reap_idle()
            session = self._sessions.get(session_id)
            if session is not None and session.is_alive():
                return session
            if session is not None:
                session.close()
            session = _CliSession(
                self.cli_path,
                self.model_name,
                system_prompt,
                self.cwd,
                self.extra_args,
                self.read_timeout,
                self.env,
                self.first_token_timeout,
            )
            self._sessions[session_id] = session
            return session

    def close_session(self, session_id):
        with self._sessions_lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    # --- 握手期预热 ---

    def warmup(self, session_id, system_prompt=""):
        """由 connection 在握手期的线程池里调用，不占用户时间；
        服务启动期也用一次性会话调一次（不带提示词），把 claude 可执行文件的冷启动付掉。"""
        started = time.time()
        try:
            session = self._get_session(session_id, system_prompt)
            for _ in session.ask(self.warm_text):
                pass
            session.sent_turns = 0
            logger.bind(tag=TAG).info(
                f"ClaudeCLI 预热完成 {time.time() - started:.2f}s session={session_id}"
            )
        except Exception as e:
            # 首字超时 / 进程中断后这个进程状态不明（CLI 未登录时会卡着等交互输入），
            # 留着只会让顾客开口时再白等一次超时。直接销毁，下一轮重新拉起。
            logger.bind(tag=TAG).warning(f"ClaudeCLI 预热失败: {e}")
            self.close_session(session_id)

    # --- 推理 ---

    # 本 provider 自己做整形（build_payload），connection 不再对它做一遍
    shapes_turns = True

    def _dish_facts(self, text):
        return _shaping.dish_facts(text, self.menu_settings)

    _has_strong_signal = staticmethod(_shaping.has_strong_signal)
    _requested_language = staticmethod(_shaping.requested_language)
    _requested_language_by_sound = staticmethod(_shaping.requested_language_by_sound)
    _reply_language = staticmethod(_shaping.reply_language)
    _history_turns = staticmethod(_shaping.history_turns)
    _split_dialogue = staticmethod(_shaping.split_dialogue)

    def response(self, session_id, dialogue, **kwargs):
        system_prompt, last_user = self._split_dialogue(dialogue)
        if not last_user:
            yield self.fallback_text
            return
        try:
            session = self._get_session(session_id, system_prompt)
            # 本链路的增强提示词（含库存快照）是每轮进入对话时才构建的，
            # 不是握手期定死的。常驻进程的 --system-prompt 改不了，
            # 所以一旦检测到变化，就把新的系统指令随本轮一起下发，
            # 进程保持不重启，热轮延迟不受影响。
            # 补上进程没见过的历史轮次。本链路很多问题由本地规则直接答掉，
            # 那些轮次不会经过这里，进程内部历史会断层，导致顾客说
            # 「这个成分是什么」时模型不知道在说哪款。
            turns = self._history_turns(dialogue)
            missed = turns[session.sent_turns:-1] if len(turns) > session.sent_turns else []
            session.sent_turns = len(turns)
            shaped = _shaping.build_payload(
                last_user, system_prompt, missed_turns=missed,
                forced_language=session.forced_language, menu_settings=self.menu_settings,
            )
            session.forced_language = shaped["forced_language"]
            payload = shaped["payload"]
            if system_prompt and system_prompt != session.system_prompt:
                session.system_prompt = system_prompt
                payload = (
                    "[系统指令已更新，以下内容覆盖此前的全部设定，"
                    "请严格遵守，不要提及这段话本身]\n"
                    f"{system_prompt}\n\n"
                    f"{payload}"
                )
            logger.bind(tag=TAG).debug(
                f"ClaudeCLI 本轮 payload {len(payload)} 字符"
            )
            _t_ask = time.time()
            produced = False
            for chunk in session.ask(payload):
                if not produced:
                    logger.bind(tag=TAG).info(
                        f"ClaudeCLI 首字 {time.time() - _t_ask:.2f}s"
                    )
                produced = True
                yield chunk
            if not produced:
                yield self.fallback_text
        except Exception as e:
            logger.bind(tag=TAG).error(f"ClaudeCLI 调用失败: {e}")
            # 超时或中断后这个子进程状态不明，销毁掉，下一轮重新拉起干净的。
            self.close_session(session_id)
            yield self.fallback_text

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        if functions and not self._warned_no_tools:
            self._warned_no_tools = True
            logger.bind(tag=TAG).warning(
                "ClaudeCLI provider 不支持工具调用，已退化为纯文本回答"
            )
        for token in self.response(session_id, dialogue, **kwargs):
            yield token, None
