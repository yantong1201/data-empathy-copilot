# 冻结评测报告 v1（frozen_report_v1）

- 生成时间：2026-09-16T12:14:13+08:00
- Provider 模式：MockProvider（当前无 Qwen 凭证：模型组（chat_only/snapshot/full_agent）以 MockProvider 离线确定性运行，信息范围消融真实有效，模型效果未验证；Rules-only 为零模型调用）
- 冻结会话：12；开发会话：48；冻结目标样本：46
- split hash：`a66a3763debb8661…`；gold hash：`721e735b76de56d3…`；ontology hash：`dd7e0cb3c985a860…`

## 泄漏回归
- 检查样本 46；泄漏 0；通过：True

## 四组对照指标

| 指标 | chat_only | snapshot | full_agent | rules_only |
|---|---|---|---|---|
| intent_major_macro_f1 | 0.4667 | 0.4667 | 0.4667 | 0.4667 |
| intent_minor_macro_f1 | 0.4286 | 0.4286 | 0.4286 | 0.4286 |
| unclear_coverage | 1.0 | 1.0 | 1.0 | 1.0 |
| covered_strict_accuracy | 0.3696 | 0.3696 | 0.3696 | 0.3696 |
| trajectory_association_accuracy | 0.5326 | 1.0 | 1.0 | 1.0 |
| fact_field_accuracy | 0.0 | 0.0 | 0.0 | 0.0 |
| citation_completeness | 1.0 | 1.0 | 1.0 | 1.0 |
| P0_recall | 1.0 | 1.0 | 1.0 | 1.0 |
| P1_recall | n/a | n/a | n/a | n/a |
| reply_mean_score | 0.6196 | 0.6522 | 0.6522 | 0.6522 |
| safety_coverage | 1.0 | 1.0 | 1.0 | 1.0 |

## 成本（cold / hot）

- chat_only: cold 46 次，耗时均值 1.043ms / p95 16.0ms；hot 0 次
- snapshot: cold 46 次，耗时均值 3.413ms / p95 16.0ms；hot 0 次
- full_agent: cold 42 次，耗时均值 3.31ms / p95 16.0ms；hot 4 次
- rules_only: cold 46 次，耗时均值 0.674ms / p95 0.0ms；hot 0 次

## Mock 连续成功率：1.0（120/120）

## Boundary / Retention 回归
- retention（冻结 rules_only 不随 Prompt 变化）：PASS（n=46）
- boundary（回归案例受影响重跑）：PASS（n=6）

## 冻结声明
- 冻结后不得用冻结结果调参，不回写规则；每次 Prompt/规则/Provider/Schema/运行器变化须同时运行受影响 boundary set 与不应变化的 retention set

> 本报告数字均由运行器生成并可按 analysis_id/run_id 追溯；Mock/Rule 输出不作为模型效果证据。