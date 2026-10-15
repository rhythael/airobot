from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .central_kitchen import CentralKitchenClient, CentralKitchenError


MACHINE_SUFFIX = re.compile(r"-(\d{2,3})$")
QUERY_TYPES = {"inventory_status", "empty_slots", "expired_items", "refill_status", "products"}
# 商品名自带装饰性 emoji（🌱🐮🐔🌶️）；语音助手会把它们念出来，先去掉。
EMOJI = re.compile(
    "[\U0001f000-\U0001faff☀-➿⬀-⯿️‍⃣]+"
)


def clean_name(value: object) -> str:
    return EMOJI.sub("", str(value or "")).strip()
# Spellings Tuya's router model has sent or plausibly sends for the same intents.
QUERY_TYPE_ALIASES = {
    "inventory": "inventory_status",
    "stock": "inventory_status",
    "status": "inventory_status",
    "empty": "empty_slots",
    "empty_slot": "empty_slots",
    "shortage": "empty_slots",
    "out_of_stock": "empty_slots",
    "expiry": "expired_items",
    "expired": "expired_items",
    "expired_item": "expired_items",
    "refill": "refill_status",
    "restock": "refill_status",
    "replenish": "refill_status",
}


def normalize_query_type(value: object) -> str:
    # The router model supplies this; a non-string must be denied, not raise.
    if not isinstance(value, str):
        return ""
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return QUERY_TYPE_ALIASES.get(key, key)


class InventoryService:
    def __init__(self, client: CentralKitchenClient, allowed: frozenset[str]):
        self.client = client
        self.allowed = allowed

    def _result(self, status: str, display: str) -> dict[str, str]:
        sentences = [part for part in display.split("。") if part]
        spoken = "。".join(sentences[:3]) + ("。" if sentences else "")
        return {
            "status": status,
            "scope": "machine 041",
            "period": "realtime",
            "spoken_summary": spoken[:360],
            "display_summary": display,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def query(self, machine_number: str, query_type: str, *, voice_snapshot: bool = False) -> dict[str, Any]:
        machine = machine_number.strip().zfill(3)
        query_type = normalize_query_type(query_type)
        if machine not in self.allowed or query_type not in QUERY_TYPES:
            return self._result("denied", "该查询超出已批准的041机器只读库存范围。")
        try:
            stores = self.client.get_store_list()
            matches = []
            for store in stores:
                name = store.get("storeName")
                store_id = store.get("storeId")
                match = MACHINE_SUFFIX.search(name) if isinstance(name, str) else None
                if store_id != 61 and match and match.group(1).zfill(3) == machine:
                    matches.append((int(store_id), name))
            if len(matches) != 1:
                return self._result("not_found", "无法唯一定位041号机器，请检查门店配置。")
            store_id, store_name = matches[0]
            all_shelves = self.client.get_store_shelves([store_id])
            slots = all_shelves.get(str(store_id))
            if not isinstance(slots, dict) or len(slots) != 18:
                return self._result("invalid_response", "041号机器的货道数据格式无效。")
            quantities = [slot.get("quantity") for slot in slots.values()]
            capacities = [slot.get("capacity") for slot in slots.values()]
            if any(not isinstance(value, int) for value in quantities + capacities):
                return self._result("invalid_response", "041号机器的货道数据格式无效。")
            empty = sorted(name for name, slot in slots.items() if slot["quantity"] == 0)
            expired = sorted(
                name
                for name, slot in slots.items()
                if slot.get("isExpired") is True and slot["quantity"] > 0
            )
            replenished = max(
                (str(slot.get("replenishDate") or "") for slot in slots.values()),
                default="",
            )
            in_stock = [
                f"{name} {clean_name(slot.get('commodityName')) or '未命名商品'}"
                f"{slot['quantity']}份"
                + ("（已过期）" if slot.get("isExpired") is True else "")
                for name, slot in sorted(slots.items())
                if slot["quantity"] > 0
            ]
            if voice_snapshot:
                purchasable = [
                    (name, slot) for name, slot in sorted(slots.items())
                    if slot["quantity"] > 0 and slot.get("isExpired") is not True
                ]
                product_names = {
                    clean_name(slot.get("commodityName")) or "未命名商品"
                    for _, slot in purchasable
                }
                available_lines = [
                    f"{name} {clean_name(slot.get('commodityName')) or '未命名商品'}{slot['quantity']}份"
                    for name, slot in purchasable
                ]
                expired_lines = [
                    f"{name} {clean_name(slots[name].get('commodityName')) or '未命名商品'}"
                    f"{slots[name]['quantity']}份（已过期，不可购买）"
                    for name in expired
                ]
                details = (
                    f"041号机器（{store_name}）可购买{len(product_names)}种商品，"
                    f"未过期库存{sum(slot['quantity'] for _, slot in purchasable)}份。"
                    f"可购买清单：{'；'.join(available_lines) or '无'}。"
                    f"仅供过期查询，不可购买的过期库存：{'；'.join(expired_lines) or '无'}。"
                    f"空货道{len(empty)}个（{', '.join(empty) or '无'}）。"
                    f"最近补货时间：{replenished or '未知'}。"
                )
                result = self._result("success", details)
                result["inventory"] = {
                    "machine_number": "041",
                    "items": [
                        {
                            "slot": name,
                            "name": clean_name(slot.get("commodityName")) or "未命名商品",
                            "quantity": slot["quantity"],
                            "purchasable": slot.get("isExpired") is not True,
                        }
                        for name, slot in sorted(slots.items()) if slot["quantity"] > 0
                    ],
                }
                return result

            if query_type == "products":
                # 接口对空货道返回 commodityName=None，所以售罄商品的名字根本查不到；
                # 报数量即可，别让助手多念一句没有内容的"售罄 0 种"。
                details = (
                    f"041号机器（{store_name}）在售{len(in_stock)}种："
                    f"{'；'.join(in_stock) or '无'}。"
                    f"另有{len(empty)}个货道已售空。"
                )
                return self._result("success", details)

            details = (
                f"041号机器（{store_name}）实时库存：{len(slots)}个货道，"
                f"库存{sum(quantities)}份/容量{sum(capacities)}份。"
                f"空货道{len(empty)}个（{', '.join(empty) or '无'}）；"
                f"过期商品{len(expired)}个（{', '.join(expired) or '无'}）。"
                f"现在有货的商品：{'；'.join(in_stock) or '无'}。"
                f"最近补货时间：{replenished or '未知'}。"
            )
            return self._result("success", details)
        except CentralKitchenError:
            return self._result("temporarily_unavailable", "041号机器数据暂时不可用，请稍后再试。")
