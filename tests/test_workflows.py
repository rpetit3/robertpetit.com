"""Guard workflow wiring that only breaks inside GitHub Actions.

Two failure modes cost a full debugging round: a non-login shell silently
skips conda activation, and `read` over a process substitution dies at EOF
under the runner's `bash -e`. Both exit non-zero with no useful output.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CONDA_WORKFLOWS = ["update-data.yml", "sync-publications.yml"]


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def steps(name: str) -> list[dict]:
    return [step for job in load(name)["jobs"].values() for step in job["steps"]]


def run_scripts(name: str) -> list[str]:
    return [step["run"] for step in steps(name) if "run" in step]


@pytest.mark.parametrize("name", CONDA_WORKFLOWS)
def test_conda_workflows_use_a_login_shell(name: str) -> None:
    shell = load(name)["defaults"]["run"]["shell"]
    program, flags, _ = shell.split()
    assert program == "bash"
    assert "l" in flags.lstrip("-")


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_no_read_over_process_substitution(path: Path) -> None:
    offenders = [
        script
        for script in (step["run"] for step in steps(path.name) if "run" in step)
        if re.search(r"^\s*read\b.*< <\(", script, re.MULTILINE)
    ]
    assert not offenders, "read returns 1 at EOF; prefix with `|| true` or use $(...)"


def test_issue_reporters_know_the_repo() -> None:
    reporters = [step for step in steps("site-health.yml") if step.get("name", "").startswith("Report ")]
    assert len(reporters) == 2
    for step in reporters:
        assert step["env"]["GH_REPO"] == "${{ github.repository }}"


def test_conda_workflows_activate_the_declared_env() -> None:
    for name in CONDA_WORKFLOWS:
        setup = [step for step in steps(name) if "setup-miniconda" in step.get("uses", "")]
        assert setup and setup[0]["with"]["activate-environment"] == "ctx-robertpetit.com-1-dev"