"""DockerSandbox: wraps LocalSubprocessSandbox with optional Docker execution.

When use_docker=True, run() executes inside the named Docker image via
`docker run --rm -v host_root:container_workdir`. File I/O goes through the
host filesystem (mounted into the container).

Set use_docker=False for local development without Docker installed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sdlc_agent.sandbox.local import LocalSubprocessSandbox, SandboxError, SandboxResult


class DockerSandbox(LocalSubprocessSandbox):
    """LocalSubprocessSandbox with an optional Docker execution layer."""

    def __init__(
        self,
        root: Path,
        image: str,
        use_docker: bool = True,
        default_test_command: list[str] | None = None,
        default_timeout_seconds: int = 120,
        container_workdir: str = "/workspace",
    ) -> None:
        super().__init__(
            root=root,
            default_test_command=default_test_command or ["python", "-m", "pytest", "-v"],
            default_timeout_seconds=default_timeout_seconds,
        )
        self.image = image
        self.use_docker = use_docker
        self.container_workdir = container_workdir

    def run(self, command: list[str], *, timeout: int | None = None) -> SandboxResult:
        if not self.use_docker:
            return super().run(command, timeout=timeout)
        return self._docker_run(command, timeout=timeout or self.default_timeout_seconds)

    def _docker_run(self, command: list[str], timeout: int) -> SandboxResult:
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.root}:{self.container_workdir}",
            "-w", self.container_workdir,
            self.image,
            *command,
        ]
        try:
            completed = subprocess.run(
                docker_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise SandboxError(f"docker run timed out after {e.timeout}s") from e
        except FileNotFoundError as e:
            raise SandboxError("docker not found on PATH") from e
        return SandboxResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
