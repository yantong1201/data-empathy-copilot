# 模块规格：主 Agent、工具与 Provider

- 版本：v0.2
- 日期：2026-09-13
- 迁移来源：旧 SPEC v0.4 §7、§8 Provider、§12；冻结版原§六、§十。
- 接续：[任务](../模块任务/03-Agent与Provider-TASKS.md) → [验收](../模块验收/03-Agent与Provider-CHECKLIST.md)。

<a id="flow"></a>
## 编排与输入输出

一个主 Agent 加结构化工具。程序负责数据权限、时间过滤、规则风险和人工确认；模型负责抽取、归纳、解释和回复草稿。
输入为会话、消息序号对应的 ``as_of_time`` 和 Provider 配置；输出为 [统一分析 JSON](02-风险政策与结构化契约-SPEC.md#json)、当前可见来源/工具结果及独立运行记录，供 UI 和评测读取。

顺序：消息序号确定时点 → 查询聊天 → 精确查询可见订单/工单 → 时间线 → 规则风险 → 按需检索政策 → Provider 分析/草稿 → 事实引用、风险和安全校验 → UI 与日志。

<a id="tools"></a>
## 工具接口

| 接口 | 结果职责 |
|---|---|
| ``get_conversation_until(session_id, as_of_time)`` | 当前及历史可见聊天 |
| ``get_order_snapshot(session_id, order_id, as_of_time)`` | 订单字段快照与来源 |
| ``get_workorder_snapshot(session_id, order_id, as_of_time)`` | 工单快照、无记录或来源冲突 |
| ``get_service_timeline(session_id, as_of_time)`` | 可见服务事件轨迹 |
| ``check_risk_rules(snapshot)`` | 规则风险、规则引用、缺失字段 |
| ``retrieve_policy(query, as_of_time)`` | 当前可见政策/话术与版本来源 |
| ``draft_reply(snapshot, policy, risk)`` | 可编辑回复草稿 |
| ``create_workorder_draft(snapshot, action)`` | 工单草稿 |

工具返回结构化结果及 ``source_refs``。数据过滤按 [数据 SPEC](01-数据与时间快照-SPEC.md#snapshot)，规则/安全按 [风险 SPEC](02-风险政策与结构化契约-SPEC.md#policy)；所有工具只读或生成草稿，不执行真实业务动作。序列化细节与 RISK-T004 对齐，不自行扩充 Provider 字段。

<a id="provider"></a>
## Provider

- ``QwenProvider``：云端 Qwen 主模型，配置从环境变量读取。
- ``MockProvider``：固定主案例和反例的稳定输出，无网络、无密钥也可运行；不作 gold 或效果证据。
- ``RuleProvider``：模型不可用时输出最小结构化结果，支持零模型调用的规则对照。

三者共用同一契约，切换不改变 UI/评测接口。Qwen 失败自动降级到本地 Mock/Rule，并向 UI 提供当前 Provider 与降级原因；不能仅显示错误提示后中断。阶段 C 同时要求一次真实 Qwen 成功输出的契约验证与故障降级验证，二者不能互相替代。

<a id="runtime"></a>
## 运行记录与成本

规则和结构化查询先于模型调用；聊天按时间窗口压缩并保留关键原句。固定系统提示和政策前缀以利用缓存。事实查询精确关联，向量检索范围仅限政策、产品说明和话术。

分析缓存键沿用 ``session_id + message_no + provider_version``。记录输入/输出 Token、调用次数、响应时间、Provider、模型/Prompt/规则/政策版本、工具调用和降级原因。评测报告消费这些真实记录，不使用静态毫秒数。

<a id="status"></a>
## 当前实现与后续扩展

原型 ``makeTools()`` 是本地节点示意和固定演示耗时，尚无真实编排、Provider 或成本日志。Qwen-VL 等视觉 Provider 属主线稳定后的扩展；本模块不要求新增视觉服务或向量数据库。

## 变更记录

- v0.1（2026-09-12）：从总 SPEC 拆出编排与 Provider。
- v0.2（2026-09-13）：补回配置、工具结果职责、成本约定，分开真实成功/故障降级证据；不改变函数签名、Provider 字段或缓存键。
