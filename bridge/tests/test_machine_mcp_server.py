from fastmcp import FastMCP

from tuya_enterprise_bridge.machine_mcp_server import create_machine_mcp_server, main


class FakeService:
    def __init__(self):
        self.calls = []

    def query(self, machine_number, query_type):
        self.calls.append((machine_number, query_type))
        return {
            "status": "success",
            "scope": "machine 041",
            "period": "realtime",
            "spoken_summary": "没有缺货。",
            "display_summary": "041号机器没有缺货。",
            "generated_at": "2026-09-15T00:00:00+00:00",
        }


async def test_machine_mcp_exposes_one_restricted_read_only_tool():
    service = FakeService()
    server = create_machine_mcp_server(service)
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == ["machine_inventory_query"]
    tool = tools[0]
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    props = tool.parameters["properties"]
    assert props["machine_number"]["enum"] == ["041"]
    assert props["query_type"]["enum"] == [
        "inventory_status", "products", "empty_slots", "expired_items", "refill_status"
    ]
    result = await server.call_tool(
        "machine_inventory_query",
        {"machine_number": "041", "query_type": "empty_slots"},
    )
    assert result.structured_content["status"] == "success"
    assert service.calls == [("041", "empty_slots")]


def test_main_skips_banner_so_startup_makes_no_pypi_request(monkeypatch):
    for name in ("TUYA_MCP_ENDPOINT", "TUYA_MCP_ACCESS_ID", "TUYA_MCP_ACCESS_SECRET", "SF_APP_KEY"):
        monkeypatch.setenv(name, "x")
    captured = {}
    monkeypatch.setattr(FastMCP, "run", lambda self, **kwargs: captured.update(kwargs))
    main()
    assert captured["show_banner"] is False
    assert (captured["host"], captured["port"]) == ("127.0.0.1", 8766)
