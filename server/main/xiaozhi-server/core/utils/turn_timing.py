# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""每轮对话的分阶段计时，最后汇成一行日志：

  TURN session=… lang=zh asr=0.04s llm_first=0.90s tts_first=1.21s first_audio=2.57s route=llm

为什么要单独一行：延迟问题排查时要在 ASR、LLM、TTS 四五个模块的日志里对表，
而且各模块各用各的起点。这里统一以「收到最后一帧语音 / 文本」为零点，
每个阶段只记第一次到达，谁先到谁算数。本地直答的轮次没有 llm_first，写成 -。

所有函数都对 conn 上缺字段、重复调用、乱序调用免疫：计时不能把链路弄挂。
"""
import time

_FIELDS = ("asr", "llm_first", "tts_first", "first_audio")


def start_turn(conn, lang=None):
    """零点。ASR 收到完整语音、或文本消息到达时调用；每轮新建字典，旧轮次的字段自然作废。"""
    conn.turn_timing = {"t0": time.monotonic(), "lang": lang, "route": None, "emitted": False}


def mark(conn, field):
    timing = getattr(conn, "turn_timing", None)
    if not timing or field in timing:
        return
    timing[field] = time.monotonic() - timing["t0"]


def set_field(conn, field, value):
    timing = getattr(conn, "turn_timing", None)
    if timing is not None and value is not None:
        timing[field] = value


def format_line(timing, session_id=""):
    parts = [f"TURN session={session_id}", f"lang={timing.get('lang') or '-'}"]
    for field in _FIELDS:
        value = timing.get(field)
        parts.append(f"{field}={value:.2f}s" if isinstance(value, (int, float)) else f"{field}=-")
    parts.append(f"route={timing.get('route') or '-'}")
    return " ".join(parts)


def emit(conn, logger, tag="turn_timing"):
    """首帧音频发出时调用一次。重复调用无效。"""
    timing = getattr(conn, "turn_timing", None)
    if not timing or timing.get("emitted"):
        return None
    timing["emitted"] = True
    line = format_line(timing, getattr(conn, "session_id", "") or "")
    try:
        logger.bind(tag=tag).info(line)
    except Exception:
        pass
    return line
