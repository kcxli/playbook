"""Draft a ``.playbook.yaml`` automatically from a live application form.

    python -m playbook_runner wizard <url> [-o playbooks/new.playbook.yaml]

Opens the URL in a browser, scrapes every form control (the same DOM logic as
``tools/form-extractor.js``, but returning structured data), guesses which
applicant-data path each field wants, and prints a draft playbook. The draft is
a *starting point*: fields it can't map are marked ``# TODO``, dropdown options
are listed as comments so you can pick the exact text, and radio groups become
``pick`` skeletons. Review it, then validate with ``--validate`` / ``--dry-run``.

It scrapes the page it lands on (usually the first page of a multi-page flow).
For later pages, re-run the wizard on each, or add the steps by hand.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any


# ── field-label → applicant-data heuristics ────────────────────────────────
# Checked in order, first match wins, so put the MOST SPECIFIC patterns first
# ("first name" before the generic "name"). Each value is a template the runner
# will resolve against the applicant JSON.
_FILL_RULES: list[tuple[str, str]] = [
    ("first name", "{{ person_name.legal_name.first }}"),
    ("given name", "{{ person_name.legal_name.first }}"),
    ("middle name", "{{ person_name.legal_name.middle }}"),
    ("middle initial", "{{ person_name.legal_name.initials }}"),
    ("last name", "{{ person_name.legal_name.last }}"),
    ("family name", "{{ person_name.legal_name.last }}"),
    ("surname", "{{ person_name.legal_name.last }}"),
    ("preferred name", "{{ person_name.preferred_name.preferred_first }}"),
    ("user name", "{{ account.user_name }}"),
    ("username", "{{ account.user_name }}"),
    ("user id", "{{ account.user_name }}"),
    ("login", "{{ account.user_name }}"),
    ("password", "{{ account.password }}"),  # also covers confirm/re-enter password
    ("e-mail", "{{ emails.institution_email }}"),
    ("email", "{{ emails.institution_email }}"),
    ("date of birth", "{{ detailed_personal_info.date_of_birth }}"),
    ("birth date", "{{ detailed_personal_info.date_of_birth }}"),
    ("address line 2", "{{ address_and_contact.primary_address.line_2 }}"),
    ("address 2", "{{ address_and_contact.primary_address.line_2 }}"),
    ("apartment", "{{ address_and_contact.primary_address.line_2 }}"),
    ("suite", "{{ address_and_contact.primary_address.line_2 }}"),
    ("address line 1", "{{ address_and_contact.primary_address.line_1 }}"),
    ("address 1", "{{ address_and_contact.primary_address.line_1 }}"),
    ("street address", "{{ address_and_contact.primary_address.line_1 }}"),
    ("address", "{{ address_and_contact.primary_address.line_1 }}"),
    ("county", "{{ answers.county }}"),
    ("country", "{{ address_and_contact.primary_address.country }}"),
    ("city", "{{ address_and_contact.primary_address.city }}"),
    ("state", "{{ address_and_contact.primary_address.state_province }}"),
    ("province", "{{ address_and_contact.primary_address.state_province }}"),
    ("zip", "{{ address_and_contact.primary_address.postal_code }}"),
    ("postal", "{{ address_and_contact.primary_address.postal_code }}"),
    ("mobile", "{{ address_and_contact.phone_numbers.mobile }}"),
    ("cell", "{{ address_and_contact.phone_numbers.mobile }}"),
    ("phone", "{{ address_and_contact.phone_numbers.mobile }}"),
    ("salary", "{{ answers.desired_salary }}"),
    ("compensation", "{{ answers.desired_salary }}"),
    ("major", "{{ answers.major }}"),
    ("field of study", "{{ answers.major }}"),
    ("institution", "{{ answers.school }}"),
    ("school", "{{ answers.school }}"),
    ("university", "{{ answers.school }}"),
    ("college", "{{ answers.school }}"),
    ("highest level", "{{ answers.highest_education }}"),
    ("highest education", "{{ answers.highest_education }}"),
    ("education level", "{{ answers.highest_education }}"),
    ("degree", "{{ answers.degree }}"),
    ("today", "{{ builtins.today }}"),
    ("date", "{{ builtins.today }}"),
    ("full name", "{{ person_name.legal_name.first }} {{ person_name.legal_name.last }}"),
    ("name", "{{ person_name.legal_name.first }} {{ person_name.legal_name.last }}"),
]

# Upload labels → which document to attach.
_UPLOAD_RULES: list[tuple[str, str]] = [
    ("cover letter", "{{ documents.cover_letter_path_or_url }}"),
    ("resume", "{{ documents.resume_path_or_url }}"),
    ("cv", "{{ documents.resume_path_or_url }}"),
    ("c.v", "{{ documents.resume_path_or_url }}"),
    ("teaching statement", "{{ documents.teaching_statement_path }}"),
    ("syllabus", "{{ documents.syllabus_path }}"),
    ("reference", "{{ documents.references_path }}"),
    ("transcript", "{{ documents.transcript_path }}"),
]

# Radio/checkbox question text → the data path that drives it (for pick skeletons).
_RADIO_SOURCE_RULES: list[tuple[str, str]] = [
    ("hispanic", "answers.is_hispanic_or_latino"),
    ("latino", "answers.is_hispanic_or_latino"),
    ("race", "answers.race_ethnicity"),
    ("ethnic", "answers.race_ethnicity"),
    ("gender", "answers.gender"),
    ("disab", "detailed_personal_info.disability_status.value"),
    ("veteran", "answers.is_veteran"),
    ("sponsor", "detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship"),
    ("visa", "detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship"),
    ("authorized to work", "answers.authorized_to_work_us"),
]

# Input types that map to a value regardless of label text.
_TYPE_RULES: dict[str, str] = {
    "email": "{{ emails.institution_email }}",
    "tel": "{{ address_and_contact.phone_numbers.mobile }}",
    "password": "{{ account.password }}",
}


def _norm(label: str) -> str:
    """Lowercase, strip trailing punctuation/markers, collapse whitespace."""
    text = " ".join((label or "").split()).strip().lower()
    return text.rstrip(" :*").strip()


def _match(label: str, rules: list[tuple[str, str]]) -> str | None:
    norm = _norm(label)
    for needle, template in rules:
        if needle in norm:
            return template
    return None


def guess_fill_value(label: str, input_type: str = "text") -> str | None:
    if input_type in _TYPE_RULES and "birth" not in _norm(label):
        return _TYPE_RULES[input_type]
    if input_type == "date" and "birth" not in _norm(label):
        return "{{ builtins.today }}"
    return _match(label, _FILL_RULES)


def guess_upload_value(label: str) -> str:
    return _match(label, _UPLOAD_RULES) or "{{ documents.resume_path_or_url }}"


def guess_radio_source(question: str, options: list[str]) -> str | None:
    blob = _norm(question) + " " + " ".join(_norm(o) for o in options)
    for needle, path in _RADIO_SOURCE_RULES:
        if needle in blob:
            return path
    return None


# ── YAML string quoting ─────────────────────────────────────────────────────
def _q(value: Any) -> str:
    """Quote a scalar for YAML. Selectors often contain double quotes
    (``[id$="x"]``) so prefer single quotes when that avoids escaping."""
    s = str(value)
    if '"' in s and "'" not in s:
        return f"'{s}'"
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ── browser scrape ───────────────────────────────────────────────────────────
_EXTRACT_JS = r"""
() => {
  const vis = el => el.offsetParent !== null || el.getClientRects().length > 0;

  function labelFor(el) {
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap && wrap.innerText.trim()) return wrap.innerText.replace(el.value || '', '').trim();
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const r = document.getElementById(lb); if (r) return r.innerText.trim(); }
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return lg.innerText.trim(); }
    if (el.placeholder) return el.placeholder.trim();
    return '';
  }

  function sel(el) {
    if (el.id) {
      const volatile = /[a-z0-9]{8,}/i.test(el.id) && !/^[a-zA-Z][\w-]*$/.test(el.id);
      if (volatile) {
        const parts = el.id.split(/[-_$]/).filter(Boolean);
        const suffix = parts.slice(-2).join('_');
        return { sel: `[id$="${suffix}"]`, volatile: true };
      }
      return { sel: `#${el.id}`, volatile: false };
    }
    if (el.name) return { sel: `[name="${el.name}"]`, volatile: false };
    return { sel: '', volatile: false };
  }

  function opts(s) {
    return Array.from(s.options).map(o => o.text.trim())
      .filter(t => t && !/^(--.*--|select\.?\.?\.?|choose.*)$/i.test(t));
  }

  const out = { url: location.href, title: document.title,
    buttons: [], textInputs: [], textareas: [], selects: [], files: [],
    radioGroups: [], checkboxes: [] };

  Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a[role=button]'))
    .filter(vis).forEach(b => {
      const text = (b.innerText || b.value || b.getAttribute('aria-label') || '').trim();
      if (text) out.buttons.push({ text, ...sel(b) });
    });

  Array.from(document.querySelectorAll(
    'input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]):not([type=submit]):not([type=button])'
  )).filter(vis).forEach(el => {
    out.textInputs.push({ label: labelFor(el), type: (el.type || 'text'), ...sel(el) });
  });

  Array.from(document.querySelectorAll('textarea')).filter(vis).forEach(el => {
    out.textareas.push({ label: labelFor(el), ...sel(el) });
  });

  Array.from(document.querySelectorAll('select')).filter(vis).forEach(el => {
    out.selects.push({ label: labelFor(el), options: opts(el), ...sel(el) });
  });

  Array.from(document.querySelectorAll('input[type=file]')).filter(vis).forEach(el => {
    out.files.push({ label: labelFor(el), ...sel(el) });
  });

  const groups = {};
  Array.from(document.querySelectorAll('input[type=radio]')).filter(vis).forEach(r => {
    const name = r.name || '(unnamed)';
    if (!groups[name]) {
      const fs = r.closest('fieldset');
      const q = fs && fs.querySelector('legend') ? fs.querySelector('legend').innerText.trim() : '';
      groups[name] = { name, question: q, options: [] };
    }
    const lbl = labelFor(r);
    if (lbl && !groups[name].options.includes(lbl)) groups[name].options.push(lbl);
  });
  out.radioGroups = Object.values(groups);

  Array.from(document.querySelectorAll('input[type=checkbox]')).filter(vis).forEach(el => {
    out.checkboxes.push({ label: labelFor(el), ...sel(el) });
  });

  return out;
}
"""


def scrape(url: str, *, headless: bool, timeout: int, wait: float) -> dict[str, Any]:
    """Open the URL and return the structured form description."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            page = browser.new_context().new_page()
            page.set_default_timeout(timeout)
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=timeout)
            except Exception:
                pass
            if wait:
                page.wait_for_timeout(int(wait * 1000))
            return page.evaluate(_EXTRACT_JS)
        finally:
            browser.close()


# ── draft assembly ───────────────────────────────────────────────────────────
def build_playbook(data: dict[str, Any], *, name: str | None, url: str) -> tuple[str, int]:
    """Turn scraped form data into a draft playbook. Returns ``(yaml, n_steps)``."""
    title = (name or data.get("title") or "New").strip()
    out: list[str] = []
    todos = 0
    steps = 0

    out.append("# Draft playbook generated by `python -m playbook_runner wizard`")
    out.append(f"# Source : {url}")
    out.append(f"# Created: {date.today().isoformat()}")
    out.append("#")
    out.append("# ⚠ DRAFT of ONE page — review every line before using:")
    out.append("#   • Confirm each value path exists in your applicant JSON.")
    out.append("#   • Fields marked `# TODO` could not be mapped automatically.")
    out.append("#   • Dropdown options are listed as comments — set value to the exact text.")
    out.append("#   • Radio groups are emitted as commented `pick` skeletons; finish the map.")
    out.append("#   • Insert click steps (Next/Submit/...) from the button list at the bottom.")
    out.append("#   • Multi-page forms: re-run the wizard on each later page.")
    out.append("")
    out.append("version: 1")
    out.append(f"name: {_q(title + ' Application')}")
    out.append(f"url: {_q(url)}")
    out.append("")
    out.append("steps:")

    def emit_selector(item: dict[str, Any]) -> None:
        if item.get("sel"):
            note = "   # ⚠ volatile id — verify this suffix is stable" if item.get("volatile") else ""
            out.append(f"    selector: {_q(item['sel'])}{note}")

    text_fields = data.get("textInputs", []) + [
        {**t, "type": "textarea"} for t in data.get("textareas", [])
    ]
    if text_fields:
        out.append("")
        out.append("  # --- text fields ---")
        for f in text_fields:
            label = f.get("label") or "(unlabeled field)"
            value = guess_fill_value(label, f.get("type", "text"))
            out.append(f"  - fill: {_q(label)}")
            emit_selector(f)
            if value:
                out.append(f"    value: {_q(value)}")
            else:
                out.append('    value: ""   # TODO: map to applicant data')
                todos += 1
            steps += 1

    if data.get("selects"):
        out.append("")
        out.append("  # --- dropdowns ---")
        for s in data["selects"]:
            label = s.get("label") or "(unlabeled dropdown)"
            value = guess_fill_value(label)
            out.append(f"  - select: {_q(label)}")
            emit_selector(s)
            if value:
                out.append(f"    value: {_q(value)}")
            else:
                out.append('    value: ""   # TODO: set to one of the options below')
                todos += 1
            if s.get("options"):
                out.append(f"    # options: {' | '.join(s['options'])}")
            steps += 1

    if data.get("files"):
        out.append("")
        out.append("  # --- file uploads ---")
        for f in data["files"]:
            label = f.get("label") or "Upload"
            out.append(f"  - upload: {_q(label)}")
            emit_selector(f)
            out.append(f"    value: {_q(guess_upload_value(label))}")
            steps += 1

    if data.get("checkboxes"):
        out.append("")
        out.append("  # --- checkboxes (delete any you should NOT tick) ---")
        for c in data["checkboxes"]:
            label = c.get("label") or "(unlabeled checkbox)"
            out.append(f"  - check: {_q(label)}")
            emit_selector(c)
            steps += 1

    if data.get("radioGroups"):
        out.append("")
        out.append("  # --- radio groups: finish each `pick` then uncomment ---")
        for g in data["radioGroups"]:
            options = g.get("options", [])
            question = g.get("question") or (options[0] if options else "")
            out.append(f"  # group {_q(g.get('name', ''))}"
                       + (f"  question: {question}" if question else ""))
            out.append(f"  #   options: {' | '.join(options) if options else '(none found)'}")
            source = guess_radio_source(question, options)
            out.append("  # - pick:")
            if question:
                out.append(f"  #     group: {_q(question)}")
            if g.get("name") and g["name"] != "(unnamed)":
                out.append(f"  #     scope: 'input[type=radio][name=\"{g['name']}\"]'")
            out.append(f"  #     source: {source or 'answers.TODO'}")
            out.append("  #     map:   # keys are your data values; edit them to match `source`")
            for opt in options:
                out.append(f"  #       {_q(opt)}: {_q(opt)}")
            out.append("  #     default: \"I do not want to answer\"")
            todos += 1

    if data.get("buttons"):
        out.append("")
        out.append("  # --- buttons on this page (add click steps where they belong) ---")
        for b in data["buttons"]:
            sel = f"  selector: {b['sel']}" if b.get("sel") else ""
            out.append(f"  #   click: {_q(b['text'])}{sel}")

    out.append("")
    return "\n".join(out) + "\n", steps


# ── entry point ──────────────────────────────────────────────────────────────
def build_wizard_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m playbook_runner wizard",
        description="Open a URL, scrape its form, and draft a .playbook.yaml.",
    )
    p.add_argument("url", help="the application form URL to scrape")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="write the draft here (default: print to stdout)")
    p.add_argument("--name", help="playbook name: (default: derived from the page title)")
    p.add_argument("--headless", action="store_true",
                   help="scrape without a visible browser window")
    p.add_argument("--timeout", type=int, default=20000, metavar="MS",
                   help="page-load timeout in milliseconds (default 20000)")
    p.add_argument("--wait", type=float, default=2.0, metavar="SECONDS",
                   help="extra seconds to let a slow SPA finish rendering (default 2)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_wizard_parser().parse_args(argv)

    try:
        data = scrape(args.url, headless=args.headless, timeout=args.timeout, wait=args.wait)
    except Exception as exc:  # noqa: BLE001
        print(f"wizard error: {exc}", file=sys.stderr)
        if "executable doesn't exist" in str(exc).lower() or "playwright install" in str(exc).lower():
            print("hint: run  .venv/bin/python -m playwright install chromium", file=sys.stderr)
        return 1

    yaml_text, n_steps = build_playbook(data, name=args.name, url=args.url)

    if args.output:
        Path(args.output).write_text(yaml_text)
        print(f"✓ wrote draft to {args.output}  ({n_steps} steps drafted)", file=sys.stderr)
        print("  next: review the # TODO lines, then "
              f"`python -m playbook_runner {args.output} -d <data.json> --validate`",
              file=sys.stderr)
    else:
        print(yaml_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
