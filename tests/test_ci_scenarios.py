"""End-to-end checks that run the scripts as subprocesses, exactly as CI invokes them,
and verify the CI workflow itself."""
import subprocess
import sys

import pytest
import yaml
from conftest import REPO_ROOT, SCRIPTS

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def run_script(name, root, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---- CLI behaviour as CI sees it ------------------------------------------------------


@pytest.mark.parametrize("script", ["validate_config.py", "check_docs.py"])
def test_scripts_exit_zero_on_valid_repo(repo, script):
    result = run_script(script, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout and "[FAIL]" not in result.stdout


def test_ci_fails_on_missing_required_key(repo, edit_config):
    edit_config(repo, "production", lambda d: d["app"].pop("base_url"))
    result = run_script("validate_config.py", repo)
    assert result.returncode == 1
    assert "[FAIL] production: config/production/app.yaml" in result.stdout
    assert "base_url" in result.stdout and "FAILED" in result.stdout


def test_ci_fails_on_invalid_value(repo, edit_config):
    edit_config(repo, "staging", lambda d: d["app"].update(port=22))
    result = run_script("validate_config.py", repo)
    assert result.returncode == 1 and "app.port" in result.stdout


def test_ci_fails_on_invalid_yaml(repo):
    (repo / "config" / "development" / "app.yaml").write_text("environment: [", encoding="utf-8")
    result = run_script("validate_config.py", repo)
    assert result.returncode == 1 and "invalid YAML format" in result.stdout


def test_ci_fails_when_a_real_env_file_is_present(repo):
    (repo / ".env").write_text("API_SECRET_KEY=abc\n", encoding="utf-8")
    result = run_script("validate_config.py", repo)
    assert result.returncode == 1 and "real environment file" in result.stdout


def test_ci_fails_on_missing_documentation(repo):
    (repo / "docs" / "rollback.md").unlink()
    result = run_script("check_docs.py", repo)
    assert result.returncode == 1
    assert "docs/rollback.md: required documentation file is missing" in result.stdout


def test_one_failure_does_not_hide_others(repo, edit_config):
    edit_config(repo, "staging", lambda d: d["app"].update(port=22))
    edit_config(repo, "production", lambda d: d["app"].update(debug=True))
    out = run_script("validate_config.py", repo).stdout
    assert "app.port" in out and "app.debug must be false" in out


def test_runtime_mode_cli(repo, tmp_path, valid_runtime_env):
    good = tmp_path / "good.env"
    good.write_text("\n".join(f"{k}={v}" for k, v in valid_runtime_env().items()) + "\n", encoding="utf-8")
    assert run_script("validate_config.py", repo, "--runtime-env", "production", "--env-file", str(good)).returncode == 0

    bad = tmp_path / "bad.env"
    bad.write_text("APP_ENV=production\nAPI_SECRET_KEY=CHANGE_ME\n", encoding="utf-8")
    result = run_script("validate_config.py", repo, "--runtime-env", "production", "--env-file", str(bad))
    assert result.returncode == 1
    assert "SESSION_SECRET is missing" in result.stdout and "placeholder" in result.stdout


def test_runtime_mode_reads_process_environment(repo, valid_runtime_env):
    import os

    env = {**os.environ, **valid_runtime_env("staging")}
    ok = subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_config.py"), "--root", str(repo), "--runtime-env", "staging"],
        capture_output=True, text=True, env=env,
    )
    assert ok.returncode == 0, ok.stdout


def test_cli_output_is_ascii_for_windows_consoles(repo, edit_config):
    edit_config(repo, "staging", lambda d: d["app"].update(port=22))
    for script in ("validate_config.py", "check_docs.py"):
        run_script(script, repo).stdout.encode("ascii")


def test_scripts_run_with_default_root():
    for script in ("validate_config.py", "check_docs.py"):
        result = subprocess.run([sys.executable, str(SCRIPTS / script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout


# ---- the workflow file itself ----------------------------------------------------------


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_triggers_on_push_and_pull_request(workflow):
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads the bare key `on` as True
    assert "push" in triggers and "pull_request" in triggers


def test_workflow_has_least_privilege_permissions(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_workflow_runs_every_check_in_order(workflow):
    steps = next(iter(workflow["jobs"].values()))["steps"]
    commands = [s["run"] for s in steps if "run" in s]
    expected = [
        "python scripts/validate_config.py",
        "python scripts/check_docs.py",
        "python -m pytest",
    ]
    positions = [commands.index(c) for c in expected]
    assert positions == sorted(positions)


def test_workflow_references_existing_scripts_and_requirements(workflow):
    text = WORKFLOW.read_text(encoding="utf-8")
    for path in ("scripts/validate_config.py", "scripts/check_docs.py", "requirements.txt"):
        assert path in text and (REPO_ROOT / path).is_file()


def test_workflow_does_not_continue_on_error(workflow):
    steps = next(iter(workflow["jobs"].values()))["steps"]
    assert not any(s.get("continue-on-error") for s in steps)
