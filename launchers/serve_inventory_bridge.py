# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Run the local read-only voice inventory bridge without Tuya SDK credentials."""
import logging
import os

from tuya_enterprise_bridge.central_kitchen import CentralKitchenClient
from tuya_enterprise_bridge.inventory import InventoryService
from tuya_enterprise_bridge.machine_mcp_server import create_machine_mcp_server


def main():
    key = os.environ.get("SF_APP_KEY", "").strip()
    if not key:
        raise SystemExit("Missing SF_APP_KEY")
    allowed = frozenset(
        number.strip().zfill(3)
        for number in os.environ.get("ALLOWED_MACHINE_NUMBERS", "041").split(",")
        if number.strip()
    )
    if allowed != frozenset({"041"}):
        raise SystemExit("ALLOWED_MACHINE_NUMBERS must be exactly 041")
    base_url = os.environ.get(
        "CENTRAL_KITCHEN_BASE_URL", "https://inventory-api.example.com/prod-api"
    ).rstrip("/")
    client = CentralKitchenClient(base_url, key)
    service = InventoryService(client, allowed)
    logging.basicConfig(level=logging.INFO)
    create_machine_mcp_server(service).run(
        transport="http", host="127.0.0.1", port=8766, path="/mcp", show_banner=False
    )


if __name__ == "__main__":
    main()
