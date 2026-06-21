# GitLab Service

This directory marks GitLab as an optional infrastructure service for the Agent sandbox evaluation.

GitLab is used to make code-oriented cases more realistic:

- host the sandbox project as a real repository
- support clone / branch / commit / push workflows
- provide a place to model issues, merge requests, labels, and CI artifacts later

Runtime control lives in:

```text
infra/services/manager/
infra/services/bootstrap/seed_gitlab.py
```

The restored service is intentionally small. It keeps GitLab, service-manager, Mailpit, and the shared service network, but does not restore unrelated legacy services.
