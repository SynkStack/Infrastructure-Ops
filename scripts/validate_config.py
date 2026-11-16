#!/usr/bin/env python3
"""Validate environment configuration for the Infrastructure-Ops repository.

Two modes:

  Repository mode (default, used by CI):
      python scripts/validate_config.py
    Validates config/<env>/app.yaml against the JSON Schema, applies
    environment-specific rules, checks every .env.example template, checks
    consistency across environments, and scans for committed secrets.

  Runtime mode (used by an operator before a deploy):
      python scripts/validate_config.py --runtime-env production --env-file .env.production
    Validates real environment variable values, from a file or from the current
    process environment. Secret values are never printed.

Exit code is 0 when everything is valid and 1 otherwise.
Works on Windows, macOS and Linux with Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator

ENVIRONMENTS = ("development", "staging", "production")
LOG_LEVELS = ("debug", "info", "warning", "error")
BASE_ENV_VARS = ("APP_ENV", "LOG_LEVEL", "APP_PORT", "APP_BASE_URL")
PLACEHOLDER = "CHANGE_ME"
MIN_SECRET_LENGTH = 16
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
SCHEMA_PATH = Path("config") / "schema" / "config.schema.json"
ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

# Patterns for credentials that must never appear in committed config or docs.
SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


@dataclass
class Check:
    """Result of one named validation step."""

    name: str
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------------------- loading


def load_yaml(path: Path, root: Path) -> tuple[dict | None, list[str]]:
    name = rel(path, root)
    if not path.is_file():
        return None, [f"{name}: file not found"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")
        return None, [f"{name}: invalid YAML format ({detail})"]
    if not isinstance(data, dict):
        return None, [f"{name}: top level must be a mapping of keys to values"]
    return data, []


def load_schema(root: Path) -> tuple[dict | None, list[str]]:
    path = root / SCHEMA_PATH
    if not path.is_file():
        return None, [f"{rel(path, root)}: schema file not found"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as exc:
        return None, [f"{rel(path, root)}: invalid JSON ({exc})"]


def parse_env_file(path: Path, root: Path) -> tuple[dict[str, str] | None, list[str]]:
    """Parse KEY=VALUE lines. Blank lines and # comments are ignored."""
    name = rel(path, root)
    if not path.is_file():
        return None, [f"{name}: file not found"]
    values: dict[str, str] = {}
    errors: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE.match(line)
        if not match:
            errors.append(f"{name}:{number}: invalid line, expected KEY=VALUE")
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key in values:
            errors.append(f"{name}:{number}: duplicate variable {key}")
        values[key] = value
    return (None if errors else values), errors


# ------------------------------------------------------------------ app.yaml checks


def _url_problems(url: str, require_https: bool, forbid_local: bool) -> list[str]:
    parsed = urlparse(url)
    problems: list[str] = []
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return [f"'{url}' is not a valid http(s) URL"]
    if require_https and parsed.scheme != "https":
        problems.append(f"'{url}' must use https")
    if forbid_local and parsed.hostname in LOCAL_HOSTS:
        problems.append(f"'{url}' must not point at a local address")
    return problems


def validate_app_config(env: str, root: Path) -> tuple[dict | None, list[str]]:
    """Validate config/<env>/app.yaml. Returns (data, errors)."""
    path = root / "config" / env / "app.yaml"
    name = rel(path, root)
    data, errors = load_yaml(path, root)
    if errors or data is None:
        return None, errors
    schema, schema_errors = load_schema(root)
    if schema is None:
        return None, schema_errors

    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        location = ".".join(str(p) for p in err.absolute_path) or "(top level)"
        errors.append(f"{name}: {location}: {err.message}")
    if errors:
        return None, errors

    if data["environment"] != env:
        errors.append(
            f"{name}: environment is '{data['environment']}' but the file lives in config/{env}/"
        )

    app, deploy = data["app"], data["deployment"]
    production = env == "production"
    shared = env in ("staging", "production")

    for problem in _url_problems(app["base_url"], require_https=shared, forbid_local=shared):
        errors.append(f"{name}: app.base_url: {problem} in {env}")

    if production:
        if app["debug"]:
            errors.append(f"{name}: app.debug must be false in production")
        if app["log_level"] == "debug":
            errors.append(f"{name}: app.log_level must not be 'debug' in production")
        if not deploy["require_approval"]:
            errors.append(f"{name}: deployment.require_approval must be true in production")
        if deploy["keep_previous_releases"] < 3:
            errors.append(
                f"{name}: deployment.keep_previous_releases must be at least 3 in production "
                "so rollback targets are available"
            )
    return (None if errors else data), errors


def validate_cross_environment(configs: Mapping[str, dict]) -> list[str]:
    """Keep configuration consistent across environments."""
    errors: list[str] = []
    if len(configs) < len(ENVIRONMENTS):
        return errors  # individual errors already reported
    secret_sets = {
        env: tuple(sorted(cfg["secrets"]["required_env_vars"])) for env, cfg in configs.items()
    }
    if len(set(secret_sets.values())) > 1:
        detail = "; ".join(f"{env}={list(names)}" for env, names in secret_sets.items())
        errors.append(f"secrets.required_env_vars differ between environments: {detail}")
    names = {cfg["app"]["name"] for cfg in configs.values()}
    if len(names) > 1:
        errors.append(f"app.name differs between environments: {sorted(names)}")
    if configs["production"]["app"]["base_url"] == configs["staging"]["app"]["base_url"]:
        errors.append("staging and production must not share the same app.base_url")
    return errors


# ------------------------------------------------------------- environment variables


def _validate_values(
    env: str,
    values: Mapping[str, str],
    secret_names: list[str],
    label: str,
    check_secrets: bool,
) -> list[str]:
    """Validate environment variable values. Secret values are never echoed."""
    errors: list[str] = []
    for name in BASE_ENV_VARS:
        if not values.get(name, "").strip():
            errors.append(f"{label}: required variable {name} is missing or empty")

    if values.get("APP_ENV") and values["APP_ENV"] != env:
        errors.append(f"{label}: APP_ENV is '{values['APP_ENV']}' but expected '{env}'")

    level = values.get("LOG_LEVEL", "")
    if level and level not in LOG_LEVELS:
        errors.append(f"{label}: LOG_LEVEL '{level}' is invalid, use one of {', '.join(LOG_LEVELS)}")
    if env == "production" and level == "debug":
        errors.append(f"{label}: LOG_LEVEL must not be 'debug' in production")

    port = values.get("APP_PORT", "")
    if port:
        if not port.isdigit() or not 1024 <= int(port) <= 65535:
            errors.append(f"{label}: APP_PORT '{port}' must be an integer from 1024 to 65535")

    url = values.get("APP_BASE_URL", "")
    if url:
        shared = env in ("staging", "production")
        for problem in _url_problems(url, require_https=shared, forbid_local=shared):
            errors.append(f"{label}: APP_BASE_URL {problem} in {env}")

    for name in secret_names if check_secrets else []:
        value = values.get(name, "")
        if not value.strip():
            errors.append(f"{label}: secret {name} is missing or empty")
        elif value.strip().upper() == PLACEHOLDER:
            errors.append(f"{label}: secret {name} still contains the placeholder {PLACEHOLDER}")
        elif len(value) < MIN_SECRET_LENGTH:
            errors.append(f"{label}: secret {name} is too short (minimum {MIN_SECRET_LENGTH} characters)")
    return errors


def validate_env_template(
    env: str, path: Path, secret_names: list[str], root: Path, expected_env: str | None = None
) -> list[str]:
    """Check an .env.example template: right keys, valid values, no real secrets."""
    label = rel(path, root)
    values, errors = parse_env_file(path, root)
    if values is None:
        return errors

    expected_keys = set(BASE_ENV_VARS) | set(secret_names)
    missing = sorted(expected_keys - values.keys())
    unexpected = sorted(values.keys() - expected_keys)
    if missing:
        errors.append(f"{label}: missing variable(s): {', '.join(missing)}")
    if unexpected:
        errors.append(
            f"{label}: unexpected variable(s): {', '.join(unexpected)} "
            "(add them to secrets.required_env_vars or remove them)"
        )
    for name in secret_names:
        if values.get(name, PLACEHOLDER) not in (PLACEHOLDER, ""):
            errors.append(
                f"{label}: {name} must be {PLACEHOLDER} in a template. "
                "Never commit real secret values."
            )
    errors += _validate_values(expected_env or env, values, secret_names, label, check_secrets=False)
    return errors


def validate_runtime_env(env: str, values: Mapping[str, str], root: Path) -> list[str]:
    """Validate real environment variable values before a deploy."""
    data, errors = validate_app_config(env, root)
    if data is None:
        return errors
    return _validate_values(
        env, values, data["secrets"]["required_env_vars"], f"runtime ({env})", check_secrets=True
    )


# -------------------------------------------------------------- repository hygiene


def find_real_env_files(root: Path) -> list[str]:
    """Real .env files must never live in the repository tree."""
    found: list[str] = []
    for base in (root, root / "config"):
        if not base.is_dir():
            continue
        for path in base.rglob(".env*") if base != root else base.glob(".env*"):
            if path.is_file() and path.name != ".env.example":
                found.append(f"{rel(path, root)}: real environment file found, remove it and keep it out of Git")
    return sorted(set(found))


def scan_for_secrets(root: Path) -> list[str]:
    errors: list[str] = []
    targets = [root / ".env.example"]
    for folder in ("config", "docs"):
        base = root / folder
        if base.is_dir():
            targets += [p for p in base.rglob("*") if p.is_file()]
    if (root / "README.md").is_file():
        targets.append(root / "README.md")
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{rel(path, root)}: possible {label} committed")
    return errors


# ------------------------------------------------------------------------ orchestration


def run_repository_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    configs: dict[str, dict] = {}

    for env in ENVIRONMENTS:
        data, errors = validate_app_config(env, root)
        checks.append(Check(f"{env}: config/{env}/app.yaml", errors))
        if data is not None:
            configs[env] = data

    for env in ENVIRONMENTS:
        template = root / "config" / env / ".env.example"
        if env in configs:
            errors = validate_env_template(env, template, configs[env]["secrets"]["required_env_vars"], root)
        else:
            errors = [f"{rel(template, root)}: skipped because config/{env}/app.yaml is invalid"]
        checks.append(Check(f"{env}: config/{env}/.env.example", errors))

    if "development" in configs:
        errors = validate_env_template(
            "development", root / ".env.example", configs["development"]["secrets"]["required_env_vars"], root
        )
    else:
        errors = [".env.example: skipped because config/development/app.yaml is invalid"]
    checks.append(Check("root template: .env.example", errors))

    checks.append(Check("cross-environment consistency", validate_cross_environment(configs)))
    checks.append(Check("no real .env files in repository", find_real_env_files(root)))
    checks.append(Check("no committed credentials", scan_for_secrets(root)))
    return checks


def print_checks(checks: list[Check]) -> int:
    failed = 0
    for check in checks:
        if check.ok:
            print(f"[ OK ] {check.name}")
        else:
            failed += 1
            print(f"[FAIL] {check.name}")
            for message in check.errors:
                print(f"         - {message}")
    total = len(checks)
    print()
    if failed:
        print(f"Configuration validation FAILED: {failed} of {total} checks failed.")
        return 1
    print(f"Configuration validation passed: {total} of {total} checks OK.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Infrastructure-Ops configuration.")
    parser.add_argument("--root", type=Path, default=default_root(), help="repository root (default: auto-detected)")
    parser.add_argument("--runtime-env", choices=ENVIRONMENTS, help="validate real environment variable values for this environment")
    parser.add_argument("--env-file", type=Path, help="KEY=VALUE file to validate in runtime mode (default: current process environment)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()

    if args.runtime_env:
        if args.env_file:
            values, errors = parse_env_file(args.env_file.resolve(), root)
            if values is None:
                return print_checks([Check(f"runtime ({args.runtime_env}): {args.env_file}", errors)])
        else:
            values = dict(os.environ)
        errors = validate_runtime_env(args.runtime_env, values, root)
        return print_checks([Check(f"runtime environment variables ({args.runtime_env})", errors)])

    return print_checks(run_repository_checks(root))


if __name__ == "__main__":
    sys.exit(main())
