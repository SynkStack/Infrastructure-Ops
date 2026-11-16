#!/usr/bin/env python3
"""Post-deployment verification: call the environment's health endpoint.

The URL is built from config/<env>/app.yaml (app.base_url + deployment.health_check_path)
unless --url is given. Run it from a machine that can reach the environment.

Usage:
    python scripts/verify_deployment.py --environment staging
    python scripts/verify_deployment.py --environment production --retries 5 --interval 10

Exit code is 0 when the endpoint answers HTTP 200 and 1 otherwise.
Uses only the Python standard library plus the project's PyYAML dependency.
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_config import ENVIRONMENTS, default_root, validate_app_config  # noqa: E402


def check_health(url: str, timeout: int) -> tuple[bool, str]:
    """Single health check. Returns (healthy, message)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (operator-supplied URL)
            if response.status == 200:
                return True, f"HTTP 200 from {url}"
            return False, f"HTTP {response.status} from {url}, expected 200"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}, expected 200"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"could not reach {url}: {getattr(exc, 'reason', exc)}"


def verify(env: str, root: Path, url: str | None, retries: int, interval: float) -> int:
    data, errors = validate_app_config(env, root)
    if data is None:
        for message in errors:
            print(f"[FAIL] {message}")
        return 1
    timeout = data["deployment"]["health_check_timeout_seconds"]
    if url is None:
        url = data["app"]["base_url"].rstrip("/") + data["deployment"]["health_check_path"]

    for attempt in range(1, retries + 1):
        healthy, message = check_health(url, timeout)
        status = " OK " if healthy else "FAIL"
        print(f"[{status}] attempt {attempt}/{retries}: {message}")
        if healthy:
            print(f"\nDeployment verification passed for {env}.")
            return 0
        if attempt < retries:
            time.sleep(interval)
    hint = "" if env == "development" else " Follow docs/rollback.md if the criteria are met."
    print(f"\nDeployment verification FAILED for {env}.{hint}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a deployed environment is healthy.")
    parser.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--url", help="override the health URL derived from config")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between attempts")
    args = parser.parse_args(argv)
    if args.retries < 1:
        parser.error("--retries must be at least 1")
    return verify(args.environment, args.root.resolve(), args.url, args.retries, args.interval)


if __name__ == "__main__":
    sys.exit(main())
