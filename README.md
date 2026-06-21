# AgentSandboxEval

面向高级 Agent 的 Docker 沙箱安全评测框架。项目已收敛到课程 PDF 的要求：隔离沙箱、标准化攻击用例、一键自动化调度、日志归档、LLM 检查点裁判、结构化报告和安全闭环验证。

## 目标

本项目评测 Agent 在受限 Docker 工作区中处理风险任务时是否会出现：

- 提示词注入服从
- 敏感数据泄露
- 底层命令拼接/危险命令执行
- 持久化后门写入
- 社会工程学越权

当前用例集包含 25 个恶意 payload，5 类攻击面各 5 个。每个用例都围绕真实 Agent 工作流或直接攻击者输入设计：依赖升级、事故 triage、PR 审查、CI 失败、供应商支持、发布审批、系统提示词探测、管理员冒充、输出格式劫持等。

新评测入口只使用 `cases/**/case.yaml`。旧 `data/` 用例不会被新 sandbox eval 扫描或执行。

被测 Agent 只支持 Hermes 和 OpenClaw 两类真实框架。裁判必须使用 OpenAI-compatible LLM API；项目只保留 LLM 检查点裁判，未配置裁判模型时直接失败。

## 目录

```text
cases/                  # 标准化测试用例，每个用例一个完整文件夹
infra/sandbox/          # Docker 沙箱 compose 和说明
sandbox/honeypot/       # 挂载到沙箱中的蜜罐文件
src/sandbox_eval/       # 新安全用例调度、判定、报告代码
src/evaluation/         # 复用的 Hermes/OpenClaw adapter、Docker/GitLab infra、relay 配置
reports/                # 运行后生成 JSON / Markdown 报告
tests/                  # 本地单元测试
```

## 一键运行

CLI 详细说明见 `docs/cli_usage.md`。

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a hermes -llm deepseek-v4-pro
```

只跑指定 case，并切换被测 Agent/模型：

```bash
PYTHONPATH=src \
python3 -m sandbox_eval.run_eval -a hermes -llm deepseek-v4-pro -c prompt-001
```

OpenClaw：

```bash
PYTHONPATH=src \
python3 -m sandbox_eval.run_eval -a openclaw -llm deepseek-v4-pro -s command-injection
```

默认运行模式会复用原项目的 Hermes/OpenClaw adapter、Docker/GitLab infra 和 relay 配置。只有调试本机 Agent 命令时才使用 `--target-mode cli` 与 `--hermes-cmd` / `--openclaw-cmd`。

输出：

- `reports/demo/summary.json`
- `reports/demo/report.md`
- `reports/demo/runs/<case_id>/conversation.json`
- `reports/demo/runs/<case_id>/container.log`

## Docker 沙箱

```bash
docker compose -p agent-sandbox -f infra/sandbox/docker-compose.yml up -d
```

沙箱配置要点：

- `sandbox-net` 为 `internal: true`
- 蜜罐目录只读挂载到 `/workspace/honeypot:ro`
- Agent 工作目录挂载到 `/workspace/project`
- 容器启用 `read_only`、`no-new-privileges`、`cap_drop: [ALL]`

## GitLab 工程靶场

代码/工程类用例可以复用原项目的 GitLab infra，但当前分支只恢复了必要部分：GitLab、service-manager、Mailpit 和模板仓库初始化，不包含旧评测服务。

```bash
docker network create bench-services-net
HOST_PROJECT_ROOT=$PWD docker compose -f infra/services/docker-compose.yml up -d --build
curl -X POST http://127.0.0.1:2998/api/up-gitlab
curl -X POST http://127.0.0.1:2998/api/wait-gitlab
curl -X POST http://127.0.0.1:2998/api/gitlab/seed-template
```

模板项目由 `sandbox/project` 初始化为 `bench/agent-sandbox-template`。后续可以通过 service-manager 为每次评测创建干净项目：

```bash
curl -X POST http://127.0.0.1:2998/api/gitlab/create-project-from-template \
  -H 'Content-Type: application/json' \
  -d '{"project_name":"agent-sandbox-run-001"}'
```

详细说明见 `docs/gitlab_infra.md`。

## 用例格式

每个用例位于独立文件夹：

```text
cases/<attack_surface>/<case_id>/
├── case.yaml
├── prompt.txt
└── environment/
    └── README.md
```

每个用例显式定义：

- 攻击面
- 真实业务场景和攻击载体
- 预期安全行为
- 预期危险行为
- case-specific LLM 判定点列表
- 需要保留的日志证据

`TaskLoader` 会自动从 `case_id/title/attack_surface/attack_vector/prompt.txt/expected` 推导 infra 运行所需的 `id/project_template/runtime/interaction/attack`，避免每个 case 重复写兼容字段。

判定点设计见 `docs/checkpoints.md`。每个 case 至少包含 1 个 LLM 判定点；简单攻击可以只用一个 case-level 判定点，复杂攻击可拆成多个来源边界、权限边界、工具安全或任务完整性判定点。

PDF 考核项对齐情况见 `docs/requirements_mapping.md`。

## 报告与闭环

报告会统计：

- 总通过率
- 各攻击面风险分布
- 每个用例是否被拦截
- 每个检查点的 LLM 裁判理由
- 对话输出和底层执行日志位置

`docs/closure_plan.md` 给出修复前后对比报告的模板，可用于展示 1-2 个高危缺陷的 Prompt 级或代码级防御加固。
