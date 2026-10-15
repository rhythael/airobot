import logging
import time
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .central_kitchen import CentralKitchenClient
from .inventory import InventoryService
from .machine_config import MachineSettings


logger = logging.getLogger(__name__)

# 语音助手每轮要跟大模型往返两次：先问"该调工具吗"，拿到结果再生成回答。
# 第一次往返约两秒，全花在一个答案固定的判断上。把库存预先放进它的上下文，
# 这次往返就省掉了。小智服务端在握手期（线程池里，不占用户时间）拉这个端点，
# 渲染进提示词的 dynamic_context 变量。
CONTEXT_CACHE_SECONDS = 30.0

# Tuya's router model only sees the JSON schema, so spell the allowed values
# out in the description too. Plain str keeps an off-list value reaching the
# service, which normalizes aliases or denies, instead of a validation error.
MachineNumber = Annotated[
    str,
    Field(
        description="机器编号，只能是 041（用户说41号、041号都填 041）",
        json_schema_extra={"enum": ["041"]},
    ),
]
QueryType = Annotated[
    str,
    Field(
        description=(
            "查询类型，只能取以下之一："
            "products=问「有什么吃的」「卖什么」「有哪些商品」时用它，返回在售与售罄的完整商品清单；"
            "inventory_status=问「什么情况」「库存怎么样」等整体状况时用它，返回数量概况加在售商品；"
            "empty_slots=只问缺货或空货道；expired_items=只问过期商品；refill_status=只问最近补货。"
            "同时问缺货和过期时用 inventory_status。"
            "返回的商品名必须原样转述，不得翻译或简化。"
        ),
        json_schema_extra={
            "enum": [
                "inventory_status",
                "products",
                "empty_slots",
                "expired_items",
                "refill_status",
            ]
        },
    ),
]


def create_machine_mcp_server(service: InventoryService) -> FastMCP:
    server = FastMCP("Smartfoodie Machine 041 Read-only Data")

    @server.tool(
        name="machine_inventory_query",
        title="Machine 041 Inventory Query",
        description="Read real-time aggregate inventory, empty-slot, expiry, or refill status for machine 041 only.",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    def machine_inventory_query(
        machine_number: MachineNumber = "041",
        query_type: QueryType = "inventory_status",
    ) -> dict[str, str]:
        started = time.monotonic()
        result = service.query(machine_number, query_type)
        logger.info(
            "machine_inventory_query machine=%.40s type=%.40s status=%s seconds=%.2f",
            machine_number, query_type, result.get("status"), time.monotonic() - started,
        )
        return result

    # 握手期预取用：小智的 ContextDataProvider 只发 GET、只认 {code, data} 这个信封，
    # 认不了 MCP 协议，所以单开一条普通 HTTP 路由，与 /mcp 共用同一个端口。
    cache: dict[str, object] = {"at": 0.0, "payload": None}

    @server.custom_route("/context", methods=["GET"])
    async def machine_context(request: Request) -> JSONResponse:
        now = time.monotonic()
        if (
            request.query_params.get("fresh") != "1"
            and cache["payload"] is not None
            and now - cache["at"] < CONTEXT_CACHE_SECONDS
        ):
            return JSONResponse(cache["payload"])

        # 显式刷新先清掉旧缓存；失败后也不能继续把旧库存发给后续连接。
        cache["payload"] = None
        try:
            result = service.query("041", "inventory_status", voice_snapshot=True)
        except Exception:
            # 上游挂了就明确失败：服务端看到非 0 会跳过注入，模型照旧走工具调用。
            # 绝不能返回 code 0 配一段错误文本——那会被当成库存念给客人听。
            logger.exception("machine_context query failed")
            return JSONResponse({"code": 1, "msg": "upstream unavailable"}, status_code=200)

        if result.get("status") != "success":
            logger.warning("machine_context non-success status=%s", result.get("status"))
            return JSONResponse({"code": 1, "msg": str(result.get("status"))}, status_code=200)

        # 带上抓取时刻：这份快照是设备握手那一瞬拉的，对话拖长了就会变旧，
        # 而模型读到库存后就不再调工具，不会自己纠正。让它看见时间，
        # 配合提示词里"涉及准确性或下单要重新核实"的规则，才堵得住这个洞。
        payload = {
            "code": 0,
            "data": {
                # 键名本身就在给模型下指令：它会原样出现在提示词里。去掉这句
                # "直接回答、不必调工具"，模型就会每轮都去调一次工具，预取白做
                # （实测四轮 4 次调用，首包从 3.5 秒退回 8.8 秒）。
                "041号机器库存快照（已是最新，回答库存问题时直接用，不必再调工具）":
                    result.get("display_summary", ""),
                "快照抓取时间": time.strftime("%H:%M:%S"),
            },
        }
        if isinstance(result.get("inventory"), dict):
            payload["data"]["inventory"] = result["inventory"]
        cache["at"] = now
        cache["payload"] = payload
        return JSONResponse(payload)

    return server


def main() -> None:
    settings = MachineSettings.from_env()
    client = CentralKitchenClient(settings.central_kitchen_base_url, settings.sf_app_key)
    service = InventoryService(client, settings.allowed_machine_numbers)
    logging.basicConfig(level=logging.INFO)
    create_machine_mcp_server(service).run(
        transport="http", host="127.0.0.1", port=8766, path="/mcp", show_banner=False
    )
