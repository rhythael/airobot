# Tuya China Machine 041 Verification

- Date: 2026-09-15
- Agent region: China
- Router model: Qwen 3.7 Plus (Tuya-hosted)
- MCP service: Smartfoodie 041 只读数据测试
- Tool count: 1
- Tool: machine_inventory_query
- Direct API store-list result: business code 200
- Machine resolution: one unique machine 041 (DEMO-041)
- Direct API shelf count: 18
- Online shelf count: 18
- Direct API empty-slot count: 8
- Online empty-slot count: 8
- Direct API expired-item count: 1
- Online expired-item count: 1
- Online completion time: reply present at the 20 s check; bridge round trip 0.32 s (tools/call received 13:48:03.108, response sent 13:48:03.430), tool 0.16 s
- Machine 042 request: denied before shelf query (no tools/call reached the bridge)
- Sales request: refused as unsupported (no tools/call reached the bridge)
- Chinese TTS: not verified — the online debugger reply shows only a copy control, no playback
- Product/PID/AI Box publication: none
- Credentials recorded in repository: no
- Existing EU configuration modified: no

## Notes

- Direct snapshot taken through the local MCP tool at 13:49:21 (stock 19/54); the Tuya 试运行 at 13:27:46 and the online answer at 13:48 show the same counts.
- Online tool calls were rejected with `-32603` / 权限错误 and never reached the bridge until 在线调试设置 → 获取用户或家庭数据 was authorized with a China data-center account.
- Before `3402e18`, Qwen sent `query_type` values `empty-slot` and `expiry`, which the tool denied; parameter descriptions plus alias normalization fixed it.
- The Q1 answer prefixed one line of the model's own reasoning ("根据规则…应使用 inventory_status 查询类型。") before the tool result.
