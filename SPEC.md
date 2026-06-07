# The `.playbook` format

A **playbook** is a YAML file describing, step by step, how to fill out and
submit one application form. The runner reads a playbook plus an applicant
**data file** (JSON), resolves every `{{ placeholder }}` from the data, evaluates
any conditions, and drives a real browser with Playwright.

Design goals: a colleague should be able to write a new playbook by copying an
existing one and editing visible labels — no programming required.

---

## File shape

```yaml
version: 1                       # optional, must be 1 if present
name: "UTHealth Taleo Application"
job_id: "260000AU"               # optional, informational
url: "https://.../jobapply.ftl?job=260000AU"   # opened automatically first

steps:
  - <step>
  - <step>
```

`url` (if given) is opened before the first step unless your steps already
begin with an explicit `open:`.

---

## Steps

Every step is a mapping with **exactly one action key** (the verb) plus optional
modifiers. The available verbs:

| Verb | Argument | Meaning |
|------|----------|---------|
| `open`   | URL | Navigate to a page |
| `click`  | accessible name | Click a button / link by its visible text |
| `fill`   | field label | Type into a text field (needs `value:`) |
| `select` | field label | Choose an option in a dropdown (needs `value:`) |
| `check`  | option label | Tick a checkbox / radio button |
| `upload` | field label | Attach a file (needs `value:` = file path) |
| `pick`   | (mapping)   | Choose an answer based on a data value — see below |
| `sleep`  | seconds | Wait (rarely needed) |

### Examples

```yaml
- open: "https://uth.taleo.net/careersection/jobapply.ftl?job=260000AU"

- click: "New User"

- fill: "Legal First Name"
  value: "{{ person_name.legal_name.first }}"

- select: "Country"
  value: "{{ address_and_contact.primary_address.country }}"

- check: "Select the resume/CV file to upload"

- upload: "Choose File"
  value: "{{ documents.resume_path_or_url }}"
```

The label you write is matched against the page's **visible text / accessible
name** (label text, button text, placeholder). It does not need to be exact —
matching is case-insensitive substring by default. Add `exact: true` to require
an exact match.

---

## Templating: `{{ ... }}`

Anywhere a string value appears (`value:`, `open:`, labels), `{{ path }}` is
replaced with a value pulled from the data file by dotted path:

```yaml
value: "{{ person_name.legal_name.first }}"
value: "{{ person_name.legal_name.first }} {{ person_name.legal_name.last }}"   # multiple OK
value: "{{ builtins.today }}"     # runner-supplied date, MM/DD/YYYY
```

- List elements use a numeric segment: `{{ education.schools.0.degree }}`.
- A path that is **missing or null raises an error** — so a required field is
  never silently submitted blank. Mark the step `optional: true` if a blank is
  acceptable.

Runner-supplied `builtins`: `today` (MM/DD/YYYY), `today_iso`, `year`,
`timestamp`, `unique` (a fresh per-run stamp), `run_id` (alias of `unique`).

### Self-refreshing data

`{{ ... }}` tokens are also expanded **inside the data file** when it loads, so a
profile can refresh itself each run. The most common use is collision-free
account credentials — no more hand-editing the username between runs:

```json
"account": {
  "user_name": "jdoe_{{ builtins.unique }}",
  "email":     "jane.doe+{{ builtins.unique }}@example.com"
},
"last_updated": "{{ builtins.today_iso }}"
```

Every run, `builtins.unique` becomes a new value (date + time + random tail), so
`user_name` and `email` come out fresh and consistent with each other. Data
tokens may reference any path (including other profile fields); expansion is a
single pass, so don't chain a token through another templated field.

---

## `pick`: choose an answer from a data value

Many forms ask Yes/No or tri-state questions driven by a single value in the
profile. `pick` maps that value to the answer to select, instead of writing a
chain of conditionals.

```yaml
# Dropdown (select) form:
- pick:
    field: "Will you require visa sponsorship?"     # the dropdown's label
    as: select
    source: detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship
    map: { true: "Yes", false: "No" }

# Checkbox / radio group form (tri-state with a fallback):
- pick:
    group: "5. F. I identify as a Veteran:"         # the question/fieldset text
    source: answers.is_veteran
    map: { true: "Yes", false: "No" }
    default: "I do not wish to provide this information"   # used if no key matches
```

- `source` is a **bare data path** (no braces) so its real type is preserved.
- `map` keys may be `true` / `false` / `null` or strings. The runner is tolerant
  of common spellings: a source of `"no"`, `"N"`, `0` all match the `false` key;
  `""`/`null` match the `null` key.
- `default` is selected when the source matches no key (e.g. value is `null`).
- `as:` is `select` (requires `field:`) or `check` (uses `group:` to scope which
  set of options, optional). It defaults to `check` when `group:` is present,
  otherwise `select`.

---

## Conditions: `when`

Add `when:` to any step to run it only if a condition holds:

```yaml
- fill: "Visa Type"
  value: "{{ detailed_personal_info.birth_and_citizenship.visa_status.type }}"
  when: "detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship == true"

- click: "Add another reference"
  when: 'answers.county != null and answers.county != ""'
```

Supported in conditions: data paths, string/number literals, `true`/`false`/
`null`, comparisons (`== != < > <= >=`), membership (`in`), and `and` / `or` /
`not` with parentheses. No arbitrary code runs — it is a small safe evaluator.

```yaml
when: '"disabled_veteran" in detailed_personal_info.veteran_status.protected_veteran_categories'
```

---

## Modifiers (allowed on any step)

| Modifier | Effect |
|----------|--------|
| `when:` | Run the step only if the condition is true |
| `optional: true` | If the element isn't found / fails, log and continue |
| `selector:` | Explicit CSS or `xpath=...` locator, bypassing label lookup |
| `exact: true` | Require an exact accessible-name match |
| `role:` | For `click`: `button` (default), `link`, or `tab` |
| `group:` | For `check`: question/fieldset text to scope the options |
| `wait_after:` | Seconds to pause after the step |
| `label:` | A human description shown in logs instead of the raw action |

### `selector:` — the escape hatch

Label-based lookup covers most fields, but legacy ATS markup (Taleo, Workday)
sometimes has unlabeled or duplicated controls. When a step can't find its
target, give it an explicit selector:

```yaml
- fill: "Cellular Number"
  selector: "#phoneNumber__cell"          # CSS
  value: "{{ address_and_contact.phone_numbers.mobile }}"

- check: "Yes"
  selector: "xpath=//legend[contains(.,'veteran')]/following::input[1]"
```

Keep a readable `target` (`fill: "Cellular Number"`) even when using a selector —
it's ignored for locating but keeps logs and `--dry-run` legible.

### Finding a selector

You need the field's element, then a *stable* attribute from it.

**On the live page (best):** right-click the field → **Inspect**. Read its
`id` / `name` in the Elements panel. Then confirm it's unique — in the DevTools
**Console**:

```js
document.querySelectorAll('#dialogTemplate-dialogForm-email')   // want length === 1
```

**From saved HTML:** every field is a `<label>` + `<input>` pair. Search the
file for the visible label text; the label's `for="..."` value is the input's
`id` (or read the `<input>`'s own `id`/`name`).

> ⚠️ Do **not** use DevTools "Copy → Copy selector". It produces a brittle
> absolute path (`body > div:nth-child(2) > form > …`) that breaks on any layout
> change. Hand-pick an attribute instead.

**Choosing the attribute — prefer the most stable:**

| Prefer | Selector | Use when |
|--------|----------|----------|
| static `id` | `#the-id` | the id looks human-authored (`dialogTemplate-dialogForm-email`) |
| stable id **fragment** | `[id$="ResumeUploadInputFile"]` | the id has a volatile chunk like `j_id_id16pc8` or `page_1` |
| `name` | `[name="…"]` | no usable id |
| type/attribute combo | `input[type=file]`, `select[id*="diversityBlock"]` | nothing unique alone — combine to narrow |

**Spotting a volatile id:** a chunk of random-looking letters/digits
(`j_id_id16pc8`, `page_1`) changes between sessions — never hardcode it. Match
the stable text around it with `[id$="…"]` (ends-with) or `[id*="…"]` (contains).

> **Selectors are only "deterministic" if they're stable.** A selector built on
> a volatile id is reliably *wrong* next session, and a clean visible label is
> often more durable than an auto-generated id. Reach for a selector when the
> label is unreliable (unlabeled, duplicated, late-rendering) or you want a hard
> guarantee — but always pick a stable handle, and verify it matches exactly one
> element.

---

## The data file

A JSON object. The runner merges one or more files passed with `-d` (later
overrides earlier) and adds the `builtins` namespace. Reference any key by path
in templates and conditions. See [applicants/test.json](applicants/test.json)
for the structure (built on [information/test.json](information/test.json) plus
two site-specific sections: `account` for the login and `answers` for
form-specific choices whose text must match the page's options exactly).

---

## Authoring workflow

1. Copy an existing playbook and update `url` / labels for the new form.
2. Run `--dry-run` to confirm every `{{ }}` resolves and `pick`/`when` behave:
   ```
   python -m playbook_runner playbooks/new.playbook.yaml -d applicants/jane.json --dry-run
   ```
3. Run for real with `--slow-mo 400` (and not `--headless`) so you can watch and
   spot any field that needs a `selector:` override.
4. Add `--screenshot-dir ./shots` so a failing step captures the page.
