# CLI Usage

## 环境变量

LLM 裁判默认会读取：

```text
.secrets/relay/relay.env
```

如果需要临时覆盖，再手动设置：

```bash
export EVAL_LLM_API_KEY=...
export EVAL_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
export EVAL_LLM_MODEL=gemini-3.1-flash-lite
```

`-llm deepseek` 会使用 `.secrets/relay/relay.env` 中的 `DEEPSEEK_MODEL`。
`-llm chatgpt` 或 `-llm gpt` 会使用同一文件中的 `CHATGPT_MODEL`。
`-llm gemini` 会使用同一文件中的 `GEMINI_MODEL`。
`-llm mimo` 会使用同一文件中的 `MIMO_MODEL`。
裁判模型固定由同一文件里的 `EVAL_LLM_MODEL`、`EVAL_LLM_API_KEY`、`EVAL_LLM_BASE_URL` 控制；当前已配置为 Gemini 3.1 Flash Lite。`-llm` 只切换被测 Agent 模型，不切换裁判。

## 全量运行

OpenClaw：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm deepseek
```

OpenClaw 修复前后对比：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval \
  -a openclaw \
  -llm deepseek \
  --report-dir reports/closure-openclaw-deepseek-baseline
```

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval \
  -a openclaw \
  -llm deepseek \
  --defense-profile openclaw-prompt-hardening \
  --report-dir reports/closure-openclaw-deepseek-hardened
```

第一条是原始版本，第二条只在发送给 Agent 的任务前追加 Prompt 级安全加固策略。case 文件、环境文件和裁判模型保持一致，用于证明“修复前/修复后”的安全闭环。

切换 ChatGPT 兼容模型：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm chatgpt
```

切换 Gemini Agent 模型：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm gemini
```

切换 MIMO Agent 模型：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm mimo
```

Hermes：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a hermes -llm deepseek
```

## 指定 Case

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm deepseek -c cmd-001
```

多个 case：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm deepseek -c cmd-001,cmd-002
```

## 指定攻击面

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a hermes -llm deepseek -s command-injection
```

可用攻击面：

```text
prompt-injection
data-exfiltration
command-injection
persistence
social-engineering
```

## 输出目录

默认输出到：

```text
reports/demo/
```

指定输出目录：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval -a openclaw -llm deepseek -c cmd-001 --report-dir reports/openclaw-cmd-001
```

主要产物：

```text
summary.json
report.md
runs/<case_id>/conversation.json
runs/<case_id>/judge/request.json
runs/<case_id>/judge/response.json
```

## 运行模式

默认运行模式是：

```text
--target-mode infra
```

这个模式直接复用 Hermes/OpenClaw adapter、Docker 容器、relay 配置和运行 artifact 导出。当前 `cases/**/case.yaml` 已经兼容 infra task schema，会作为一等 case 输入；不会包装成旧的 `task.yaml`，也不会扫描 `data/` 里的旧用例。

需要快速调试本机 CLI 时才使用：

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval \
  -a hermes \
  -llm deepseek \
  -c prompt-001 \
  --target-mode cli \
  --hermes-cmd 'hermes run --model {model}'
```

```bash
PYTHONPATH=src python3 -m sandbox_eval.run_eval \
  -a openclaw \
  -llm deepseek \
  -c prompt-001 \
  --target-mode cli \
  --openclaw-cmd 'openclaw run --model {model}'
```

## 常用参数

| 参数 | 含义 |
|---|---|
| `-a` | Agent 框架：`hermes` 或 `openclaw` |
| `-llm` | Agent 模型别名；裁判模型由 `EVAL_LLM_*` 单独控制 |
| `-c` | 指定 case id |
| `-s` | 指定攻击面 |
| `--target-mode` | `infra` 复用原 Docker/GitLab/Agent adapter；`cli` 仅用于本机调试 |
| `--report-dir` | 指定报告输出目录 |
| `--timeout` | 单个 case 超时时间 |
| `--keep-container` | infra 模式下保留容器用于调试 |
| `--keep-report-dir` | 不清空已有报告目录 |
| `--defense-profile` | Prompt 级加固配置；默认 `none`，演示安全闭环时使用 `openclaw-prompt-hardening` |
