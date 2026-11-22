"""Exercise the CSP report handler on the Workers runtime semantics it needs.

The function runs as a Pages Function, so a POST body must be drained into the
log while every other method answers 204 without touching the body.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HANDLER = Path(__file__).parents[1] / "functions" / "csp-report.mjs"

DRIVER = """
import {{ onRequest }} from "{target}";
const logged = [];
console.log = (...args) => logged.push(args.join(" "));
const request = new Request("https://www.robertpetit.com/csp-report", {{
  method: {method},
  body: {body},
}});
const response = await onRequest({{ request }});
process.stdout.write(JSON.stringify({{ status: response.status, logged }}));
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run(tmp_path: Path, method: str, body: str | None = None) -> dict:
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        DRIVER.format(
            target=HANDLER.as_uri(),
            method=json.dumps(method),
            body=json.dumps(body),
        )
    )
    result = subprocess.run(["node", str(driver)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_post_is_logged_and_acknowledged(tmp_path: Path) -> None:
    outcome = run(tmp_path, "POST", '{"blocked-uri":"https://example.com"}')
    assert outcome["status"] == 204
    assert any("csp-report" in line for line in outcome["logged"])


def test_the_report_body_reaches_the_log(tmp_path: Path) -> None:
    outcome = run(tmp_path, "POST", "blocked-uri")
    assert any("blocked-uri" in line for line in outcome["logged"])


def test_other_methods_do_not_log(tmp_path: Path) -> None:
    outcome = run(tmp_path, "GET")
    assert outcome["status"] == 204
    assert outcome["logged"] == []