# Application Answer System

This document explains the recent applicant-profile, application-defaults,
employer-exceptions, and equivalence-matching updates. It is the map for how the
current runner works and how the same model should become the future website
experience.

## Goal

The project is moving away from asking AI to interpret forms during a normal
application run. Instead, the runner should use:

- one structured applicant profile,
- reusable default answers for common application questions,
- employer-specific exceptions only when needed,
- deterministic option equivalences for dropdowns/radios/checkboxes,
- playbooks that declare the workflow but do not hard-code every applicant's
  answer in site-specific wording.

The intended outcome is that applicants answer stable questions once, playbooks
stay easier to write, and the runner adapts common wording differences like
`TX` versus `Texas`, `Job Board` versus `Web-based job posting board`, and
`false` versus `No, I do not require visa sponsorship`.

## The Data Layers

The runner now thinks about data in three layers.

### 1. Canonical Profile Facts

Canonical facts are stable facts about the applicant. They should live in their
natural profile location and should not be duplicated per employer.

Examples:

```text
person_name.legal_name.first
address_and_contact.primary_address.state_province
education.schools.0.institution
work_history.0.job_title
documents.resume_path_or_url
```

Playbooks should use these paths directly when the form is asking for the
actual applicant fact:

```yaml
- fill: "First Name"
  value: "{{ person_name.legal_name.first }}"

- upload: "Resume"
  value: "{{ documents.resume_path_or_url }}"
```

### 2. General Application Defaults

Application defaults are answers to common application questions where the
applicant usually wants one answer reused across many employers.

These live under `application_defaults`:

```json
"application_defaults": {
  "authorized_to_work_us": true,
  "requires_visa_sponsorship": false,
  "desired_salary": "82000",
  "salary_period": "annual",
  "referral_source": "Job Board",
  "specific_referral_source": "",
  "employee_referral": false,
  "employee_referrer_name": "",
  "employee_referrer_relationship": "",
  "previously_employed_by_employer": false,
  "previously_employed_by_employer_details": "",
  "previous_employer_employee_id": "",
  "related_to_employer_employee": false,
  "related_to_employer_employee_details": "",
  "has_conflict_of_interest": false,
  "has_conflict_of_interest_details": "",
  "claims_veterans_preference": false,
  "excluded_from_government_program": false,
  "excluded_from_government_program_details": "N/A"
}
```

These are not facts about one specific school. They are the applicant's normal
default answers when a form asks a repeated screening/source/relationship
question.

### 3. Employer Exceptions

Employer exceptions are only for cases where the default answer is wrong for
one employer or platform. They live under `application_exceptions.<employer_key>`.

Example:

```json
"application_exceptions": {
  "nyulangone": {
    "previously_employed_by_employer": true,
    "previously_employed_by_employer_details": "Research collaboration appointment, Biostatistics Core, June 2022 to August 2022.",
    "previous_employer_employee_id": "N/A"
  },
  "umn": {
    "referral_source": "HERC - Higher Education Recruitment Consortium",
    "specific_referral_source": "HERC statistics faculty mailing list"
  }
}
```

The key, such as `nyulangone` or `umn`, comes from the playbook's
`employer_key`.

## Generated `app_answers`

Playbooks do not read `application_defaults` and `application_exceptions`
directly. The runner generates a merged namespace called `app_answers`.

For a playbook with:

```yaml
employer_key: "nyulangone"
```

the runner builds `app_answers` in this order:

1. canonical facts derived from the structured applicant profile,
2. legacy `answers.*` values so older profiles keep working,
3. `application_defaults`,
4. `application_exceptions.nyulangone`.

Later layers win. This means the playbook can simply write:

```yaml
source: app_answers.previously_employed_by_employer
value: "{{ app_answers.referral_source }}"
value: "{{ app_answers.desired_salary }}"
```

and it does not need to know whether the value came from a default, a canonical
profile field, a legacy answer, or an employer exception.

The loader also ignores `null` values inside the new defaults/exceptions layer
so an incomplete blank profile does not erase a real derived value. Legacy
`answers.*` still preserves `null` because older override files may use it
intentionally.

Implementation:

- [`playbook_runner/context.py`](../playbook_runner/context.py) loads data,
  deep-merges data files, expands templates, and builds `app_answers`.
- [`playbook_runner/parser.py`](../playbook_runner/parser.py) reads
  `employer_key`, `application_key`, or `site_key` from playbooks.
- [`playbook_runner/cli.py`](../playbook_runner/cli.py) passes the playbook key
  into the context loader.

## Deep Merge Data Files

Multiple `-d` files now merge recursively.

Example command:

```bash
.venv/bin/python -m playbook_runner playbooks/umn.playbook.yaml \
  -d applicants/test.json \
  -d applicants/umn_overrides.json \
  --validate
```

Earlier behavior was a shallow top-level merge. If the override file contained
`answers`, it could replace the whole base `answers` object. Now dictionaries
merge recursively:

```text
// base
{
  "answers": {
    "referral_source": "Job Board",
    "gender": "Female"
  }
}

// override
{
  "answers": {
    "referral_source": "HERC"
  }
}
```

Result:

```json
{
  "answers": {
    "referral_source": "HERC",
    "gender": "Female"
  }
}
```

Lists and scalar values still replace earlier values. This makes small override
files much safer.

## Equivalence Matching

The equivalence layer is deterministic. It is not AI, and it does not randomly
try every option until something happens to work.

When a playbook selects or checks an option, the runner does this:

1. Render the playbook value from the applicant context.
2. Try exact matching first.
3. If exact matching fails, read the live available options/labels from the
   page.
4. Normalize the desired value and the live candidates.
5. Score candidates through context-aware alias groups.
6. Select/click the safest best match.
7. Fail with a clear error if there is no safe match.

For native dropdowns, the available options come from the live page's
`<option>` elements at runtime. The playbook writer usually does not need to
list all possible options ahead of time.

For radio and checkbox groups, the runner inspects the input labels/values in
the relevant group or scope.

Implementation:

- [`playbook_runner/equivalences.py`](../playbook_runner/equivalences.py)
  contains normalization, alias groups, context activation, scoring, and tie
  handling.
- [`information/custom_equivalences.json`](../information/custom_equivalences.json)
  contains shared aliases learned from real application forms without changing
  code.
- [`playbook_runner/engine.py`](../playbook_runner/engine.py) calls the matcher
  for `select`, `check`, scoped radio/checkbox matching, and `pick`, and writes
  `equivalence-gap.json` when a safe option match cannot be found.
- [`tools/accept_equivalence_gap.py`](../tools/accept_equivalence_gap.py)
  promotes a confirmed failed option match into the shared custom equivalence
  file.
- [`tests/test_equivalences.py`](../tests/test_equivalences.py) covers important
  matching cases and non-matches.

### What Is Matched

Current equivalence groups include:

- yes/no,
- decline/prefer-not-to-answer wording,
- gender,
- degree labels,
- phone number types,
- race/ethnicity,
- veteran status,
- disability status,
- citizenship status,
- work authorization,
- visa sponsorship,
- education/employment status,
- referral source,
- salary period,
- US states,
- Canadian provinces,
- common country names.

Capitalization, punctuation, accents, and spacing are ignored for matching.
For example, `u.s.a.`, `USA`, and `U S A` normalize to comparable forms.

Custom learned aliases live in `information/custom_equivalences.json`:

```json
{
  "groups": {
    "referral": {
      "job board": ["Web-based Job Posting Board"]
    }
  },
  "context_hints": {
    "referral": ["Application Source"]
  }
}
```

These aliases are global wording fixes, not applicant-specific answers. For
example, `Web-based Job Posting Board` can be a global alias for `Job Board`;
"I know Professor Smith at UCI" belongs in that applicant's
`application_exceptions.uci`, not in the equivalence file.

### Context-Aware Matching

Some abbreviations are dangerous globally. For example:

- `M` can mean `Male`,
- `M` can also be part of a marital-status or size dropdown,
- `IN` can mean `Indiana`,
- `in` can also be an ordinary word.

So abbreviation-heavy groups only activate when the field/question label gives
the right context.

Example:

```yaml
- select: "Gender"
  value: "M"
```

can match `Male`.

But this should not:

```yaml
- select: "Marital Status"
  value: "M"
```

This is why playbooks should use useful field/group labels, even when a
selector is present.

## How Playbooks Should Be Written Now

Use canonical paths for stable facts:

```yaml
value: "{{ person_name.legal_name.first }}"
value: "{{ education.schools.0.institution }}"
value: "{{ documents.resume_path_or_url }}"
```

Use `app_answers.*` for repeated application questions:

```yaml
value: "{{ app_answers.referral_source }}"
source: app_answers.requires_visa_sponsorship
source: app_answers.previously_employed_by_employer
value: "{{ app_answers.desired_salary }}"
```

Use prefixed `answers.*` only for true site/platform weirdness:

```yaml
value: "{{ answers.ua_referral_source }}"
value: "{{ answers.nyulangone_degree }}"
value: "{{ answers.cuhk_publication_type }}"
```

For repeated yes/no radio groups, use `group` and/or `scope` so the runner does
not click the wrong repeated `Yes`/`No`:

```yaml
- pick:
    group: "Have you ever been employed by this employer?"
    scope: 'input[type=radio][name="previousEmployee"]'
    source: app_answers.previously_employed_by_employer
    map: { true: "Yes", false: "No" }
```

For native dropdowns, do not list every option in the playbook. Let the runner
read the live options.

For custom dropdowns, typeaheads, or popup search dialogs, the playbook may
still need a specific interaction pattern such as `press`, `search_dialog`, or
a stable selector. Those widgets often do not expose all options until after
typing or opening a popup.

## Salary Handling

Salary now works in two common form shapes.

General salary defaults live in `application_defaults.desired_salary`, and the
generated playbook path is `app_answers.desired_salary`. Playbooks can fill text
inputs with:

```yaml
value: "{{ app_answers.desired_salary }}"
```

For native salary dropdowns, the equivalence matcher can also parse visible
salary ranges. If `app_answers.desired_salary` is `"82000"` and the live options
are:

```text
$60,000 - $79,999
$80,000 - $99,999
$100,000+
```

the runner selects `$80,000 - $99,999`.

The matcher handles forms such as:

- `$60,000 - $79,999`
- `$80k-$99k`
- `100000+`
- `At least $100,000`
- `Under $50,000`
- `Up to $50k`

If no range contains the applicant's salary, the matcher may choose the nearest
range only when it is close to the boundary. It will not choose a far-away range
just to avoid failing.

The structured profile should keep richer salary preferences:

```json
"salary_expectation": {
  "currency": "USD",
  "amount_min": 82000,
  "amount_target": 90000,
  "amount_max": 105000,
  "period": "annual",
  "negotiable": true
}
```

`app_answers.desired_salary` is derived from `amount_target`, then `amount_min`,
then `amount_max`, unless the applicant has an explicit
`application_defaults.desired_salary`. This remains deterministic and does not
require AI.

## Missing Equivalence Repair Loop

When a new application uses wording the matcher does not know yet, the run
should fail once and leave enough evidence to fix the system for the future.

Run new playbooks with a screenshot directory:

```bash
.venv/bin/python -m playbook_runner playbooks/new-site.playbook.yaml \
  -d applicants/test.json \
  --slow-mo 300 \
  --screenshot-dir ./shots/new-site
```

If a native dropdown/radio/checkbox option cannot be matched, the failure folder
contains:

```text
shots/new-site/error-step-###/
  screenshot.png
  page.html
  failure.txt
  equivalence-gap.json
```

`equivalence-gap.json` records the playbook value, normalized value, field or
group context, active equivalence groups, and the live option labels/values the
page exposed. After confirming which live option is correct, promote it:

```bash
python3 tools/accept_equivalence_gap.py \
  shots/new-site/error-step-###/equivalence-gap.json \
  --group referral \
  --candidate-index 3
```

If the group is obvious from the field label, `--group` can be omitted. If the
field label did not activate the right group, pass `--group`; the tool will add
the failed field label as a context hint unless `--no-auto-context-hint` is
used.

Then rerun tests and validation:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m playbook_runner playbooks/new-site.playbook.yaml \
  -d applicants/test.json --validate
```

This gives us a repeatable maintenance loop: failures produce structured
artifacts, the helper updates one shared equivalence file, and future playbooks
benefit without AI and without one-off playbook overrides. The helper does not
guess the correct answer; it records the option that a maintainer or surrounding
automation explicitly chooses from the captured candidate list.

## Important Files

### Documentation

- [`README.md`](../README.md): project overview and quick usage. Now includes
  application defaults and recursive data merging.
- [`SPEC.md`](../SPEC.md): playbook format reference. Now includes
  `employer_key`, generated `app_answers`, and equivalence behavior.
- [`docs/applicant-profile-questions.md`](applicant-profile-questions.md):
  applicant intake blueprint. It lists the basic questions, permitted values,
  general defaults, and what should not be asked globally.
- [`docs/application-answer-system.md`](application-answer-system.md): this
  architecture/update document.
- [`docs/ai-playbook-drafting-context.md`](ai-playbook-drafting-context.md):
  pasteable background for a fresh AI/Codex/Claude prompt. It summarizes the
  deterministic drafting rules, data layers, equivalence repair loop,
  Interfolio/Yale history, and important files.
- [`docs/job-auto-apply-research.txt`](job-auto-apply-research.txt): research
  notes and product direction; updated to point at `app_answers` for reusable
  answers.
- [`docs/terminal-and-linux.md`](terminal-and-linux.md): terminal/setup help.

### Applicant Data

- [`information/test.json`](../information/test.json): canonical blank schema
  for the applicant profile. It now includes `application_defaults` and
  `application_exceptions`.
- [`information/custom_equivalences.json`](../information/custom_equivalences.json):
  shared learned aliases and context hints for deterministic option matching.
- [`applicants/test.json`](../applicants/test.json): fake general applicant
  profile with defaults filled in.
- [`applicants/test_stats_rao.json`](../applicants/test_stats_rao.json): fake
  statistics/biostatistics profile. Includes a `nyulangone` employer exception
  for prior work.
- [`applicants/test_stats_rodriguez.json`](../applicants/test_stats_rodriguez.json):
  fake statistics applicant profile with defaults.
- [`applicants/*_overrides.json`](../applicants/): legacy/application-layer data
  files used during debugging and validation. They still work because data files
  deep-merge and because legacy `answers.*` feeds into `app_answers`.
- [`applicants/uci.secret.json`](../applicants/uci.secret.json): local secret or
  sensitive override file. Secrets should stay out of committed general
  profiles.

### Runner Internals

- [`playbook_runner/context.py`](../playbook_runner/context.py): data loading,
  recursive merge, builtins, template refresh, and `app_answers` generation.
- [`playbook_runner/equivalences.py`](../playbook_runner/equivalences.py):
  deterministic option matching, alias groups, salary range parsing, custom
  equivalence loading, and gap-report creation.
- [`playbook_runner/engine.py`](../playbook_runner/engine.py): executes
  playbook actions and invokes equivalence matching for `select`, `check`, and
  `pick`; failed option matches write `equivalence-gap.json` when a screenshot
  directory is configured.
- [`playbook_runner/parser.py`](../playbook_runner/parser.py): parses playbooks,
  including `employer_key`.
- [`playbook_runner/cli.py`](../playbook_runner/cli.py): command-line entry
  point; passes the playbook key into the context loader.
- [`playbook_runner/conditions.py`](../playbook_runner/conditions.py): safe
  condition expression evaluator.
- [`playbook_runner/template.py`](../playbook_runner/template.py): resolves
  `{{ dotted.path }}` templates.

### Authoring Tools

- [`tools/form-extractor.js`](../tools/form-extractor.js): browser-console tool
  for capturing live form controls, labels, selectors, option lists, iframes,
  visible validation messages, data-path hints, review flags, likely exclusive
  checkbox groups, and conditional/modal fields. Its output is intentionally
  shaped for deterministic playbook authoring, not runtime AI.
- [`tools/accept_equivalence_gap.py`](../tools/accept_equivalence_gap.py):
  updates the shared custom equivalence file from a failed-run
  `equivalence-gap.json` artifact.

### Archived Attempts

- [`past_attempts/`](../past_attempts/): historical experiments and snapshots
  that are not part of the active workflow.
- [`past_attempts/terminal_draft_playbook.py`](../past_attempts/terminal_draft_playbook.py):
  former terminal paste-based playbook generator from extractor output.
- [`past_attempts/live_wizard_drafter.py`](../past_attempts/live_wizard_drafter.py):
  former live-page draft helper.
- [`past_attempts/ai_recovery.py`](../past_attempts/ai_recovery.py): former
  OpenAI-based runtime recovery/page copilot. The current approach is
  deterministic playbooks plus equivalence repair instead.
- [`past_attempts/project_snapshot_legacy/`](../past_attempts/project_snapshot_legacy/):
  old nested repo snapshot moved out of the active root.

### Tests

- [`tests/test_equivalences.py`](../tests/test_equivalences.py): verifies alias
  and context-sensitive option matching.
- [`tests/test_context.py`](../tests/test_context.py): verifies recursive data
  merge and `app_answers` generation/default/exception behavior.
- [`tests/test_dryrun.py`](../tests/test_dryrun.py): verifies that unresolved
  `pick` mappings are caught during validation.
- [`tests/test_equivalence_gap_tool.py`](../tests/test_equivalence_gap_tool.py):
  verifies the custom-equivalence repair helper.

### Playbooks

Each playbook now has an `employer_key`:

```yaml
employer_key: "umn"
```

Current playbooks:

- [`playbooks/umn.playbook.yaml`](../playbooks/umn.playbook.yaml)
- [`playbooks/uthealth.playbook.yaml`](../playbooks/uthealth.playbook.yaml)
- [`playbooks/nyulangone.playbook.yaml`](../playbooks/nyulangone.playbook.yaml)
- [`playbooks/ua.playbook.yaml`](../playbooks/ua.playbook.yaml)
- [`playbooks/uci.playbook.yaml`](../playbooks/uci.playbook.yaml)
- [`playbooks/ucsb.playbook.yaml`](../playbooks/ucsb.playbook.yaml)
- [`playbooks/yale.playbook.yaml`](../playbooks/yale.playbook.yaml)
- [`playbooks/cuhk.playbook.yaml`](../playbooks/cuhk.playbook.yaml)

Several playbooks now read common answers from `app_answers.*` instead of
site-specific `answers.*`.

## Overrides Versus Exceptions

Overrides and exceptions are related but not the same.

### Override Files

Override files are extra JSON files passed with `-d`. They can change any part
of the profile for a run:

```bash
-d applicants/test.json -d applicants/umn_overrides.json
```

They are useful for:

- debug/test data,
- alternate document paths,
- temporary login/email setup,
- old playbook compatibility,
- secret/local values that should not live in the base profile.

Because data files now deep-merge, override files can be much smaller and safer.

### Employer Exceptions

Employer exceptions live inside the applicant profile under
`application_exceptions.<employer_key>`.

They are best for:

- "I normally use Job Board, but for UMN use HERC",
- "I normally have not worked for the employer, but I did work for NYU Langone",
- "I normally have no related employee, but at this school my spouse works in a
  department".

Long term, the website should prefer employer exceptions for answer differences
and reserve separate override files for developer/debug/secrets workflows.

## Website Application Vision

The website should make this model invisible to normal applicants. They should
not think in terms of YAML, `app_answers`, or JSON paths.

### 1. General Profile Onboarding

Ask for the basic canonical profile:

- name,
- contact info,
- address,
- work authorization,
- sponsorship,
- education,
- current/recent employment,
- documents,
- references,
- voluntary demographics with decline options.

Then ask general application defaults:

- default referral/source,
- desired salary,
- prior employer default,
- related employee default,
- conflict-of-interest default,
- employee-referral default/details when applicable.

The UI phrasing should be:

> "What should we answer by default when applications ask this?"

not:

> "Answer this question for every employer now."

### 2. Playbook-Specific Review

When the user chooses a specific application, the website should read the
playbook's `employer_key` and eventually its declared required answer metadata.

The review page should show:

```text
For NYU Langone, we will use:

Referral source: Job Board
Previously employed here: No
Related to an employee: No
Conflict of interest: No
Desired salary: $82,000
```

Each row should have an edit action. If the user edits a value for this
employer only, the website saves an employer exception:

```json
"application_exceptions": {
  "nyulangone": {
    "previously_employed_by_employer": true,
    "previously_employed_by_employer_details": "Research collaboration appointment..."
  }
}
```

### 3. Unique Playbook Questions

Every playbook should eventually declare the application-specific answers it
needs. A future playbook section could look like:

```yaml
required_app_answers:
  - key: referral_source
    defaultable: true
  - key: previously_employed_by_employer
    defaultable: true
  - key: nyulangone_degree
    defaultable: false
```

The website can then:

- show defaultable questions prefilled from `app_answers`,
- ask only missing required values,
- allow optional questions to be skipped,
- save changed reusable values as employer exceptions,
- save true platform-specific answers under prefixed `answers.*`.

This prevents onboarding from becoming a 200-question form while still making
each application review honest and complete.

### 4. Run Readiness

Before launching a playbook, the website should validate:

- required canonical profile fields,
- required documents,
- general defaults used by the playbook,
- employer exceptions if the user changed them,
- playbook templates via the runner's existing `--validate` behavior.

If validation fails, the website should show the missing fields in applicant
language, not raw JSON paths.

### 5. Human Review Before Submit

The website should keep final submission under human control. Automated filling
can handle the repetitive work, but final attestation/submission should be
reviewed by the applicant.

## Current Status

Implemented:

- Recursive data merge.
- Generated `app_answers`.
- Playbook `employer_key`.
- General application defaults in the canonical schema and fake profiles.
- Employer exceptions in fake profile data.
- Equivalence matching for common option wording differences.
- Salary range matching for native dropdown options.
- Structured `equivalence-gap.json` artifacts for missing option matches.
- Shared `custom_equivalences.json` plus a helper tool for learned aliases.
- Validation now treats a `pick` with no matching map/default as a problem.
- Playbook migrations for several common answer fields.
- Active docs now direct new playbooks toward extractor evidence plus
  hand-reviewed YAML, not terminal-generated drafts.
- Past attempts are grouped under `past_attempts/`.
- Fresh-prompt context doc for AI-assisted drafting/debugging.
- Tests for context merging and equivalence matching.

Validated:

- Unit tests for context/equivalences.
- Full validation matrix across fake profiles, playbooks, and legacy override
  combinations.

Still to build:

- Explicit `required_app_answers` metadata in playbooks.
- Website UI for defaults/exceptions review.
- Better migration away from legacy override files where possible.
- More equivalence groups as real forms reveal new categories, not merely new
  wording inside existing categories.

## Practical Authoring Rules

For new playbooks:

1. Use canonical profile paths for stable facts.
2. Use `app_answers.*` for common repeated application questions.
3. Use `answers.<platform>_*` only for true platform/site-specific fields.
4. Give fields/groups clear labels because equivalence matching uses context.
5. Use `scope` for repeated yes/no groups.
6. Do not list every native dropdown option in the playbook unless documenting
   helpful context.
7. Use extractor captures for custom widgets, hidden fields, typeaheads,
   validation errors, and checkbox choice groups.
8. Keep sensitive/legal/financial answers out of general defaults.
9. Run new playbooks with `--screenshot-dir`; if an option mismatch produces
   `equivalence-gap.json`, promote the confirmed wording into
   `information/custom_equivalences.json` instead of patching one playbook.
