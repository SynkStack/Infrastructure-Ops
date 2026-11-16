# Infrastructure-Ops

Infrastructure and deployment configuration for the project. This repository holds the environment configuration, the checks that keep it valid, and the documented procedures for deploying and rolling back. It is intentionally small and changes rarely.

## Overview

**Owner:** shared across the engineering team.

| Responsibility | Where |
|---|---|
| Environment configuration (development, staging, production) | [config/](config/) and [docs/configuration.md](docs/configuration.md) |
| Deployment documentation | [docs/deployment.md](docs/deployment.md) |
| CI validation | [.github/workflows/ci.yml](.github/workflows/ci.yml) |
| Architecture diagram | [docs/architecture.md](docs/architecture.md) |
| Rollback documentation | [docs/rollback.md](docs/rollback.md) |

## Architecture overview

Developers change configuration through pull requests. GitHub Actions validates every push and pull request. Releases are deployed to staging, verified, then deployed to production after approval. If verification fails, the team rolls back to the last tagged release. The full Mermaid diagram and component descriptions are in [docs/architecture.md](docs/architecture.md).

## Repository structure

```text
.
├── .env.example                  # Root template for local development
├── .gitattributes                # Consistent line endings on Windows and Linux
├── .gitignore                    # Keeps real .env files out of Git
├── .github/workflows/ci.yml      # CI workflow
├── README.md
├── pytest.ini
├── requirements.txt              # PyYAML, jsonschema, pytest
├── config/
│   ├── schema/config.schema.json # JSON Schema for every app.yaml
│   ├── development/              # app.yaml + .env.example
│   ├── staging/                  # app.yaml + .env.example
│   └── production/               # app.yaml + .env.example
├── docs/
│   ├── architecture.md           # Mermaid diagram and components
│   ├── configuration.md          # Variables and validation rules
│   ├── deployment.md             # Deployment guide
│   └── rollback.md               # Rollback runbook
├── scripts/
│   ├── validate_config.py        # Configuration validation
│   ├── check_docs.py             # Documentation checks
│   └── verify_deployment.py      # Post-deployment health check
└── tests/                        # pytest suite
```

## Environment configuration

Each environment has two kinds of files:

- `config/<env>/app.yaml` holds non-secret settings and is validated against `config/schema/config.schema.json`.
- `config/<env>/.env.example` is a template of environment variables. Secret values stay as `CHANGE_ME`.

Real values go in a file **outside** the repository. See [docs/configuration.md](docs/configuration.md) for every variable and rule.

## Installation and setup

Requires Python 3.9 or newer.

PowerShell (Windows):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. If `python` is not found, use `py`.

Bash (Linux or macOS):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Validation commands

```powershell
python scripts/validate_config.py        # configuration, templates, consistency, secret scan
python scripts/check_docs.py             # required docs, sections, diagram, links
python scripts/validate_config.py --runtime-env staging --env-file "$HOME\opssynk-secrets\staging.env"
python scripts/verify_deployment.py --environment staging
```

All commands exit with code 0 on success and 1 on failure, and print `[ OK ]` or `[FAIL]` per check with the file and the reason.

## Testing

```powershell
python -m pytest
```

The suite covers valid configuration for all three environments, missing and invalid values, malformed YAML, invalid templates, missing and broken documentation, runtime environment validation, the health-check script against a local test server, and end-to-end failure scenarios that run the scripts the way CI does.

## CI workflow

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push and pull request. One job, on `ubuntu-latest` with Python 3.12, runs in order:

1. Install dependencies from `requirements.txt`.
2. `python scripts/validate_config.py`
3. `python scripts/check_docs.py`
4. `python -m pytest`

Any failing step fails the workflow. To show a status badge, add this line below the title after the repository exists on GitHub, replacing `OWNER`:

```markdown
![CI](https://github.com/OWNER/Infrastructure-Ops/actions/workflows/ci.yml/badge.svg)
```

## Deployment and rollback

- [Deployment guide](docs/deployment.md): prerequisites, setup, staging, production, verification, common failures.
- [Rollback procedure](docs/rollback.md): criteria, step-by-step process, configuration rollback, recovery checklist, post-rollback note.

## Security considerations

- No secrets are stored in this repository. `app.yaml` lists variable names only, and templates contain `CHANGE_ME`.
- `.gitignore` excludes `.env` and `.env.*` except `.env.example`.
- CI fails if a real `.env` file is present or a known credential pattern (cloud keys, GitHub tokens, private key blocks) appears in config, docs or the README.
- Runtime validation never prints secret values.
- Production configuration must use https, have debug off, and require approval. These are enforced by the validator.
- If a secret is committed by mistake, treat it as exposed: rotate it, then remove it from the repository history.
