# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""机器连服务端要走的每个接口，直接打在正在运行的服务上。

这是集成测试，不在默认回归门里（pyproject 的 testpaths 不含 tests_live）：
    cd main/xiaozhi-server && ~/.venvs/xiaozhi-server/bin/python -m pytest -q tests_live

连接顺序就是设备开机的顺序：
    1. OTA   http://<Mac>:8003/xiaozhi/ota/   拿到 WebSocket 地址
    2. WS    ws://<Mac>:8000/xiaozhi/v1/      hello 握手后开始对话
    3. 库存  http://127.0.0.1:8766/context 与 /mcp（服务端每轮对话用）

地址默认取本机当前局域网 IP，取法与服务端下发给设备的一致；可用 XIAOZHI_HOST 覆盖。
服务没起时相应测试跳过，不算失败。

WebSocket 握手会让服务端预热一次大模型（本机 Claude 账户调用一次 Haiku），
两条握手测试即两次调用。

2026-09-24 起因：Mac 的 IP 从 192.168.0.201 变成了 .202，设备 NVS 里仍记着 .201，
接机失败。test_device_points_at_this_mac 专门抓这种地址漂移。
"""

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests
import websockets

HTTP_PORT, WS_PORT, BRIDGE = 8003, 8000, "http://127.0.0.1:8766"
TIMEOUT = 10


def _lan_ip():
    """与服务端 core.utils.util.get_local_ip 同一取法，下发给设备的就是这个地址。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


HOST = os.environ.get("XIAOZHI_HOST") or _lan_ip()
OTA = f"http://{HOST}:{HTTP_PORT}/xiaozhi/ota/"
WS = f"ws://{HOST}:{WS_PORT}/xiaozhi/v1/"
DEVICE = {"device-id": "sf-api-test", "client-id": "sf-api-test"}
HELLO = {"type": "hello", "version": 1, "transport": "websocket",
         "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}


def _up(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


needs_server = pytest.mark.skipif(not _up(HOST, HTTP_PORT), reason=f"语音服务未在 {HOST}:{HTTP_PORT} 运行")
needs_ws = pytest.mark.skipif(not _up(HOST, WS_PORT), reason=f"WebSocket 未在 {HOST}:{WS_PORT} 运行")
needs_bridge = pytest.mark.skipif(not _up("127.0.0.1", 8766), reason="库存桥接未在 127.0.0.1:8766 运行")


def _post_ota(body="", headers=None):
    h = dict(DEVICE if headers is None else headers)
    h.setdefault("Content-Type", "application/json")
    started = time.monotonic()
    r = requests.post(OTA, data=body.encode() if isinstance(body, str) else body, headers=h, timeout=TIMEOUT)
    return r, time.monotonic() - started


# ---------------------------------------------------------------- 1. OTA


@needs_server
def test_ota_get_hands_out_this_macs_address():
    r = requests.get(OTA, timeout=TIMEOUT)
    assert r.status_code == 200
    assert WS in r.text, f"OTA 下发的地址不是本机当前 IP {HOST}：{r.text}"


@needs_server
def test_ota_post_returns_websocket_config():
    r, elapsed = _post_ota(json.dumps({"application": {"version": "1.9.2"}, "board": {"type": "nulllab-esp32"}}))
    assert r.status_code == 200
    d = r.json()
    assert d["websocket"]["url"] == WS
    assert d["websocket"]["token"] == ""  # 当前未开鉴权
    assert d["firmware"] == {"version": "1.9.2", "url": ""}  # data/bin 里没有更新的固件
    assert d["server_time"]["timezone_offset"] == 120  # 配置 timezone_offset: +2，单位分钟
    assert abs(d["server_time"]["timestamp"] / 1000 - time.time()) < 60
    assert elapsed < 2, f"OTA 响应 {elapsed:.2f}s，设备开机会等它"


@needs_server
def test_ota_version_header_wins_over_body():
    h = dict(DEVICE, **{"device-version": "2.0.0"})
    r, _ = _post_ota(json.dumps({"application": {"version": "1.9.2"}}), h)
    assert r.json()["firmware"]["version"] == "2.0.0"


@needs_server
@pytest.mark.parametrize("body", ["", "not json", "{}", "[]", '"x"', '{"application": "x"}',
                                  json.dumps({"pad": "a" * 200_000})],
                         ids=["empty", "not-json", "empty-object", "array", "string", "application-not-object", "200KB"])
def test_ota_tolerates_odd_bodies(body):
    """设备固件版本各异，请求体不规范也必须照常下发 WebSocket 地址。"""
    r, _ = _post_ota(body)
    assert r.status_code == 200
    d = r.json()
    assert d["websocket"]["url"] == WS
    assert d["firmware"]["version"] == "0.0.0"


@needs_server
@pytest.mark.parametrize("headers", [{}, {"device-id": "x"}, {"client-id": "x"}],
                         ids=["no-ids", "no-client-id", "no-device-id"])
def test_ota_rejects_missing_ids(headers):
    # 上游写法：出错也回 HTTP 200，只在正文里标 success=false
    r, _ = _post_ota("{}", headers)
    assert r.status_code == 200
    assert r.json() == {"success": False, "message": "request error."}


@needs_server
def test_ota_rejects_oversize_body():
    # aiohttp 默认上限 1 MiB；超出时 413 被处理函数吞掉，同样回 200 + success=false
    r, _ = _post_ota("a" * 1_200_000)
    assert r.json().get("success") is False
    assert "websocket" not in r.json()


@needs_server
def test_ota_preflight_allows_device_headers():
    r = requests.options(OTA, timeout=TIMEOUT)
    assert r.status_code == 200
    allowed = r.headers.get("Access-Control-Allow-Headers", "").lower()
    for h in ("device-id", "client-id", "content-type"):
        assert h in allowed


@needs_server
@pytest.mark.parametrize("name", ["..%2F..%2Fdata%2F.config.yaml", "..%2Fconfig.yaml", "%2Fetc%2Fpasswd",
                                  "x.txt", "a b.bin", "....%2F%2F.config.yaml"])
def test_firmware_download_blocks_traversal(name):
    r = requests.get(f"{OTA}download/{name}", timeout=TIMEOUT)
    assert r.status_code in (400, 403, 404), r.status_code
    # data/.config.yaml 里有活凭据，绝不能漏出来
    assert "selected_module" not in r.text and "root:" not in r.text


@needs_server
def test_firmware_download_missing_file():
    assert requests.get(f"{OTA}download/does-not-exist.bin", timeout=TIMEOUT).status_code == 404


@needs_server
def test_vision_endpoint_alive():
    r = requests.get(f"http://{HOST}:{HTTP_PORT}/mcp/vision/explain", timeout=TIMEOUT)
    assert r.status_code == 200 and "运行正常" in r.text


# ---------------------------------------------------------------- 2. WebSocket


async def _hello(uri, headers):
    async with websockets.connect(uri, additional_headers=headers, open_timeout=TIMEOUT) as ws:
        await ws.send(json.dumps(HELLO))
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic())
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "hello":
                    return data
    raise AssertionError("没收到服务端的 hello")


@needs_ws
def test_ws_without_device_id_says_port_ok_and_closes():
    async def run():
        async with websockets.connect(WS, open_timeout=TIMEOUT) as ws:
            first = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
            with pytest.raises(websockets.ConnectionClosed):
                await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
            return first
    assert "端口正常" in asyncio.run(run())


@needs_ws
def test_ws_hello_handshake_with_headers():
    started = time.monotonic()
    data = asyncio.run(_hello(WS, dict(DEVICE, **{"protocol-version": "1"})))
    assert data["transport"] == "websocket"
    assert data.get("session_id")
    assert time.monotonic() - started < 5


@needs_ws
def test_ws_hello_handshake_with_query_params():
    """部分固件把 device-id 放在 URL 参数里而不是请求头。"""
    data = asyncio.run(_hello(f"{WS}?device-id=sf-api-test&client-id=sf-api-test", {}))
    assert data.get("session_id")


# ---------------------------------------------------------------- 3. 库存桥接


@needs_bridge
def test_context_returns_fresh_snapshot():
    started = time.monotonic()
    r = requests.get(f"{BRIDGE}/context?fresh=1", timeout=TIMEOUT)
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    d = r.json()
    assert d["code"] == 0, f"上游不可用：{d}"
    summary = next(v for k, v in d["data"].items() if "041号机器库存快照" in k)
    assert "041号机器" in summary
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", d["data"]["快照抓取时间"])
    assert elapsed < 5, f"库存快照 {elapsed:.2f}s，每轮对话都要等它"


@needs_bridge
def test_context_is_cached_between_turns():
    first = requests.get(f"{BRIDGE}/context?fresh=1", timeout=TIMEOUT).json()
    second = requests.get(f"{BRIDGE}/context", timeout=TIMEOUT).json()
    assert second["data"]["快照抓取时间"] == first["data"]["快照抓取时间"]


def _sse(raw: bytes):
    # SSE 规定一律 UTF-8，但响应头没带 charset，requests 会按 Latin-1 解码成乱码
    out, buf = [], []
    for line in raw.decode("utf-8").split("\n"):  # 不用 splitlines：它会在 U+2028 之类处断开
        line = line.rstrip("\r")
        if line.startswith("data:"):
            buf.append(line[5:].lstrip(" "))
        elif not line and buf:
            out.append(json.loads("\n".join(buf)))
            buf = []
    if buf:
        out.append(json.loads("\n".join(buf)))
    return out


class _Mcp:
    H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

    def __init__(self):
        self.sid = None
        r, _ = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "sf-api-test", "version": "1"}})
        self.sid = r.headers["mcp-session-id"]
        self.rpc("notifications/initialized", notify=True)

    def rpc(self, method, params=None, notify=False, session=True):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = 1
        h = dict(self.H)
        if session and self.sid:
            h["mcp-session-id"] = self.sid
        r = requests.post(f"{BRIDGE}/mcp", headers=h, data=json.dumps(body), timeout=TIMEOUT)
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            return r, _sse(r.content)
        return r, ([r.json()] if r.content.strip() else [])

    def call(self, name, arguments):
        r, msgs = self.rpc("tools/call", {"name": name, "arguments": arguments})
        assert r.status_code == 200
        return msgs[0]["result"]


@pytest.fixture(scope="module")
def mcp():
    if not _up("127.0.0.1", 8766):
        pytest.skip("库存桥接未运行")
    return _Mcp()


def test_mcp_exposes_only_the_readonly_inventory_tool(mcp):
    _, msgs = mcp.rpc("tools/list")
    tools = msgs[0]["result"]["tools"]
    assert [t["name"] for t in tools] == ["machine_inventory_query"]
    assert tools[0]["annotations"]["readOnlyHint"] is True


@pytest.mark.parametrize("machine,query,status", [
    ("041", "empty_slots", "success"),
    ("41", "empty_slots", "success"),          # 「41号」补成 041
    ("042", "products", "denied"),             # 只批准了 041
    ("041", "delete_everything", "denied"),    # 查询类型白名单
    ("", "products", "denied"),
])
def test_mcp_inventory_scope(mcp, machine, query, status):
    result = mcp.call("machine_inventory_query", {"machine_number": machine, "query_type": query})
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == status


def test_mcp_unknown_tool_is_an_error(mcp):
    assert mcp.call("no_such_tool", {})["isError"] is True


def test_mcp_requires_a_session(mcp):
    r, _ = mcp.rpc("tools/list", session=False)
    assert r.status_code == 400


# ---------------------------------------------------------------- 4. 设备配置


def _device_ota_url():
    if os.environ.get("DEVICE_OTA_URL"):
        return os.environ["DEVICE_OTA_URL"], "环境变量 DEVICE_OTA_URL"
    # 设备 NVS 镜像在仓库的 device-backup/ 里（原来写死 ~/xiaozhi/device-backup）
    backups = sorted(Path(__file__).resolve().parents[4].joinpath("device-backup").glob("*.bin"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for p in backups:
        m = re.search(rb"https?://[0-9A-Za-z.\-]+:\d+/xiaozhi/ota/", p.read_bytes())
        if m:
            return m.group().decode(), f"设备 NVS 备份 {p.name}"
    return None, None


def _this_mac_addresses():
    out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
    return set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)) - {"127.0.0.1"}


def test_device_points_at_this_mac():
    """设备里存的 OTA 地址必须落在本机身上，而且能访问。

    Mac 在公司 Wi-Fi 上用私有随机网卡地址，主 IP 会漂（.201 → .202 → .200），所以不再要求
    设备地址等于主 IP：设备固定用 192.168.0.201，由 tools/ota-alias 的常驻服务保证它一直在本机。
    2026-09-24、10-09 两次接机失败都是这个地址不在本机上。"""
    url, source = _device_ota_url()
    if not url:
        pytest.skip("找不到设备的 OTA 地址（设 DEVICE_OTA_URL，或把设备 NVS 镜像放到仓库 device-backup/，该目录不入库）")
    parsed = urlparse(url)
    addresses = _this_mac_addresses()
    assert parsed.hostname in addresses, (
        f"{source} 里设备连的是 {url}，本机地址只有 {sorted(addresses)}。"
        "检查常驻服务：scripts/status.sh；没装就 sudo tools/ota-alias/install.sh")
    assert parsed.port == HTTP_PORT
    assert requests.get(url, timeout=TIMEOUT).status_code == 200
