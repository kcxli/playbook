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
uncertain fields as `TODO`. Navigation and submit-like buttons are commented by
default; enable them only after review.

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
| `--screenshot-dir DIR` | Save targeted failure artifacts under `DIR/error-step-###/` |
| `--ai-recover` | On a non-optional step failure, ask an OpenAI model for a bounded recovery plan before failing |
| `--ai-recover-model MODEL` | Model for `--ai-recover` (default: `PLAYBOOK_AI_MODEL` or `gpt-5.4-mini`) |
| `--ai-recover-attempts N` | Maximum AI recovery attempts per failed step (default 1) |
| `--ai-recover-min-confidence FLOAT` | Minimum accepted recovery confidence (default 0.55) |

### AI recovery

`--ai-recover` is an optional repair layer for brittle live forms. The runner
still executes the playbook normally first. If a non-optional step fails, it
captures a compact page snapshot (visible controls, selectors, page text, recent
steps, and the failed step), asks an OpenAI model for structured JSON, and only
executes ordinary safe playbook actions: `click`, `fill`, `select`, `check`,
`upload`, `press`, `wait_for`, `scroll`, or `sleep`.

```bash
export OPENAI_API_KEY="..."
.venv/bin/python -m playbook_runner playbooks/umn.playbook.yaml \
    -d applicants/test.json -d applicants/umn_overrides.json \
    --slow-mo 300 --screenshot-dir ./shots/umn --ai-recover
```

The recovery layer is deliberately conservative. It will not run arbitrary
JavaScript, solve/bypass CAPTCHA, click final submit-like actions, or invent
answers for sensitive fields. If the model is unsure, below the confidence
threshold, or proposes a blocked action, the original failure path is used and
the targeted failure artifacts are saved.

For more extension-like assistance, insert an `ai_fill_page` step in a playbook.
That step asks the same bounded AI layer to inspect the current visible page,
map fields to allowed applicant-profile values, and execute a short safe action
plan. This is useful for pages whose exact selectors are still moving:

```yaml
- ai_fill_page:
    allowed_sources: [person_name, emails, address_and_contact, education, answers, documents]
    max_actions: 12
    instructions: "Fill the visible profile section only. Stop before Next or Submit."
```

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
- **Share the targeted failure folder when debugging with Codex.** A failed run
  with `--screenshot-dir ./shots/ua` writes a compact bundle like
  `shots/ua/error-step-048/` with `screenshot.png`, `page.html`, and
  `failure.txt`. Hand Codex that one folder instead of the whole historical
  `shots/` tree.
- **CAPTCHAs / email verification / 2FA** are common on these sites and cannot
  be solved by this tool; a run will stop there.
- **Check terms of service.** Automated bulk submission may violate the ATS or
  employer's terms. This is intended to assist real applicants, not to mass-spam
  applications. Verify each applicant's data is accurate before submitting.
