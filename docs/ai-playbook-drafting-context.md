# AI Playbook Drafting Context

Use this document when opening a fresh AI/Codex/Claude prompt to draft or debug a
new playbook. Paste or attach it together with the relevant extractor output and,
for failures, the targeted `shots/<site>/error-step-###/` folder.

## Project Goal

`project-playbook` fills job applications with deterministic Playwright actions.
AI may help draft playbooks or inspect failure artifacts, but normal application
runs should not need AI in the loop.

The runner combines:

- one structured applicant profile,
- reusable application defaults,
- employer-specific exceptions,
- deterministic option equivalences,
- one YAML playbook per application workflow.

The desired playbook should describe the workflow and point at reusable data. It
should not hard-code one applicant's site-specific wording unless the question is
truly unique to that site.

## Current Authoring Workflow

1. Open the application page in a browser.
2. Paste [`tools/form-extractor.js`](../tools/form-extractor.js) into DevTools.
3. Save the full extractor output for every page/state in the flow.
4. Write or revise the YAML directly, using a similar existing playbook when
   possible. If an AI drafting assistant is used, give it the extractor output
   plus this document.
5. Review every `TODO`, custom widget, modal, hidden field, and commented button.
6. Keep final submit/certify buttons commented until a human is ready to submit.
7. Validate before running:

```bash
.venv/bin/python -m playbook_runner playbooks/site.playbook.yaml \
  -d applicants/test.json --validate
```

8. Test visibly first:

```bash
.venv/bin/python -m playbook_runner playbooks/site.playbook.yaml \
  -d applicants/test.json \
  --slow-mo 300 \
  --screenshot-dir ./shots/site
```

## Data Layers

Use canonical profile paths for stable applicant facts:

```yaml
value: "{{ person_name.legal_name.first }}"
value: "{{ address_and_contact.primary_address.state_province }}"
value: "{{ education.schools.0.institution }}"
value: "{{ work_history.0.job_title }}"
value: "{{ documents.resume_path_or_url }}"
```

Use generated `app_answers.*` for common application questions:

```yaml
value: "{{ app_answers.referral_source }}"
source: app_answers.authorized_to_work_us
source: app_answers.requires_visa_sponsorship
source: app_answers.previously_employed_by_employer
source: app_answers.related_to_employer_employee
source: app_answers.has_conflict_of_interest
value: "{{ app_answers.desired_salary }}"
```

`app_answers` is built by [`playbook_runner/context.py`](../playbook_runner/context.py)
from, weakest to strongest:

1. derived canonical facts,
2. legacy `answers.*`,
3. `application_defaults`,
4. `application_exceptions.<employer_key>`.

Use prefixed `answers.*` only for true site/platform oddities:

```yaml
value: "{{ answers.ua_referral_source }}"
value: "{{ answers.nyulangone_degree }}"
value: "{{ answers.cuhk_publication_type }}"
value: "{{ answers.interfolio_discipline }}"
```

For made-up account values, such as site usernames that must be generated per
run, use a playbook `generated_values` entry and fill the field from the same
template. Do not ask the applicant to pre-answer those values:

```yaml
generated_values:
  - key: account.utah_user_name
    label: "Utah username"
    value: "ut{{ builtins.short_unique }}"
```

The runner records rendered generated values locally in
`.run/generated-values.jsonl`, which is gitignored.

Every new playbook should set a stable `employer_key`:

```yaml
employer_key: "umn"
```

That key is how the runner selects `application_exceptions.umn`.

## Equivalence Matching

The option matcher is deterministic and does not require AI. It is implemented in
[`playbook_runner/equivalences.py`](../playbook_runner/equivalences.py).

For `select`, `check`, and `pick`, the runner:

1. renders the desired value from the applicant context,
2. tries exact matching,
3. reads the live options/labels from the page,
4. normalizes capitalization, punctuation, accents, dots, and spacing,
5. scores against context-aware alias groups,
6. selects the safest match or fails clearly.

Examples:

- `TX` can match `Texas`.
- `U.S.A.`, `USA`, and `United States of America` are treated alike.
- `M` can match `Male` only when the field context is gender/sex.
- `Job Board` can match known job-board/source wording.
- A numeric salary like `82000` can match a live range such as `$80,000 - $99,999`.

For native `<select>` elements, the playbook does not need to list every option;
the runner reads the live options at runtime. For custom comboboxes/typeaheads,
the playbook may need `press`, `click`, `search_dialog`, or a specific selector
because options often render only after opening or typing.

If a new form uses unknown wording, run with `--screenshot-dir`. A failed option
match can write `equivalence-gap.json` beside the screenshot and HTML. After a
human confirms the right live option, promote it:

```bash
python3 tools/accept_equivalence_gap.py \
  shots/site/error-step-###/equivalence-gap.json \
  --group referral \
  --candidate-index 3
```

This updates [`information/custom_equivalences.json`](../information/custom_equivalences.json)
so future playbooks benefit without per-site overrides.

## Playbook Writing Rules

- Prefer visible labels and stable selectors; never use brittle full DevTools
  copied selectors like `body > div:nth-child(...)`.
- Keep a readable label even when a selector is present because logs and
  equivalence context use it.
- Use `select` for native dropdowns.
- Use `press` or explicit open/type/click steps for custom widgets.
- Use `pick` for yes/no/decline radio groups, checkbox groups, or dropdowns driven
  by a profile value.
- Put `scope` inside the `pick:` mapping, not beside it.
- Use `scope` for repeated yes/no groups so the runner clicks the correct group.
- Use `upload` for file inputs and canonical document paths.
- Use `wait_for` when the next page/section loads asynchronously.
- Keep final submit, certify, withdraw, delete, and payment-like actions commented.
- Do not invent sensitive answers. If a sensitive answer is missing, leave a TODO
  or require an applicant-specific value.
- Do not add felony, SSN, government ID, banking, payment, or final attestation
  answers to general defaults.

Example `pick`:

```yaml
- pick:
    group: "Will you now or in the future require visa sponsorship?"
    scope: 'input[type=radio][name="requiresSponsorship"]'
    source: app_answers.requires_visa_sponsorship
    map:
      true: "Yes"
      false: "No"
```

Example salary dropdown:

```yaml
- select: "Desired Salary"
  value: "{{ app_answers.desired_salary }}"
```

## Form Extractor Notes

Extractor output is drafting evidence, not a finished playbook.

Use:

- labels,
- stable selectors,
- option lists,
- custom widget notes,
- iframes,
- visible validation errors,
- `data_hint`,
- `suggested_template`,
- `review_flags`,
- likely exclusive checkbox groups.

Treat `hidden_controls` as informational unless the workflow deliberately reveals
them. If visible validation errors appear in the extractor output, the draft
probably needs to fix an earlier step rather than fill fields on an error page.

For very long dropdowns such as schools, employers, countries, and disciplines,
confirm the expected option exists or use the widget's real search/typeahead
behavior.

## Previous Interfolio Attempt

The prior Interfolio playbook attempt in this repo is
[`playbooks/yale.playbook.yaml`](../playbooks/yale.playbook.yaml):

- Yale Senior Lecturer application.
- `job_id: "185331"`.
- `employer_key: "yale"`.
- `url: "https://apply.interfolio.com/185331"`.

UCI and UCSB are not Interfolio playbooks. They are UC Recruit/AP Recruit:

- [`playbooks/uci.playbook.yaml`](../playbooks/uci.playbook.yaml)
- [`playbooks/ucsb.playbook.yaml`](../playbooks/ucsb.playbook.yaml)

Yale/Interfolio lessons:

- The Interfolio SPA may render slowly; explicit `wait_for` steps are often better
  than relying on `networkidle`.
- Cookie banners are timing/session dependent.
- Account creation, profile setup, dossier onboarding, returning to the job
  posting, and the application packet are distinct phases.
- Dossier application URLs can contain dynamic per-account IDs, so reopen the
  public posting and click `Apply Now` instead of hard-coding packet URLs.
- Angular/Material/custom controls may need `press` or open/type/click workflows.
- Repeated `Add File` buttons often need stable section targeting or carefully
  verified positional XPath.
- The historical failure bundle at `shots/yale-rao/error-step-002/` failed on
  `Apply Now` while the page URL was `about:blank`; that points to a navigation or
  start-state issue, not an equivalence mismatch.

Current Interfolio-specific answer keys seen in the fake profiles/playbook:

```text
answers.interfolio_state
answers.interfolio_position_status
answers.interfolio_referral_source
answers.interfolio_discipline
```

When drafting future Interfolio playbooks, prefer migrating reusable values to
`app_answers.*` where they have normal application meaning. Keep only true
Interfolio/platform setup values under `answers.interfolio_*`.

## Fresh Prompt Template

Paste this into a new AI session:

```text
You are drafting a project-playbook YAML playbook. First read
docs/ai-playbook-drafting-context.md, SPEC.md, docs/application-answer-system.md,
and the form-extractor output I provide. Draft deterministic Playwright steps;
do not rely on AI at runtime. Use canonical profile paths for applicant facts,
app_answers.* for reusable application answers, and prefixed answers.* only for
true site-specific values. Preserve stable selectors from the extractor, use
pick with scope for repeated choice groups, keep final submit commented, and
leave TODOs instead of inventing sensitive or missing answers.
```

## Key Files

- [`README.md`](../README.md): quick project usage.
- [`SPEC.md`](../SPEC.md): YAML playbook format.
- [`docs/application-answer-system.md`](application-answer-system.md): full
  profile/defaults/exceptions/equivalence architecture.
- [`docs/applicant-profile-questions.md`](applicant-profile-questions.md): intake
  questions and permitted profile answers.
- [`tools/form-extractor.js`](../tools/form-extractor.js): page capture tool.
- [`tools/accept_equivalence_gap.py`](../tools/accept_equivalence_gap.py): promotes
  confirmed option aliases from failed runs.
- [`information/test.json`](../information/test.json): canonical blank profile
  schema.
- [`information/custom_equivalences.json`](../information/custom_equivalences.json):
  learned shared option aliases.
- [`past_attempts/`](../past_attempts/): archived experiments, including the
  terminal draft generator and AI runtime recovery/copilot. These are reference
  material, not the active workflow.
