# 评测与冻结检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| EVAL-C001 | EVAL-T001 | 开发 48、冻结 12、同买家/事件不跨集；`intent_ontology_v1` 类别和 gold 标注不可变且标注员盲于预测；划分、gold、ontology、标注和冻结 hash 可核对 | 划分/ontology/gold 文件、盲法记录、双人冲突裁决、版本记录和 hash | 待验证 |
| EVAL-C002 | EVAL-T002 | Chat-only/Snapshot/Full Agent/Rules-only 全部运行；同一样本逐项配对；模型组控制模型/参数；泄漏回归通过 | 运行矩阵、样本配对清单、模型/Provider/Prompt/采样参数记录和回归报告 | 待验证 |
| EVAL-C003 | EVAL-T003 | 轨迹、意图、事实、引用、回复、成本指标按协议公式；`unclear` 覆盖/严格准确率、错误类型、安全覆盖率和首错归因正确；报告显式列 n、k、分子、分母、失败/超时/取消及排除原因；Full Agent 缺安全记录或关联失败计入 `missing_safety_check` | 指标脚本、手算抽查、`analysis_id`/`run_id`关联、失败清单、首错和 boundary/retention 报告 | 待验证 |
| EVAL-C004 | EVAL-T004 | 报告含样本、集合、版本、`analysis_id`/`run_id`、原始 JSON、`safety_check_result`、工具、Token、耗时、gold、support、错误和证据；冻结后不调参；若使用 LLM 裁判则有候选顺序交换和分歧处理记录 | JSON/CSV/Markdown 报告、冻结 hash、回归记录及关联抽查；不使用 LLM 裁判时登记不适用 | 待验证 |

## 证据层级约定

- 本清单的“待验证”不是实现失败结论；只有对应运行产物和抽查结果齐全后才能改为通过。
- A/B 阶段模块验证报告不属于四组评测、冻结 gold 或效果收益证据。
- 静态评测入口、Mock 固定答案和手工填数不能作为 EVAL-C001–C004 的通过证据。

## 变更记录

- v0.2（2026-09-13）：补充逐样本配对、n/k/失败口径、采样参数、冻结 hash 和 LLM 裁判条件证据。
- v0.1（2026-09-13）：补充安全校验记录关联和报告字段验收。
