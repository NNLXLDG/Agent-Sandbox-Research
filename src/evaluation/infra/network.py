"""Network discovery helpers used by adapters that need to find relay networks."""
from __future__ import annotations

from typing import Optional

from evaluation.config.constants import RELAY_NETWORK_NAME, SERVICES_NETWORK_NAME
from evaluation.infra.docker import DockerClient
from evaluation.infra.shell import ShellExecutor


class NetworkInspector:
    def __init__(self, shell: Optional[ShellExecutor] = None, docker: Optional[DockerClient] = None) -> None:
        self.shell = shell or ShellExecutor()
        self.docker = docker or DockerClient(self.shell)

    def list_networks(self) -> list[str]:
        result = self.shell.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"], timeout=30,
        )
        if not result.ok:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def discover_relay_networks(self) -> list[str]:
        """Return non-default networks suitable for routing relay traffic."""
        names: list[str] = []
        for name in self.list_networks():
            if not name or name == RELAY_NETWORK_NAME:
                continue
            if name == SERVICES_NETWORK_NAME or name.endswith("_relay-egress"):
                names.append(name)
        return names

    def container_networks(self, container: str) -> list[str]:
        result = self.docker.inspect(
            container, "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}",
        )
        if not result.ok:
            return []
        return [n for n in result.stdout.strip().split() if n]

    def network_exists(self, name: str) -> bool:
        result = self.shell.run(
            ["docker", "network", "ls", "--filter", f"name=^{name}$", "--format", "{{.Name}}"],
            timeout=30,
        )
        return name in (result.stdout or "").splitlines()

    def connect(self, network: str, container: str) -> bool:
        result = self.shell.run(
            ["docker", "network", "connect", network, container], timeout=30,
        )
        if result.ok:
            return True
        # "already exists" is benign.
        combined = (result.stderr or "") + (result.stdout or "")
        return "already exists" in combined
