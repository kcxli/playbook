"""Execute a parsed Playbook against a live browser via Playwright.

The engine maps each canonical action to resilient locator strategies. Real
ATS markup (Taleo, Workday, ...) is inconsistent, so every field lookup tries
several strategies in order and falls back to an explicit ``selector:`` override
when the playbook provides one.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from . import conditions
from .context import DataError
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
    ):
        self.context = context
        self.headless = headless
        self.slow_mo = slow_mo
        self.default_timeout = default_timeout
        self.screenshot_dir = screenshot_dir
        self.pace = pace
        self.log = log
        self._pw = None
        self._browser = None
        self.page = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "Engine":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)
        ctx = self._browser.new_context(accept_downloads=True)
        ctx.set_default_timeout(self.default_timeout)
        self.page = ctx.new_page()
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
            self.log(f"→ open (from playbook url) {playbook.url}")
            self.page.goto(playbook.url)
            self._settle()

        for n, step in enumerate(playbook.steps, start=1):
            if step.when is not None and not conditions.evaluate(step.when, self.context):
                self.log(f"  · skip [{n}] {step.describe()}  (when: {step.when})")
                continue
            self.log(f"→ [{n}] {step.describe()}")
            try:
                self._execute(step)
            except Exception as exc:  # noqa: BLE001 - we re-raise after handling
                if step.optional:
                    self.log(f"  ! optional step failed, continuing: {exc}")
                    continue
                self._on_error(n, step)
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
        ctx = self.page.context
        pages_before = len(ctx.pages)
        loc.click()
        self._settle()
        if len(ctx.pages) > pages_before:
            self.page = ctx.pages[-1]
            self._settle()

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
            loc.select_option(value=option)

    def _check_in_group(self, option: str, group: str | None, step: Step,
                        scope_sel: str | None = None) -> None:
        if scope_sel:
            loc = self._scoped_radio(scope_sel, option)
            if loc is None:
                raise StepError(step, f"could not locate option {option!r} "
                                      f"within scope {scope_sel!r}")
        else:
            loc = self._checkbox(option, group, step)
        loc.check()

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

    def _by_selector(self, selector: str):
        """Resolve an explicit selector, searching iframes; falls back to the
        main frame so Playwright's auto-wait can handle late-rendering fields."""
        selector = render_text(selector, self.context)
        for scope in self._scopes():
            try:
                if scope.locator(selector).count() > 0:
                    return scope.locator(selector).first
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
            return self._by_selector(step.selector)
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
            where = f" within group {group!r}" if group else ""
            raise StepError(step, f"could not locate option {option!r}{where}")
        return found

    def _scoped_radio(self, scope_sel: str, option: str):
        """Find a radio/checkbox inside a CSS-scoped group whose label matches.

        Used when many identically-labelled options ("Yes"/"No"/...) repeat
        across questions and only a group selector (e.g. a shared ``name``
        suffix) distinguishes them. Matches the option by its own label text,
        so it never picks another question's radio.
        """
        target = _norm_label(option)
        deadline = time.monotonic() + max(self.default_timeout, 1000) / 1000.0
        while True:
            for scope in self._scopes():
                radios = scope.locator(scope_sel)
                try:
                    n = radios.count()
                except Exception:
                    n = 0
                for i in range(n):
                    r = radios.nth(i)
                    if _norm_label(self._label_of(scope, r)) in (target,) or \
                       _norm_label(self._label_of(scope, r)).startswith(target):
                        return r
            if time.monotonic() >= deadline:
                return None
            self._poll_pause()

    @staticmethod
    def _label_of(scope, radio) -> str:
        """Best-effort visible label for a radio/checkbox locator."""
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
    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=self.default_timeout)
        except Exception:
            pass

    def _on_error(self, n: int, step: Step) -> None:
        if not self.screenshot_dir:
            return
        try:
            out = Path(self.screenshot_dir)
            out.mkdir(parents=True, exist_ok=True)
            shot = out / f"error-step-{n}.png"
            self.page.screenshot(path=str(shot), full_page=True)
            self.log(f"  · saved screenshot {shot}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"  · could not save screenshot: {exc}")


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
