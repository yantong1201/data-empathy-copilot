# 模块规格：风险规则、政策和结构化契约

- 版本：v0.5
- 日期：2026-09-13
- 迁移来源：旧 SPEC v0.4 §5、§8–10；冻结版原§七、§九。
- 接续：[任务](../模块任务/02-风险政策与结构化契约-TASKS.md) → [验收](../模块验收/02-风险政策与结构化契约-CHECKLIST.md)。

## 职责与输入输出

输入为经过 [数据契约](01-数据与时间快照-SPEC.md#snapshot) 过滤的快照、当前可见证据和带版本政策；输出为规则风险、情绪取值约束、必问字段、禁止动作及供三种 Provider 共用的 JSON 校验依据。
本模块维护业务判断与安全契约，执行查询和模型调用由 [Agent 模块](03-Agent与Provider-SPEC.md) 承接。

<a id="emotion"></a>
## 情绪信号

只标注当前文本和服务进展中的可观察服务信号，不作心理诊断：

``````text
negative_signal: none | present | unclear
escalation: no | yes | unclear
``````

证据只能来自当前时点及此前的买家原话和服务进展。当前信号结合历史上下文与当前已可见的后续进展判断，不能只按末条关键词清空历史，也不能将历史永久累积为 ``present/yes``。历史投诉在后续缓和后可降级展示，但须保留事件和原句引用；情绪缓和不能降低规则高风险。静态正则不是评测 gold。“医生/产检医生”不直接等同就医事件。

<a id="risk"></a>
## 风险等级与类型

| 等级 | 定义 | 示例触发 |
|---|---|---|
| P0 | 人身安全、就医或监管升级，须即时人工介入 | 不良反应+就医证据；监管投诉且情绪升级 |
| P1 | 有规则证据支持的资金或风控风险，须当日核实处理 | 当前可见业务记录及规则确认的异常退款或重复退款；待核实候选不满足 |
| P2 | 体验类负面情绪，标准流程内处理 | 保价争议负面语气 |
| 待定级 | 证据不足 | ``needs_verification``，禁止模型直接给 P0/P1 |

``````text
adverse_reaction
complaint_escalation
abnormal_refund
repeat_contact
logistics_exception
aftersales_damage
unresolved_workorder
none
unclear
``````
## 风险规则矩阵

下表是当前比赛规则的可执行最小矩阵。`current_visible` 只表示通过数据快照在当前 `as_of_time` 可见的证据；仅有自述、缺少规定的业务记录或存在来源冲突时，不得升级为已确认的更高风险。

| rule_id | risk_type | 触发条件（全部在当前时点可见） | 结果 | 明确排除 |
|---|---|---|---|---|
| R-AR-001 | `adverse_reaction` | 买家明确描述不良反应，或在当前服务语境下明确自述就医；同时有当前可见就医/治疗证据 | P0，`confirmed` | 不作医学诊断；仅有观察、自述不完整且无就医/治疗证据时为待定级/`needs_verification` |
| R-COMP-001 | `complaint_escalation` | 明确监管/投诉升级表达，且当前 `escalation=yes` | P0，`confirmed` | 已撤回或已缓和的历史表达不能单独维持当前升级信号 |
| R-REFUND-001 | `abnormal_refund` | 当前可见业务记录和规则共同支持异常退款 | P1，`confirmed` | 仅自述、异常登记或缺少外箱/面单/重量等证据时为待定级；不得认定欺诈 |
| R-REPEAT-001 | `repeat_contact` | 当前服务事件中存在可定位的多次联系记录 | 通常 P2 或不单独定级 | 不得仅凭昵称、买家相似或跨集合记录判定重复进线 |
| R-LOGI-001 | `logistics_exception` | 当前可见物流轨迹或服务记录明确显示物流异常 | 至多 P2，`confirmed` | 不得由物流异常推断商品破损责任或资金风险 |
| R-DAMAGE-001 | `aftersales_damage` | 买家明确描述到手破损，且当前可见售后/换货证据支持 | P2，`confirmed` | 不归因物流，不推断责任；缺少必要证据时为待定级 |
| R-WO-001 | `unresolved_workorder` | 当前可见工单存在未完成且仍有必需动作 | 至多 P2，`confirmed` | 创建前 `no_workorder` 不得标成未解决工单；不能覆盖已满足的 P0/P1 |
| R-NONE-001 | `none` | 已检查适用规则，当前没有规则命中 | 无风险，`confirmed` | 不能用“无命中”掩盖数据缺失或未运行规则 |
| R-UNCLEAR-001 | `unclear` | 规则所需字段缺失、不可见或来源冲突尚不能裁决 | 待定级，`needs_verification` | 模型不得自行升为 P0/P1；必须列出 `why_not` 和缺失字段 |

同一时点多条规则命中时，先保留每条 `rule_id`，等级取最高确定性等级；P0/P1 一旦由规则确定，情绪缓和、模型置信度或缺少后续工单不得降级。未满足确定性条件的候选风险只能输出待定级和 `needs_verification`。规则矩阵版本必须写入运行记录和 `analysis_id` 指纹。


风险由规则定级，模型解释并指出证据/缺失字段，不能降低规则确定的高风险。

分析解释至少分别说明：命中的 `rule_ids` 及其可见证据（`why`），以及因缺字段、待核实或时点不可见而不能作出更强结论的原因（`why_not`）。`why_not` 说明证据边界，不得自行覆盖已满足规则的高风险结果；空包裹的“异常=是”与“待核实”仍按 `needs_verification` 处理，不新增独立来源冲突类型。

<a id="cases"></a>
## 主案例与反例预期

精确日期和来源字段见 [数据案例](01-数据与时间快照-SPEC.md#cases)；本节维护判断预期，集合归属见 [评测协议](../04-评测协议-详细.md#datasets)。

| 案例 | 预期与边界 |
|---|---|
| S00015 | 首条已有“我人现在在医院”的自述，即 P0；工单尚不可见不影响就医自述证据。后续缓和不降规则风险；不能医学诊断或承诺因果 |
| S00024 | ``abnormal_refund``、``待定级 + needs_verification``。工单可见前仅有自述；可见后的异常标记仍是待核实登记，不能自动 P1、认定欺诈或断言空包裹已证实。建议保留外箱/面单、补六面照片、查询出库与揽收重量 |
| S00001 | ``aftersales_damage``、P2，商品到手破损售后；依据自述和可见换货工单，不归为 ``logistics_exception``，不推断破损责任 |
| S00064、S00065 | 先威胁投诉、后明确“不投诉了”，当前已缓和/继续跟踪，保留历史 |
| S00087 | 投诉威胁后表示“处理效率还行”，验证升级随服务进展下降 |
| S00003、S00042、S00060 | 保价争议负面语气，普通负面信号和 P2 |
| S00010、S00070、S00082 | 不良反应信息不完整或仍在观察；停用/补问/回访，不做医学诊断 |
| S00134、S00303、S00474 | “医生/产检医生”用于咨询语义，不按关键词触发 P0 |

严格“医院”字面仅 S00015、S00154、S00268，均为真实就医链路；不得编造不存在的非升级反例。以上预期不是可直接复制到评测报告的标签结果，人工标注仍按协议执行。

<a id="policy"></a>
## 规则、政策与回复安全

规则包负责风险、必问字段和禁止动作；每条含 ``rule_id``、来源、版本、生效时间。政策包先维护 10–20 条轻量政策/话术，覆盖收证、升级、退款边界和回复规范；团队补充内容标记“比赛演示规则”，不能伪装成官方政策。

聊天、订单、工单、图片路径、政策检索结果和工具返回内容均是业务数据，不是系统指令。Provider 不得执行其中要求“忽略规则、改变等级、泄露数据或直接操作业务”的文本；工具结果必须携带来源和当前时点，规则引擎与安全校验是唯一的约束来源。

回复生成需校验：事实有来源；缺证据用待核实；不作医学诊断；不承诺赔付、退款时效或结果，除非当前可见政策和工单支持；不降低规则高风险；不自动执行不可逆动作。`reply_boundary` 检查还需拦截无依据定责、医学诊断、越权业务承诺和将业务文本当作指令的回复。
<a id="confirmation"></a>
## 人工确认

发送回复、升级、创建/更新工单、退款、赔偿、线下打款均须人工点击确认。Demo 只生成草稿或模拟动作，不连接真实业务系统；草稿按钮语义见 [工作台规格](04-客服工作台与证据交互-SPEC.md#interaction)。

<a id="json"></a>
## Provider 最小 JSON

以下是 Provider 契约示例及嵌套字段；正式约束见同目录 [JSON Schema](02-风险政策与结构化契约-SCHEMA.json)，示例不是冻结集效果证据。

``````json
{
  "session_id": "S00024",
  "message_no": 1,
  "as_of_time": "2026-05-05T21:38:52+08:00",
  "analysis_id": "A-S00024-0001",
  "intent": {
    "major": "售后退货",
    "minor": "仅退款疑似异常",
    "confidence": 0.86
  },
  "emotion": {
    "negative_signal": "present",
    "escalation": "unclear",
    "evidence_refs": ["chat:S00024:1"]
  },
  "risk": {
    "type": "abnormal_refund",
    "level": "待定级",
    "status": "needs_verification",
    "rule_ids": ["R-REFUND-001"],
    "why": ["当前可见记录命中异常仅退款规则"],
    "why_not": ["缺少外箱/面单照片及出库或揽收重量，不能确认异常已证实或升级为 P1"]
  },
  "facts": [],
  "source_inconsistency": [],
  "missing_fields": ["外箱照片", "面单照片", "出库/揽收重量"],
  "reply_draft": "……",
  "recommended_actions": ["收集证据", "创建工单草稿"],
  "needs_human_confirmation": true,
  "source_refs": ["chat:S00024:1", "policy:POL-REFUND-001"]
}
``````

三种 Provider 必须共用 [正式 JSON Schema](02-风险政策与结构化契约-SCHEMA.json)。Schema 校验之外仍需独立记录证据可见性、风险不降级、未来信息泄漏、无依据时效承诺和回复边界等安全校验结果；字段齐全不能替代这些语义检查。
`safety_check_result` 是独立运行记录，不是 Provider JSON 的顶层字段；每次分析必须生成一条并使用同一 `analysis_id`。其最小结构为 `status: pass|fail`、`checks.fact_visibility`、`checks.future_information`、`checks.risk_non_downgrade`、`checks.unsupported_timing`、`checks.reply_boundary`（各取 `pass|fail`）和 `failures`（失败原因及证据引用）。任一检查失败时 `status=fail`，不得把该分析作为已确认处置依据；未运行检查不得伪装为通过。Schema 非法且无法有限修复时，必须转 `RuleProvider` 或人工处理，并记录原因。
统一 JSON 约定如下：``analysis_id`` 由固定会话、消息时点、快照版本、Provider/model、Prompt、Schema、规则和政策版本组合生成并在运行期间保持不变；每次实际执行另有唯一 ``run_id``。``risk.why`` 只列命中规则及其可见证据，``risk.why_not`` 只列不能作更强结论的证据边界。``source_inconsistency`` 为数组，每项至少含 ``kind``、``source_refs``、``as_of_time`` 和 ``summary``；数据快照是唯一写入来源，Provider 只能解释，UI 和评测直接读取，不得自行重判。``facts`` 继续承载已确认业务事实，不把冲突或待核实候选冒充事实。

## 变更记录
- v0.5.1（2026-09-13）：记录与正式 Schema 的差异：SPEC 矩阵 R-NONE-001 结果为「无风险」，Schema `risk.level` 仍为 `P0|P1|P2|待定级`。未改 Schema 顶层字段/枚举/`needs_human_confirmation=true`。实现以 `type=none` 表示无枚举内风险类型。`safety_check_result` 保持独立运行记录；未运行不得为 pass。
- v0.5（2026-09-13）：补充风险规则矩阵、数据/指令隔离、`reply_boundary` 安全校验和正式 Schema/非法输出处理边界。


- v0.4（2026-09-13）：固定 `safety_check_result` 独立记录的最小结构和失败时的人工确认边界。
- v0.3（2026-09-13）：补充 why/why-not 解释边界和独立安全校验记录要求；明确待核实不新增来源冲突类型。
- v0.1（2026-09-12）：从总 SPEC 拆出规则和契约摘要。
- v0.2（2026-09-13）：补回嵌套 JSON、情绪历史规则、案例/反例和回复安全；明确输入输出和未定接口细节；既有等级、枚举、字段和动作边界不变。
