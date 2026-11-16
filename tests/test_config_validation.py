"""Repository-mode validation of app.yaml files, templates and cross-environment rules."""
import pytest
from conftest import REPO_ROOT

import validate_config as vc


def errors_for(env, root):
    data, errors = vc.validate_app_config(env, root)
    return data, errors


# ---- valid configuration -------------------------------------------------------------


@pytest.mark.parametrize("env", vc.ENVIRONMENTS)
def test_real_environment_config_is_valid(env):
    data, errors = errors_for(env, REPO_ROOT)
    assert errors == []
    assert data["environment"] == env


def test_all_repository_checks_pass_on_real_repo():
    checks = vc.run_repository_checks(REPO_ROOT)
    failures = {c.name: c.errors for c in checks if not c.ok}
    assert failures == {}


# ---- missing required values ---------------------------------------------------------


@pytest.mark.parametrize(
    "section,key",
    [("app", "base_url"), ("app", "port"), ("deployment", "health_check_path"), ("secrets", "required_env_vars")],
)
def test_missing_required_key_is_reported(repo, edit_config, section, key):
    edit_config(repo, "staging", lambda d: d[section].pop(key))
    data, errors = errors_for("staging", repo)
    assert data is None
    assert any(key in e and "required" in e for e in errors), errors


def test_missing_config_file_is_reported(repo):
    (repo / "config" / "production" / "app.yaml").unlink()
    _, errors = errors_for("production", repo)
    assert errors == ["config/production/app.yaml: file not found"]


def test_missing_top_level_section_is_reported(repo, edit_config):
    edit_config(repo, "development", lambda d: d.pop("deployment"))
    _, errors = errors_for("development", repo)
    assert any("deployment" in e for e in errors)


# ---- invalid values ------------------------------------------------------------------


@pytest.mark.parametrize(
    "change,expected",
    [
        (lambda d: d["app"].update(port=80), "app.port"),
        (lambda d: d["app"].update(port="8080"), "app.port"),
        (lambda d: d["app"].update(log_level="verbose"), "app.log_level"),
        (lambda d: d["app"].update(base_url="not a url"), "app.base_url"),
        (lambda d: d["app"].update(name="Bad Name"), "app.name"),
        (lambda d: d["deployment"].update(health_check_path="healthz"), "health_check_path"),
        (lambda d: d["secrets"].update(required_env_vars=["lowercase"]), "required_env_vars"),
        (lambda d: d.update(unknown_key=True), "unknown_key"),
    ],
)
def test_invalid_values_are_reported_with_location(repo, edit_config, change, expected):
    edit_config(repo, "staging", change)
    data, errors = errors_for("staging", repo)
    assert data is None
    assert any(expected in e and e.startswith("config/staging/app.yaml") for e in errors), errors


def test_environment_must_match_directory(repo, edit_config):
    edit_config(repo, "staging", lambda d: d.update(environment="production"))
    _, errors = errors_for("staging", repo)
    assert any("lives in config/staging/" in e for e in errors)


@pytest.mark.parametrize(
    "change,expected",
    [
        (lambda d: d["app"].update(debug=True), "app.debug must be false"),
        (lambda d: d["app"].update(log_level="debug"), "must not be 'debug'"),
        (lambda d: d["app"].update(base_url="http://opssynk.example.com"), "must use https"),
        (lambda d: d["app"].update(base_url="https://localhost"), "local address"),
        (lambda d: d["deployment"].update(require_approval=False), "require_approval must be true"),
        (lambda d: d["deployment"].update(keep_previous_releases=1), "at least 3"),
    ],
)
def test_production_rules_are_enforced(repo, edit_config, change, expected):
    edit_config(repo, "production", change)
    _, errors = errors_for("production", repo)
    assert any(expected in e for e in errors), errors


def test_staging_rejects_local_address(repo, edit_config):
    edit_config(repo, "staging", lambda d: d["app"].update(base_url="https://127.0.0.1:8080"))
    _, errors = errors_for("staging", repo)
    assert any("local address" in e for e in errors)


def test_development_allows_localhost_and_debug():
    data, errors = errors_for("development", REPO_ROOT)
    assert errors == []
    assert data["app"]["debug"] is True


# ---- invalid file format -------------------------------------------------------------


def test_malformed_yaml_is_reported(repo):
    (repo / "config" / "staging" / "app.yaml").write_text("app: [unclosed\n  key: : :", encoding="utf-8")
    data, errors = errors_for("staging", repo)
    assert data is None
    assert len(errors) == 1 and "invalid YAML format" in errors[0]


def test_yaml_that_is_not_a_mapping_is_reported(repo):
    (repo / "config" / "staging" / "app.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    _, errors = errors_for("staging", repo)
    assert any("must be a mapping" in e for e in errors)


def test_invalid_schema_file_is_reported(repo):
    (repo / "config" / "schema" / "config.schema.json").write_text("{ not json", encoding="utf-8")
    _, errors = errors_for("staging", repo)
    assert any("invalid JSON" in e for e in errors)


def test_missing_schema_file_is_reported(repo):
    (repo / "config" / "schema" / "config.schema.json").unlink()
    _, errors = errors_for("staging", repo)
    assert any("schema file not found" in e for e in errors)


# ---- .env.example templates ----------------------------------------------------------


def template_errors(repo, env="staging"):
    secrets = ["API_SECRET_KEY", "SESSION_SECRET"]
    return vc.validate_env_template(env, repo / "config" / env / ".env.example", secrets, repo)


@pytest.mark.parametrize("env", vc.ENVIRONMENTS)
def test_real_templates_are_valid(env):
    assert template_errors(REPO_ROOT, env) == []


def test_template_missing_variable(repo):
    path = repo / "config" / "staging" / ".env.example"
    lines = [l for l in path.read_text().splitlines() if not l.startswith("SESSION_SECRET")]
    path.write_text("\n".join(lines) + "\n")
    assert any("missing variable(s): SESSION_SECRET" in e for e in template_errors(repo))


def test_template_unexpected_variable(repo):
    path = repo / "config" / "staging" / ".env.example"
    path.write_text(path.read_text() + "EXTRA_SETTING=1\n")
    assert any("unexpected variable(s): EXTRA_SETTING" in e for e in template_errors(repo))


def test_template_with_real_secret_is_rejected_without_echoing_it(repo):
    path = repo / "config" / "production" / ".env.example"
    real = "sup3r-secret-value-that-must-not-leak"
    path.write_text(path.read_text().replace("API_SECRET_KEY=CHANGE_ME", f"API_SECRET_KEY={real}"))
    errors = template_errors(repo, "production")
    assert any("API_SECRET_KEY must be CHANGE_ME" in e for e in errors)
    assert real not in "\n".join(errors)


def test_template_invalid_line_format(repo):
    path = repo / "config" / "staging" / ".env.example"
    path.write_text(path.read_text() + "this line is not valid\n")
    assert any("invalid line, expected KEY=VALUE" in e for e in template_errors(repo))


def test_template_duplicate_variable(repo):
    path = repo / "config" / "staging" / ".env.example"
    path.write_text(path.read_text() + "LOG_LEVEL=info\n")
    assert any("duplicate variable LOG_LEVEL" in e for e in template_errors(repo))


def test_template_wrong_app_env(repo):
    path = repo / "config" / "staging" / ".env.example"
    path.write_text(path.read_text().replace("APP_ENV=staging", "APP_ENV=production"))
    assert any("APP_ENV is 'production' but expected 'staging'" in e for e in template_errors(repo))


def test_production_template_with_debug_log_level(repo):
    path = repo / "config" / "production" / ".env.example"
    path.write_text(path.read_text().replace("LOG_LEVEL=warning", "LOG_LEVEL=debug"))
    assert any("must not be 'debug' in production" in e for e in template_errors(repo, "production"))


# ---- cross-environment and repository hygiene ----------------------------------------


def test_secret_names_must_match_across_environments(repo, edit_config):
    edit_config(repo, "production", lambda d: d["secrets"]["required_env_vars"].append("EXTRA_TOKEN"))
    checks = {c.name: c for c in vc.run_repository_checks(repo)}
    assert any("differ between environments" in e for e in checks["cross-environment consistency"].errors)


def test_staging_and_production_must_not_share_url(repo, edit_config):
    url = "https://shared.opssynk.example.com"
    edit_config(repo, "production", lambda d: d["app"].update(base_url=url))
    edit_config(repo, "staging", lambda d: d["app"].update(base_url=url))
    checks = {c.name: c for c in vc.run_repository_checks(repo)}
    assert any("same app.base_url" in e for e in checks["cross-environment consistency"].errors)


def test_real_env_file_is_detected(repo):
    (repo / "config" / "production" / ".env").write_text("API_SECRET_KEY=x\n")
    assert any("real environment file" in e for e in vc.find_real_env_files(repo))
    (repo / ".env.local").write_text("A=b\n")
    assert len(vc.find_real_env_files(repo)) == 2


def test_committed_credential_patterns_are_detected(repo):
    (repo / "docs" / "notes.md").write_text("key: AKIAABCDEFGHIJKLMNOP\n")
    errors = vc.scan_for_secrets(repo)
    assert any("AWS access key id" in e for e in errors)
    (repo / "docs" / "notes.md").write_text("-----BEGIN RSA PRIVATE KEY-----\n")
    assert any("private key block" in e for e in vc.scan_for_secrets(repo))


def test_clean_repo_has_no_secret_findings():
    assert vc.scan_for_secrets(REPO_ROOT) == []
    assert vc.find_real_env_files(REPO_ROOT) == []
