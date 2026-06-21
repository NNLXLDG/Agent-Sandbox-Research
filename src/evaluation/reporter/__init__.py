"""Reporter helpers used by sandbox adapter runs."""

__all__ = ["ArtifactExporter"]


def __getattr__(name: str):
    if name == "ArtifactExporter":
        from evaluation.reporter.artifact_exporter import ArtifactExporter

        return ArtifactExporter
    raise AttributeError(name)
