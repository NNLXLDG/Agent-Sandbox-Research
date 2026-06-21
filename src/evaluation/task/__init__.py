"""Task domain: models, YAML loader."""

__all__ = [
    "Task",
    "TaskMeta",
    "AttackMeta",
    "Round",
    "TurnResult",
    "SetupResult",
    "TaskLoader",
]


def __getattr__(name: str):
    if name == "TaskLoader":
        from evaluation.task.loader import TaskLoader

        return TaskLoader
    if name in {
        "Task",
        "TaskMeta",
        "AttackMeta",
        "Round",
        "TurnResult",
        "SetupResult",
    }:
        from evaluation.task import models

        return getattr(models, name)
    raise AttributeError(name)
