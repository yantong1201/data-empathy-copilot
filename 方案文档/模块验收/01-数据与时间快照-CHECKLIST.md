# 数据与时间快照检查项

| ID | 关联任务 | 检查与通过标准 | 验证方式/证据 | 状态 |
|---|---|---|---|---|
| DATA-C001 | DATA-T001 | 7 表、行数、字段和 ID 类型与审计一致 | `python -m backend.data_empathy verify`；`data/reports/loader.log`；`data/reports/loader_selfcheck.json`（998/138/112、113、80、819/819、629/629，`input_audit_all_match=true`）；`data/reports/field_mapping.json` | 通过（2026-09-13）。输入审计通过 ≠ 快照验收；快照见 C002–C004 |
| DATA-C002 | DATA-T002 | 聊天/订单/工单各字段按 `as_of_time` 过滤，并按 `Asia/Shanghai` 稳定解析无时区输入 | `data/reports/phase_a_verification.json` DATA-C002；`data/fixtures/S00015/first_message.json`（`no_workorder`，`as_of_time=2026-05-05T16:33:33+08:00`）；S00024/S00001 空完成时间不显示完结 | 通过（2026-09-13） |
| DATA-C003 | DATA-T003 | 通用 `source_inconsistency` 规则覆盖提前声称建单会话；保留双方来源和统一字段，禁止回填号提前可见且不泄漏未来字段 | `data/reports/source_inconsistency_scan.json`（46 会话，`missing_conflict=[]`）；`data/fixtures/S00015/claim_created.json` 含 `kind/source_refs/as_of_time/summary` 及聊天原句+系统暂无记录 | 通过（2026-09-13） |
| DATA-C004 | DATA-T004 | 三主案例快照重复运行一致，带偏移时间和引用可定位，不受机器本地时区影响 | `data/fixtures/manifest.json`；`data/reports/repeatability.json`（`repeat_match=true`，`in_memory_match=true`，`tz_env_independent=true`） | 通过（2026-09-13） |
