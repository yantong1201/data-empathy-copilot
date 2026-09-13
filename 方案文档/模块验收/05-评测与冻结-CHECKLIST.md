# 评测与冻结检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| EVAL-C001 | EVAL-T001 | 开发 48、冻结 12、同买家/事件不跨集；`intent_ontology_v1` 类别和 gold 标注不可变且标注员盲于预测 | 划分/ontology 文件、盲法记录、双人冲突裁决和 hash | 待验证 |
| EVAL-C002 | EVAL-T002 | Chat-only/Snapshot/Full Agent/Rules-only 全部运行；泄漏回归通过 | 运行矩阵和回归报告 | 待验证 |
| EVAL-C003 | EVAL-T003 | 轨迹、意图、事实、引用、回复、成本指标按协议公式；`unclear` 覆盖/严格准确率、错误类型、安全覆盖率和首错归因正确；Full Agent 缺安全记录或关联失败计入 `missing_safety_check` | 指标脚本、手算抽查、`analysis_id`/`run_id`关联、首错和 boundary/retention 报告 | 待验证 |
| EVAL-C004 | EVAL-T004 | 报告含样本、集合、版本、`analysis_id`/`run_id`、原始 JSON、`safety_check_result`、工具、Token、耗时、gold、support、错误和证据；冻结后不调参 | JSON/CSV/Markdown 报告、冻结 hash、回归记录及关联抽查 | 待验证 |

## 变更记录

- v0.1（2026-09-13）：补充安全校验记录关联和报告字段验收。
