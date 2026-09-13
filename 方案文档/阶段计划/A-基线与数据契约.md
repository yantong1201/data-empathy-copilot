# 阶段 A：基线与数据契约

进入条件：材料只读可访问；原型现状已登记。涉及 DATA-T001–T004，可并行准备字段映射和审计，但快照依赖 loader。
退出条件：DATA-C001–C004 全部通过；字符串 ID、`Asia/Shanghai` 时区解析、字段级 `as_of_time` 过滤、来源冲突和三主案例可重复快照均有证据。当前：DATA-C001–C004 已通过（2026-09-13），证据见 `data/reports/phase_a_verification.json`。本阶段不包含 Agent/Provider/风险/UI/评测。下一阶段 B。
