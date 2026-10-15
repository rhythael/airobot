from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CentralKitchenError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


Transport = Callable[[Request, float], HttpResponse]


def default_transport(request: Request, timeout: float) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read())
    except HTTPError as exc:
        return HttpResponse(exc.code, exc.read())
    except (URLError, TimeoutError, OSError) as exc:
        raise CentralKitchenError("network unavailable") from exc


class CentralKitchenClient:
    def __init__(
        self,
        base_url: str,
        app_key: str,
        transport: Transport = default_transport,
        now: Callable[[], float] = time.time,
    ):
        self.base_url = base_url.rstrip("/")
        self._app_key = app_key
        self.transport = transport
        self.now = now

    def _get(self, endpoint: str, business: Mapping[str, str] | None = None):
        params = {"appKey": self._app_key, "timeStamp": str(int(self.now() * 1000))}
        params.update(business or {})
        material = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
        params["sign"] = hashlib.sha256((material + self._app_key).encode()).hexdigest()
        request = Request(f"{self.base_url}{endpoint}?{urlencode(params)}", method="GET")
        response = self.transport(request, 5.0)
        if response.status != 200:
            raise CentralKitchenError(f"HTTP {response.status}")
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CentralKitchenError("invalid JSON") from exc
        if payload.get("code") != 200:
            raise CentralKitchenError("request rejected")
        return payload.get("data")

    def get_store_list(self) -> list[dict]:
        data = self._get("/centralKitchen/api/getStoreList")
        if not isinstance(data, list):
            raise CentralKitchenError("invalid store list")
        return data

    def get_store_shelves(self, store_ids: Sequence[int]) -> dict[str, dict]:
        if not store_ids:
            raise CentralKitchenError("store ids required")
        value = ",".join(str(int(store_id)) for store_id in store_ids)
        data = self._get(
            "/centralKitchen/api/getStoreGoodsShelvesList",
            {"storeIdList": value},
        )
        if not isinstance(data, dict):
            raise CentralKitchenError("invalid shelf list")
        return data
