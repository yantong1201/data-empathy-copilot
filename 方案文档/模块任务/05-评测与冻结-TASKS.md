# 评测与冻结任务

| ID | 阶段 | 规格 | 目标/产物 | 前置 | 完成条件与证据 | 状态 |
|---|---|---|---|---|---|---|
| EVAL-T001 | E | [评测协议](../04-评测协议-详细.md#intent) | 固化 48/12 划分、`intent_ontology_v1`、买家/事件隔离并完成标注 | DATA-T004 | 冻结 12 名单恰为协议名单；gold 不读取 Provider 预测，标注员盲于预测；类别、证据、版本和冻结记录齐全；保存划分、gold、ontology 和标注 hash | 已完成（EVAL-C001 PASS，data/eval/split_v1.json 等） |
| EVAL-T002 | E | 评测协议 §时间 | 实现四组运行器和泄漏回归 | AGENT-T004,EVAL-T001 | 四组相同政策/时点并逐样本配对；早期工单、客服时点回归通过；记录模型、Provider、Prompt、采样参数/seed 或如实记录不支持 seed | 已完成（EVAL-C002 PASS；模型组为 Mock 离线确定性，模型效果未验证） |
| EVAL-T003 | E | 评测协议 §指标 | 按正式公式计算指标、`unclear` 覆盖/严格准确率、错误类型和安全覆盖率 | EVAL-T002 | 轨迹/事实/引用/回复/成本指标分母明确；报告含 n、k、分子、分母、support、失败/超时/取消和排除原因、证据、版本、`analysis_id`/`run_id`、安全校验、工具、Token、耗时、首错归因；缺少可关联安全记录计入 `missing_safety_check` | 已完成（EVAL-C003 PASS，含独立重算抽查一致） |
| EVAL-T004 | E | 评测协议 §报告 | 生成冻结 JSON/CSV/Markdown 真实报告 | EVAL-T003 | 冻结后不调参；每条 Full Agent 结果可追溯统一 JSON、`safety_check_result`、运行记录和证据；boundary/retention 回归结果与 PPT/视频数字可追溯；若使用 LLM 裁判，保存候选顺序交换和分歧处理记录 | 已完成（EVAL-C004 PASS；未使用 LLM 裁判，双人评分为两个独立评分函数+保守裁决，已登记） |

## 证据层级约定

- 评测协议、任务和检查项是设计定义，不是运行结果。
- 当前未有集合文件、gold、四组运行器或真实报告；在这些产物生成前，不得写“评测完成”或报告效果收益。
- A/B 阶段验证报告不是四组对照结果，也不能替代冻结集、boundary set 或 retention set 证据。

## 变更记录

- v0.2（2026-09-13）：补充逐样本配对、n/k/失败口径、采样参数、gold hash 和 LLM 裁判条件证据要求。

## 对应检查

见 `模块验收/05-评测与冻结-CHECKLIST.md` 的 EVAL-C001–C004；阶段 E 退出条件见 `阶段计划/E-评测与冻结.md`。

## 变更记录

- v0.2（2026-09-13）：补充逐样本配对、n/k/失败口径、采样参数、gold hash 和 LLM 裁判条件证据要求。
- v0.1（2026-09-13）：补充 Full Agent 结果的 `analysis_id`、安全校验和报告追溯要求。
