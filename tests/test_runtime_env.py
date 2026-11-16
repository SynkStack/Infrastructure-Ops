"""Runtime-mode validation of real environment variable values."""
import validate_config as vc
from conftest import REPO_ROOT, STRONG_SECRET


def run(env, values):
    return vc.validate_runtime_env(env, values, REPO_ROOT)


def test_valid_values_pass_for_every_environment(valid_runtime_env):
    for env in vc.ENVIRONMENTS:
        assert run(env, valid_runtime_env(env)) == [], env


def test_missing_variables_are_each_reported(valid_runtime_env):
    values = valid_runtime_env()
    for name in ("APP_ENV", "API_SECRET_KEY", "SESSION_SECRET"):
        del values[name]
    errors = run("production", values)
    assert any("APP_ENV is missing" in e for e in errors)
    assert any("secret API_SECRET_KEY is missing" in e for e in errors)
    assert any("secret SESSION_SECRET is missing" in e for e in errors)


def test_empty_value_counts_as_missing(valid_runtime_env):
    values = valid_runtime_env()
    values["APP_BASE_URL"] = "   "
    assert any("APP_BASE_URL is missing or empty" in e for e in run("production", values))


def test_placeholder_secret_is_rejected(valid_runtime_env):
    values = valid_runtime_env()
    values["API_SECRET_KEY"] = "change_me"
    assert any("still contains the placeholder" in e for e in run("production", values))


def test_short_secret_is_rejected_and_never_echoed(valid_runtime_env):
    values = valid_runtime_env()
    values["SESSION_SECRET"] = "short-one"
    errors = run("production", values)
    assert any("too short" in e for e in errors)
    assert "short-one" not in "\n".join(errors)


def test_strong_secrets_never_appear_in_any_output(valid_runtime_env):
    values = valid_runtime_env()
    values["APP_PORT"] = "bad"
    assert STRONG_SECRET not in "\n".join(run("production", values))


def test_wrong_app_env(valid_runtime_env):
    values = valid_runtime_env("staging")
    assert any("expected 'production'" in e for e in run("production", values))


def test_invalid_port_values(valid_runtime_env):
    for bad in ("80", "70000", "abc", "-1", "80.5"):
        values = valid_runtime_env()
        values["APP_PORT"] = bad
        assert any("APP_PORT" in e for e in run("production", values)), bad


def test_invalid_log_level(valid_runtime_env):
    values = valid_runtime_env()
    values["LOG_LEVEL"] = "verbose"
    assert any("LOG_LEVEL 'verbose' is invalid" in e for e in run("production", values))


def test_production_rejects_debug_http_and_local_urls(valid_runtime_env):
    values = valid_runtime_env()
    values["LOG_LEVEL"] = "debug"
    assert any("must not be 'debug'" in e for e in run("production", values))
    values = valid_runtime_env()
    values["APP_BASE_URL"] = "http://opssynk.example.com"
    assert any("must use https" in e for e in run("production", values))
    values["APP_BASE_URL"] = "https://localhost"
    assert any("local address" in e for e in run("production", values))


def test_garbage_url_is_rejected(valid_runtime_env):
    values = valid_runtime_env("development")
    values["APP_BASE_URL"] = "localhost8080"
    assert any("not a valid http(s) URL" in e for e in run("development", values))


def test_invalid_app_config_is_reported_instead_of_crashing(repo, valid_runtime_env):
    (repo / "config" / "production" / "app.yaml").write_text("app: [oops", encoding="utf-8")
    errors = vc.validate_runtime_env("production", valid_runtime_env(), repo)
    assert any("invalid YAML format" in e for e in errors)


def test_env_file_parsing(tmp_path):
    path = tmp_path / "prod.env"
    path.write_text('# comment\n\nA=1\nB="two words"\nC=\'x\'\n', encoding="utf-8")
    values, errors = vc.parse_env_file(path, tmp_path)
    assert errors == []
    assert values == {"A": "1", "B": "two words", "C": "x"}


def test_env_file_errors_have_line_numbers(tmp_path):
    path = tmp_path / "bad.env"
    path.write_text("GOOD=1\nthis is wrong\n9BAD=1\n", encoding="utf-8")
    values, errors = vc.parse_env_file(path, tmp_path)
    assert values is None
    assert errors == ["bad.env:2: invalid line, expected KEY=VALUE", "bad.env:3: invalid line, expected KEY=VALUE"]


def test_missing_env_file(tmp_path):
    values, errors = vc.parse_env_file(tmp_path / "nope.env", tmp_path)
    assert values is None and "file not found" in errors[0]
