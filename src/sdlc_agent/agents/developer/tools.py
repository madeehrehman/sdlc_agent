"""Tools for the Developer/Tester agent. All operate within the sandbox."""
from __future__ import annotations
import re
from langchain_core.tools import tool
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.sandbox.local import Sandbox


def make_developer_tools(sandbox: Sandbox, git_client: LocalGitClient) -> list:

    @tool
    def read_file(relative_path: str) -> str:
        """Read a file from the codebase."""
        return sandbox.read_file(relative_path)

    @tool
    def write_file(relative_path: str, content: str) -> dict:
        """Write content to a file in the codebase."""
        sandbox.write_file(relative_path, content)
        return {"written": relative_path}

    @tool
    def list_files(glob: str = "**/*.py") -> list[str]:
        """List files in the codebase matching a glob pattern."""
        return sandbox.list_files(glob)

    @tool
    def run_tests(test_command: list[str] | None = None) -> dict:
        """Run the test suite. Returns exit code, stdout, stderr."""
        result = sandbox.run_tests(test_command)
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr, "passed": result.ok}

    @tool
    def run_shell_command(command: list[str], timeout: int = 120) -> dict:
        """Run a shell command inside the sandbox."""
        result = sandbox.run(command, timeout=timeout)
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}

    @tool
    def search_codebase(pattern: str, file_glob: str = "**/*.py") -> list[str]:
        """Search for a pattern in codebase files. Returns matching lines."""
        matches = []
        for rel_path in sandbox.list_files(file_glob):
            try:
                content = sandbox.read_file(rel_path)
                for i, line in enumerate(content.splitlines(), 1):
                    if re.search(pattern, line):
                        matches.append(f"{rel_path}:{i}: {line.strip()}")
            except Exception:
                pass
        return matches

    @tool
    def git_create_branch(branch_name: str) -> dict:
        """Create and checkout a new git branch."""
        result = sandbox.run(["git", "checkout", "-b", branch_name])
        return {"branch": branch_name, "success": result.ok, "output": result.stdout}

    @tool
    def git_commit_all(message: str) -> dict:
        """Stage all changes and create a git commit."""
        committed = git_client.commit_all(message)
        sha_result = sandbox.run(["git", "rev-parse", "HEAD"])
        return {"committed": committed, "sha": sha_result.stdout.strip()}

    @tool
    def git_push(branch: str | None = None) -> dict:
        """Push the current branch to origin."""
        try:
            git_client.push_branch(branch)
            return {"pushed": True}
        except Exception as e:
            return {"pushed": False, "error": str(e)}

    return [read_file, write_file, list_files, run_tests, run_shell_command,
            search_codebase, git_create_branch, git_commit_all, git_push]
