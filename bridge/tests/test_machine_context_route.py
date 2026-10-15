"""握手期预取端点 /context 的行为：信封、缓存、以及上游异常时不能谎报成功。

不联网、不起进程：用假的 InventoryService 驱动 ASGI 应用。
"""

import json

import pytest

from tuya_enterprise_bridge.machine_mcp_server import create_machine_mcp_server


class FakeService:
    """只实现 query，记录被调用次数，用来验证缓存是否生效。"""

    def __init__(self, result=None, raises=False):
        self.result = result if result is not None else {
            "status": "success",
            "display_summary": "041号机器在售18种：1-1 牛肉炒面3份；1-4 Creamy Mac & Cheese1份。",
        }
        self.raises = raises
        self.calls = 0

    def query(self, machine_number, query_type, *, voice_snapshot=False):
        self.calls += 1
        if self.raises:
            raise RuntimeError("upstream down")
        return self.result


def get_context(app, client_cls):
    client = client_cls(app)
    return client.get("/context")


@pytest.fixture
def client_cls():
    starlette_testclient = pytest.importorskip("starlette.testclient")
    return starlette_testclient.TestClient


def build(service):
    server = create_machine_mcp_server(service)
    return server.http_app(path="/mcp")


def test_success_uses_the_envelope_the_voice_server_understands(client_cls):
    service = FakeService()
    resp = get_context(build(service), client_cls)
    assert resp.status_code == 200
    body = resp.json()
    # ContextDataProvider 只认 code==0 且 data 是 dict，别的形状会被静默丢弃
    assert body["code"] == 0
    assert isinstance(body["data"], dict)
    joined = " ".join(f"{k} {v}" for k, v in body["data"].items())
    assert "041" in joined
    assert "牛肉炒面" in joined


def test_snapshot_carries_the_time_it_was_taken(client_cls):
    """时间戳不是装饰：模型读到库存后就不再调工具，只有看见快照时间，
    提示词里"对话拖久了要重新核实"那条规则才有依据。少了它规则就是空话。"""
    body = get_context(build(FakeService()), client_cls).json()
    stamp = next((v for k, v in body["data"].items() if "时间" in k), None)
    assert stamp is not None, f"快照缺少抓取时间: {body['data'].keys()}"
    assert stamp.count(":") == 2  # HH:MM:SS


def test_second_call_within_window_is_served_from_cache(client_cls):
    service = FakeService()
    app = build(service)
    get_context(app, client_cls)
    get_context(app, client_cls)
    # 每台设备握手都会打这个端点，不缓存就是每次都捅上游一次
    assert service.calls == 1


def test_upstream_exception_never_reports_success(client_cls):
    service = FakeService(raises=True)
    body = get_context(build(service), client_cls).json()
    # 返回 code 0 配一段错误文本的话，那段文本会被当成库存念给客人
    assert body["code"] != 0
    assert "data" not in body


def test_non_success_status_never_reports_success(client_cls):
    service = FakeService(result={"status": "denied"})
    body = get_context(build(service), client_cls).json()
    assert body["code"] != 0
    assert "data" not in body


def test_failure_is_not_cached(client_cls):
    """失败不该被缓存住，否则上游恢复后还要干等一个缓存周期。"""
    service = FakeService(raises=True)
    app = build(service)
    get_context(app, client_cls)
    get_context(app, client_cls)
    assert service.calls == 2


def test_explicit_refresh_bypasses_cache_and_updates_snapshot(client_cls):
    service = FakeService()
    client = client_cls(build(service))
    client.get("/context")
    service.result = {"status": "success", "display_summary": "牛肉炒面已售罄"}
    refreshed = client.get("/context?fresh=1").json()
    assert service.calls == 2
    assert "已售罄" in json.dumps(refreshed, ensure_ascii=False)
    assert client.get("/context").json() == refreshed
    assert service.calls == 2


def test_failed_explicit_refresh_invalidates_old_cache(client_cls):
    service = FakeService()
    client = client_cls(build(service))
    assert client.get("/context").json()["code"] == 0
    service.raises = True
    assert client.get("/context?fresh=1").json()["code"] != 0
    assert client.get("/context").json()["code"] != 0
    assert service.calls == 3


def test_structured_inventory_is_forwarded_without_changing_rows(client_cls):
    inventory = {"machine_number": "041", "items": [
        {"slot": "2-7", "name": "鸡肉蔬菜蒸饺(10粒）", "quantity": 1, "purchasable": True},
        {"slot": "1-6", "name": "鸡肉蔬菜蒸饺(10粒）", "quantity": 2, "purchasable": False},
    ]}
    service = FakeService(result={"status": "success", "display_summary": "可购买1种商品", "inventory": inventory})
    body = get_context(build(service), client_cls).json()
    assert body["code"] == 0
    assert body["data"]["inventory"] == inventory
