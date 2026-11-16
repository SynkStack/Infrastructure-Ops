# Deployment Guide

Commands are shown for **PowerShell** (Windows) first. Bash equivalents are given only where they differ.

## Scope and assumptions

- Application artifacts are built and released by the application repositories. This repository owns the **configuration**, the **pre- and post-deployment checks**, and the **procedure**.
- The deploy action itself (copying or starting the release on a target) uses the mechanism the team already has for that environment. Step 4 below is where it happens.
- A deployment is recorded as a Git tag on this repository, which also gives [rollback](rollback.md) a known target.

## Prerequisites

| Requirement | Check |
|---|---|
| Git 2.30 or newer | `git --version` |
| Python 3.9 or newer | `python --version` (Windows launcher alternative: `py --version`) |
| Repository cloned and on an up-to-date `main` | `git checkout main; git pull` |
| Access to the secret values for the target environment | Held by the Deploy Lead (password manager or equivalent) |
| Network access to the target environment | Needed for post-deployment verification |
| Application release version to deploy | From the application repository's release notes |

Install the validation dependencies once:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. On Linux or macOS use `python3 -m venv .venv` and `source .venv/bin/activate`.

## Environment setup

1. Create the real environment file **outside the repository**, starting from the template:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\opssynk-secrets" | Out-Null
   Copy-Item config\staging\.env.example "$HOME\opssynk-secrets\staging.env"
   ```

2. Replace every `CHANGE_ME` with a real value. Generate a strong secret with:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. Do not paste secret values into issues, pull requests, chat or logs.

Repeat with `config\production\.env.example` for production. If you must keep a real `.env` file inside the clone, `.gitignore` excludes it, but the validator will still flag it in CI-style checks, so prefer a location outside the repository.

## Configuration instructions

Settings that are not secret live in `config/<env>/app.yaml` and change through a pull request. Secret values live only in the environment file created above. The full variable list and rules are in [configuration.md](configuration.md).

Before any deployment, validate the repository and your real values:

```powershell
python scripts/validate_config.py
python scripts/validate_config.py --runtime-env staging --env-file "$HOME\opssynk-secrets\staging.env"
```

Expected result: every line starts with `[ OK ]` and the last line says validation passed. Any `[FAIL]` line names the file and the problem. Fix it before continuing.

## Deployment steps

These steps apply to both environments. Staging always comes first.

1. **Confirm CI is green** on the commit you are deploying (GitHub Actions tab, workflow `CI`).
2. **Validate** configuration and documentation locally:

   ```powershell
   python scripts/validate_config.py
   python scripts/check_docs.py
   ```

3. **Tag the commit** so the deployment is recorded and can be rolled back to. Use `<environment>-<YYYYMMDD>-<N>`, where N counts deployments that day:

   ```powershell
   git tag -a staging-20261116-1 -m "Staging deploy: app release 1.4.0"
   git push origin staging-20261116-1
   ```

4. **Deploy the application release** to the environment using the team's existing mechanism, with the configuration from `config/<env>/app.yaml` and the values from your environment file.
5. **Verify** the deployment (see [Post-deployment verification](#post-deployment-verification)).
6. **Record the result** in the release notes or the tracking issue: tag, app release, who deployed, verification outcome.

## Staging deployment

1. Complete steps 1 to 3 above with a `staging-*` tag.
2. Validate your real staging values:

   ```powershell
   python scripts/validate_config.py --runtime-env staging --env-file "$HOME\opssynk-secrets\staging.env"
   ```

3. Deploy the application release to staging (step 4).
4. Run the verification:

   ```powershell
   python scripts/verify_deployment.py --environment staging
   ```

5. Exercise the main user flows by hand and confirm no new errors appear in the application logs.
6. Leave the release on staging long enough for the team to review. Do not start a production deployment until staging is verified.

## Production deployment

Production needs approval (`require_approval: true` in its config).

**Go / no-go checklist.** Every answer must be yes:

- [ ] The same commit and application release were verified on staging.
- [ ] CI is green on that commit.
- [ ] A second team member has approved the deployment.
- [ ] The previous production tag is known and noted (`git tag --list "production-*" --sort=-creatordate`).
- [ ] The Deploy Lead and one other person are available for the next hour.
- [ ] The rollback steps in [rollback.md](rollback.md) have been read by the Deploy Lead.

**Steps:**

1. Note the current last known good release:

   ```powershell
   git tag --list "production-*" --sort=-creatordate
   ```

2. Validate real production values:

   ```powershell
   python scripts/validate_config.py --runtime-env production --env-file "$HOME\opssynk-secrets\production.env"
   ```

3. Tag the commit, for example `production-20261116-1`, and push the tag (deployment steps, step 3).
4. Deploy the application release to production (step 4).
5. Run the verification with more retries to allow for startup time:

   ```powershell
   python scripts/verify_deployment.py --environment production --retries 6 --interval 10
   ```

6. If verification fails, do not troubleshoot indefinitely. Apply the [decision criteria](rollback.md#decision-criteria).

## Post-deployment verification

1. **Automated health check.** `verify_deployment.py` calls `app.base_url` + `deployment.health_check_path` (currently `/healthz`) and expects HTTP 200 within `health_check_timeout_seconds`. It retries and exits non-zero on failure.
2. **Manual smoke test.** Open the environment's base URL, sign in or exercise the primary flow, and confirm it behaves as on the previous release.
3. **Logs.** Confirm there are no new repeated errors since the deployment time.
4. **Record.** Write the outcome next to the tag in the release notes.

## Common deployment failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `[FAIL] ... missing or empty` from `--runtime-env` | Variable not set in the environment file | Add it. Compare with `config/<env>/.env.example` |
| `secret ... still contains the placeholder CHANGE_ME` | Template copied but not filled in | Generate and set a real value |
| `secret ... is too short` | Secret under 16 characters | Regenerate with the Python command above |
| `APP_ENV is 'staging' but expected 'production'` | Wrong environment file used | Use the file created for the target environment |
| `app.base_url ... must use https` | Staging or production URL set to http or localhost | Correct `config/<env>/app.yaml` through a pull request |
| `invalid YAML format` | Indentation or syntax error in `app.yaml` | Fix the file. The message includes the line and column |
| Verification: `could not reach ...` | Service not started, wrong URL, or network or firewall block | Check the service, the URL in `app.yaml`, and your network access |
| Verification: `HTTP 500` or `HTTP 503` | Application failed to start, often a wrong variable value | Check application logs, then apply the [rollback criteria](rollback.md#decision-criteria) |
| `git push` of the tag is rejected | Tag name already exists | Increment N in the tag name. Never move an existing tag |
| `python` not found on Windows | Python not on PATH | Use `py` instead of `python`, or reinstall with "Add to PATH" |
| CI is red on `main` | Merged change broke validation | Fix forward in a small pull request. Do not deploy a red commit |
