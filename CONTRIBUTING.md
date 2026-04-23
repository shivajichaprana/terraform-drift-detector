# Contributing to terraform-drift-detector

Thanks for your interest in improving this project. This guide covers the dev setup, the conventions the codebase follows, and the review bar for pull requests.

## Philosophy

Keep the core small and the extension points obvious. The detector has three moving parts — a plan runner, a set of reporters, and a set of notifiers — and every PR should leave that shape intact. If a change blurs those boundaries, push back on the design before you write the code.

New policies for severity classification, new report formats, and new notification channels are all expected extensions. Adding one of those is a one-file change in most cases; see [docs/extending.md](./docs/extending.md).

## Local development setup

```bash
git clone https://github.com/shivajichaprana/terraform-drift-detector.git
cd terraform-drift-detector

# Create a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev extras
pip install -e .
pip install -r requirements-dev.txt  # pytest, flake8, mypy, coverage

# Run the test suite
pytest

# Run linting
flake8 detector tests
mypy detector
```

You do not need a real Terraform installation to develop or run tests — the test suite mocks `subprocess.run`, so plan output is provided by fixtures.

## Running against real Terraform

If you want to exercise the detector against a real Terraform directory, point it at any Terraform root module you have credentials for:

```bash
# Write a minimal config
cat > /tmp/dev-config.yaml <<'EOF'
targets:
  - path: /path/to/your/terraform
    workspaces: [default]
detection:
  refresh_only: true
  save_results: false
  output_format: console
EOF

drift-detector detect --config /tmp/dev-config.yaml -vv
```

`refresh_only: true` avoids producing speculative plans, which is the right mode when you're testing drift detection specifically.

## Code style

### Python

- **Format:** no strict formatter is enforced, but `flake8` must pass. Match the surrounding code — 4-space indents, double quotes, trailing commas in multi-line literals.
- **Typing:** public functions carry type hints. `mypy` runs in CI with the default config; `Any` is acceptable where the external API is untyped (e.g. subprocess output parsing) but should be explained in a comment.
- **Docstrings:** every public function, class, and module has a docstring. Use the Google style already in use (`Args:`, `Returns:`, `Raises:`).
- **Imports:** standard library first, third-party next, local imports last, separated by blank lines. `from __future__ import annotations` at the top of every file that uses forward references.
- **No bare `except`:** always specify the exception type. If you're deliberately catching everything for defensive reasons (e.g. a notifier), catch `Exception` and log the traceback.

### Shell scripts

- `set -euo pipefail` at the top.
- `trap cleanup EXIT` if the script creates temporary files or state.
- A `usage()` function reachable via `-h` or `--help`.
- `shellcheck` passes in CI — warnings are treated as errors.

### YAML / Markdown

- 2-space indentation for YAML.
- Markdown tables use pipes with spaces (`| foo | bar |`), not Unicode box drawing.
- Trailing newline on every file.

## Commit messages

The project uses [Conventional Commits](https://www.conventionalcommits.org/). The scope identifies the affected area:

```
feat(reporters):     add HTML reporter
fix(drift_checker):  handle empty plan output on exit code 2
docs(readme):        document --notify github flag
test(config):        cover env-var expansion edge cases
refactor(notifiers): extract common retry logic
ci(detector):        bump Python matrix to include 3.12
chore(build):        update requirements.txt pins
```

One commit should correspond to one logical change. If your branch has five exploratory commits, squash before opening the PR.

## Pull request process

1. Open an Issue or discussion first if the change is larger than ~50 lines of code. That's not a hard rule — trivial fixes are fine as direct PRs — but non-trivial design changes are easier to review with the motivation written down first.
2. Branch from `main`. Branch naming is free-form; `feat/html-reporter` or `fix/empty-plan-crash` are typical.
3. Write tests for new behaviour. Every reporter and notifier has a corresponding test module; new ones should too. See [docs/extending.md](./docs/extending.md) for the test patterns we use.
4. Update docs. If your change affects the CLI, `config.example.yaml`, or adds a new extension point, update the README or the `docs/` page it lives under.
5. Run `pytest`, `flake8`, and `mypy` locally before pushing.
6. Open the PR. Fill in the template: what the change does, how it was tested, any backwards-incompatible implications.

## Testing requirements

New behaviour is expected to ship with tests. The minimum bar:

- **New reporter:** at least one test that verifies output format against a synthetic `DetectionRun` (both with drift and without).
- **New notifier:** at least one test that mocks the transport (`requests.post`, `smtplib.SMTP`, etc.) and asserts the payload shape.
- **New plan-parsing branch:** a fixture with the specific terraform output and an assertion on the resulting `DriftedResource`.
- **New config field:** a test that covers the default, an explicit value, and an invalid value.

Aim for 85%+ line coverage on the module you touched. The CI job will fail below that threshold.

## Reporting bugs

Open an Issue with:

1. What you ran (CLI command and redacted config).
2. What you expected.
3. What happened (full error output with `-vv`).
4. `drift-detector --version` and your Terraform version.

If the bug is in plan parsing, attach a minimal Terraform configuration that reproduces the issue (or at least the `terraform plan` output that trips the parser).

## Security disclosures

Do not open a public Issue for security-sensitive reports. Email the maintainer instead and allow a reasonable window for a fix before disclosure.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE).
