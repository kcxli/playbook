# project-playbook

Automate filling and submitting job-application forms from a declarative
**playbook** + an applicant **data file**, driven by Playwright.

- Write the steps once in a `.playbook` YAML file — see **[SPEC.md](SPEC.md)**.
- Keep each applicant's data in a JSON profile (see
  [applicants/test.json](applicants/test.json)).
- The runner resolves the data into the steps and drives a browser end-to-end.

## Layout

```
playbook_runner/        the Python engine (parser, templating, conditions, Playwright)
playbooks/              .playbook files (one per application form)
applicants/             per-applicant data (JSON)
information/test.json   the canonical applicant-profile schema
SPEC.md                 how to write a .playbook file
docs/terminal-and-linux.md   terminal & Linux guide (venv, running this, the server)
```

New to the terminal or to Linux? Start with
**[docs/terminal-and-linux.md](docs/terminal-and-linux.md)** — it's tailored to
the exact commands this project uses.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

## Draft a new playbook (form-extractor.js)

To start a new form, open it in your browser, open the DevTools console, and
paste in the full [tools/form-extractor.js](tools/form-extractor.js). It prints
a structured summary of the page — labels, stable selectors, native and custom
dropdown options, radio groups, hidden uploads, same-origin iframe fields, and
conditional/modal fields discovered by safe probes — and copies it to your
clipboard. Hand that output to Claude/Codex to draft a `.playbook.yaml`.

It captures the page you're on; for a multi-page flow, run it on each later page.
Then review and validate (below). If the form has fields behind a path the safe
probes did not open, manually pick that answer or open that modal and run the
extractor again on the revealed state.

## Use

Dry run first — validates every template/condition without opening a browser:

```bash
.venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml \
    -d applicants/test.json --dry-run
```

`--validate` is the same check but stricter: it also confirms every upload file
exists on disk and **exits non-zero** if anything is wrong — use it in scripts
and before a batch run:

```bash
.venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml \
    -d applicants/test.json --validate
```

Run for real (visible browser; drop `--headless` while testing):

```bash
.venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml \
    -d applicants/test.json --slow-mo 300 --screenshot-dir ./shots
```

### Options

| Flag | Purpose |
|------|---------|
| `-d, --data FILE` | Applicant JSON (repeatable; later files override earlier) |
| `--dry-run` | Resolve and print the plan; no browser |
| `--validate` | Like `--dry-run` but also checks upload files exist; exits non-zero on any problem |
| `--headless` | No visible window |
| `--slow-mo MS` | Slow each Playwright action by MS milliseconds |
| `--pace SECONDS` | Pause SECONDS after every step (overall slowdown to watch) |
| `--timeout MS` | Per-action timeout (default 15000) |
| `--screenshot-dir DIR` | Save a screenshot if a step fails |

Batch over applicants (validate each first, skip any that fail):

```bash
for who in applicants/*.json; do
  if .venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml -d "$who" --validate; then
    .venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml -d "$who"
  else
    echo "SKIP $who — validation failed" >&2
  fi
done
```

## Important notes

- **Selectors will need tuning per site.** The engine tries label/role/text
  strategies, but legacy ATS markup is inconsistent. When a field isn't found,
  add a `selector:` override to that step (see SPEC.md → "escape hatch"). Run
  non-headless with `--slow-mo` to see exactly where it stops.
- **CAPTCHAs / email verification / 2FA** are common on these sites and cannot
  be solved by this tool; a run will stop there.
- **Check terms of service.** Automated bulk submission may violate the ATS or
  employer's terms. This is intended to assist real applicants, not to mass-spam
  applications. Verify each applicant's data is accurate before submitting.
