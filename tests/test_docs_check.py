"""Documentation checks: required files, sections, diagram and links."""
import pytest
from conftest import REPO_ROOT

import check_docs as cd


def failing(root):
    return {name: errors for name, errors in cd.run(root) if errors}


def test_real_documentation_passes():
    assert failing(REPO_ROOT) == {}


@pytest.mark.parametrize("doc", sorted(cd.REQUIRED_DOCS))
def test_missing_required_doc_is_reported(repo, doc):
    (repo / doc).unlink()
    errors = failing(repo)["required documentation files and sections"]
    assert f"{doc}: required documentation file is missing" in errors


def test_empty_doc_is_reported(repo):
    (repo / "docs" / "rollback.md").write_text("# Rollback\n", encoding="utf-8")
    errors = failing(repo)["required documentation files and sections"]
    assert any("docs/rollback.md" in e and "too short" in e for e in errors)


def test_missing_section_is_reported(repo):
    path = repo / "docs" / "rollback.md"
    path.write_text(path.read_text(encoding="utf-8").replace("## Recovery checklist", "## Something else"), encoding="utf-8")
    errors = failing(repo)["required documentation files and sections"]
    assert "docs/rollback.md: missing required section 'Recovery checklist'" in errors


def test_missing_diagram_is_reported(repo):
    path = repo / "docs" / "architecture.md"
    path.write_text(path.read_text(encoding="utf-8").replace("```mermaid", "```text"), encoding="utf-8")
    assert "architecture diagram present" in failing(repo)


def test_readme_must_link_all_docs(repo):
    path = repo / "README.md"
    path.write_text(path.read_text(encoding="utf-8").replace("docs/rollback.md", "docs/other.md"), encoding="utf-8")
    result = failing(repo)
    assert "README.md: missing link to docs/rollback.md" in result["README links to all docs"]
    assert "relative links resolve" in result  # the replaced link now also points at a missing file


def test_broken_relative_link_is_reported(repo):
    path = repo / "docs" / "deployment.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nSee [gone](missing-file.md).\n", encoding="utf-8")
    assert any("missing-file.md" in e for e in failing(repo)["relative links resolve"])


def test_broken_anchor_is_reported(repo):
    path = repo / "docs" / "deployment.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nSee [x](rollback.md#no-such-heading).\n", encoding="utf-8")
    assert any("heading that does not exist" in e for e in failing(repo)["relative links resolve"])


def test_links_inside_code_blocks_and_external_links_are_ignored(repo):
    path = repo / "docs" / "deployment.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n```text\n[fake](nowhere.md)\n```\n[site](https://example.com/x)\n",
        encoding="utf-8",
    )
    assert "relative links resolve" not in failing(repo)


def test_slugify_matches_github_rules():
    assert cd.slugify("Post-deployment verification") == "post-deployment-verification"
    assert cd.slugify("Decision criteria") == "decision-criteria"
    assert cd.slugify("Rollback `procedure`!") == "rollback-procedure"


def test_same_broken_link_is_reported_once_per_file(repo):
    path = repo / "docs" / "deployment.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n[a](gone.md) and [b](gone.md)\n", encoding="utf-8")
    errors = failing(repo)["relative links resolve"]
    assert sum("gone.md" in e for e in errors) == 1
