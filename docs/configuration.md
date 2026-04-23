# Configuration reference

The detector reads a single YAML file. By convention it is named `config.yaml` and sits next to the project; the CLI requires `--config <path>` on every invocation.

The file is structured into three top-level sections — `targets`, `detection`, and `notifications` — each documented below with every option, its default, and why you'd change it.

Environment variables in values are expanded. `${SLACK_WEBHOOK_URL}` in the YAML becomes the value of that env var at load time; if the variable is unset, the literal string stays in place (notifiers treat empty credentials as "disabled" rather than erroring).

## File skeleton

```yaml
targets:
  - path: ./infrastructure/production
    workspaces: [default]
    enabled: true

detection:
  terraform_binary: terraform
  parallelism: 1
  init_before_plan: true
  refresh_only: false
  plan_timeout: 300
  save_results: true
  results_dir: ./drift-results
  output_format: console

notifications:
  slack:
    webhook_url: ${SLACK_WEBHOOK_URL}
    channel: "#infrastructure-alerts"
    notify_on: drift
  email:
    smtp_host: ${SMTP_HOST}
    smtp_port: 587
    smtp_user: ${SMTP_USER}
    smtp_password: ${SMTP_PASSWORD}
    from_address: drift@example.com
    to_addresses: [team@example.com]
    notify_on: drift
```

Everything except `targets` is optional; omitted sections fall back to the defaults below.

---

## `targets`

A list of Terraform root modules to scan. Each entry is an independent target — `drift-detector` runs `terraform plan` once per (target, workspace) combination.

### Per-target options

| Key | Type | Default | Description |
|---|---|---|---|
| `path` | string (required) | — | Directory containing the Terraform root module. Supports `~` and env-var expansion. |
| `workspaces` | list\[string\] | `[default]` | Workspaces to check. One plan runs per workspace. |
| `var_file` | string | _unset_ | Optional `-var-file=<path>` passed to `terraform plan`. Path is relative to `path`. |
| `backend_config` | string | _unset_ | Optional `-backend-config=<path>` passed to `terraform init`. |
| `enabled` | bool | `true` | Toggle to skip a target without deleting the entry. |

### Example — multi-workspace, multi-region

```yaml
targets:
  - path: ./infrastructure/shared
    workspaces: [us-east-1, eu-west-1, ap-south-1]
    var_file: shared.tfvars

  - path: ./infrastructure/production
    workspaces: [default]
    backend_config: backend-prod.hcl

  - path: ./infrastructure/legacy
    workspaces: [default]
    enabled: false   # paused — keeps the entry around but skips it
```

### Path resolution

- Relative paths are resolved against the current working directory when `drift-detector` runs. In CI this is usually the repo root.
- Absolute paths work unchanged.
- Env vars like `$HOME`, `${TF_ROOT}` are expanded.

### Workspaces and the `default` workspace

If you don't use workspaces, leave `workspaces: [default]`. The detector runs `terraform workspace select <name>` before each plan; `default` is always selectable, so it's safe to leave in place.

If you use workspaces, each one produces a separate `DriftResult` in the final report and a separate GitHub Issue (when the GitHub notifier is enabled). This keeps drift-in-us-east distinct from drift-in-eu-west.

---

## `detection`

Global settings that govern how `terraform plan` is invoked and what happens with the output.

| Key | Type | Default | Description |
|---|---|---|---|
| `terraform_binary` | string | `terraform` | Path to the `terraform` executable. Useful for pinning a specific version on CI workers. |
| `parallelism` | int | `1` | Number of targets to check concurrently. Each thread holds one Terraform process; 2-4 is a reasonable upper bound unless your backend supports much more. |
| `init_before_plan` | bool | `true` | Run `terraform init -input=false` before each plan. Required on a fresh checkout; can be disabled in persistent environments. |
| `refresh_only` | bool | `false` | Pass `-refresh-only` to `terraform plan`. Reports only drift between state and reality; ignores proposed changes from `.tf` edits. **Recommended for drift detection.** |
| `plan_timeout` | int (seconds) | `300` | Kill a plan that exceeds this. Large state files plus slow cloud APIs can legitimately run long — bump this if you see false positives as timeouts. |
| `save_results` | bool | `true` | Write the `DetectionRun` as JSON to `results_dir` after each run. |
| `results_dir` | string | `./drift-results` | Directory for saved result files. Created if missing. |
| `output_format` | enum | `console` | Default output format when `--output-format` is not passed. One of `console`, `json`, `markdown`. |

### `refresh_only: false` vs `refresh_only: true`

This is the most important knob in the file.

- `refresh_only: false` — the plan includes any changes your `.tf` files would make on top of the current state. This is useful if you want to know about _both_ pending deploys and drift, but noisy if you're only interested in drift.
- `refresh_only: true` — the plan compares state to real cloud resources only. A clean plan means state matches reality. This is what drift detection usually wants.

When in doubt, start with `refresh_only: true` and flip if you need the extra signal.

### Parallelism guidance

Each concurrent worker holds:

- One `terraform` process (can be memory-heavy for large states).
- One cloud SDK connection pool.
- One lock on the state backend (some backends serialize regardless of `parallelism`).

On a laptop, `parallelism: 1` is fine. On CI with a beefy runner, 2–4 speeds things up without tripping rate limits. Past that, you usually hit cloud API throttling before you gain anything.

### Saved result files

When `save_results: true`, each run writes a file named:

```
drift-results/drift-<ISO8601-start-time>.json
```

The filename replaces colons with dashes for Windows compatibility. The file is valid input for `drift-detector report --input <file>`, so you can always re-render past runs in a different format.

---

## `notifications`

Settings for each supported notification channel. A channel is "configured" if its section is present and has non-empty credentials; if it's missing, attempts to `--notify <channel>` will raise a clear error.

All channels respect a shared `notify_on` field:

| Value | Meaning |
|---|---|
| `always` | Send on every run, even clean ones. |
| `drift` | Send only when drift was detected (**default**). |
| `error` | Send only when one or more targets errored. |

### `notifications.slack`

| Key | Type | Default | Description |
|---|---|---|---|
| `webhook_url` | string | _unset_ | Incoming webhook URL from the Slack app. Env-var expansion is the common pattern. |
| `channel` | string | `""` | Channel override (the webhook has a default). Include the `#`. |
| `username` | string | `Drift Detector` | Display name for the bot. |
| `icon_emoji` | string | `:warning:` | Emoji shown next to the bot name. |
| `notify_on` | enum | `drift` | See table above. |

**Creating the webhook:** Slack → _Apps → Manage → Custom Integrations → Incoming Webhooks_. Or via an official Slack app with `incoming-webhook` scope. Copy the URL into an env var (never commit it).

### `notifications.email`

| Key | Type | Default | Description |
|---|---|---|---|
| `smtp_host` | string | _unset_ | SMTP server hostname. |
| `smtp_port` | int | `587` | SMTP port. 587 for STARTTLS, 465 for implicit TLS. |
| `smtp_user` | string | _unset_ | Login user. |
| `smtp_password` | string | _unset_ | Login password or app token. |
| `use_tls` | bool | `true` | Wrap the session in STARTTLS. |
| `from_address` | string | _unset_ | RFC 5322 `From:` header. |
| `to_addresses` | list\[string\] | `[]` | One or more RFC 5322 addresses. |
| `subject_prefix` | string | `[Drift Detector]` | Prepended to the computed subject. |
| `notify_on` | enum | `drift` | See table above. |

**App-specific passwords:** Gmail, Outlook, and Fastmail all require app-specific passwords (or OAuth tokens) — your regular login will not work.

### GitHub Issues

The GitHub notifier is configured entirely through environment variables rather than the YAML, because the CI environment already provides them:

| Env var | Description |
|---|---|
| `GH_TOKEN` or `GITHUB_TOKEN` | Personal access token or `${{ secrets.GITHUB_TOKEN }}` in Actions. Must have `issues: write`. |
| `GITHUB_REPOSITORY` | `owner/repo`. Automatically set by Actions. |

The notifier opens a new Issue per drifted target and dedupes by title: if an Issue with the same title is already open, it comments on it instead of creating a duplicate.

---

## Environment variable expansion

Any value in the YAML that looks like `${VAR_NAME}` is replaced with the environment variable's value at load time. This is the normal pattern for credentials:

```yaml
notifications:
  slack:
    webhook_url: ${SLACK_WEBHOOK_URL}
  email:
    smtp_password: ${SMTP_PASSWORD}
```

If `SLACK_WEBHOOK_URL` is unset, the notifier sees an empty string and refuses to send (with a warning log) rather than crashing.

`${VAR:-default}` syntax **is not supported** — use a concrete default in code or set the env var explicitly.

---

## Validating your config

Before committing, run:

```bash
drift-detector detect --config config.yaml -vv
```

The `-vv` flag produces DEBUG logs that show which targets were loaded, which workspaces, and what command lines were built. Config errors (missing required fields, invalid types) surface immediately with a descriptive message.

If you want to validate without actually running Terraform, delete or temporarily rename a target `path` — the detector will error with a "target path does not exist" message that proves the config parsed correctly before failing.

---

## Multi-repo setups

For monorepo-style setups (one detector scanning Terraform code across several repos), see [`examples/multi-repo-config.yaml`](../examples/multi-repo-config.yaml). The pattern is:

1. Check out each target repo into a shared workspace directory at the start of the CI job.
2. Point `targets` at the checkouts.
3. Run `drift-detector detect`.

The Dockerfile is particularly useful here — one image, N repos mounted in.
