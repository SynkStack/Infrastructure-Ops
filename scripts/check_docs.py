#!/usr/bin/env python3
"""Check that required documentation exists, has its key sections, and has no broken links.

Usage:
    python scripts/check_docs.py [--root PATH]

Exit code is 0 when documentation is complete and 1 otherwise.
Works on Windows, macOS and Linux with Python 3.9+.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MIN_LENGTH = 300  # characters; guards against empty or stub files

# file -> headings (case-insensitive substrings) that must be present
REQUIRED_DOCS: dict[str, tuple[str, ...]] = {
    "README.md": ("Overview", "Repository structure", "Validation", "Testing", "Security"),
    "docs/deployment.md": (
        "Prerequisites",
        "Environment setup",
        "Staging deployment",
        "Production deployment",
        "Post-deployment verification",
        "Common deployment failures",
    ),
    "docs/rollback.md": (
        "When rollback is required",
        "Decision criteria",
        "Rollback procedure",
        "Configuration rollback",
        "Recovery checklist",
        "Post-rollback",
    ),
    "docs/architecture.md": ("Diagram", "Components"),
    "docs/configuration.md": ("Files", "Variables", "Validation rules"),
}

# README must link to each of these.
README_MUST_LINK = ("docs/deployment.md", "docs/rollback.md", "docs/architecture.md", "docs/configuration.md")

FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
MERMAID = re.compile(r"^```mermaid\s*$", re.MULTILINE)


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


def strip_code(text: str) -> str:
    return FENCE.sub("", text)


def check_required_docs(root: Path) -> list[str]:
    errors: list[str] = []
    for name, headings in REQUIRED_DOCS.items():
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: required documentation file is missing")
            continue
        text = path.read_text(encoding="utf-8")
        if len(text.strip()) < MIN_LENGTH:
            errors.append(f"{name}: file is empty or too short (minimum {MIN_LENGTH} characters)")
            continue
        found = [h.lower() for h in HEADING.findall(strip_code(text))]
        for wanted in headings:
            if not any(wanted.lower() in h for h in found):
                errors.append(f"{name}: missing required section '{wanted}'")
    return errors


def check_architecture_diagram(root: Path) -> list[str]:
    path = root / "docs" / "architecture.md"
    if not path.is_file():
        return []  # already reported by check_required_docs
    if not MERMAID.search(path.read_text(encoding="utf-8")):
        return ["docs/architecture.md: no ```mermaid diagram block found"]
    return []


def check_readme_links(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    targets = {t.split("#", 1)[0] for t in LINK.findall(strip_code(text))}
    return [f"README.md: missing link to {doc}" for doc in README_MUST_LINK if doc not in targets]


def slugify(heading: str) -> str:
    """Approximate GitHub's heading-to-anchor rule."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def anchors_in(path: Path) -> set[str]:
    return {slugify(h) for h in HEADING.findall(strip_code(path.read_text(encoding="utf-8")))}


def check_relative_links(root: Path) -> list[str]:
    errors: list[str] = []
    files = [root / "README.md"]
    if (root / "docs").is_dir():
        files += sorted((root / "docs").glob("*.md"))
    for path in files:
        if not path.is_file():
            continue
        for target in dict.fromkeys(LINK.findall(strip_code(path.read_text(encoding="utf-8")))):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue  # external URL or mailto
            file_part, _, fragment = target.partition("#")
            resolved = (path.parent / file_part).resolve() if file_part else path
            name = path.relative_to(root).as_posix()
            if not resolved.exists():
                errors.append(f"{name}: broken link to '{target}'")
            elif fragment and resolved.suffix == ".md" and fragment.lower() not in anchors_in(resolved):
                errors.append(f"{name}: link '{target}' points to a heading that does not exist")
    return errors


def run(root: Path) -> list[tuple[str, list[str]]]:
    return [
        ("required documentation files and sections", check_required_docs(root)),
        ("architecture diagram present", check_architecture_diagram(root)),
        ("README links to all docs", check_readme_links(root)),
        ("relative links resolve", check_relative_links(root)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check required documentation.")
    parser.add_argument("--root", type=Path, default=default_root())
    root = parser.parse_args(argv).root.resolve()

    failed = 0
    results = run(root)
    for name, errors in results:
        if errors:
            failed += 1
            print(f"[FAIL] {name}")
            for message in errors:
                print(f"         - {message}")
        else:
            print(f"[ OK ] {name}")
    print()
    if failed:
        print(f"Documentation check FAILED: {failed} of {len(results)} checks failed.")
        return 1
    print(f"Documentation check passed: {len(results)} of {len(results)} checks OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
