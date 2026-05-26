"""Tools for the Release Engineer agent."""
from __future__ import annotations
import subprocess
from langchain_core.tools import tool
from langgraph.types import interrupt
from sdlc_agent.config import DockerConfig
from sdlc_agent.mcp.git import LocalGitClient


def make_release_tools(git_client: LocalGitClient, docker_config: DockerConfig) -> list:

    @tool
    def git_merge_branch(feature_branch: str, target_branch: str = "main") -> dict:
        """Merge the approved feature branch into the target branch."""
        try:
            git_client._run("checkout", target_branch)
            git_client._run("merge", "--no-ff", feature_branch, "-m", f"Merge {feature_branch} into {target_branch}")
            return {"merged": True, "branch": feature_branch, "into": target_branch}
        except Exception as e:
            return {"merged": False, "error": str(e)}

    @tool
    def git_tag_release(tag: str, message: str) -> dict:
        """Create an annotated git release tag."""
        try:
            git_client._run("tag", "-a", tag, "-m", message)
            return {"tagged": True, "tag": tag}
        except Exception as e:
            return {"tagged": False, "error": str(e)}

    @tool
    def docker_build(context_path: str = ".", image_tag: str = "app:latest") -> dict:
        """Build the production Docker image."""
        try:
            result = subprocess.run(["docker", "build", "-t", image_tag, context_path],
                                    capture_output=True, text=True, timeout=300)
            return {"built": result.returncode == 0, "image": image_tag, "output": result.stdout[-500:]}
        except FileNotFoundError:
            return {"built": False, "error": "docker not found — running in dry-run mode"}
        except subprocess.TimeoutExpired:
            return {"built": False, "error": "docker build timed out"}

    @tool
    def run_smoke_tests(image_tag: str = "app:latest") -> dict:
        """Run smoke tests against the built Docker image."""
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", image_tag, "python", "-m", "pytest", "tests/smoke/", "-v"],
                capture_output=True, text=True, timeout=120)
            return {"passed": result.returncode == 0, "output": result.stdout[-500:]}
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"passed": False, "error": str(e)}

    @tool
    def generate_release_summary(feature_branch: str, issue_title: str,
                                  diff_stats: str, test_results: str, image_tag: str) -> str:
        """Generate a human-readable release summary for the approval gate."""
        return (f"## Release Summary\n\n**Issue:** {issue_title}\n**Branch:** {feature_branch}\n"
                f"**Image:** {image_tag}\n\n### Changes\n{diff_stats}\n\n### Test Results\n{test_results}\n")

    @tool
    def request_human_approval(summary: str) -> dict:
        """Present the release summary and wait for human approval. Triggers LangGraph interrupt."""
        human_response = interrupt({
            "type": "release_approval",
            "summary": summary,
            "prompt": 'Respond with {"approved": true/false, "reason": "..."}',
        })
        approved = human_response.get("approved", False)
        reason = human_response.get("reason", "No reason provided.")
        return {"approved": approved, "reason": reason}

    @tool
    def docker_deploy(image_tag: str = "app:latest", container_name: str = "sdlc-app-prod") -> dict:
        """Deploy the Docker image. Only call after human approval."""
        try:
            subprocess.run(["docker", "stop", container_name], capture_output=True)
            subprocess.run(["docker", "rm", container_name], capture_output=True)
            result = subprocess.run(["docker", "run", "-d", "--name", container_name, image_tag],
                                    capture_output=True, text=True, timeout=60)
            return {"deployed": result.returncode == 0, "container": container_name,
                    "deployment_url": f"docker://{container_name}"}
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"deployed": False, "error": str(e)}

    return [git_merge_branch, git_tag_release, docker_build, run_smoke_tests,
            generate_release_summary, request_human_approval, docker_deploy]
