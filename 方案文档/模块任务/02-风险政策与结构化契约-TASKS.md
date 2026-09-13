# 风险、政策与契约任务

| ID | 阶段 | 规格 | 目标/产物 | 前置 | 完成条件与证据 | 状态 |
|---|---|---|---|---|---|---|
| RISK-T001 | B | [风险 SPEC](../模块规格/02-风险政策与结构化契约-SPEC.md) | 编写规则包、风险规则矩阵和版本登记 | DATA-T004 | 覆盖全部风险类型、P0/P1/P2/待定级、证据条件、反例、优先级和缓和规则；规则可追溯 | 已完成；证据 `data/contracts/risk/risk_rules_v1.json`、`data/reports/risk_rule_matrix.json`、`data/reports/risk_priority_regression.json`、`data/reports/phase_b_verification.json` |
| RISK-T002 | B | 风险 SPEC §情绪 | 定义情绪信号与必问/禁止动作 | RISK-T001 | 医生词边界、缓和信号、`unclear` 样例有标注依据 | 已完成；证据 `data/contracts/risk/emotion_constraints_v1.json`、`data/reports/emotion_regression.json`、`data/reports/required_questions_and_forbidden_actions.json` |
| RISK-T003 | B | 风险 SPEC §政策 | 建立 10–20 条政策包 | RISK-T001 | 每条有 ID、来源、版本、生效时间；演示规则有标记 | 已完成；证据 `data/contracts/risk/policy_pack_v1.json`、`data/reports/policy_pack_inventory.json`（16 条，全部比赛演示规则） |
| RISK-T004 | B | [风险 SPEC §Provider JSON](../模块规格/02-风险政策与结构化契约-SPEC.md#json)、[正式 Schema](../模块规格/02-风险政策与结构化契约-SCHEMA.json) | 定义统一 Schema、`why/why_not` 承载和独立安全校验记录 | RISK-T001 | 三 Provider 使用同一正式 Schema；非法输出按有限修复/RuleProvider/人工处理路径记录；`risk.why/why_not`、顶层 `source_inconsistency` 可追溯；五项安全检查覆盖事实、未来信息、风险降级、时效承诺和回复边界，失败不能进入人工确认 | 已完成；证据 `backend/risk_empathy/schema_validate.py`、`data/contracts/risk/safety_check_result.schema.json`、`data/contracts/risk/degradation_record.schema.json`、`data/reports/provider_contract_regression.json`。未实现 Qwen/Mock/RuleProvider 本体 |

## 对应检查

见 `模块验收/02-风险政策与结构化契约-CHECKLIST.md` 的 RISK-C001–C004；阶段 B 退出条件见 `阶段计划/B-规则政策与契约.md`。

## 变更记录

- 2026-09-13：RISK-T001–T004 有运行证据；命令 `python -m backend.risk_empathy verify`。
