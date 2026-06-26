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
| `wait_for` | label / text | Block until an element appears (robust alternative to `sleep`) |
| `scroll` | label, or `top`/`bottom` | Scroll an element into view, or the page to an edge |
| `hover`  | label | Move the pointer over an element (reveals hover menus) |
| `press`  | (description) | Send keystrokes / typeahead to a widget (needs `value:`) |
| `script` | (description) | Run a snippet of JavaScript on the page (needs `value:`) |
| `sleep`  | seconds | Wait a fixed time (prefer `wait_for`; use only as a last resort) |
| `await_email_link` | (mapping) | Read a just-arrived email over IMAP and follow the link inside it — see below |
| `await_email_code` | (mapping) | Read a just-arrived email over IMAP, extract a verification code, and fill it |
| `ai_fill_page` | (mapping) | Ask the bounded AI copilot to interpret and fill the current visible page from profile data |

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

## AI page copilot: `ai_fill_page`

`ai_fill_page` is for pages where a browser-extension-style assistant is more
useful than hand-written selectors. The runner captures the current page
snapshot, selected applicant-profile values, visible dialogs/validation errors,
and iframe controls, then asks the AI for a short list of ordinary playbook
actions. It still executes only normal runner verbs and blocks CAPTCHA,
payment/SSN/banking, and final-submit-like actions.

```yaml
- wait_for: "First name"

- ai_fill_page:
    allowed_sources:
      - person_name
      - emails
      - address_and_contact
      - education
      - work_history
      - answers
      - documents
    max_actions: 12
    instructions: "Fill the visible profile page only. Stop before any Next or Submit button."
```

Run with `--ai-recover`; the same model configuration powers failed-step
recovery and page copilot actions:

```bash
export OPENAI_API_KEY="..."
.venv/bin/python -m playbook_runner playbooks/example.playbook.yaml \
  -d applicants/test_stats_rao.json --ai-recover --screenshot-dir ./shots/example
```

Useful config keys:

| Key | Meaning |
|-----|---------|
| `allowed_sources` | Data namespaces or dotted paths the model may use. Defaults to common profile sections. |
| `max_actions` | Maximum actions returned by this one AI step, 1-30, default 12. |
| `min_confidence` | Override the CLI confidence threshold for this step. |
| `instructions` | Human guidance for the current page or section. |

---

## Timing verbs: `wait_for`, `scroll`, `hover`

These ATS pages re-render constantly via AJAX. The fragile way to cope is to
sprinkle `sleep`/`wait_after` and hope the guess is long enough. The robust way
is to **wait for the thing you need**:

```yaml
# Wait until a button/heading/field appears before continuing. Far better than
# guessing a sleep duration — it proceeds the instant the element is ready, and
# fails with a clear message if it never shows up.
- wait_for: "Apply Now"

# Wait on a specific element by selector, with a longer timeout for a slow SPA:
- wait_for: "application packet"
  selector: "#packet-root"
  timeout: 30000            # milliseconds (default is the run's --timeout)

# Scroll a control into view (some lazy-loaded forms only render on scroll, and
# off-screen buttons can be unclickable):
- scroll: "Submit Application"
- scroll: "bottom"          # or "top" — jump to the page edge

# Reveal a hover-triggered menu, then click the item it exposes:
- hover: "Account"
- click: "Sign out"
```

`wait_for` is the recommended replacement for most `sleep`/`wait_after` uses:
write `wait_for` the *next* element you're about to interact with, instead of
pausing a fixed number of seconds.

---

## Email magic-links: `await_email_link`

Some sign-ins are **passwordless**: the site emails you a one-time link and you
have to click it to continue (UC Recruit works exactly this way — enter email,
"Send verification email", then click the link). `await_email_link` closes that
gap: it watches a mailbox over IMAP, finds the message that just arrived, pulls
the link out of it, and navigates the browser there — no manual copy-paste, so a
run stays end-to-end.

```yaml
- click: "Send verification email"
- await_email_link:
    subject: "verif"          # only consider mail whose Subject contains this
    from: "recruit"           # optional: and whose From contains this
    link_pattern: 'https://recruit\.ap\.uci\.edu/[^\s"<>]+(verif|confirm|token)[^\s"<>]*'
    timeout: 240              # seconds to wait for the email (default 180)
    poll: 5                   # seconds between inbox checks (default 5)
  wait_after: 3
```

- **Credentials come from the environment, not the playbook** — set `IMAP_USER`
  and `IMAP_PASSWORD` (and optionally `IMAP_HOST`, default `imap.gmail.com`).
  For Gmail the password must be a **16-character app password** (Google Account
  → Security → 2-Step Verification → App passwords), not your normal login
  password. You *may* instead put templated `username:`/`password:` keys in the
  step (resolved from the data file) — keep those in a gitignored profile.
- It reads the inbox of **the address you applied with**. A convenient trick is a
  Gmail `+tag` alias: apply with `you+uci@gmail.com` (mail still lands in
  `you@gmail.com`), so each site is filterable and `IMAP_USER` stays your real
  address.
- **Only mail newer than the run's start counts**, so a stale link from an
  earlier run is never reused. `link_pattern` defaults to the first `http(s)`
  link; set it to target the real link and skip footer/logo URLs.

### Email verification codes: `await_email_code`

Some account-creation forms email a short code instead of a clickable link. Use
`await_email_code` after clicking the site's "Get Code" / "Send code" control:

```yaml
- click: "Get Code"
- await_email_code:
    field: "Verification Code"
    to: "{{ account.email }}"
    code_pattern: '\b([0-9]{4,8})\b'
    timeout: 240
```

Credentials and freshness rules are the same as `await_email_link`. If
`selector:` is provided on the step, it fills that control; otherwise it locates
the control by `field:`.

## Custom-widget verbs: `press`, `script`

Most controls are reachable with the verbs above. Two escape hatches handle the
widgets that aren't (custom dropdowns with no real `<option>`s, stuck overlays):

```yaml
# press: focus a control (via selector) and send keystrokes. `value` is a
# comma-separated list; a token that names a key (Enter, Tab, Escape, ArrowDown,
# Backspace, ...) is pressed as that key, anything else is typed as text. This
# drives typeahead widgets (Angular Material mat-select, comboboxes) that ignore
# select_option:
- press: "Select state"        # description for logs only
  selector: "#state"
  value: "{{ answers.interfolio_state }}, Enter"

# script: run a small piece of JavaScript on the page. Use sparingly — e.g. to
# dismiss an overlay that intercepts clicks:
- script: "Dismiss state overlay"   # description for logs only
  value: >
    var b = document.querySelector('.cdk-overlay-backdrop');
    if (b) { b.click(); }
```

For `press` and `script` the action argument is just a human-readable label for
the logs; the real work is in `value` (and, for `press`, the `selector:`).

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
| `role:` | For `click`: `button` (default), `link`, `tab`, or `option` |
| `group:` | For `check`: question/fieldset text to scope the options |
| `scope:` | CSS selector restricting which radio/checkbox set a `check`/`pick` targets |
| `wait_after:` | Seconds to pause after the step |
| `timeout:` | For `wait_for`: how long to wait, in milliseconds (overrides `--timeout`) |
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

1. **Extract the form** — open the page, open the DevTools console, and paste in
   [tools/form-extractor.js](tools/form-extractor.js). It prints every field's
   label, stable selector, and options, followed by a
   `PLAYBOOK_EXTRACT_JSON_START` / `PLAYBOOK_EXTRACT_JSON_END` block. Save the
   full output for the draft generator, or hand it to Claude/Codex to draft a
   playbook. Or start from an existing playbook: copy it and edit `url` /
   labels.
2. **Generate the first draft** when you have extractor output:
   ```
   python3 tools/draft_playbook.py \
     --collect \
     --name "Site Application" \
     --url "https://..." \
     --job-id "..." \
     --out playbooks/site.playbook.yaml
   ```
   Paste each page's full extractor output into that one running command. The
   generator saves each completed paste when it sees
   `PLAYBOOK_EXTRACT_JSON_END`, appends it to one combined capture file, and
   regenerates the same draft playbook. Press `Ctrl-D` only after the last
   page/state. Wait to hand-edit the generated playbook until the capture pass
   is done. The generator writes conservative field steps and comments out
   navigation/submit-like buttons until a human enables them.
3. **Finish the draft**: resolve the `# TODO` fields, set dropdown `value:`s to
   the exact option text (listed in comments), and complete any `pick` skeletons.
4. **Validate** that every `{{ }}` resolves, files exist, and `pick`/`when` behave:
   ```
   python -m playbook_runner playbooks/new.playbook.yaml -d applicants/jane.json --validate
   ```
5. **Run for real** with `--slow-mo 400` (and not `--headless`) so you can watch
   and spot any field that needs a `selector:` override. Prefer `wait_for` over
   `sleep` for any timing issues you hit.
6. Add `--screenshot-dir ./shots/<site>` so a failing step captures a targeted
   artifact bundle like `shots/<site>/error-step-048/`. Share that one folder
   (`screenshot.png`, `page.html`, `failure.txt`) when asking Codex to debug;
   avoid sending the whole historical `shots/` directory.
