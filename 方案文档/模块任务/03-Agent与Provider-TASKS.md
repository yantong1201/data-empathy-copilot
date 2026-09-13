# Agent 与 Provider 任务

| ID | 阶段 | 规格 | 目标/产物 | 前置 | 完成条件与证据 | 状态 |
|---|---|---|---|---|---|---|
| AGENT-T001 | C | [Agent SPEC](../模块规格/03-Agent与Provider-SPEC.md) | 实现主 Agent 和 8 个结构化工具适配 | DATA-T002,RISK-T004 | 调用顺序和权限边界可记录；工具无外部副作用 | 待实现 |
| AGENT-T002 | C | Agent SPEC §Provider | 实现 MockProvider 与 RuleProvider | AGENT-T001,DATA-T004 | 断网无密钥三主案例连续运行，输出通过 Schema | 待实现 |
| AGENT-T003 | C | Agent SPEC §Provider | 实现 QwenProvider 和自动降级 | AGENT-T002 | 失败显示原因并切 Mock/Rule；接口不变 | 待实现 |
| AGENT-T004 | C | Agent SPEC §运行记录 | 接入日志、缓存和 Token/耗时统计 | AGENT-T003 | 每次结果可回溯版本、工具、Token、耗时、降级原因 | 待实现 |

## 对应检查

见 `模块验收/03-Agent与Provider-CHECKLIST.md` 的 AGENT-C001–C004；阶段 C 退出条件见 `阶段计划/C-Agent与Provider.md`。
