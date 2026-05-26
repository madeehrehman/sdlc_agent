from sdlc_agent.docker.sandbox import DockerSandbox
from sdlc_agent.sandbox.local import SandboxResult


def test_docker_sandbox_falls_back_to_local(tmp_path):
    """Without Docker, DockerSandbox falls back to LocalSubprocessSandbox."""
    sandbox = DockerSandbox(root=tmp_path, image="sdlc-developer:latest", use_docker=False)
    sandbox.write_file("hello.txt", "world")
    content = sandbox.read_file("hello.txt")
    assert content == "world"


def test_docker_sandbox_run_local(tmp_path):
    sandbox = DockerSandbox(root=tmp_path, image="sdlc-developer:latest", use_docker=False)
    result = sandbox.run(["python", "-c", "print('hi')"])
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert "hi" in result.stdout
