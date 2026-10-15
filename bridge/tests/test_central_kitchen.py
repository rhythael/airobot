import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

from tuya_enterprise_bridge.central_kitchen import (
    CentralKitchenClient,
    CentralKitchenError,
    HttpResponse,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def ok(data):
    return HttpResponse(200, json.dumps({"code": 200, "msg": "操作成功", "data": data}).encode())


def test_store_list_uses_fresh_millisecond_signature():
    transport = FakeTransport([ok([]), ok([])])
    ticks = iter((1789200000.001, 1789200000.002))
    client = CentralKitchenClient("https://api.example/prod-api", "secret", transport, lambda: next(ticks))
    client.get_store_list()
    client.get_store_list()
    first = parse_qs(urlparse(transport.requests[0][0].full_url).query)
    second = parse_qs(urlparse(transport.requests[1][0].full_url).query)
    assert first["timeStamp"] == ["1789200000001"]
    assert second["timeStamp"] == ["1789200000002"]
    unsigned = {"appKey": "secret", "timeStamp": "1789200000001"}
    material = "&".join(f"{key}={value}" for key, value in sorted(unsigned.items())) + "secret"
    assert first["sign"] == [hashlib.sha256(material.encode()).hexdigest()]


def test_shelf_request_is_get_and_encodes_comma_without_spaces():
    transport = FakeTransport([ok({"72": {}})])
    client = CentralKitchenClient("https://api.example/prod-api", "secret", transport, lambda: 1.0)
    client.get_store_shelves([72, 66])
    request, timeout = transport.requests[0]
    assert request.method == "GET"
    assert "storeIdList=72%2C66" in request.full_url
    assert timeout == 5.0


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (HttpResponse(503, b"busy"), "HTTP 503"),
        (HttpResponse(200, b"not-json"), "invalid JSON"),
        (
            HttpResponse(200, '{"code":500,"msg":"验签失败","data":null}'.encode()),
            "request rejected",
        ),
    ],
)
def test_errors_are_normalized_without_upstream_body(response, message):
    client = CentralKitchenClient(
        "https://api.example/prod-api", "secret", FakeTransport([response]), lambda: 1.0
    )
    with pytest.raises(CentralKitchenError, match=message) as caught:
        client.get_store_list()
    assert "验签失败" not in str(caught.value)
