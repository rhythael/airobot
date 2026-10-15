# Smartfoodie 041 语音链路 — 交接说明

交接时间：2026-09-17 13:20 CEST
交接人：Claude（本轮工作）→ Codex（接手）

这份文档描述**本轮做了什么、当前处于什么状态、还剩什么**。每条结论都经过实测或代码核对；
凡是没验证的，文中明确标注"未验证"。

---

## 1. 这条链路是什么

ESP32 设备（`aa:bb:cc:dd:ee:ff`，固件 2.2.2）通过自建服务端做语音问答，查询 041 号售货机
的实时库存。**完全独立于涂鸦开发者平台和小智官方云**。

```
ESP32 ──ws──> xiaozhi-server (:8000)
                  │  ASR: sherpa-onnx (SenseVoice 优先，德语回退 Whisper)
                  │  LLM: 火山方舟 豆包 lite
                  │  TTS: EdgeTTS
                  │
                  ├──http──> 041 桥 (:8766) /context   ← 握手期预取库存
                  └──mcp───> 041 桥 (:8766) /mcp       ← 工具调用（现在很少走）
                                  │
                                  └──> Central Kitchen API
                                       inventory-api.example.com/prod-api
```

### 两个仓库

| 仓库 | 路径 | 本轮改动 |
|---|---|---|
| 小智服务端 | `~/airobot/server`（原 `~/xiaozhi/xiaozhi-esp32-server`） | 提示词、TTS 切句、标点清理、预取消费端 |
| 041 桥 | `~/airobot/bridge`（原 `~/Documents/.vibe-worktrees/…/Codex/2026-09-11/xia`） | 新增 `/context` 端点 |

### 启停

```bash
# 服务端（LLM Key 从钥匙串 smartfoodie-xiaozhi-server 读）
~/.venvs/xiaozhi-server/bin/python ~/airobot/launchers/start_server.py

# 041 桥（5 个凭据从钥匙串 smartfoodie-041-bridge 读）
~/.venvs/xiaozhi-server/bin/python ~/airobot/launchers/start_bridge.py

# 仿真器（跳过 ASR，直接测 LLM+TTS）
cd ~/airobot/launchers && ~/.venvs/xiaozhi-server/bin/python device_sim.py text "41号机器现在有什么吃的？"
```

**两者都不是开机自启**，Mac 重启后要手动拉起。

---

## 2. 本轮的主要成果：首包延迟 7-9 秒 → 4 秒

### 原理

每轮对话原本要跟大模型往返两次：

1. 判断"该不该调工具" ≈ 2 秒
2. 拿工具结果生成回答 ≈ 4 秒（含 TTS 首句合成）

而 MCP 工具本身只要 **0.12 秒**（实测，不是估算）。所以瓶颈全在 LLM，第一次往返又是
在一个答案固定的判断上浪费时间。

解法：桥新增 `GET /context`，服务端在**握手期**（线程池里，不占用户时间）拉一次库存，
渲染进提示词的 `{{ dynamic_context }}`。用户开口时库存已在上下文里，模型一次往返答完。

### 实测数据

| | 改造前 | 改造后 |
|---|---|---|
| 中文首包 | 7-9s | **3.58 / 4.25s** |
| 德语首包 | 6.3-8.2s | **4.47s** |
| 英语首包 | 7.1-9.0s | **4.27s** |
| 每轮工具调用 | 1 次 | **0 次** |
| 桥故障时首包 | 19.91s | **9.28s** |

### 关键实现细节（容易踩的坑）

**桥返回的键名本身就是指令。** `/context` 返回的 JSON 键会原样出现在模型提示词里：

```python
"041号机器库存快照（已是最新，回答库存问题时直接用，不必再调工具）": display_summary
```

我曾把它简化成"041号机器库存快照"，结果模型每轮照旧调工具、预取完全白做
（四轮 4 次调用，首包退回 8.8 秒）。**改这个键名前务必想清楚。**

**服务端与桥是隐性耦合。** `core/connection.py` 里用 `"库存快照" in self.prompt` 判断
是否跳过等待工具就绪。改了桥的键名，这里会**静默失效**（不报错，只是退回白等 5 秒）。

**失败时绝不能返回 `code: 0`。** `ContextDataProvider` 只认 `{"code": 0, "data": {...}}`
信封。上游异常时返回 `code: 1`，服务端会跳过注入、模型回退到工具调用。如果返回
`code: 0` 配一段错误文本，那段文本会被当成库存**念给站在机器前的顾客听**。

---

## 3. 已知未解决的问题（按严重程度排序）

### 3.1 【高】降级时把系统内部错误讲给顾客

桥挂掉时实测的三句话：

```
[ 9.15s] 我现在查一下实时库存信息                    ← 违反提示词的"静默调用工具"
[12.53s] 请稍等
[19.62s] 不好意思，刚才调用的工具查的是农历黄历，
         没法获取售货机的食物库存信息                ← 把内部工具错误暴露给顾客
```

**根因**：`get_lunar`（农历工具）被 `core/providers/tools/server_plugins/plugin_executor.py:98`
写死成必要函数：

```python
necessary_functions = ["handle_exit_intent", "get_lunar"]
all_required_functions = list(set(necessary_functions + config_functions))
```

配置里清空 `Intent.function_call.functions: []` **对它无效**。桥挂掉、库存工具不可用时，
模型会病急乱投医去调农历工具，然后把这件事告诉顾客。

**待决策**：关掉它要改上游源码，是 fork 点，以后升级 xiaozhi-esp32-server 会冲突。
用户尚未拍板。**建议先关掉**——对客话术的严重性高于升级成本。

**顺序很重要**：先关 `get_lunar`，第三句荒唐话会自动消失，再看还剩什么问题，
然后才改提示词的降级话术。反过来做会白改。

### 3.2 【中】库存快照会过期，而模型已不再调工具

快照在握手时抓一次，桥侧缓存 30 秒。今天实测 041 的库存**两小时内从 18 种掉到 12 种**。
一次对话若持续几分钟，模型手里的数字会越来越旧，**而它不会自我纠正**——因为预取生效后
它不调工具了。报一个刚卖光的商品，顾客走过去会扑空。

**已做的缓解（未充分验证）**：
- 快照带 `快照抓取时间` 字段（有用例守着）
- 提示词规定三种情况必须重新调工具：快照缺失、顾客要买某件具体商品、对话已久快照过旧

**未验证**：这三条例外在真实多轮对话中是否真的触发。本轮只测了单轮提问。
建议 Codex 补一个多轮场景测试：先问"有什么吃的"，再问"那个牛肉炒面还有吗"，
确认第二问触发了工具调用。

### 3.3 【中】降级仍需 9.28 秒

19.91 → 9.28 已改善一半，但仍然太久。剩余耗时主要是 `mcp_manager.py:57` 那个
`asyncio.wait_for(..., timeout=10)`——桥没了就干等满 10 秒。

**不要简单调短这个超时**：它是握手期给 MCP 初始化的额度，调短会让正常情况下工具
来不及就绪，退回到"模型说我没有这个工具"的老 bug（`d7f4cee` 修的就是它）。
需要更聪明的做法，比如探测端口可达性后再决定等多久。

### 3.4 【低】提示词管不住细粒度措辞

明确禁用 `right now` / `im Angebot` / `目前` 这类废词，三语照说不误。多次加码无效，
已放弃。规则留在提示词里（无害），别指望它。

---

## 4. 商品定价：数据源根本不存在

用户问过"为什么接的 API 调取不到货物具体商品信息/价格"。查证结论：

| 接口 | 有价格吗 |
|---|---|
| `getStoreGoodsShelvesList`（语音链路在用） | ❌ 12 个字段全无价格 |
| `GET /commodities` | ❌ 只有 `commodityId` + `commodityName` |
| `GET /menu/products` | ❌ 名称、类型、分类、供应商 |
| `GET /sales` | ✅ `unitPrice` —— **但那是成交价** |

**整套 API 的商品档案里没有挂牌价**，价格只存在于历史订单中，且 `/sales` 里有
`allDiscount` 字段，说明成交价可能含折扣。

**当前处理**：提示词明令禁止估算或推断价格，改口"价格贴在货道标签上"。实测有效
（问"鸡肉蔬菜蒸饺多少钱"→"价格贴在货道标签上，你看一下就知道了"，5.83 秒）。

**不要用成交价冒充定价**：没卖过的商品查不到价，有折扣时成交价≠标价，对着顾客
报错价格会出实际问题。要真正支持价格问答，得先确认 Smartfoodie 的定价主数据存在哪里
——这个问题用户尚未回答。

---

## 5. 提交记录

### 小智服务端 `~/airobot/server`（原 `~/xiaozhi/xiaozhi-esp32-server`）

```
92dd920 test: 把 Smartfoodie 定制逻辑的离线用例纳入仓库
7cd8898 perf: 握手期预取库存，首包从 7-9 秒降到 4 秒
82f735a fix(prompt): 禁止播报"没有空货道"这类缺席信息
c129c20 fix(prompt,tts): 补上价格口径、禁止追问，并清掉被念出来的分号
d3a0a09 fix(tts): 让流式切句认得英文句号，德语首包不再等整段
```

工作区干净，无未提交改动。

注意 `data/.config.yaml` 被 gitignore（含 `context_providers` 配置和模块选择），
不在版本控制内。换机器要手动重建。

### 041 桥

```
7eea78c fix(bridge): 快照键名带回"不必再调工具"的指令
0c72e5b feat(bridge): 库存快照带上抓取时间
3e37118 feat(bridge): 加 /context 端点，供语音端握手期预取库存
```

⚠️ **这个仓库有 10 个未提交文件，不是本轮改的**：

```
M src/tuya_enterprise_bridge/mcp_server.py      M tests/test_mcp_server.py
M src/tuya_enterprise_bridge/policy.py          M tests/test_policy.py
M src/tuya_enterprise_bridge/service.py         M tests/test_service.py
```

内容看起来是 Codex 之前的在途工作（涂鸦试运行表单空字段兼容、审计日志记录内部原因等）。
本轮**只动过 `machine_mcp_server.py` 和新增的 `tests/test_machine_context_route.py`**，
其余一个字没碰。提交时别混在一起。

---

## 6. 测试

```bash
# 桥（23 个用例）
cd ~/airobot/bridge
~/.venvs/tuya-enterprise-bridge/bin/python -m pytest tests/test_machine_context_route.py \
  tests/test_machine_mcp_server.py tests/test_inventory.py -q

# 服务端（19 个用例，已纳入仓库）
cd ~/airobot/server/main/xiaozhi-server
~/.venvs/xiaozhi-server/bin/python tests_smartfoodie/test_sentence_split.py      # 断句 9 例
~/.venvs/xiaozhi-server/bin/python tests_smartfoodie/test_punctuation_strip.py   # 标点 10 例
```

**改动 TTS 文本处理时必须两组都跑。** `base.py` 的切句逻辑和 `textUtils.py` 的标点表
存在隐性耦合：分号既在切分符表里，又在清理表里。只改一处、只跑一组，很容易把
已修好的行为改回去（本轮就是靠回归跑发现两张表有交集的）。

---

## 7. 测延迟的注意事项（踩过坑）

**单次采样不可信。** 服务端重启后第一轮请求包含 MCP 冷连接开销，我曾据此误判
"中文延迟退步 6 秒"，打乱顺序复测三次后发现完全正常。

规则：
- 至少复测三次并打乱语言/用例顺序
- 丢弃服务端重启后的第一轮（日志里 `服务端MCP客户端已连接` 出现在哪轮，哪轮就是冷的）
- 组内离散度经常有 2-5 秒，小于这个幅度的差异不要下结论

**别用裸 API 调用代替真实链路测延迟。** 我试过直接打 Ark API 比较模型速度，
结论（DeepSeek 比豆包快 40%）在真实链路上完全没兑现——TTS 和切句的固定开销把
差异稀释掉了。真实链路有流式切句、出首句就停，裸测复现不了。

---

## 8. 待用户决定 / 用户侧动作

这些我无权或不该代劳：

1. **`get_lunar` 要不要关**（见 3.1）——需要改上游源码，fork 点
2. **方舟 API Key 轮换** —— `ark-5ef5436e-...` 曾在截图中暴露，一直未换
3. **定价主数据存在哪里**（见第 4 节）——决定价格问答能否实现
4. **launchd 开机自启** —— 目前 Mac 重启后两个服务都要手动拉起

火山引擎语音合成大模型（双向流式 TTS）**已放弃**：音色库 114 条里**没有德语**
（中文约 90、中/英 12、纯英 8、日/西 6、西 1、日 2）。服务已停用，用量 0 字符，
未产生费用。当前 TTS 仍是 EdgeTTS（免费，三语可用）。

---

## 9. 建议的下一步顺序

1. 关掉 `get_lunar`，重测降级路径（3.1）—— 需用户先拍板是否接受 fork 上游
2. 补多轮对话测试，验证快照过期的三条例外真的会触发（3.2）
3. 视情况处理降级的 9.28 秒（3.3）

第 6 节提到的"把离线用例移进仓库"已在 `92dd920` 完成，不必重做。
