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
CONDA_WORKFLOWS = ["ci.yml", "deploy.yml", "update-data.yml", "sync-publications.yml"]


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


def test_gate_covers_every_non_fatal_step() -> None:
    """A step the gate inspects must not abort the job, and vice versa."""
    workflow = steps("update-data.yml")
    optional = {step["id"] for step in workflow if step.get("continue-on-error") is True and step.get("id")}
    gate = next(step for step in workflow if step.get("name") == "Fail on a failed source")
    gated = set(re.findall(r"steps\.(\w+)\.outcome", gate["run"]))
    assert optional
    assert gated == optional


def test_ci_runs_checks_and_tests_on_pull_requests() -> None:
    """The deploy is main-only, so PRs must still gate a merge."""
    workflow = load("ci.yml")
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" in triggers
    runs = " ".join(run_scripts("ci.yml"))
    assert "actionlint" in runs
    assert "pytest" in runs