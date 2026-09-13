# 数据与时间快照检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| DATA-C001 | DATA-T001 | 7 表、行数、字段和 ID 类型与审计一致 | loader 日志、字段映射、行数报告 | 待验证 |
| DATA-C002 | DATA-T002 | 聊天/订单/工单各字段按 `as_of_time` 过滤 | 单元/回归输出；S00015 msg1 no_workorder | 待验证 |
| DATA-C003 | DATA-T003 | 三例 source_inconsistency 保留双方来源且不泄漏 | fixture JSON 与引用 | 待验证 |
| DATA-C004 | DATA-T004 | 三主案例快照重复运行一致、引用可定位 | hash/差异报告、样本 JSON | 待验证 |
