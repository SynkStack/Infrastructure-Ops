"""Shared fixtures. Tests run against a throwaway copy of the repository so they can break it freely."""
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

COPIED = ("config", "docs", ".github", "README.md", ".env.example")
STRONG_SECRET = "Zx9-test-value-not-a-real-secret-1234"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A fresh copy of the config, docs, workflow, README and root template."""
    for name in COPIED:
        src = REPO_ROOT / name
        dst = tmp_path / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return tmp_path


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture()
def edit_config():
    """Return a function that loads config/<env>/app.yaml, applies a change, and saves it."""

    def _edit(root: Path, env: str, change) -> None:
        path = root / "config" / env / "app.yaml"
        data = read_yaml(path)
        change(data)
        write_yaml(path, data)

    return _edit


@pytest.fixture()
def valid_runtime_env() -> dict:
    def build(env: str = "production") -> dict:
        urls = {
            "development": "http://localhost:8080",
            "staging": "https://staging.opssynk.example.com",
            "production": "https://opssynk.example.com",
        }
        return {
            "APP_ENV": env,
            "LOG_LEVEL": "info",
            "APP_PORT": "8080",
            "APP_BASE_URL": urls[env],
            "API_SECRET_KEY": STRONG_SECRET,
            "SESSION_SECRET": STRONG_SECRET + "-session",
        }

    return build
