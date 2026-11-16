# Configuration Reference

## Files

| Path | Purpose | Committed |
|---|---|---|
| `config/schema/config.schema.json` | JSON Schema that every `app.yaml` must satisfy | Yes |
| `config/<env>/app.yaml` | Non-secret settings for `development`, `staging`, `production` | Yes |
| `config/<env>/.env.example` | Template of the environment variables for that environment | Yes |
| `.env.example` | Root template for local development (same keys as `config/development/.env.example`) | Yes |
| `.env`, `.env.*` (real files) | Real values, including secrets | **Never** (ignored by `.gitignore`) |

## Variables

| Variable | Secret | Rule |
|---|---|---|
| `APP_ENV` | No | Must equal the environment name |
| `LOG_LEVEL` | No | One of `debug`, `info`, `warning`, `error`. `debug` is rejected in production |
| `APP_PORT` | No | Integer from 1024 to 65535 |
| `APP_BASE_URL` | No | Valid `http(s)` URL. Staging and production require `https` and a non-local host |
| `API_SECRET_KEY` | Yes | At least 16 characters, not `CHANGE_ME` |
| `SESSION_SECRET` | Yes | At least 16 characters, not `CHANGE_ME` |

The list of secret names comes from `secrets.required_env_vars` in each `app.yaml`. Templates must contain exactly the four base variables plus those secret names, and every secret in a template must stay `CHANGE_ME`.

## Validation rules

Repository mode, run by CI and by `python scripts/validate_config.py`:

1. Each `app.yaml` parses as YAML and satisfies the JSON Schema (required keys, types, ranges, patterns, no unknown keys).
2. `environment` inside the file matches its directory.
3. Staging and production: `app.base_url` uses https and is not a local address.
4. Production only: `debug: false`, `log_level` is not `debug`, `require_approval: true`, `keep_previous_releases >= 3`.
5. Each `.env.example` has the expected variable set, valid non-secret values, and placeholder-only secrets.
6. Across environments: identical `secrets.required_env_vars`, identical `app.name`, and different staging and production base URLs.
7. No real `.env` files exist in the tree, and no known credential patterns (cloud keys, GitHub tokens, private key blocks) appear in `config/`, `docs/`, `README.md` or `.env.example`.

Runtime mode checks real values before a deploy and never prints secret values:

```powershell
python scripts/validate_config.py --runtime-env production --env-file C:\secure\opssynk\production.env
```

Add `--env-file` pointing at a file outside the repository. Without it, the validator reads the current process environment.

## Changing configuration

- **Change a value:** edit `config/<env>/app.yaml` (and the matching `.env.example` if it is an environment variable), run `python scripts/validate_config.py`, open a pull request.
- **Add a secret or variable:** add its name to `secrets.required_env_vars` in all three `app.yaml` files, add it to all four `.env.example` templates, and update the table above. Validation fails if the three environments drift apart.
- **Add a base variable:** add it to `BASE_ENV_VARS` in `scripts/validate_config.py`, add a rule for it in `_validate_values`, add a test, and update the templates and this document.
