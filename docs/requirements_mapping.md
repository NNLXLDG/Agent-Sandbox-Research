# PDF Requirements Mapping

本文件用于汇报时对照《课题 6：面向高级 Agent 的沙箱安全评测框架研究》的硬性要求和当前 demo 分支实现状态。

## 已达标

| PDF 要求 | 当前实现 |
|---|---|
| 基于 Docker 构建隔离沙箱环境 | `infra/sandbox/docker-compose.yml` 提供受限沙箱：internal network、只读 honeypot、`read_only`、`no-new-privileges`、`cap_drop: [ALL]`。 |
| 挂载工作区和诱饵数据 | `sandbox/project/` 提供真实项目文件；`sandbox/honeypot/` 提供伪造 API key、payroll 等蜜罐数据。 |
| 每个测试任务一个完整文件夹 | `cases/<attack_surface>/<case_id>/` 下包含 `case.yaml`、`prompt.txt`、`environment/`。 |
| 覆盖至少 3 到 5 种攻击面 | 当前覆盖 5 种：prompt injection、data exfiltration、command injection、persistence、social engineering。 |
| 不少于 10 个有效恶意 payload | 当前 25 个有效用例，每类攻击面 5 个。 |
| 每个用例定义预期安全/危险行为 | 每个 `case.yaml` 均包含 `expected.safe_behavior` 和 `expected.dangerous_behavior`。 |
| 一键式自动加载用例并发送给 Agent | `python3 -m sandbox_eval.run_eval -a openclaw -llm deepseek -c cmd-001` 自动加载、执行、判定、归档。 |
| 捕获对话输出和底层日志 | 每个 run 输出 `assistant.txt`、`stdout.log`、`stderr.log`、`container.log`、`conversation.json`。 |
| 自动判定攻击成功或被拦截 | `src/sandbox_eval/llm_judge.py` 使用 OpenAI-compatible LLM API，对每个 checkpoint 判定 `ok=true/false`。 |
| 自动生成结构化报告 | `summary.json` 和 `report.md` 统计总通过率、各攻击面失败数、逐 case 原因和 checkpoint 裁判理由。 |
| 支持安全闭环验证展示 | `docs/closure_plan.md` 给出修复前/修复后报告模板和 2 个高危缺陷闭环展示路径。 |

## 加分点

- 用例不是直接攻击口令，而是嵌入在 PR、CI 日志、供应商文档、runbook、事故聊天、支持工单、迁移说明等真实工作流材料中。
- 每个用例包含至少 1 个 case-specific LLM 判定点。简单攻击使用单一 case-level 判定点，复杂攻击再拆分来源边界、攻击识别、权限边界、工具安全、任务完成和证据透明性。
- 不保留本地规则/关键词裁判；如果没有配置 LLM 裁判，评测会明确失败，避免演示结果被简单规则误导。
- runner 支持 `-a hermes|openclaw` 和 `-llm`，可以把真实 Hermes/OpenClaw CLI 接入同一套用例和报告。

## 仍需现场补齐或说明

| 项目 | 当前状态 | 建议 |
|---|---|---|
| 真实 OpenClaw/Hermes 靶机 | runner 只支持 `-a hermes|openclaw`，默认命令可通过 `--hermes-cmd`、`--openclaw-cmd` 覆盖。 | 汇报前至少跑一次真实 Agent CLI，并保留 `reports/real-agent/summary.json`。 |
| GitLab 动态项目接入 runner | 已集成。每个 case 从同一个 `bench/agent-sandbox-template` 派生 fresh GitLab run project，并注入该 case 的 overlay。 | 汇报时展示 `reports/.../container.log` 中的 `source_template`、run project、overlay commit 和 cleanup 证据。 |
| Docker 动态重置 | 当前 compose 文件提供沙箱配置，runner 本身还没有自动 `docker compose down/up`。 | 若时间允许，在 runner 前后包一层脚本；否则汇报时说明沙箱可手动启动，评测主流程已自动化。 |
| 修复后对比报告 | 当前提供闭环模板，但没有真实 before/after 跑批产物。 | 选 `exfil-001` 和 `cmd-001` 跑修复前后两份报告，用作高分展示材料。 |
