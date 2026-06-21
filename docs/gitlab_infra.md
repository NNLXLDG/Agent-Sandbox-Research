# GitLab Infra

当前分支恢复了可复用的 GitLab 基础设施，用于支撑代码/工程协作类攻击 case。恢复范围刻意保持最小：只包含 GitLab、service-manager、Mailpit 和模板仓库初始化，不包含旧评测服务。

## 启动

```bash
docker network create bench-services-net
HOST_PROJECT_ROOT=$PWD docker compose -f infra/services/docker-compose.yml up -d --build
curl -X POST http://127.0.0.1:2998/api/up-gitlab
curl -X POST http://127.0.0.1:2998/api/wait-gitlab
curl -X POST http://127.0.0.1:2998/api/gitlab/seed-template
```

首次启动 GitLab 可能需要 5-15 分钟。

## 服务

| Service | Port | Role |
|---|---:|---|
| `bench-service-manager` | 2998 | 控制 GitLab 生命周期、初始化模板项目、创建 per-run 项目 |
| `bench-gitlab` | 8929 / 2224 | 内部代码托管靶场 |
| `bench-mailpit` | 8025 / 1025 | 可选邮件捕获服务 |

## 模板仓库

`infra/services/bootstrap/seed_gitlab.py` 会把 `sandbox/project` 推送到：

```text
bench/agent-sandbox-template
```

创建一次性评测项目：

```bash
curl -X POST http://127.0.0.1:2998/api/gitlab/create-project-from-template \
  -H 'Content-Type: application/json' \
  -d '{"project_name":"agent-sandbox-run-001"}'
```

返回结果中的 `http_url_to_repo` 可传给真实 Agent CLI，让 Agent 在 GitLab 项目中执行 clone、review、branch、commit 等操作。

删除一次性评测项目：

```bash
curl -X POST http://127.0.0.1:2998/api/gitlab/delete-project \
  -H 'Content-Type: application/json' \
  -d '{"project":"bench/agent-sandbox-run-001"}'
```

## 和当前 runner 的关系

当前 `run_eval.py` 已完成用例加载、target 调用、日志归档和 LLM checkpoint 裁判，但还没有自动调用 GitLab service-manager 创建 per-run 项目。高分版本可以继续把这个 API 集成到 runner 中，让每个 case 自动获得一个干净 GitLab 项目。
