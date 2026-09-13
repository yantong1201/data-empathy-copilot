# 风险、政策与契约检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| RISK-C001 | RISK-T001 | 规则矩阵覆盖全部类型、等级、证据条件、优先级、持续/缓和规则和已登记反例；模型不能降级 | `data/reports/risk_rule_matrix.json`、`data/reports/risk_priority_regression.json`、`data/reports/phase_b_verification.json`；`python -m backend.risk_empathy verify` | 通过 |
| RISK-C002 | RISK-T002 | 情绪仅两枚信号，医生语义和缓和案例不误触发 | `data/reports/emotion_regression.json`、`data/reports/required_questions_and_forbidden_actions.json` | 通过 |
| RISK-C003 | RISK-T003 | 政策 10–20 条且元数据齐全 | `data/reports/policy_pack_inventory.json`（16 条，来源均为比赛演示规则） | 通过 |
| RISK-C004 | RISK-T004 | 三 Provider 使用正式同一 Schema；缺证据为 `unclear/needs_verification`；`why/why_not` 与顶层冲突引用可追溯；五项安全校验均有结果；非法输出有有限修复/降级路径，失败不能进入人工确认 | `data/reports/provider_contract_regression.json`；Schema 入口 `backend/risk_empathy/schema_validate.py`；独立 `safety_check_result`；未运行不得作为确认依据 | 通过 |

本检查项通过只证明规则、政策与契约已完成，不证明 Agent、Provider、工作台 UI 或评测已完成。
