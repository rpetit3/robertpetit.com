"""Guard the Cloudflare Pages deploy surface.

Pages reads `_headers` and `_redirects` from the build output and routes
Functions from `functions/` at the repo root. Renaming any of them silently
drops the security headers, the legacy redirect, or the CSP report endpoint, so
pin all three plus the workflow wiring.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "static"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
PROJECT = "robertpetit-com"


def steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def step(name: str) -> dict:
    return next(step for step in steps() if step.get("name") == name)


def header_blocks() -> dict[str, dict[str, str]]:
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in (STATIC / "_headers").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            current = blocks.setdefault(line.strip(), {})
            continue
        assert current is not None, f"header before a path: {line}"
        name, _, value = line.strip().partition(":")
        current[name.lower()] = value.strip()
    return blocks


def redirects() -> list[list[str]]:
    return [
        line.split()
        for line in (STATIC / "_redirects").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_every_path_gets_the_security_headers() -> None:
    block = header_blocks().get("/*", {})
    for name in (
        "access-control-allow-origin",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy-report-only",
    ):
        assert block.get(name), f"{name} missing from /*"


def test_pages_dev_hosts_are_noindex() -> None:
    blocks = header_blocks()
    for pattern in ("https://:project.pages.dev/*", "https://:version.:project.pages.dev/*"):
        assert blocks.get(pattern, {}).get("x-robots-tag") == "noindex"


def test_csp_reports_reach_the_function() -> None:
    assert "report-uri /csp-report" in header_blocks()["/*"]["content-security-policy-report-only"]
    handler = (ROOT / "functions" / "csp-report.mjs").read_text()
    assert "onRequest" in handler


def test_old_about_page_redirects() -> None:
    assert ["/about/about*", "/about/", "301"] in redirects()


def test_no_catch_all_shadows_real_pages() -> None:
    """Pages follows redirects even when an asset matches."""
    assert all(rule[0] != "/*" for rule in redirects())
    assert all(rule[2:] != ["200"] for rule in redirects())


def test_netlify_config_is_gone() -> None:
    assert not (ROOT / "netlify.toml").exists()
    assert not (ROOT / "netlify").exists()


def test_deploy_targets_the_pages_project() -> None:
    command = step("Deploy")["with"]["command"]
    assert command == (
        "pages deploy public/ --project-name=robertpetit-com --branch=main --commit-dirty=true"
    )


def test_deploy_uses_the_repository_secrets() -> None:
    send = step("Deploy")["with"]
    assert send["apiToken"] == "${{ secrets.CLOUDFLARE_API_TOKEN }}"
    assert send["accountId"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"


def test_checkout_fetches_the_theme_and_pdfs() -> None:
    checkout = step("Checkout")["with"]
    assert checkout["submodules"] == "recursive"
    assert checkout["lfs"] is True


def test_checks_and_tests_gate_the_deploy() -> None:
    names = [entry.get("name") for entry in steps()]
    deploy = names.index("Deploy")
    for required in ("Lint workflows", "Test", "Build"):
        assert names.index(required) < deploy
    runs = " ".join(entry["run"] for entry in steps() if "run" in entry)
    assert "actionlint" in runs
    assert "pytest" in runs


def test_deploy_guards_the_pages_limits() -> None:
    runs = " ".join(entry["run"] for entry in steps() if "run" in entry)
    assert "19000" in runs
    assert "-size +25M" in runs


def test_deploy_creates_the_project_if_missing() -> None:
    names = [entry.get("name") for entry in steps()]
    guard = step("Ensure the Pages project exists")
    assert names.index(guard["name"]) < names.index("Deploy")
    assert "github.ref == 'refs/heads/main'" in guard["if"]
    assert 'pages project create robertpetit-com --production-branch main' in guard["run"]
    assert "PROJECT=" not in guard["run"]
    assert "already exists" in guard["run"]
    assert step("Deploy")["with"]["wranglerVersion"] == "3.90.0"


def test_deploy_runs_only_on_main() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]