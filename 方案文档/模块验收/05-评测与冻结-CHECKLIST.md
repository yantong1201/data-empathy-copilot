# 评测与冻结检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| EVAL-C001 | EVAL-T001 | 开发 48、冻结 12、同买家/事件不跨集；冻结记录不可变 | 划分文件、双人标注和 hash | 待验证 |
| EVAL-C002 | EVAL-T002 | Chat-only/Snapshot/Full Agent/Rules-only 全部运行；泄漏回归通过 | 运行矩阵和回归报告 | 待验证 |
| EVAL-C003 | EVAL-T003 | `unclear` 覆盖率+覆盖内严格准确率；错误类型和安全覆盖率按协议 | 指标脚本、手算抽查 | 待验证 |
| EVAL-C004 | EVAL-T004 | 报告含样本、版本、原始 JSON、工具、Token、耗时、证据 | JSON/CSV/Markdown 报告 | 待验证 |
