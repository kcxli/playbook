"""Execute a parsed Playbook against a live browser via Playwright.

The engine maps each canonical action to resilient locator strategies. Real
ATS markup (Taleo, Workday, ...) is inconsistent, so every field lookup tries
several strategies in order and falls back to an explicit ``selector:`` override
when the playbook provides one.
"""
from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from . import conditions
from .artifacts import ensure_private_dir, make_private, write_private_text
from .context import DataError
from .equivalences import OptionCandidate, best_match, candidate_preview, equivalence_gap_report
from .parser import Playbook, Step
from .template import render_text, resolve_native


# Keyboard key names recognised by the ``press`` action (passed through to
# Playwright's keyboard.press); anything else is typed as literal text.
_NAMED_KEYS = {
    "Enter", "Tab", "Escape", "Backspace", "Delete", "Space",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Home", "End", "PageUp", "PageDown",
}


class StepError(Exception):
    def __init__(self, step: Step, message: str):
        self.step = step
        super().__init__(message)


def _xpath_literal(text: str) -> str:
    """Build an XPath string literal that survives embedded quotes."""
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    parts = text.split('"')
    return "concat(" + ", '\"', ".join(f'"{p}"' for p in parts) + ")"


def _selector_candidates(selector: str) -> list[str]:
    """Return selector fallbacks for common generated/CSS escaping mistakes."""
    out = [selector]
    if selector.startswith("#") and not any(ch in selector for ch in " >+~:["):
        raw_id = selector[1:].replace("\\$", "$")
        escaped = raw_id.replace("\\", "\\\\").replace('"', '\\"')
        attr = f'[id="{escaped}"]'
        if attr not in out:
            out.append(attr)
    return out


class Engine:
    def __init__(
        self,
        context: dict[str, Any],
        *,
        headless: bool = False,
        slow_mo: int = 0,
        default_timeout: int = 15000,
        screenshot_dir: str | None = None,
        pace: float = 0.0,
        log: Callable[[str], None] = print,
        human_prompt: Callable[[str], None] | None = None,
        email_handler: Callable[[str, dict[str, Any], float], str] | None = None,
    ):
        self.context = context
        self.headless = headless
        self.slow_mo = slow_mo
        self.default_timeout = default_timeout
        self.screenshot_dir = screenshot_dir
        self.pace = pace
        self.log = log
        self.human_prompt = human_prompt
        self.email_handler = email_handler
        self._pw = None
        self._browser = None
        self.page = None
        self._started_at = time.time()  # only await_email_link mail newer than this counts
        self._return_page = None
        self._recent_steps: list[str] = []
        self._last_equivalence_gap: dict[str, Any] | None = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "Engine":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)
        # Present a normal desktop-Chrome identity. Playwright's default headless
        # user-agent contains "HeadlessChrome", which some ATS/recruiting sites
        # (UC Recruit among them) bot-block by serving a blank page. A realistic
        # UA avoids that and changes nothing for sites that don't care.
        ctx = self._browser.new_context(
            accept_downloads=True,
            user_agent=os.environ.get(
                "PLAYBOOK_USER_AGENT",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ),
        )
        ctx.set_default_timeout(self.default_timeout)
        self.page = ctx.new_page()
        self._started_at = time.time()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    # -- run loop ----------------------------------------------------------
    def run(self, playbook: Playbook) -> None:
        if playbook.url and not any(s.kind == "open" for s in playbook.steps):
            self._step_log(f"→ open (from playbook url) {playbook.url}")
            self.page.goto(playbook.url)
            self._settle()

        for n, step in enumerate(playbook.steps, start=1):
            self._ensure_live_page()
            if step.when is not None and not conditions.evaluate(step.when, self.context):
                self._step_log(f"  · skip [{n}] {step.describe()}  (when: {step.when})")
                continue
            self._step_log(f"→ [{n}] {step.describe()}")
            try:
                self._last_equivalence_gap = None
                self._execute(step)
            except Exception as exc:  # noqa: BLE001 - we re-raise after handling
                if step.optional:
                    self._step_log(f"  ! optional step failed, continuing: {exc}")
                    continue
                self._on_error(n, step, exc)
                raise StepError(step, f"step [{n}] {step.describe()} failed: {exc}") from exc
            if step.wait_after:
                time.sleep(float(step.wait_after))
            elif self.pace:
                time.sleep(self.pace)

    # -- per-action dispatch ----------------------------------------------
    def _execute(self, step: Step) -> None:
        getattr(self, f"_do_{step.kind}")(step)

    def _do_open(self, step: Step) -> None:
        url = render_text(step.target, self.context)
        self.page.goto(url)
        self._settle()

    def _do_click(self, step: Step) -> None:
        name = render_text(step.target, self.context)
        loc = self._clickable(name, step)
        opener = self.page
        popup = None
        clicked = False
        timeout = int(step.timeout) if step.timeout else self.default_timeout
        try:
            with self.page.expect_popup(timeout=2500) as popup_info:
                loc.click(timeout=timeout, no_wait_after=True)
                clicked = True
            popup = popup_info.value
        except Exception:
            if not clicked:
                loc.click(timeout=timeout, no_wait_after=True)
        if popup is not None:
            self._return_page = opener
            self.page = popup
        self._settle()
        self._ensure_live_page()

    def _do_fill(self, step: Step) -> None:
        field = render_text(step.target, self.context)
        text = render_text(step.value, self.context)
        loc = self._control(field, step, kinds=("input", "textarea"))
        loc.fill(text)

    def _do_select(self, step: Step) -> None:
        field = render_text(step.target, self.context)
        option = render_text(step.value, self.context)
        self._select_on(field, option, step)

    def _do_check(self, step: Step) -> None:
        option = render_text(step.target, self.context)
        self._check_in_group(option, step.group, step, scope_sel=step.scope)

    def _do_upload(self, step: Step) -> None:
        field = render_text(step.target, self.context)
        path = render_text(step.value, self.context)
        if not Path(path).exists():
            raise DataError(f"upload file does not exist: {path}")

        # 1) explicit selector override.
        if step.selector:
            self._by_selector(step.selector).set_input_files(path)
            return
        # 2) a real <input type=file> somewhere (incl. iframes, even if hidden).
        loc = self._file_input(field)
        if loc is not None:
            loc.set_input_files(path)
            return
        # 3) styled button that opens a native file chooser when clicked.
        clickable = self._clickable(field, step)
        with self.page.expect_file_chooser(timeout=self.default_timeout) as fc:
            clickable.click()
        fc.value.set_files(path)

    def _do_sleep(self, step: Step) -> None:
        time.sleep(float(step.target))

    def _do_pause_for_user(self, step: Step) -> None:
        if self.headless:
            raise DataError("pause_for_user requires a visible browser")
        if self.human_prompt is None:
            raise DataError("pause_for_user requires a human-prompt callback")
        self.human_prompt(render_text(step.target, self.context))

    def _do_wait_for(self, step: Step) -> None:
        """Block until an element appears and is visible, then continue.

        The robust alternative to a blind ``sleep``/``wait_after`` on AJAX-heavy
        ATS pages: wait for the *thing you need* rather than guessing a duration.
        Waits for ``selector:`` if given, else any element matching the text.
        """
        timeout = int(step.timeout) if step.timeout else self.default_timeout
        target = render_text(step.target, self.context)
        deadline = time.monotonic() + max(timeout, 1000) / 1000.0
        while True:
            loc = self._locate_any(target, step)
            if loc is not None:
                try:
                    if loc.is_visible():
                        return
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                raise StepError(step, f"timed out after {timeout}ms waiting for: {target!r}")
            self._poll_pause()

    def _do_scroll(self, step: Step) -> None:
        """Scroll an element into view, or the page to ``top``/``bottom``."""
        target = render_text(step.target, self.context)
        if not step.selector and target.strip().lower() in ("top", "bottom"):
            y = "0" if target.strip().lower() == "top" else "document.body.scrollHeight"
            self.page.evaluate(f"window.scrollTo(0, {y})")
            return
        loc = self._locate_any(target, step)
        if loc is None:
            raise StepError(step, f"could not locate element to scroll to: {target!r}")
        loc.scroll_into_view_if_needed()

    def _do_hover(self, step: Step) -> None:
        """Hover the pointer over an element (to reveal hover menus, tooltips)."""
        name = render_text(step.target, self.context)
        loc = self._locate_any(name, step)
        if loc is None:
            raise StepError(step, f"could not locate element to hover: {name!r}")
        loc.hover()

    def _do_script(self, step: Step) -> None:
        js = render_text(step.value, self.context)
        self.page.evaluate(js)

    def _do_search_dialog(self, step: Step) -> None:
        """Drive a PageUp SearchDialog popup.

        PageUp lookup fields (Major, Company name) open a small
        ``SearchDialog.aspx`` window. The normal playbook verbs can miss that
        window if the browser doesn't report it as the current page, so this
        verb explicitly finds the dialog, searches, selects the best matching
        option, clicks Select, and returns to the opener.
        """
        label = render_text(step.target, self.context)
        query = render_text(step.value, self.context)
        opener = self._return_page if self._return_page else self.page
        dialog = self._find_search_dialog(label)
        if dialog is None:
            raise StepError(step, f"could not find PageUp search dialog for {label!r}")

        self.page = dialog
        dialog.locator("input[id$='MainContentPlaceHolder_SearchText'], input[type='text']").first.fill(query)
        search = dialog.locator(
            "input[id$='MainContentPlaceHolder_SearchButton'], "
            "input[value='Search'], button:has-text('Search'), input[type='button'][value='Search']"
        ).first
        if search.count() > 0:
            search.click()
            self._settle()

        selects = dialog.locator("select[id$='MainContentPlaceHolder_SearchSelectBox'], select")
        select = selects.last if selects.count() > 1 else selects.first
        select.wait_for(state="visible", timeout=self.default_timeout)
        self._select_best_option(select, query, step, context_label=label)

        dialog.locator("input[value='Select'], button:has-text('Select')").first.click()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                if dialog.is_closed():
                    break
            except Exception:
                break
            time.sleep(0.1)
        if opener is not None:
            self.page = opener
        self._ensure_live_page()

    def _do_await_email_link(self, step: Step) -> None:
        """Ask an injected mailbox broker, or local IMAP as a fallback, for a
        just-arrived link matching ``link_pattern`` and navigate to it.

        This unblocks the very common "click the link we emailed you" gate
        (magic-link sign-in, account/email verification) that otherwise stops an
        automated run cold. Credentials come from env vars (preferred) or
        templated ``username``/``password`` in the config. Product integrations
        inject a broker so mailbox credentials never enter runner data. Only mail
        newer than the run's start counts, so stale verification is never reused.
        """
        import email as _email
        import imaplib
        import re
        from email.utils import parsedate_to_datetime

        cfg = step.config
        if self.email_handler is not None:
            resolved = self._resolved_email_config(cfg)
            link = self.email_handler("link", resolved, self._started_at)
            pattern = re.compile(resolved.get("link_pattern") or r"https?://\S+")
            if not pattern.search(link):
                raise StepError(step, "await_email_link: mailbox broker returned an invalid link")
            if urlsplit(link).scheme not in {"http", "https"}:
                raise StepError(step, "await_email_link: mailbox broker returned an unsafe link")
            self.log("  · found verification link, navigating")
            self.page.goto(link)
            self._settle()
            return
        host = (render_text(cfg["imap_host"], self.context) if cfg.get("imap_host")
                else os.environ.get("IMAP_HOST", "imap.gmail.com"))
        user = (render_text(cfg["username"], self.context) if cfg.get("username")
                else os.environ.get("IMAP_USER", ""))
        password = (render_text(cfg["password"], self.context) if cfg.get("password")
                    else os.environ.get("IMAP_PASSWORD", ""))
        if not user or not password:
            raise StepError(step, "await_email_link: no mailbox credentials — set "
                                  "IMAP_USER and IMAP_PASSWORD (an app password for "
                                  "Gmail), or username:/password: in the step")
        mailbox = render_text(cfg.get("mailbox") or "INBOX", self.context)
        want_from = (render_text(cfg["from"], self.context) if cfg.get("from") else "").lower()
        want_subj = (render_text(cfg["subject"], self.context) if cfg.get("subject") else "").lower()
        pattern = re.compile(render_text(cfg["link_pattern"], self.context)
                             if cfg.get("link_pattern") else r"https?://\S+")
        timeout_s = float(cfg["timeout"]) if cfg.get("timeout") else 180.0
        poll_s = float(cfg["poll"]) if cfg.get("poll") else 5.0
        # Mail clocks can lag the local clock; allow a small backdate so a fast
        # send isn't filtered out as "too old".
        floor = self._started_at - 60

        def body_text(msg) -> str:
            chunks = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() in ("text/plain", "text/html"):
                        try:
                            chunks.append(part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", "replace"))
                        except Exception:
                            pass
            else:
                try:
                    chunks.append(msg.get_payload(decode=True).decode(
                        msg.get_content_charset() or "utf-8", "replace"))
                except Exception:
                    pass
            return "\n".join(chunks)

        self.log(f"  · await_email_link: polling {user}@{host} for a link "
                 f"(from~{want_from or 'any'}, subject~{want_subj or 'any'})")
        deadline = time.time() + timeout_s
        imap = imaplib.IMAP4_SSL(host)
        try:
            imap.login(user, password)
            while True:
                imap.select(mailbox)
                # Newest first; only need to scan the most recent handful.
                typ, data = imap.search(None, "ALL")
                ids = data[0].split() if typ == "OK" and data and data[0] else []
                for mid in reversed(ids[-25:]):
                    typ, msg_data = imap.fetch(mid, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    msg = _email.message_from_bytes(msg_data[0][1])
                    try:
                        when = parsedate_to_datetime(msg.get("Date")).timestamp()
                    except Exception:
                        when = None
                    if when is not None and when < floor:
                        continue
                    if want_from and want_from not in (msg.get("From", "")).lower():
                        continue
                    if want_subj and want_subj not in (msg.get("Subject", "")).lower():
                        continue
                    m = pattern.search(body_text(msg))
                    if m:
                        link = m.group(0).rstrip('"\'<>)].,').replace("&amp;", "&")
                        self.log(f"  · found link, navigating: {link[:90]}")
                        self.page.goto(link)
                        self._settle()
                        return
                if time.time() >= deadline:
                    raise StepError(step, f"await_email_link: no matching email with a "
                                          f"link in {int(timeout_s)}s")
                time.sleep(poll_s)
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def _do_await_email_code(self, step: Step) -> None:
        """Poll a mailbox for a just-arrived verification code and fill it.

        CUHK-style account creation sends a numeric code, not a magic link. This
        verb mirrors ``await_email_link`` but extracts a code with
        ``code_pattern`` and types it into ``field:``/``selector:``.
        """
        import email as _email
        import imaplib
        import re
        from email.utils import parsedate_to_datetime

        cfg = step.config
        if self.email_handler is not None:
            resolved = self._resolved_email_config(cfg)
            code = self.email_handler("code", resolved, self._started_at)
            pattern = re.compile(
                resolved.get("code_pattern") or r"\b([0-9]{4,8})\b"
            )
            if not pattern.search(code):
                raise StepError(step, "await_email_code: mailbox broker returned an invalid code")
            field = resolved.get("field") or "Verification Code"
            self.log("  · found verification code")
            self._control(field, step, kinds=("input", "textarea")).fill(code)
            return
        host = (render_text(cfg["imap_host"], self.context) if cfg.get("imap_host")
                else os.environ.get("IMAP_HOST", "imap.gmail.com"))
        user = (render_text(cfg["username"], self.context) if cfg.get("username")
                else os.environ.get("IMAP_USER", ""))
        password = (render_text(cfg["password"], self.context) if cfg.get("password")
                    else os.environ.get("IMAP_PASSWORD", ""))
        if not user or not password:
            raise StepError(step, "await_email_code: no mailbox credentials — set "
                                  "IMAP_USER and IMAP_PASSWORD (an app password for "
                                  "Gmail), or username:/password: in the step")

        mailbox = render_text(cfg.get("mailbox") or "INBOX", self.context)
        want_from = (render_text(cfg["from"], self.context) if cfg.get("from") else "").lower()
        want_to = (render_text(cfg["to"], self.context) if cfg.get("to") else "").lower()
        want_subj = (render_text(cfg["subject"], self.context) if cfg.get("subject") else "").lower()
        pattern = re.compile(
            render_text(cfg["code_pattern"], self.context)
            if cfg.get("code_pattern")
            else r"\b([0-9]{4,8})\b"
        )
        timeout_s = float(cfg["timeout"]) if cfg.get("timeout") else 180.0
        poll_s = float(cfg["poll"]) if cfg.get("poll") else 5.0
        floor = self._started_at - 60

        def body_text(msg) -> str:
            chunks = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() in ("text/plain", "text/html"):
                        try:
                            chunks.append(part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", "replace"))
                        except Exception:
                            pass
            else:
                try:
                    chunks.append(msg.get_payload(decode=True).decode(
                        msg.get_content_charset() or "utf-8", "replace"))
                except Exception:
                    pass
            return "\n".join(chunks)

        self.log(f"  · await_email_code: polling {user}@{host} for a code "
                 f"(from~{want_from or 'any'}, to~{want_to or 'any'}, "
                 f"subject~{want_subj or 'any'})")
        deadline = time.time() + timeout_s
        imap = imaplib.IMAP4_SSL(host)
        try:
            imap.login(user, password)
            while True:
                imap.select(mailbox)
                typ, data = imap.search(None, "ALL")
                ids = data[0].split() if typ == "OK" and data and data[0] else []
                for mid in reversed(ids[-25:]):
                    typ, msg_data = imap.fetch(mid, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    msg = _email.message_from_bytes(msg_data[0][1])
                    try:
                        when = parsedate_to_datetime(msg.get("Date")).timestamp()
                    except Exception:
                        when = None
                    if when is not None and when < floor:
                        continue
                    if want_from and want_from not in (msg.get("From", "")).lower():
                        continue
                    if want_subj and want_subj not in (msg.get("Subject", "")).lower():
                        continue
                    text = body_text(msg)
                    if want_to:
                        to_headers = " ".join([
                            msg.get("To", ""),
                            msg.get("Cc", ""),
                            msg.get("Delivered-To", ""),
                            msg.get("X-Original-To", ""),
                        ]).lower()
                        if want_to not in to_headers and want_to not in text.lower():
                            continue
                    m = pattern.search(text)
                    if m:
                        code = (m.group(1) if m.groups() else m.group(0)).strip()
                        field = render_text(cfg.get("field") or "Verification Code", self.context)
                        self.log("  · found verification code")
                        self._control(field, step, kinds=("input", "textarea")).fill(code)
                        return
                if time.time() >= deadline:
                    raise StepError(step, f"await_email_code: no matching email with a "
                                          f"code in {int(timeout_s)}s")
                time.sleep(poll_s)
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def _resolved_email_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            key: render_text(value, self.context) if isinstance(value, str) else value
            for key, value in config.items()
        }

    def _do_press(self, step: Step) -> None:
        """Send keyboard input. ``selector:`` focuses an element first; then each
        token in ``value`` (comma-separated) is either typed as text or, if it
        names a key (Enter, Tab, Escape, ArrowDown, ...), pressed as that key.

        This is the reliable way to drive custom widgets (Angular Material
        mat-select, comboboxes) that don't expose real <option> elements: focus
        the control and type the value, letting the widget's own typeahead match.
        """
        if step.selector:
            self._by_selector(step.selector).focus()
        value = render_text(step.value, self.context)
        for token in [t.strip() for t in value.split(",") if t.strip()]:
            if token in _NAMED_KEYS:
                self.page.keyboard.press(token)
            else:
                self.page.keyboard.type(token)
            self.page.wait_for_timeout(150)

    def _do_pick(self, step: Step) -> None:
        cfg = step.pick
        source_value = resolve_native(str(cfg["source"]), self.context)
        mapping = cfg["map"]
        chosen = mapping.get(_match_key(source_value, mapping), cfg.get("default"))
        if chosen is None:
            raise DataError(
                f"pick: source {cfg['source']}={source_value!r} matched no map key "
                f"and no default was given"
            )
        if cfg["as"] == "select":
            field = render_text(cfg["field"], self.context)
            self._select_on(field, str(chosen), step)
        else:
            group = render_text(cfg["group"], self.context) if cfg.get("group") else None
            self._check_in_group(str(chosen), group, step, scope_sel=cfg.get("scope"))

    # -- shared action helpers --------------------------------------------
    def _select_on(self, field: str, option: str, step: Step) -> None:
        loc = self._control(field, step, kinds=("select",))
        try:
            loc.select_option(label=option)
        except Exception:
            try:
                loc.select_option(value=option)
            except Exception:
                self._select_best_option(loc, option, step, context_label=field)

    def _check_in_group(self, option: str, group: str | None, step: Step,
                        scope_sel: str | None = None) -> None:
        if scope_sel:
            loc = self._scoped_radio(
                scope_sel,
                option,
                context_label=group or step.describe(),
                step=step,
            )
            if loc is None:
                raise StepError(step, f"could not locate option {option!r} "
                                      f"within scope {scope_sel!r}")
        else:
            loc = self._checkbox(option, group, step)
        try:
            loc.check()
        except Exception as exc:  # noqa: BLE001
            if self._force_custom_check(loc):
                self._step_log("  · custom checkbox fallback succeeded")
                return
            raise exc

    def _force_custom_check(self, loc) -> bool:
        """Handle styled ATS checkboxes/switches whose native state lags.

        PeopleSoft renders switches as an input plus a visible indicator and a
        hidden ``$chk`` field. Playwright's ``check()`` can click the input but
        still fail because the native ``checked`` property does not change. For
        those widgets, click the visible wrapper/indicator and, as a last resort,
        set the submitted hidden value plus normal input/change events.
        """
        script = r"""
        el => {
          const checkedVal = el.getAttribute('ptchecked_val') || el.value || 'Y';
          const hidden = el.id ? document.getElementById(`${el.id}$chk`) : null;
          const isOn = () =>
            el.checked === true ||
            el.getAttribute('aria-checked') === 'true' ||
            (hidden && hidden.value === checkedVal);
          if (isOn()) return true;

          const labels = el.labels ? Array.from(el.labels) : [];
          const candidates = [
            el.nextElementSibling,
            el.closest('.ps_box-control'),
            el.closest('.ps_box-checkbox'),
            ...labels,
            el.parentElement,
          ].filter(Boolean);
          for (const candidate of candidates) {
            try {
              candidate.click();
            } catch (_) {}
            if (isOn()) return true;
          }

          if (hidden || el.classList.contains('ps-checkbox') || el.getAttribute('role') === 'switch') {
            el.checked = true;
            el.setAttribute('aria-checked', 'true');
            if (hidden) hidden.value = checkedVal;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            if (hidden) hidden.dispatchEvent(new Event('change', { bubbles: true }));
            return isOn();
          }
          return false;
        }
        """
        try:
            return bool(loc.evaluate(script))
        except Exception:
            return False

    # -- locator resolution -----------------------------------------------
    # All lookups search the main document *and* every iframe, since ATS apply
    # flows (Taleo, Workday) often render fields inside nested frames.
    def _scopes(self):
        try:
            return list(self.page.frames) or [self.page]
        except Exception:
            return [self.page]

    def _try_resolve(self, build):
        """One pass: try each candidate locator in each frame; first present wins."""
        for scope in self._scopes():
            try:
                candidates = build(scope)
            except Exception:
                continue
            for loc in candidates:
                try:
                    if loc.count() > 0:
                        return loc.first
                except Exception:
                    continue
        return None

    def _resolve(self, build):
        """Like ``_try_resolve`` but polls until found or the timeout elapses.

        These ATS pages re-render via AJAX after every action, so a field may
        not exist the instant we look. We retry (re-evaluating across all
        frames, since frames also come and go) instead of failing immediately.
        """
        deadline = time.monotonic() + max(self.default_timeout, 1000) / 1000.0
        while True:
            found = self._try_resolve(build)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                return None
            self._poll_pause()

    def _poll_pause(self, ms: int = 250) -> None:
        """Short pause between resolution attempts, tolerant of a closed page."""
        try:
            self.page.wait_for_timeout(ms)
        except Exception:
            time.sleep(ms / 1000.0)

    def _find_search_dialog(self, label: str):
        """Find the PageUp search popup among open pages."""
        deadline = time.monotonic() + max(self.default_timeout, 1000) / 1000.0
        while True:
            try:
                pages = [p for ctx in self._browser.contexts for p in ctx.pages if not p.is_closed()]
            except Exception:
                pages = []
            for page in reversed(pages):
                try:
                    url = page.url or ""
                    title = page.title() or ""
                    if ("SearchDialog.aspx" in url or "Search -" in title or
                            title.strip().lower() == "search" or label.lower() in title.lower()):
                        return page
                    if page.locator("input[id$='MainContentPlaceHolder_SearchText'], input[type='text']").count() > 0 \
                            and page.locator("input[value='Search'], button:has-text('Search')").count() > 0:
                        return page
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                return None
            self._poll_pause()

    def _select_best_option(
        self,
        select,
        query: str,
        step: Step,
        *,
        context_label: str | None = None,
    ) -> None:
        """Select the best matching option using deterministic equivalences."""
        deadline = time.monotonic() + max(self.default_timeout, 1000) / 1000.0
        while True:
            options = select.locator("option")
            try:
                count = options.count()
            except Exception as exc:
                raise StepError(step, f"could not read search results: {exc}") from exc

            candidates: list[OptionCandidate] = []
            loading = False
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip()
                value = opt.get_attribute("value") or text
                norm = _norm_label(text)
                if norm in ("loading", "loading...", "please wait"):
                    loading = True
                    continue
                if text or value:
                    candidates.append(OptionCandidate(label=text, value=value, index=i))

            match = best_match(query, candidates, context=context_label or step.describe())
            if match is not None:
                value = match.candidate.value or match.candidate.label
                self._step_log(
                    f"  · option match: {query!r} -> {match.candidate.label!r} "
                    f"({match.reason})"
                )
                select.select_option(value=value)
                return
            if not loading or time.monotonic() >= deadline:
                break
            self._poll_pause()

        preview = candidate_preview(candidates)
        self._record_equivalence_gap(
            action="select",
            wanted=query,
            candidates=candidates,
            context=context_label or step.describe(),
            step=step,
        )
        raise StepError(step, f"no option matching {query!r}; first options: {preview}")

    def _ensure_live_page(self) -> None:
        """If a popup closed itself, return to the still-open application page."""
        try:
            if self.page and not self.page.is_closed():
                return
        except Exception:
            pass
        try:
            if self._return_page and not self._return_page.is_closed():
                self.page = self._return_page
                return
        except Exception:
            pass
        try:
            for page in reversed(self._browser.contexts[0].pages):
                if not page.is_closed():
                    self.page = page
                    return
        except Exception:
            pass

    def _by_selector(self, selector: str):
        """Resolve an explicit selector, searching iframes; falls back to the
        main frame so Playwright's auto-wait can handle late-rendering fields."""
        selector = render_text(selector, self.context)
        for scope in self._scopes():
            for candidate in _selector_candidates(selector):
                try:
                    if scope.locator(candidate).count() > 0:
                        return scope.locator(candidate).first
                except Exception:
                    continue
        for candidate in _selector_candidates(selector):
            try:
                return self.page.locator(candidate).first
            except Exception:
                continue
        return self.page.locator(selector).first

    def _locate_any(self, text: str, step: Step):
        """Find *any* element matching a selector or visible text — one pass.

        Used by wait_for/scroll/hover, which aren't tied to a specific control
        type (input vs button vs plain text). Returns the first match, or None.
        """
        if step.selector:
            loc = self._by_selector(step.selector)
            try:
                return loc if loc.count() > 0 else None
            except Exception:
                return None
        lit = _xpath_literal(text)
        return self._try_resolve(lambda scope: [
            scope.get_by_role("button", name=text, exact=step.exact),
            scope.get_by_role("link", name=text, exact=step.exact),
            scope.get_by_label(text, exact=step.exact),
            scope.get_by_text(text, exact=step.exact),
            scope.locator(f"xpath=//*[contains(normalize-space(.),{lit})]"),
        ])

    def _control(self, field: str, step: Step, kinds: tuple[str, ...]):
        """Resolve a form control (input/textarea/select) by label or override."""
        if step.selector:
            return self._by_selector_control(step.selector, kinds)
        lit = _xpath_literal(field)

        def build(scope):
            cands = [scope.get_by_label(field, exact=step.exact)]
            if "input" in kinds:
                cands.append(scope.get_by_placeholder(field))
                cands.append(scope.get_by_role("textbox", name=field, exact=step.exact))
            cands.append(scope.locator(f"xpath=//label[contains(normalize-space(.),{lit})]//input"))
            cands.append(scope.locator(
                f"xpath=//label[contains(normalize-space(.),{lit})]/following::"
                f"*[self::input or self::textarea or self::select][1]"
            ))
            return cands

        found = self._resolve(build)
        if found is None:
            raise StepError(step, f"could not locate field: {field!r}")
        return found

    def _by_selector_control(self, selector: str, kinds: tuple[str, ...]):
        """Resolve an explicit selector, preferring actual form controls.

        Site playbooks often use stable id prefixes. PeopleSoft sometimes gives
        labels/spans related ids before the real input/select, so a plain
        ``locator(selector).first`` can land on the label. For control actions,
        scan all matches in all frames and return the first matching tag/type.
        """
        rendered = render_text(selector, self.context)
        allowed_tags: set[str] = set()
        if "input" in kinds:
            allowed_tags.add("input")
        if "textarea" in kinds:
            allowed_tags.add("textarea")
        if "select" in kinds:
            allowed_tags.add("select")

        for scope in self._scopes():
            for selector_candidate in _selector_candidates(rendered):
                try:
                    loc = scope.locator(selector_candidate)
                    count = loc.count()
                except Exception:
                    continue
                for index in range(count):
                    candidate = loc.nth(index)
                    try:
                        tag = (candidate.evaluate("el => el.tagName.toLowerCase()") or "").lower()
                    except Exception:
                        continue
                    if tag in allowed_tags:
                        return candidate
                for index in range(count):
                    candidate = loc.nth(index)
                    try:
                        child = candidate.locator(",".join(sorted(allowed_tags))).first
                        if child.count() > 0:
                            return child
                    except Exception:
                        continue
        return self._by_selector(rendered)

    def _clickable(self, name: str, step: Step):
        if step.selector:
            return self._by_selector(step.selector)
        role = step.role or "button"
        lit = _xpath_literal(name)

        def build(scope):
            return [
                scope.get_by_role(role, name=name, exact=step.exact),
                scope.get_by_role("button", name=name, exact=step.exact),
                scope.get_by_role("link", name=name, exact=step.exact),
                scope.get_by_text(name, exact=step.exact),
                scope.locator(
                    f"xpath=//*[self::button or self::a or @role='button' or "
                    f"(self::input and (@type='submit' or @type='button'))]"
                    f"[contains(normalize-space(.),{lit}) or @value={lit}]"
                ),
            ]

        found = self._resolve(build)
        if found is None:
            raise StepError(step, f"could not locate clickable: {name!r}")
        return found

    def _checkbox(self, option: str, group: str | None, step: Step):
        if step.selector:
            return self._by_selector(step.selector)
        olit = _xpath_literal(option)

        def build(scope):
            container = scope
            if group:
                glit = _xpath_literal(group)
                grouped = scope.locator(
                    f"xpath=//*[self::fieldset or self::table or self::div or self::section]"
                    f"[.//input][contains(normalize-space(.),{glit})][last()]"
                )
                try:
                    if grouped.count() > 0:
                        container = grouped.last
                except Exception:
                    pass
            return [
                container.get_by_label(option, exact=step.exact),
                container.get_by_role("radio", name=option, exact=step.exact),
                container.get_by_role("checkbox", name=option, exact=step.exact),
                container.locator(
                    f"xpath=.//label[contains(normalize-space(.),{olit})]//input"
                ),
            ]

        found = self._resolve(build)
        if found is None:
            found = self._choice_by_equivalence(option, step, group=group)
        if found is None:
            where = f" within group {group!r}" if group else ""
            raise StepError(step, f"could not locate option {option!r}{where}")
        return found

    def _scoped_radio(
        self,
        scope_sel: str,
        option: str,
        context_label: str | None = None,
        step: Step | None = None,
    ):
        """Find a radio/checkbox inside a CSS-scoped group whose label matches.

        Used when many identically-labelled options ("Yes"/"No"/...) repeat
        across questions and only a group selector (e.g. a shared ``name``
        suffix) distinguishes them. Matches the option by its own label text,
        so it never picks another question's radio.
        """
        deadline = time.monotonic() + max(self.default_timeout, 1000) / 1000.0
        last_candidates: list[OptionCandidate] = []
        while True:
            for scope in self._scopes():
                radios = scope.locator(scope_sel)
                try:
                    n = radios.count()
                except Exception:
                    n = 0
                candidates: list[OptionCandidate] = []
                for i in range(n):
                    r = radios.nth(i)
                    label = self._label_of(scope, r)
                    value = None
                    try:
                        value = r.get_attribute("value")
                    except Exception:
                        pass
                    candidates.append(OptionCandidate(label=label or value or "", value=value, index=i))
                if candidates:
                    last_candidates = candidates
                match = best_match(option, candidates, context=context_label)
                if match is not None:
                    self._step_log(
                        f"  · option match: {option!r} -> {match.candidate.label!r} "
                        f"({match.reason})"
                    )
                    return radios.nth(match.candidate.index)
            if time.monotonic() >= deadline:
                if step is not None and last_candidates:
                    self._record_equivalence_gap(
                        action="check",
                        wanted=option,
                        candidates=last_candidates,
                        context=context_label,
                        step=step,
                    )
                return None
            self._poll_pause()

    def _choice_by_equivalence(
        self,
        option: str,
        step: Step,
        *,
        group: str | None = None,
        scope_sel: str | None = None,
    ):
        """Resolve radio/checkbox labels through the shared equivalence table."""
        all_candidates: list[OptionCandidate] = []
        for scope in self._scopes():
            container = scope
            if scope_sel:
                controls = scope.locator(scope_sel)
            else:
                if group:
                    glit = _xpath_literal(group)
                    grouped = scope.locator(
                        f"xpath=//*[self::fieldset or self::table or self::div or self::section]"
                        f"[.//input][contains(normalize-space(.),{glit})][last()]"
                    )
                    try:
                        if grouped.count() > 0:
                            container = grouped.last
                    except Exception:
                        pass
                controls = container.locator(
                    "input[type=radio],input[type=checkbox],[role=radio],[role=checkbox]"
                )
            try:
                n = controls.count()
            except Exception:
                continue
            candidates: list[OptionCandidate] = []
            for i in range(n):
                control = controls.nth(i)
                label = self._label_of(scope, control)
                value = None
                try:
                    value = control.get_attribute("value")
                except Exception:
                    pass
                candidates.append(OptionCandidate(label=label or value or "", value=value, index=i))
            all_candidates.extend(candidates)
            match = best_match(option, candidates, context=group or step.describe())
            if match is not None:
                self._step_log(
                    f"  · option match: {option!r} -> {match.candidate.label!r} "
                    f"({match.reason})"
                )
                return controls.nth(match.candidate.index)
        if all_candidates:
            self._record_equivalence_gap(
                action="check",
                wanted=option,
                candidates=all_candidates,
                context=group or step.describe(),
                step=step,
            )
        return None

    @staticmethod
    def _label_of(scope, radio) -> str:
        """Best-effort visible label for a radio/checkbox locator."""
        script = r"""
        el => {
          const text = node => (node && (node.innerText || node.textContent || ''))
            .replace(/\s+/g, ' ').trim();
          const esc = value => window.CSS && CSS.escape
            ? CSS.escape(String(value))
            : String(value).replace(/["\\#.:,[\]= >+~*|^$]/g, '\\$&');
          if (el.id) {
            const lbl = document.querySelector(`label[for="${esc(el.id)}"]`);
            if (text(lbl)) return text(lbl);
          }
          const wrap = el.closest && el.closest('label');
          if (text(wrap)) return text(wrap);
          const aria = el.getAttribute('aria-label');
          if (aria) return aria.trim();
          const labelledBy = el.getAttribute('aria-labelledby');
          if (labelledBy) {
            const joined = labelledBy.split(/\s+/)
              .map(id => text(document.getElementById(id))).filter(Boolean).join(' ');
            if (joined) return joined;
          }
          const next = el.nextElementSibling;
          if (next && next.tagName && next.tagName.toLowerCase() === 'label' && text(next)) {
            return text(next);
          }
          const parent = el.parentElement;
          if (text(parent)) return text(parent);
          return '';
        }
        """
        try:
            label = radio.evaluate(script)
            if label:
                return label
        except Exception:
            pass
        try:
            rid = radio.get_attribute("id")
        except Exception:
            rid = None
        if rid:
            try:
                lbl = scope.locator(f'label[for="{rid}"]')
                if lbl.count():
                    return lbl.first.inner_text()
            except Exception:
                pass
        try:
            return radio.get_attribute("aria-label") or ""
        except Exception:
            return ""

    def _file_input(self, field: str):
        """Return a real <input type=file> if one exists anywhere, else None."""
        lit = _xpath_literal(field)
        return self._resolve(lambda scope: [
            scope.locator(
                f"xpath=//label[contains(normalize-space(.),{lit})]/following::input[@type='file'][1]"
            ),
            scope.locator("input[type=file]"),
        ])

    # -- misc --------------------------------------------------------------
    def _step_log(self, message: str) -> None:
        """Log a step event and keep a compact tail for failure artifacts."""
        self._recent_steps.append(message)
        self._recent_steps = self._recent_steps[-25:]
        self.log(message)

    def _record_equivalence_gap(
        self,
        *,
        action: str,
        wanted: Any,
        candidates: list[OptionCandidate],
        context: str | None,
        step: Step,
    ) -> None:
        report = equivalence_gap_report(
            wanted,
            candidates,
            context=context,
            action=action,
        )
        report["step"] = {
            "kind": step.kind,
            "description": step.describe(),
            "target": step.target,
            "value": _redact_for_artifact(step.value),
            "group": step.group,
            "scope": step.scope,
            "selector": step.selector,
        }
        self._last_equivalence_gap = report

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=self.default_timeout)
        except Exception:
            pass

    def _on_error(self, n: int, step: Step, error: Exception) -> None:
        if not self.screenshot_dir:
            return
        try:
            out = ensure_private_dir(self.screenshot_dir)
            failure_dir = ensure_private_dir(out / f"error-step-{n:03d}")

            shot = failure_dir / "screenshot.png"
            shot.touch(mode=0o600, exist_ok=True)
            make_private(shot)
            self.page.screenshot(path=str(shot), full_page=True)
            make_private(shot)

            html = failure_dir / "page.html"
            try:
                write_private_text(html, self.page.content())
            except Exception as exc:  # noqa: BLE001
                write_private_text(html, f"Could not capture page HTML: {exc}\n")

            write_private_text(
                failure_dir / "failure.txt",
                self._failure_report(n, step, error, shot, html),
            )
            if self._last_equivalence_gap:
                write_private_text(
                    failure_dir / "equivalence-gap.json",
                    json.dumps(self._last_equivalence_gap, indent=2, sort_keys=True)
                    + "\n",
                )
            self.log(f"  · saved failure artifacts {failure_dir}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"  · could not save failure artifacts: {exc}")

    def _failure_report(self, n: int, step: Step, error: Exception, shot: Path, html: Path) -> str:
        try:
            url = self.page.url
        except Exception:
            url = "(unavailable)"
        try:
            title = self.page.title()
        except Exception:
            title = "(unavailable)"
        lines = [
            f"failed_step: {n}",
            f"action: {step.kind}",
            f"description: {step.describe()}",
            f"url: {url}",
            f"title: {title}",
            f"error: {type(error).__name__}: {error}",
            f"screenshot: {shot.name}",
            f"html: {html.name}",
        ]
        if self._last_equivalence_gap:
            lines.append("equivalence_gap: equivalence-gap.json")
        lines.extend([
            "",
            "step:",
            f"  target: {step.target!r}",
            f"  value: {_redact_for_artifact(step.value)!r}",
            f"  selector: {step.selector!r}",
            f"  group: {step.group!r}",
            f"  scope: {step.scope!r}",
            f"  role: {step.role!r}",
            f"  exact: {step.exact}",
            f"  optional: {step.optional}",
            f"  wait_after: {step.wait_after!r}",
            f"  timeout: {step.timeout!r}",
        ])
        if step.when:
            lines.append(f"  when: {step.when!r}")
        if step.kind == "pick":
            lines.extend(["  pick:", f"    {step.pick!r}"])
        if step.config:
            lines.extend(["  config:", f"    {_redact_for_artifact(step.config)!r}"])
        lines.extend(["", "recent_steps:", *self._recent_steps])
        return "\n".join(lines) + "\n"


def _norm_label(text: str) -> str:
    """Lowercase and collapse whitespace for tolerant label comparison."""
    return " ".join((text or "").split()).strip().lower()


def _match_key(value: Any, mapping: dict[Any, Any]) -> Any:
    """Find the map key matching a source value, tolerant of str/bool forms."""
    if value in mapping:
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        for candidate, normalized in ((True, ("true", "yes", "y", "1")),
                                      (False, ("false", "no", "n", "0")),
                                      (None, ("", "null", "none"))):
            if low in normalized and candidate in mapping:
                return candidate
        if low in mapping:
            return low
    return value


def _redact_for_artifact(value: Any) -> Any:
    """Best-effort redaction for secrets in failure artifacts."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in {"password", "token", "secret", "api_key", "apikey"}:
                redacted[key] = "(redacted)"
            else:
                redacted[key] = _redact_for_artifact(item)
        return redacted
    if isinstance(value, list):
        return [_redact_for_artifact(item) for item in value]
    return value
