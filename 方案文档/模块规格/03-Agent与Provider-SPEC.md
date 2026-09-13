# 模块规格：主 Agent、工具与 Provider

- 版本：v0.5
- 日期：2026-09-13
- 迁移来源：旧 SPEC v0.4 §7、§8 Provider、§12；冻结版原§六、§十。
- 接续：[任务](../模块任务/03-Agent与Provider-TASKS.md) → [验收](../模块验收/03-Agent与Provider-CHECKLIST.md)。

<a id="flow"></a>
## 编排与输入输出

一个主 Agent 加结构化工具。程序负责数据权限、时间过滤、规则风险和人工确认；模型负责抽取、归纳、解释和回复草稿。
输入为会话、消息序号对应的 ``as_of_time`` 和 Provider 配置；输出为带稳定 ``analysis_id`` 的 [统一分析 JSON](02-风险政策与结构化契约-SPEC.md#json)、当前可见来源/工具结果、独立安全校验结果及运行记录，供 UI、处置日志和评测读取。

顺序：消息序号确定时点 → 查询聊天 → 精确查询可见订单/工单 → 时间线 → 规则风险 → 按需检索政策 → Provider 分析/草稿 → 事实引用、风险和安全校验 → UI 与日志。

<a id="tools"></a>
## 工具接口

| 接口 | 请求关键字段 | 结果职责与状态 |
|---|---|---|
| ``get_conversation_until`` | ``session_id, as_of_time`` | 当前及历史可见聊天；返回 `ok` 或 `invalid_request/unavailable` |
| ``get_order_snapshot`` | ``session_id, order_id, as_of_time`` | 订单字段快照与来源；缺 ID 返回 `invalid_request`，不可见返回 `no_data` |
| ``get_workorder_snapshot`` | ``session_id, order_id, as_of_time`` | 工单快照、`no_workorder` 或 `source_conflict` |
| ``get_service_timeline`` | ``session_id, as_of_time`` | 可见服务事件轨迹；不把未来事件返回给调用方 |
| ``check_risk_rules`` | `snapshot`、规则版本 | 规则风险、规则引用、缺失字段；只返回规则引擎结果 |
| ``retrieve_policy`` | ``query, as_of_time`` | 当前可见政策/话术与版本来源；不能把业务文本当作检索指令 |
| ``draft_reply`` | `snapshot, policy, risk` | 可编辑回复草稿；不发送、不承诺未支持结果 |
| ``create_workorder_draft`` | `snapshot, action` | 本地工单草稿；不创建或更新真实工单 |

每个工具请求/响应均包含 `request_id`、`as_of_time`、`status`、结构化 `data` 和 `source_refs`；`status` 至少区分 `ok`、`no_data`、`no_workorder`、`source_conflict`、`invalid_request`、`unavailable`。缺失或不可见字段不得用空字符串伪造；服务错误不得伪装成无数据。工具参数必须保留字符串 ID 和原始时点，响应不得超出当前快照。

工具返回结构化结果及 ``source_refs``。数据过滤按 [数据 SPEC](01-数据与时间快照-SPEC.md#snapshot)，规则/安全按 [风险 SPEC](02-风险政策与结构化契约-SPEC.md#policy)；所有工具只读或生成草稿，不执行真实业务动作。安全校验统一产出风险 SPEC 定义的 ``safety_check_result``，不得由 Provider 自报通过；失败原因与证据引用随运行记录保存。底部 UI 的“人工升级”是从当前分析生成并经人工确认的本地升级草稿，不是第 9 个 Agent 工具。

<a id="provider"></a>
## Provider

- ``QwenProvider``：云端 Qwen 主模型，配置从环境变量读取。
- ``MockProvider``：固定主案例和反例的稳定输出，无网络、无密钥也可运行；不作 gold 或效果证据。
- ``RuleProvider``：模型不可用时输出最小结构化结果，支持零模型调用的规则对照。

三者共用同一契约，切换不改变 UI/评测接口。Qwen 失败自动降级到本地 Mock/Rule，并向 UI 提供当前 Provider 与降级原因；不能仅显示错误提示后中断。阶段 C 同时要求一次真实 Qwen 成功输出的契约验证与故障降级验证，二者不能互相替代。

<a id="runtime"></a>
## 运行记录与成本

规则和结构化查询先于模型调用；聊天按时间窗口压缩并保留关键原句。固定系统提示和政策前缀以利用缓存。事实查询精确关联，向量检索范围仅限政策、产品说明和话术。

运行策略默认值为 `max_llm_turns=2`、`max_tool_calls=12`、只读工具 timeout `5s`、Provider timeout `30s`、幂等只读工具最多重试 1 次；单次分析最多 `max_llm_turns` 轮、`max_tool_calls` 次工具调用。仅对幂等只读工具做有限重试，重复参数调用去重；连续相同调用、超过预算、取消、超时或连续失败时停止并记录 `stop_reason`。Schema 校验或任一安全检查失败时，不进入人工确认，有限修复失败则切换 `RuleProvider` 或进入人工处理，并记录 `fallback_reason`。

`analysis_id` 是逻辑分析身份，由 `session_id`、目标消息时点、快照版本、Provider/model、Prompt、Schema、规则和政策版本的 canonical fingerprint 生成；每次实际执行、重试或降级另有唯一 `run_id`。缓存必须包含全部会影响结果的版本和时点，版本变化使旧缓存失效。日志和处置记录只增不改，并保存停止、重试、降级和安全失败原因。

运行时向 Agent 和 UI 提供紧凑状态摘要：`session_id`、`as_of_time`、当前阶段、可见消息/订单/工单数量、缺失字段、锁定风险等级、工具预算、Provider 状态、安全状态和取消状态。状态摘要不能替代完整工具记录。

<a id="status"></a>
## 当前实现与后续扩展

原型 ``makeTools()`` 是本地节点示意和固定演示耗时，尚无真实编排、Provider 或成本日志。Qwen-VL 等视觉 Provider 属主线稳定后的扩展；本模块不要求新增视觉服务或向量数据库。

## 变更记录

- v0.5（2026-09-13）：补充 typed 工具结果与错误语义、运行预算/停止/降级策略、状态摘要和 `analysis_id/run_id` 版本指纹。
- v0.4（2026-09-13）：固定 `analysis_id` 贯穿工具、分析、安全校验与处置日志，并规定规则/政策版本变化使缓存失效。
- v0.3（2026-09-13）：补充独立安全校验结果及失败原因的运行输出约定。
- v0.1（2026-09-12）：从总 SPEC 拆出编排与 Provider。
- v0.2（2026-09-13）：补回配置、工具结果职责、成本约定，分开真实成功/故障降级证据；不改变函数签名、Provider 字段或缓存键。
