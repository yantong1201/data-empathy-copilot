# Agent 与 Provider 任务

| ID | 阶段 | 规格 | 目标/产物 | 前置 | 完成条件与证据 | 状态 |
|---|---|---|---|---|---|---|
| AGENT-T001 | C | [Agent SPEC](../模块规格/03-Agent与Provider-SPEC.md) | 实现主 Agent、8 个结构化工具、数据/指令隔离和独立安全校验适配 | DATA-T002,RISK-T004 | 每次分析有稳定 `analysis_id` 和唯一 `run_id`；调用预算、timeout、有限重试、重复调用检测、取消/熔断、注入隔离和五项安全校验写入统一运行记录；工具无外部副作用 | 已完成（AGENT-C001 PASS，data/reports/agent_c001_evidence.json） |
| AGENT-T002 | C | Agent SPEC §Provider | 实现 MockProvider 与 RuleProvider | AGENT-T001,DATA-T004 | 断网无密钥三主案例连续运行，输出通过 Schema | 已完成（AGENT-C002 PASS，data/reports/agent_offline_runs.json：3案例×20次×2Provider=120/120） |
| AGENT-T003 | C | Agent SPEC §Provider | 实现 QwenProvider 和自动降级 | AGENT-T002 | 失败显示原因并切 Mock/Rule；接口不变 | 已完成（AGENT-C003 PASS，data/reports/agent_degradation_cases.json；Qwen 无凭证，成功路径未验证） |
| AGENT-T004 | C | Agent SPEC §运行记录 | 接入日志、缓存、append-only 运行记录和 Token/耗时统计 | AGENT-T003 | `analysis_id` 按完整时点/快照/Provider/model/Prompt/Schema/规则/政策指纹生成；`run_id` 贯穿实际尝试；版本变化使旧缓存失效；每次结果可回溯停止、重试、降级、版本、Token、耗时和安全原因 | 已完成（AGENT-C004 PASS，data/reports/agent_c004_evidence.json） |

## 对应检查

见 `模块验收/03-Agent与Provider-CHECKLIST.md` 的 AGENT-C001–C004；阶段 C 退出条件见 `阶段计划/C-Agent与Provider.md`。
