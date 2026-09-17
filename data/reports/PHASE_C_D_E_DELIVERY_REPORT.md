# 阶段 C/D/E 交付报告（2026-09-16）

> 执行范围：按 C/D/E 阶段提示词实现 Agent 与三种 Provider、客服工作台 UI、评测与冻结，并完成 AGENT/UI/EVAL-C001–C004 验收。未执行 Git 提交/推送，未连接真实业务系统，未修改原始 Excel。

## 一、总体结果

| 阶段 | 检查项 | 结果 | 关键证据 |
|---|---|---|---|
| C Agent与Provider | AGENT-C001–C004 | **全部 PASS** | `data/reports/agent_phase_c_verification.json` |
| D 工作台 UI | UI-C001–C004 | **全部 PASS** | `data/reports/workbench_phase_d_verification.json` + `data/reports/ui_evidence/`（9 张截图） |
| E 评测与冻结 | EVAL-C001–C004 | **全部 PASS** | `data/eval/eval_phase_e_verification.json` + `data/eval/results/frozen_report_v1.{json,csv,md}` |

前置回归：`python -m backend.data_empathy verify`、`python -m backend.risk_empathy verify` 均通过。

## 二、阶段 C：Agent 与三种 Provider

新增模块 `backend/agent_empathy/`：

- `tools.py`：8 个结构化工具（get_conversation_until / get_order_snapshot / get_workorder_snapshot / get_service_timeline / check_risk_rules / retrieve_policy / draft_reply / create_workorder_draft），统一 request_id/as_of_time/status/data/source_refs 响应封套，六类状态语义（ok/no_data/no_workorder/source_conflict/invalid_request/unavailable），只读或本地草稿。
- `providers.py`：QwenProvider（配置仅从环境变量读取，密钥不落源码/日志）、MockProvider、RuleProvider 共用正式 Schema；意图推导不读取 Excel `scene_major/scene_minor` gold 字段。
- `agent.py`：主 Agent 编排 + 自动降级链（Qwen→Mock→Rule）、熔断、预算（max_llm_turns=2/max_tool_calls=12/只读 5s/Provider 30s/幂等重试 1 次）、重复调用去重、取消、稳定 `analysis_id`（覆盖会话/时点/快照/Provider/模型/Prompt/Schema/规则/政策指纹）与每次执行唯一 `run_id`。
- `runlog.py`：append-only 哈希链运行记录（`data/runs/run_log.jsonl`）+ 版本化缓存（指纹任一部分变化即失效）+ Token/耗时统计。
- `verify.py`：AGENT-C001–C004 全覆盖验证。

要点结果：
- 三主案例 Mock/Rule 断网无密钥连续运行 3×20×2=120/120 完整有效（Schema 合法 + 独立安全校验 + 可关联运行记录）。
- 6 类故障注入（超时/网络/鉴权/非法 JSON/Schema 非法/安全失败）全部按约定降级到 Mock 并记录 failure_reason/fallback_reason；连续 3 次失败后熔断直接跳过云端调用。
- 注入回归：聊天中的"忽略规则/直接退款"文本只作为数据，风险不变、回复不被劫持、系统提示词固定。
- **发现的 B 阶段契约缺陷及修复**：`safety.reply_boundary` 的定责正则对"不推断物流或商家责任"这类隔字否定表述误判（S00001 主案例被误拒）。已修复 `backend/risk_empathy/safety.py` 否定窗口检测并重跑 Phase B 全部验证（RISK-C001–C004 仍 PASS），缺陷与回归证据登记于 C 验证报告 `contract_defects_found`。
- **未验证项**：Qwen 真实成功路径（环境中 `QWEN_API_KEY`/`DASHSCOPE_API_KEY` 为空），按规范记录"未验证"，未伪造。

## 三、阶段 D：客服工作台

新增 `backend/workbench/`（`server.py` + `state.py` + `static/index.html`），启动：`python -m backend.workbench --port 8765`。

- 真实接入：138 个会话全部来自真实 Excel 快照，队列风险由规则引擎实时计算；分析、工具请求/响应、Provider/Token/耗时/降级、安全校验全部来自真实 Agent 运行记录。
- UI-T001：三栏布局 + 消息回放（上一条/下一条/滑条/回到首条/点击可见消息）+ 三个时点入口（工单创建后/完成后用真实工单时间重算；完成时间为空即禁用并说明原因，S00024/S00001 已验证）。
- UI-T002：证据定位不改时点、工具抽屉展示同次运行的 Request/Response/source_refs/as_of/analysis_id/run_id、回复草稿按会话+时点隔离保存（revision/hash）、工单/人工升级为本地草稿（不调用第 9 个工具）。
- UI-T003：判断卡内紧凑状态入口，人工确认携带并校验 analysis_id/as_of_time/草稿 revision/draft_hash/幂等 operation_id；已验证 open→watching 接受、resolved 因待核验动作被拒（`pending_actions_block_resolve`）、异步旧分析被拒（`stale_analysis`）、旧草稿被拒（`stale_draft`）、P0 不得 resolved；处置日志 append-only。
- UI-T004：桌面 1440px 与窄屏 600px 截图、Esc/按钮关闭抽屉、消息气泡键盘可选时点、关键状态有文字不单靠颜色；`prototype/index.html` 静态基线保留未动。

## 四、阶段 E：评测与冻结

新增 `backend/eval_empathy/`，入口 `python -m backend.eval_empathy run` / `verify`。

- EVAL-T001：冻结 12（协议名单原样）+ 回归 10 + 开发 48（session_id 升序排除冻结/回归同买家会话后取前 48；同买家跨集隔离验证通过）；`intent_ontology_v1`（10 major + 41 minor 原字符串）；gold 盲于预测生成（意图为可见文本规则推导，scene_* 源字段仅冲突登记），split/gold/ontology 均有 sha256；冻结目标样本 46 个（与协议审计数一致）。
- EVAL-T002：四组（chat_only/snapshot/full_agent/rules_only）× 46 = 184 条逐样本配对运行；泄漏回归 0 泄漏（chat_only 上下文物理剥离订单/工单字段）。
- EVAL-T003：协议公式全实现（含 n/k/分子/分母/support、unclear 覆盖率与覆盖内严格准确率、安全覆盖率、missing_safety_check 计数、11 类固定错误类型 + first_error_step）；独立重算抽查与报告值完全一致（intent major Macro-F1、P0 recall、missing_safety_check）。
- EVAL-T004：JSON/CSV/Markdown 冻结报告 + boundary/retention 回归（Prompt 变化后冻结集 rules_only 结果逐字一致=retention PASS；回归案例受影响重跑=boundary PASS）。
- 关键数字（Mock 离线确定性模式）：轨迹关联 chat_only 0.5326 vs 其他组 1.0（信息范围消融真实）；P0 recall 1.0（13 个 gold P0 样本）；Mock 连续成功率 120/120。
- **如实登记的限制**：无 Qwen 凭证 → 模型组以 MockProvider 离线确定性运行，信息范围消融与程序侧指标真实，模型效果未验证；`fact_field_accuracy` 当前为 0（分析 facts 仅含订单/工单可见性事实、未展开字段级值，gold 侧已登记目标字段）——已在报告中作为已知限制登记，待字段级 facts 丰富后按 boundary/retention 流程复跑。

## 五、修改文件清单

- 新增：`backend/agent_empathy/`（8 文件）、`backend/workbench/`（5 文件，含 static/index.html）、`backend/eval_empathy/`（7 文件）
- 修改：`backend/risk_empathy/safety.py`（契约缺陷修复，附回归证据）；`方案文档/` 下 03/04/05 模块任务与验收、C/D/E 阶段计划（状态更新）
- 产物：`data/reports/agent_*`、`data/reports/workbench_phase_d_verification.json`、`data/reports/ui_evidence/*.png`(9)、`data/eval/**`、`data/runs/**`、`data/workbench/**`

## 六、尚未实现 / 未验证

1. Qwen 真实成功路径（无凭证，已按规范标记未验证；配置好 `QWEN_API_KEY` 后重跑 `python -m backend.agent_empathy verify` 与 `python -m backend.eval_empathy run` 即可切换为真实模型组）。
2. 字段级 facts 丰富化后的 fact_field_accuracy 复跑。
3. 阶段 F（PPT/视频/候选提交）未开始，属下一阶段。
