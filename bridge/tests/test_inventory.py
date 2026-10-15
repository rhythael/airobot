import pytest

from tuya_enterprise_bridge.inventory import InventoryService


SLOTS = {
    f"{column}-{row}": {
        "quantity": 3,
        "capacity": 3,
        "commodityName": "饺子",
        "barCode": f"private-{column}-{row}",
        "isExpired": False,
        "replenishDate": "2026-09-15 08:00:00",
    }
    for column in (1, 2)
    for row in range(1, 10)
}
SLOTS["1-2"].update(quantity=0, commodityName=None, barCode="", replenishDate="2026-09-14 08:00:00")
SLOTS["1-3"].update(quantity=1, commodityName="面", isExpired=True, replenishDate="2026-09-15 07:00:00")


class FakeClient:
    def __init__(self, stores, shelves):
        self.stores = stores
        self.shelves = shelves
        self.calls = []

    def get_store_list(self):
        self.calls.append("stores")
        return self.stores

    def get_store_shelves(self, ids):
        self.calls.append(tuple(ids))
        return self.shelves


def service(stores=None, shelves=None):
    stores = [{"storeId": 81, "storeName": "M-Test-041"}] if stores is None else stores
    shelves = {"81": SLOTS} if shelves is None else shelves
    return InventoryService(FakeClient(stores, shelves), frozenset({"041"}))


def test_inventory_summary_uses_unique_machine_and_safe_fields():
    result = service().query("041", "inventory_status")
    assert result["status"] == "success"
    assert result["scope"] == "machine 041"
    assert "18个货道" in result["display_summary"]
    assert "库存49份/容量54份" in result["display_summary"]
    assert "空货道1个" in result["display_summary"]
    assert "过期商品1个" in result["display_summary"]
    assert "private-" not in str(result)


def test_inventory_summary_names_the_products_in_stock():
    result = service().query("041", "inventory_status")
    assert result["status"] == "success"
    assert "饺子" in result["display_summary"]
    assert "private-" not in str(result)


def test_products_lists_in_stock_and_sold_out_without_emoji():
    shelves = {"81": {**SLOTS}}
    shelves["81"]["1-1"] = {**SLOTS["1-1"], "commodityName": "🌱鱼香茄子盖饭🌶️"}
    result = InventoryService(FakeClient(
        [{"storeId": 81, "storeName": "M-Test-041"}], shelves
    ), frozenset({"041"})).query("041", "products")
    assert result["status"] == "success"
    assert "鱼香茄子盖饭" in result["display_summary"]
    assert "🌱" not in result["display_summary"]
    assert "🌶" not in result["display_summary"]
    assert "在售" in result["display_summary"] and "售空" in result["display_summary"]
    assert "private-" not in str(result)


def test_non_allowlisted_machine_is_denied_before_api_call():
    client = FakeClient([], {})
    result = InventoryService(client, frozenset({"041"})).query("042", "inventory_status")
    assert result["status"] == "denied"
    assert client.calls == []


@pytest.mark.parametrize(
    "stores",
    [
        [{"storeId": 72, "storeName": "M-Test-037"}],
        [
            {"storeId": 81, "storeName": "M-A-041"},
            {"storeId": 82, "storeName": "M-B-041"},
        ],
    ],
)
def test_missing_or_duplicate_machine_fails_safely(stores):
    result = service(stores=stores).query("041", "inventory_status")
    assert result["status"] == "not_found"


@pytest.mark.parametrize("query_type", ["empty-slot", "expiry", "Refill", " inventory_status "])
def test_router_model_spellings_are_normalized(query_type):
    result = service().query("41", query_type)
    assert result["status"] == "success"


@pytest.mark.parametrize("query_type", [None, 123, {"q": "inventory_status"}])
def test_non_string_query_type_is_denied_not_raised(query_type):
    client = FakeClient([], {})
    result = InventoryService(client, frozenset({"041"})).query("041", query_type)
    assert result["status"] == "denied"
    assert client.calls == []


def test_unknown_query_type_is_still_denied_before_api_call():
    client = FakeClient([], {})
    result = InventoryService(client, frozenset({"041"})).query("041", "sales")
    assert result["status"] == "denied"
    assert client.calls == []


def test_invalid_slot_shape_is_not_reported_as_success():
    result = service(shelves={"81": {}}).query("041", "inventory_status")
    assert result["status"] == "invalid_response"


def test_voice_snapshot_separates_purchase_stock_from_expired_stock_and_deduplicates_names():
    result = service().query("041", "inventory_status", voice_snapshot=True)
    text = result["display_summary"]
    purchasable, expired = text.split("仅供过期查询", 1)
    assert "可购买1种商品" in purchasable
    assert "未过期库存48份" in purchasable
    assert "饺子" in purchasable
    assert "1-3 面" not in purchasable
    assert "1-3 面1份（已过期，不可购买）" in expired
    assert "空货道1个（1-2）" in text
    assert "最近补货时间：2026-09-15 08:00:00" in text
    assert "private-" not in text


def test_voice_snapshot_does_not_change_machine_allowlist():
    client = FakeClient([], {})
    result = InventoryService(client, frozenset({"041"})).query(
        "042", "inventory_status", voice_snapshot=True
    )
    assert result["status"] == "denied"
    assert client.calls == []


def test_voice_snapshot_structured_items_keep_expired_separate_and_exclude_private_fields():
    result = service().query("041", "inventory_status", voice_snapshot=True)
    data = result["inventory"]
    assert data["machine_number"] == "041"
    assert len(data["items"]) == 17
    expired = next(item for item in data["items"] if item["slot"] == "1-3")
    assert expired == {"slot": "1-3", "name": "面", "quantity": 1, "purchasable": False}
    assert "barCode" not in str(data)
    assert "private-" not in str(data)
    assert "inventory" not in service().query("041", "inventory_status")
