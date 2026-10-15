# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Emulate a Xiaozhi device against the local server, without touching real hardware.

  device_sim.py text "41号机器现在有什么缺货？"     # skips ASR: tests LLM + TTS
  device_sim.py text "有什么吃的？" "那个牛肉炒面还有吗？"  # same connection, multiple turns
  SMARTFOODIE_SIM_READY_WAIT_SECONDS=6 device_sim.py text "有什么吃的？"  # allow handshake prefetch
  device_sim.py audio path/to/16k-mono.wav          # full path: opus -> ASR -> LLM -> TTS
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
import wave

import opuslib_next
import websockets

# 默认打本机服务端；测试另一个实例时用环境变量覆盖，如 XIAOZHI_WS_URL=ws://127.0.0.1:8010/xiaozhi/v1/
URL = os.environ.get("XIAOZHI_WS_URL", "ws://127.0.0.1:8000/xiaozhi/v1/")
SAMPLE_RATE = 16000
FRAME_MS = 60
QUIET_SECONDS = 20  # stop waiting once the server has been silent this long after TTS started


def opus_frames(path: str) -> list[bytes]:
    with wave.open(path) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
            raise SystemExit("需要 16 kHz、单声道、16 bit 的 wav")
        pcm = wav.readframes(wav.getnframes())
    encoder = opuslib_next.Encoder(SAMPLE_RATE, 1, opuslib_next.APPLICATION_VOIP)
    step = SAMPLE_RATE * FRAME_MS // 1000 * 2
    pcm += b"\0" * (-len(pcm) % step)
    return [encoder.encode(pcm[i : i + step], step // 2) for i in range(0, len(pcm), step)]


async def run(mode: str, payload: str | list[str]) -> None:
    headers = {"device-id": "sim-mac-device", "client-id": str(uuid.uuid4())}
    async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "hello", "version": 1, "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": SAMPLE_RATE, "channels": 1, "frame_duration": FRAME_MS},
        }))
        welcome = json.loads(await asyncio.wait_for(ws.recv(), 10))
        print(f"welcome: session={welcome.get('session_id', '-')} audio={welcome.get('audio_params')}")

        await asyncio.sleep(float(os.environ.get("SMARTFOODIE_SIM_READY_WAIT_SECONDS", "0")))
        turns = payload if isinstance(payload, list) else [payload]
        for turn_number, payload in enumerate(turns, 1):
            print(f"\n轮次 {turn_number}: {payload}")
            started = time.monotonic()
            if mode == "text":
                await ws.send(json.dumps({"type": "listen", "state": "detect", "text": payload}))
            else:
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
                for frame in opus_frames(payload):
                    await ws.send(frame)
                    await asyncio.sleep(FRAME_MS / 1000)
                await ws.send(json.dumps({"type": "listen", "state": "stop"}))
                started = time.monotonic()
    
            frames, first_audio, spoken = 0, None, []
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), QUIET_SECONDS)
                except asyncio.TimeoutError:
                    print(f"(服务端 {QUIET_SECONDS}s 无消息，结束)")
                    break
                elapsed = time.monotonic() - started
                if isinstance(message, bytes):
                    frames += 1
                    first_audio = first_audio if first_audio is not None else elapsed
                    continue
                msg = json.loads(message)
                kind, state, text = msg.get("type"), msg.get("state"), msg.get("text")
                if kind == "stt":
                    print(f"[{elapsed:5.2f}s] 识别: {text}")
                elif kind == "llm" and text:
                    print(f"[{elapsed:5.2f}s] 表情: {text} {msg.get('emotion', '')}")
                elif kind == "tts" and state == "sentence_start":
                    spoken.append(text)
                    print(f"[{elapsed:5.2f}s] 播报: {text}")
                elif kind == "tts" and state == "stop":
                    print(f"[{elapsed:5.2f}s] TTS 结束")
                    break
                elif kind not in ("tts",):
                    print(f"[{elapsed:5.2f}s] {kind}: {json.dumps(msg, ensure_ascii=False)[:160]}")
    
            print(f"结果: 首包音频 {first_audio:.2f}s, 音频帧 {frames} 个（约 {frames * FRAME_MS / 1000:.1f}s）, 句子 {len(spoken)}"
                  if first_audio is not None else f"结果: 没有收到音频, 句子 {len(spoken)}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("text", "audio") or (sys.argv[1] == "audio" and len(sys.argv) != 3):
        raise SystemExit(__doc__)
    asyncio.run(run(sys.argv[1], sys.argv[2:] if sys.argv[1] == "text" else sys.argv[2]))
