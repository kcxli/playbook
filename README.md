# project-playbook

`project-playbook` is the deterministic browser-automation engine and maintained
playbook catalog for filling job applications. It combines a structured
applicant profile with a reviewed YAML playbook and executes ordinary
Playwright actions against the application site.

This repository is currently a standalone testing and maintainer tool. The
planned product uses [Project Exchange](https://github.com/SharpDressedMan/project-exchange)
for the user-facing React/Django application and a signed local companion on
each applicant's computer to run this engine in a visible browser. See the
[integration plan](docs/project-exchange-integration.md) and the
[beginner setup guide](docs/project-exchange-beginner-guide.md).

## Current Policy

- **No runtime AI.** AI recovery was an experiment and has been sunset and
  removed. A maintainer may use Codex or another assistant offline to draft or
  debug a playbook, but application runs never call an AI model.
- **Human final submission.** During the testing stage, automation fills the
  form and then reaches `pause_for_user`. The applicant reviews the visible
  browser and personally clicks the final submit button. Live headless runs are
  rejected when a human gate is present.
- **Trusted automation only.** End users will manage their own profile,
  documents, targets, and runs through Project Exchange. Only maintainers may
  create or publish playbooks, scripts, equivalences, or runner code.
- **Later automatic submission is a separate feature.** It will require an
  explicit product policy, consent flow, and guarded implementation. It is not
  enabled by uncommenting a button in a playbook.

## Repository Map

| Path | Purpose |
|------|---------|
| `playbook_runner/` | Installable Python package: parser, intake contract, context building, deterministic matching, dry-run validation, artifact handling, and Playwright engine |
| `playbook_runner/data/` | Reviewed equivalence aliases and global country options shipped with the package |
| `playbooks/` | Maintainer-owned YAML workflows for supported application forms |
| `tools/` | Form extractor, conservative draft generator, and equivalence-repair helper |
| `tests/` | Unit, contract, security, packaging, and full playbook/profile validation tests |
| `applicants/` | Fake local fixtures and document samples for development; not production user storage |
| `information/` | Applicant-profile contract fixture and local equivalence overlay |
| `docs/` | Authoring, data-model, terminal, research, and Project Exchange integration documentation |
| `SPEC.md` | Complete playbook format and maintainer workflow |
| `pyproject.toml` | Package metadata and `playbook-runner` command |
| `requirements.txt` | Fully pinned development/runtime dependencies |
| `.github/workflows/ci.yml` | Python 3.11/3.12 validation in CI |

Production applicant data, credentials, browser sessions, and failure artifacts
must never be committed to this repository.

## Product Intake Contract

`playbook_runner/intake.py` is the source of truth for the private application
profile used by Project Exchange. It declares reusable profile fields,
canonical choice values, per-playbook requirements, required document paths,
true position overrides, and known playbook blockers. The website renders
that contract instead of maintaining a second list of application fields.
Each maintained YAML file names its unique contract with `intake.key`; this is
separate from the reusable employer/account scope in `employer_key`.

Reusable facts are stored once in the applicant's private profile. Generated
`app_answers.*` values translate those facts into deterministic ATS-specific
labels. A target's optional `position_overrides.*` data is limited to referral,
institution-relationship, and genuinely unique prompts; ordinary education,
employment, demographic, and platform facts are never re-requested there.
Government IDs and criminal-history answers are runtime-only and must not be
stored in ordinary profile JSON.

New to the terminal or to Linux? Start with
**[docs/terminal-and-linux.md](docs/terminal-and-linux.md)** — it's tailored to
the exact commands this project uses.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e . --no-deps
.venv/bin/python -m playwright install chromium
```

## Draft a new playbook (form-extractor.js)

To start a new form, open it in your browser, open the DevTools console, and
paste in the full [tools/form-extractor.js](tools/form-extractor.js). It prints
a structured summary of the page — labels, stable selectors, native and custom
dropdown options, radio groups, hidden uploads, same-origin iframe fields, and
conditional/modal fields discovered by safe probes — plus a
`PLAYBOOK_EXTRACT_JSON_START` / `PLAYBOOK_EXTRACT_JSON_END` block for future
draft-generation tooling. It copies the full output to your clipboard. Hand that
output to Claude/Codex, or save it for the playbook generator.

It captures the page you're on; for a multi-page flow, run it on each later page.
Then review and validate (below). If the form has fields behind a path the safe
probes did not open, manually pick that answer or open that modal and run the
extractor again on the revealed state.

## Generate a draft playbook

After copying the extractor output, generate the first YAML draft with
[tools/draft_playbook.py](tools/draft_playbook.py). For a multi-page form, run
the generator once in collect mode, then just paste each page's extractor output
as you capture it. The tool appends every page to one combined capture file and
regenerates the same playbook draft after each paste:

```bash
python3 tools/draft_playbook.py \
  --collect \
  --name "University Example Application" \
  --url "https://example.edu/jobs/123#apply" \
  --job-id "123" \
  --out playbooks/example.playbook.yaml
```

Paste page 1's full extractor output. When the tool sees
`PLAYBOOK_EXTRACT_JSON_END`, it saves that page and regenerates the draft. Then
paste page 2, page 3, and so on. Press `Ctrl-D` only when you're done collecting
pages. By default the combined extractor archive is saved as
`extracts/example.txt` based on the output filename; pass `--capture-file` if
you want a different archive path. Do not hand-edit the generated playbook until
you are done collecting pages, because the draft is rewritten after each paste.

You can also save extractor output files yourself and pass them in page order
instead of using `--collect`:

```bash
mkdir -p extracts/example
pbpaste > extracts/example/page-1-personal.txt

python3 tools/draft_playbook.py \
  -x extracts/example/page-1-personal.txt \
  -x extracts/example/page-2-education.txt \
  --name "University Example Application" \
  --url "https://example.edu/jobs/123#apply" \
  --job-id "123" \
  --out playbooks/example.playbook.yaml
```

The generator writes conservative `fill`/`select`/`upload`/`press`/`pick`
steps, preserves exact selectors and option lists as comments, and leaves
uncertain fields as `TODO`. Navigation buttons are commented until a maintainer
reviews their ordering. Final-submit buttons remain inactive, and the generator
appends `pause_for_user` for applicant review and submission.

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

Run for real in a visible browser:

```bash
.venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml \
    -d applicants/test.json --slow-mo 300 --screenshot-dir ./shots
```

Every maintained playbook ends at a human gate. The browser stays open while
the applicant reviews and submits manually; the terminal closes it only after
the applicant confirms that the requested action is complete.

### Options

| Flag | Purpose |
|------|---------|
| `-d, --data FILE` | Applicant JSON (repeatable; later files override earlier) |
| `--dry-run` | Resolve and print the plan; no browser |
| `--validate` | Like `--dry-run` but also checks upload files exist; exits non-zero on any problem |
| `--headless` | No visible window; rejected for live playbooks containing `pause_for_user` |
| `--slow-mo MS` | Slow each Playwright action by MS milliseconds |
| `--pace SECONDS` | Pause SECONDS after every step (overall slowdown to watch) |
| `--timeout MS` | Per-action timeout (default 15000) |
| `--screenshot-dir DIR` | Save targeted failure artifacts under `DIR/error-step-###/` |

Live execution is deliberately deterministic: a step succeeds, is explicitly
optional, pauses for a person, or fails with a targeted artifact bundle used to
repair the playbook or equivalence table. There is no AI recovery branch.

## Important notes

- **Selectors will need tuning per site.** The engine tries label/role/text
  strategies, but legacy ATS markup is inconsistent. When a field isn't found,
  add a `selector:` override to that step (see SPEC.md → "escape hatch"). Run
  non-headless with `--slow-mo` to see exactly where it stops.
- **Share the targeted failure folder when debugging with Codex.** A failed run
  with `--screenshot-dir ./shots/ua` writes a compact bundle like
  `shots/ua/error-step-048/` with `screenshot.png`, `page.html`, and
  `failure.txt`. Hand Codex that one folder instead of the whole historical
  `shots/` tree.
- **Treat failure artifacts as private applicant data.** They are written with
  owner-only permissions, but screenshots and page HTML may contain names,
  answers, and uploaded-document metadata. Never commit or publish them.
- **CAPTCHAs and 2FA challenges require the applicant.** A playbook should pause
  at those checkpoints rather than bypass them. Email verification links and
  codes can be handled deterministically with `await_email_link` and
  `await_email_code` when access to the application mailbox is configured.
- **Check terms of service.** Automated bulk submission may violate the ATS or
  employer's terms. This is intended to assist real applicants, not to mass-spam
  applications. Verify each applicant's data is accurate before submitting.
