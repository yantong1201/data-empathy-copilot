# 评测与冻结任务

| ID | 阶段 | 规格 | 目标/产物 | 前置 | 完成条件与证据 | 状态 |
|---|---|---|---|---|---|---|
| EVAL-T001 | E | [评测协议](../04-评测协议-详细.md#intent) | 固化 48/12 划分、`intent_ontology_v1`、买家/事件隔离并完成标注 | DATA-T004 | 冻结 12 名单恰为协议名单；gold 不读取 Provider 预测，标注员盲于预测；类别、证据、版本和冻结记录齐全 | 待实现 |
| EVAL-T002 | E | 评测协议 §时间 | 实现四组运行器和泄漏回归 | AGENT-T004,EVAL-T001 | 四组相同政策/时点；早期工单、客服时点回归通过 | 待实现 |
| EVAL-T003 | E | 评测协议 §指标 | 按正式公式计算指标、`unclear` 覆盖/严格准确率、错误类型和安全覆盖率 | EVAL-T002 | 轨迹/事实/引用/回复/成本指标分母明确；报告含 support、证据、版本、`analysis_id`/`run_id`、安全校验、工具、Token、耗时、首错归因；缺少可关联安全记录计入 `missing_safety_check` | 待实现 |
| EVAL-T004 | E | 评测协议 §报告 | 生成冻结 JSON/CSV/Markdown 真实报告 | EVAL-T003 | 冻结后不调参；每条 Full Agent 结果可追溯统一 JSON、`safety_check_result`、运行记录和证据；boundary/retention 回归结果与 PPT/视频数字可追溯 | 待实现 |

## 对应检查

见 `模块验收/05-评测与冻结-CHECKLIST.md` 的 EVAL-C001–C004；阶段 E 退出条件见 `阶段计划/E-评测与冻结.md`。

## 变更记录

- v0.1（2026-09-13）：补充 Full Agent 结果的 `analysis_id`、安全校验和报告追溯要求。
