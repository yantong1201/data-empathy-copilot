# 数据与时间快照检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| DATA-C001 | DATA-T001 | 7 表、行数、字段和 ID 类型与审计一致 | loader 日志、字段映射、行数报告 | 待验证 |
| DATA-C002 | DATA-T002 | 聊天/订单/工单各字段按 `as_of_time` 过滤，并按 `Asia/Shanghai` 稳定解析无时区输入 | 单元/回归输出；S00015 msg1 `no_workorder`；跨时区运行对照 | 待验证 |
| DATA-C003 | DATA-T003 | 通用 `source_inconsistency` 规则覆盖提前声称建单会话；保留双方来源和统一字段，禁止回填号提前可见且不泄漏未来字段 | 全量时点回归、三例 fixture JSON、`kind/source_refs/as_of_time/summary` 引用核对 | 待验证 |
| DATA-C004 | DATA-T004 | 三主案例快照重复运行一致，带偏移时间和引用可定位，不受机器本地时区影响 | hash/差异报告、样本 JSON、跨时区对照 | 待验证 |
