/**
 * form-extractor.js
 *
 * Paste this whole file into DevTools Console on any job application page.
 * It prints a structured field report you can hand to Codex/Claude to draft a
 * playbook. It is deliberately a live probe, not just a static DOM dump:
 *
 * - reads main page + same-origin iframes
 * - lists native selects with option text
 * - opens custom dropdowns/comboboxes briefly to read overlay options
 * - reports hidden file inputs and hidden-but-present controls
 * - clicks radios/checkboxes and likely modal buttons to detect new fields
 * - tries to restore the page state after each probe
 * - appends a machine-readable JSON block for draft-playbook generators
 *
 * Safety knobs live in CONFIG below. The defaults avoid submit/navigation
 * buttons, but they do click visible radios, checkboxes, and likely "Add/Search"
 * modal buttons. If a site is fragile, set probeConditionals/probeModalButtons
 * to false and run the extractor again after you manually reveal each section.
 */

(async function extractForm() {
  const CONFIG = {
    probeCustomDropdowns: true,
    probeConditionals: true,
    probeNativeSelectConditionals: true,
    probeModalButtons: true,
    waitMs: 350,
    maxOptions: 150,
    maxCustomWidgets: 60,
    maxConditionalTriggers: 80,
    maxModalButtonTriggers: 30,
    maxHiddenControls: 80,
    includeHiddenControls: true,
    includeMachineJson: true
  };

  const lines = [];
  const warnings = [];
  const log = (...args) => lines.push(args.join(" "));
  const warn = (...args) => warnings.push(args.join(" "));

  const CONTROL_SELECTOR = [
    "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset])",
    "textarea",
    "select",
    "[role=combobox]",
    "[contenteditable=true]"
  ].join(",");

  const CUSTOM_WIDGET_SELECTOR = [
    "[role=combobox]",
    "[aria-haspopup=listbox]",
    "[aria-haspopup=menu]",
    "[aria-controls][aria-expanded]",
    "[data-toggle=dropdown]",
    "[data-bs-toggle=dropdown]",
    ".select2-selection",
    ".select2-container",
    ".ant-select",
    ".ant-select-selector",
    ".el-select",
    ".el-input",
    ".mat-select",
    ".mat-mdc-select",
    ".MuiSelect-select",
    ".react-select__control",
    "[class*=select__control]",
    "[class*=dropdown-toggle]"
  ].join(",");

  const OPTION_SELECTOR = [
    "[role=option]",
    "[role=menuitem]",
    "[role=treeitem]",
    ".select2-results__option",
    ".ant-select-item-option",
    ".ant-select-item-option-content",
    ".el-select-dropdown__item",
    ".mat-option",
    ".mat-mdc-option",
    ".MuiMenuItem-root",
    ".react-select__option",
    "[class*=select__option]",
    ".dropdown-menu li",
    ".dropdown-menu a",
    ".q-item",
    ".v-list-item"
  ].join(",");

  const DIALOG_SELECTOR = [
    "[role=dialog]",
    "[aria-modal=true]",
    ".modal",
    ".modal-dialog",
    ".ant-modal",
    ".el-dialog",
    ".mat-dialog-container",
    ".MuiDialog-root",
    ".swal2-popup",
    ".cdk-overlay-pane"
  ].join(",");

  const PAGE_ORDER_SELECTOR = [
    CONTROL_SELECTOR,
    "button",
    "input[type=button]",
    "input[type=submit]",
    "input[type=reset]",
    "a",
    "[role=button]",
    ".link-type"
  ].join(",");

  const REVEAL_WORDS = /(?:\b(yes|other|add|attach|upload|choose|browse|search|lookup|select|new|more|edit|details?|explain|specify|current|previous|former|relative|family|felony|visa|sponsor|employee|reference|education|degree|employer|position)\b|是|否|其他|添加|上传|选择|浏览|搜索|查找|新增|更多|编辑|详情|说明|当前|以前|曾经|亲属|家属|家庭|签证|资助|雇员|员工|推荐|教育|学位|雇主|职位|岗位|附件|简历|证明|文件)/i;
  const NAV_WORDS = /(?:\b(next|continue|submit|save|apply|register|login|log in|sign in|sign up|create account|finish|done|cancel|delete|remove|close|back|previous|home|logout|sign out|send verification|email)\b|下一步|继续|提交|保存|申请|注册|登录|登入|完成|取消|删除|移除|关闭|返回|上一步|首页|退出|发送|邮箱|邮件)/i;
  const FINAL_SUBMIT_WORDS = /\b(submit|finish|certify and submit|send application|complete application|withdraw|delete|remove)\b/i;
  const SENSITIVE_WORDS = /\b(ssn|social security|date of birth|birth date|dob|passport|driver'?s license|national id|government id|visa number|bank|routing|payment|credit card|felony|convicted|disability|veteran|race|ethnic|hispanic|latino|gender|sex|citizenship|sponsor|sponsorship|signature|attest|certify)\b/i;
  const ERROR_SELECTOR = [
    "[role=alert]",
    "[aria-live=assertive]",
    "[aria-live=polite]",
    ".error",
    ".errors",
    ".field-validation-error",
    ".validation-summary-errors",
    ".invalid-feedback",
    ".alert-danger",
    ".alert-error",
    ".message-error",
    ".ps_box-error",
    ".ps-message",
    ".ui-message-error",
    ".has-error",
    ".form-error"
  ].join(",");

  // -- small utilities -------------------------------------------------------

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async function copyTextToClipboard(text) {
    const modernError = await tryModernClipboard(text);
    if (!modernError) return { ok: true, method: "navigator.clipboard" };

    const execCopied = copyWithExecCommand(text);
    if (execCopied) return { ok: true, method: "document.execCommand" };

    showCopyPanel(text, modernError);
    return { ok: false, method: "manual panel", error: modernError };
  }

  async function tryModernClipboard(text) {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      return "navigator.clipboard.writeText is unavailable";
    }
    try {
      await navigator.clipboard.writeText(text);
      return "";
    } catch (err) {
      return err && err.message ? err.message : String(err);
    }
  }

  function copyWithExecCommand(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.top = "0";
    textarea.style.left = "0";
    textarea.style.width = "1px";
    textarea.style.height = "1px";
    textarea.style.opacity = "0.01";
    textarea.style.zIndex = "2147483647";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (_err) {
      copied = false;
    }
    textarea.remove();
    return copied;
  }

  function showCopyPanel(text, failureReason) {
    const existing = document.getElementById("playbook-extractor-copy-panel");
    if (existing) existing.remove();

    const panel = document.createElement("div");
    panel.id = "playbook-extractor-copy-panel";
    panel.style.position = "fixed";
    panel.style.right = "16px";
    panel.style.bottom = "16px";
    panel.style.width = "min(720px, calc(100vw - 32px))";
    panel.style.maxHeight = "min(520px, calc(100vh - 32px))";
    panel.style.padding = "12px";
    panel.style.background = "#fff";
    panel.style.color = "#111";
    panel.style.border = "2px solid #444";
    panel.style.boxShadow = "0 8px 28px rgba(0,0,0,0.35)";
    panel.style.zIndex = "2147483647";
    panel.style.font = "13px/1.35 system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";

    const title = document.createElement("div");
    title.textContent = "Form extractor output";
    title.style.fontWeight = "700";
    title.style.marginBottom = "6px";

    const help = document.createElement("div");
    help.textContent = "Automatic clipboard copy was blocked. Click Copy, or press Cmd/Ctrl+C while the text below is selected.";
    help.style.marginBottom = "8px";

    const reason = document.createElement("div");
    reason.textContent = `Clipboard failure: ${failureReason}`;
    reason.style.marginBottom = "8px";
    reason.style.color = "#555";

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.width = "100%";
    textarea.style.height = "300px";
    textarea.style.boxSizing = "border-box";
    textarea.style.font = "12px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    textarea.style.whiteSpace = "pre";

    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.gap = "8px";
    row.style.marginTop = "8px";
    row.style.alignItems = "center";

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.textContent = "Copy";
    copyButton.style.padding = "6px 10px";

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.textContent = "Close";
    closeButton.style.padding = "6px 10px";

    const status = document.createElement("span");
    status.textContent = "Text is selected.";
    status.style.color = "#555";

    copyButton.addEventListener("click", async () => {
      const modernError = await tryModernClipboard(text);
      if (!modernError || copyWithExecCommand(text)) {
        status.textContent = "Copied.";
        status.style.color = "#067d17";
        textarea.focus();
        textarea.select();
        return;
      }
      status.textContent = "Copy still blocked. Press Cmd/Ctrl+C.";
      status.style.color = "#a33";
      textarea.focus();
      textarea.select();
    });

    closeButton.addEventListener("click", () => panel.remove());

    row.append(copyButton, closeButton, status);
    panel.append(title, help, reason, textarea, row);
    document.body.appendChild(panel);
    textarea.focus();
    textarea.select();
  }

  function textOf(el) {
    if (!el) return "";
    const value = (el.innerText || el.value || el.textContent || "").replace(/\s+/g, " ").trim();
    return value;
  }

  function attr(el, name) {
    return (el.getAttribute && el.getAttribute(name)) || "";
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
    return String(value).replace(/["\\#.:,[\]= >+~*|^$]/g, "\\$&");
  }

  function attrEscape(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function xpathLiteral(text) {
    if (!text.includes('"')) return `"${text}"`;
    if (!text.includes("'")) return `'${text}'`;
    return "concat(" + text.split('"').map(part => `"${part}"`).join(", '\"', ") + ")";
  }

  function ownDoc(el) {
    return el && el.ownerDocument ? el.ownerDocument : document;
  }

  function ownWin(el) {
    const doc = ownDoc(el);
    return doc.defaultView || window;
  }

  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    const win = ownWin(el);
    const style = win.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isDisabled(el) {
    return Boolean(el.disabled || attr(el, "aria-disabled") === "true");
  }

  function requiredInfo(el) {
    const sources = [];
    const label = labelFor(el);
    if (el.required) sources.push("html required");
    if (attr(el, "aria-required") === "true") sources.push("aria-required");
    if (/\*|\brequired\b|\(required\)/i.test(label)) sources.push("label");
    const formItem = el.closest && el.closest([
      ".required",
      ".is-required",
      ".form-group",
      ".form-field",
      ".field",
      ".question",
      ".ant-form-item",
      ".el-form-item",
      ".mat-form-field",
      ".mat-mdc-form-field",
      ".MuiFormControl-root",
      "tr",
      "li"
    ].join(","));
    if (formItem) {
      const cls = String(formItem.className || "");
      if (/\b(required|is-required)\b/i.test(cls)) sources.push("container class");
      const labelNode = formItem.querySelector("label,.label,.control-label,.ant-form-item-label,.el-form-item__label,.mat-label,.MuiFormLabel-root");
      if (labelNode && /\*|\brequired\b|\(required\)/i.test(textOf(labelNode))) sources.push("container label");
    }
    return { required: sources.length > 0, sources: unique(sources) };
  }

  function requiredMark(el) {
    return requiredInfo(el).required ? " required" : "";
  }

  function unique(arr) {
    return Array.from(new Set(arr.filter(Boolean)));
  }

  function truncate(text, max = 160) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > max ? clean.slice(0, max - 3) + "..." : clean;
  }

  function norm(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function slug(text) {
    return norm(text).replace(/\s+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64) || "todo";
  }

  function template(path) {
    return path ? `{{ ${path} }}` : "";
  }

  function dataHintForText(rawText, action = "") {
    const text = norm(rawText);
    const patterns = [
      [/\bverification code\b/, null, "one-time code; use await_email_code or manual step"],
      [/\bconfirm password\b|\bpassword confirmation\b|\bre enter password\b/, "account.password", "account password"],
      [/\bpassword\b/, "account.password", "account password"],
      [/\buser\s*name\b|\busername\b|\blogin id\b/, "account.user_name", "account username"],
      [/\bemail\b/, "emails.institution_email", "email"],
      [/\bfull name\b|\bfull legal name\b|\byour name\b|\bapplicant name\b|\bsignature\b/, "person_name.legal_name.first + person_name.legal_name.last", "full name"],
      [/\bfirst name\b|\bgiven name\b|\blegal first\b/, "person_name.legal_name.first", "first name"],
      [/\bmiddle name\b|\blegal middle\b/, "person_name.legal_name.middle", "middle name"],
      [/\blast name\b|\bfamily name\b|\bsurname\b|\blegal last\b/, "person_name.legal_name.last", "last name"],
      [/\bsuffix\b/, "person_name.legal_name.suffix", "name suffix"],
      [/^(title|prefix|salutation)\b/, "person_name.legal_name.prefix", "name prefix"],
      [/\bdate of birth\b|\bbirth date\b|\bdob\b/, "detailed_personal_info.date_of_birth", "date of birth"],
      [/\btoday'?s date\b|\bsignature date\b|\bdate signed\b|^date$/, "builtins.today", "today"],
      [/\baddress line 2\b|\baddress 2\b|\bline two\b|\bline 2\b|\bapt\b|\bapartment\b/, "address_and_contact.primary_address.line_2", "address line 2"],
      [/\bstreet\b|\baddress line 1\b|\baddress 1\b|\bhome address\b|\bmailing address\b|\baddress\b/, "address_and_contact.primary_address.line_1", "address line 1"],
      [/\bzip\b|\bpostal\b/, "address_and_contact.primary_address.postal_code", "postal code"],
      [/\bstate\b|\bprovince\b|\bdistrict\b/, "address_and_contact.primary_address.state_province", "state/province"],
      [/\bcountry\b|\bnation\b/, "address_and_contact.primary_address.country", "country"],
      [/\bcity\b/, "address_and_contact.primary_address.city", "city"],
      [/\bmobile\b|\bcell\b/, "address_and_contact.phone_numbers.mobile", "mobile phone"],
      [/\bhome phone\b|\btelephone.*home\b/, "address_and_contact.phone_numbers.home", "home phone"],
      [/\bwork phone\b|\boffice phone\b|\btelephone.*office\b/, "address_and_contact.phone_numbers.work", "work phone"],
      [/\bphone\b|\btelephone\b|\bprimary number\b/, "address_and_contact.phone_numbers.mobile", "phone"],
      [/\bhighest.*education\b|\beducation level\b|\bhighest level\b/, "app_answers.highest_education", "application answer"],
      [/\bdegree\b|\bqualification\b/, "app_answers.degree", "application answer"],
      [/\bmajor\b|\bfield of study\b|\bdiscipline\b/, "app_answers.major", "application answer"],
      [/\binstitution\b|\bschool\b|\buniversity\b|\bcollege\b/, "app_answers.school", "application answer"],
      [/\bgraduation\b|\bdate earned\b|\byear acquired\b|\bdate obtained\b/, "app_answers.degree_date_earned", "application answer"],
      [/\bcurrent title\b|\bjob title\b|\bposition title\b/, "app_answers.current_title", "application answer"],
      [/\bcurrent organization\b|\bcurrent employer\b|\bcurrent company\b/, "app_answers.current_organization", "application answer"],
      [/\bemployer\b|\bcompany\b|\borganization\b/, "work_history.0.company", "work history"],
      [/\bsupervisor\b|\bmanager\b/, "work_history.0.supervisor_name", "work history"],
      [/\bresponsibilit|\bnature of work\b|\bduties\b/, "work_history.0.responsibilities", "work history"],
      [/\breason for leaving\b/, "work_history.0.reason_for_leaving", "work history"],
      [/\bstart date\b|\bdate started\b/, "work_history.0.start_date", "work history"],
      [/\bend date\b|\bdate ended\b/, "work_history.0.end_date", "work history"],
      [/\bavailability\b|\bearliest date\b|\bstart work\b/, "app_answers.availability_to_start", "application answer"],
      [/\bsalary\b|\bcompensation\b|\bpay\b|\bwage\b/, "app_answers.desired_salary", "application answer"],
      [/\bspecific referral\b|\breferral detail\b/, "app_answers.specific_referral_source", "application answer"],
      [/\breferral source\b|\bhow did you hear\b|\bsource\b/, "app_answers.referral_source", "application answer"],
      [/\bauthorized\b.*\bwork\b|\bwork authorization\b/, "app_answers.authorized_to_work_us", "application answer"],
      [/\bvisa\b|\bsponsor\b|\bsponsorship\b/, "app_answers.requires_visa_sponsorship", "application answer"],
      [/\bformer employee\b|\bpreviously employed\b|\bever been employed\b/, "app_answers.previously_employed_by_employer", "application answer"],
      [/\brelated\b.*\bemployee\b|\bfamily\b.*\bemployee\b|\brelative\b/, "app_answers.related_to_employer_employee", "application answer"],
      [/\bconflict\b/, "app_answers.has_conflict_of_interest", "application answer"],
      [/\bgender\b|\bsex\b/, "app_answers.gender", "application answer"],
      [/\bhispanic\b|\blatino\b|\blatina\b/, "app_answers.is_hispanic_or_latino", "application answer"],
      [/\brace\b|\bethnic\b/, "app_answers.race_ethnicity", "application answer"],
      [/\bveteran\b|\bmilitary\b|\barmed forces\b/, "app_answers.is_veteran", "application answer"],
      [/\bdisability\b|\bdisabled\b/, "app_answers.has_disability", "application answer"],
      [/\blinkedin\b/, "documents.linkedin_url", "document/profile URL"],
      [/\bgithub\b/, "documents.github_url", "document/profile URL"],
      [/\bportfolio\b|\bwebsite\b/, "documents.portfolio_url", "document/profile URL"]
    ];
    for (const [pattern, path, reason] of patterns) {
      if (!pattern.test(text)) continue;
      if (!path) return { path: "", template: "", confidence: "none", reason, kind: "manual" };
      if (path.includes(" + ")) {
        return {
          path,
          template: "{{ person_name.legal_name.first }} {{ person_name.legal_name.last }}",
          confidence: "medium",
          reason,
          kind: "canonical"
        };
      }
      return {
        path,
        template: template(path),
        confidence: action === "click" ? "low" : "medium",
        reason,
        kind: path.startsWith("app_answers.") ? "app_answers" : path.startsWith("answers.") ? "answers" : "canonical"
      };
    }
    return { path: `answers.${slug(rawText)}`, template: "", confidence: "todo", reason: "unknown field", kind: "todo" };
  }

  function dataHintForElement(el, action = "") {
    const text = [
      labelFor(el),
      el.placeholder || "",
      attr(el, "name"),
      el.id || "",
      sectionFor(el)
    ].join(" ");
    return dataHintForText(text, action);
  }

  function reviewFlagsForText(rawText, action = "") {
    const text = String(rawText || "");
    const flags = [];
    if (SENSITIVE_WORDS.test(text)) flags.push("sensitive_or_legal_review");
    if (FINAL_SUBMIT_WORDS.test(text) || (action === "click" && NAV_WORDS.test(text))) flags.push("navigation_or_submit_review");
    if (/\b(captcha|2fa|two factor|verification|one time|otp)\b/i.test(text)) flags.push("manual_or_email_verification");
    return unique(flags);
  }

  function reviewFlagsForElement(el, action = "") {
    const text = [
      labelFor(el),
      textOf(el),
      attr(el, "name"),
      el.id || "",
      attr(el, "title"),
      sectionFor(el)
    ].join(" ");
    const flags = reviewFlagsForText(text, action);
    if (!isVisible(el)) flags.push("hidden_or_collapsed_do_not_draft_unless_revealed");
    if (isDisabled(el)) flags.push("disabled_in_captured_state");
    return unique(flags);
  }

  function countInDoc(doc, selector) {
    try {
      return doc.querySelectorAll(selector).length;
    } catch (_err) {
      return 0;
    }
  }

  function selectorInfo(el) {
    const doc = ownDoc(el);
    const tag = el.tagName ? el.tagName.toLowerCase() : "*";
    const notes = [];

    function result(selector, extraNotes = [], strategy = "") {
      return { selector, notes: notes.concat(extraNotes).filter(Boolean), strategy };
    }

    if (el.id) {
      const id = el.id;
      const idSelector = `#${cssEscape(id)}`;
      const uniqueId = countInDoc(doc, idSelector) === 1;
      const volatile = looksVolatile(id);
      if (uniqueId && !volatile) return result(idSelector, [], "id");

      const suffix = stableSuffix(id);
      if (suffix) {
        const suffixSelector = `[id$="${attrEscape(suffix)}"]`;
        const count = countInDoc(doc, suffixSelector);
        if (count === 1) {
          return result(suffixSelector, [`id looked volatile: ${id}`], "id suffix");
        }
        if (count > 1) notes.push(`id looked volatile and suffix matched ${count}: ${id}`);
      }
      if (uniqueId) return result(idSelector, [`id may be volatile: ${id}`], "id");
    }

    for (const name of ["data-testid", "data-test", "data-qa", "data-cy", "data-automation-id"]) {
      const value = attr(el, name);
      if (!value) continue;
      const selector = `[${name}="${attrEscape(value)}"]`;
      if (countInDoc(doc, selector) === 1) return result(selector, [], name);
    }

    if (el.name) {
      const nameSelector = `[name="${attrEscape(el.name)}"]`;
      const tagNameSelector = `${tag}[name="${attrEscape(el.name)}"]`;
      if (countInDoc(doc, nameSelector) === 1) return result(nameSelector, [], "name");
      if (countInDoc(doc, tagNameSelector) === 1) return result(tagNameSelector, [], "tag+name");
      notes.push(`name is shared by ${countInDoc(doc, nameSelector)} elements`);
    }

    const aria = attr(el, "aria-label");
    if (aria) {
      const selector = `[aria-label="${attrEscape(aria)}"]`;
      if (countInDoc(doc, selector) === 1) return result(selector, [], "aria-label");
    }

    if (el.placeholder) {
      const selector = `${tag}[placeholder="${attrEscape(el.placeholder)}"]`;
      if (countInDoc(doc, selector) === 1) return result(selector, [], "placeholder");
    }

    const type = attr(el, "type");
    if (tag === "input" && type) {
      const label = labelFor(el);
      if (label && label !== "(unlabeled)") {
        const lit = xpathLiteral(label);
        const xpath = `xpath=//label[contains(normalize-space(.), ${lit})]/following::input[@type=${xpathLiteral(type)}][1]`;
        return result(xpath, notes.concat(["XPath from nearby label"]), "label xpath");
      }
    }

    const text = truncate(textOf(el), 80);
    if ((tag === "button" || attr(el, "role") === "button" || tag === "a") && text) {
      const lit = xpathLiteral(text);
      return result(`xpath=(//*[self::button or self::a or @role='button'][contains(normalize-space(.), ${lit})])[1]`, [], "button text xpath");
    }

    const classes = Array.from(el.classList || [])
      .filter(c => !/^(ng-|js-|is-|has-|active|focus|selected|open|show|disabled|valid|invalid|touched|dirty|pristine|css-|sc-)/.test(c))
      .filter(c => c.length < 48)
      .slice(0, 3);
    if (classes.length) {
      for (let i = classes.length; i >= 1; i -= 1) {
        const clsSelector = `${tag}.${classes.slice(0, i).map(cssEscape).join(".")}`;
        if (countInDoc(doc, clsSelector) === 1) return result(clsSelector, [], "class");
      }
    }

    const label = labelFor(el);
    if (label && label !== "(unlabeled)") {
      return result(`xpath=(//*[contains(normalize-space(.), ${xpathLiteral(label)})]//${tag} | //*[contains(normalize-space(.), ${xpathLiteral(label)})]/following::${tag}[1])[1]`, notes.concat(["fallback XPath from visible label"]), "fallback label xpath");
    }

    return result("(no stable selector)", notes, "none");
  }

  function stableSelector(el) {
    const info = selectorInfo(el);
    return info.notes.length ? `${info.selector}  note: ${info.notes.join("; ")}` : info.selector;
  }

  function selectorRecord(el) {
    const info = selectorInfo(el);
    return {
      selector: info.selector,
      strategy: info.strategy || "",
      notes: info.notes,
      stable: info.selector !== "(no stable selector)"
    };
  }

  function looksVolatile(value) {
    const s = String(value);
    if (/\d{4,}/.test(s)) return true;
    if (/[a-z0-9]{8,}/i.test(s) && !/^[A-Za-z_-]+$/.test(s)) return true;
    if (/[:$]/.test(s)) return true;
    if (/(ember|react|mui|radix|headlessui|j_id|uuid|guid|generated|auto)/i.test(s)) return true;
    return false;
  }

  function stableSuffix(id) {
    const parts = String(id).split(/[:._$-]/).filter(Boolean);
    for (let len = Math.min(3, parts.length); len >= 1; len -= 1) {
      const suffix = parts.slice(-len).join(id.includes(":") ? ":" : id.includes("$") ? "$" : id.includes("_") ? "_" : "-");
      if (suffix.length >= 3) return suffix;
    }
    return "";
  }

  function labelFor(el) {
    if (!el) return "(unlabeled)";
    const doc = ownDoc(el);

    if (el.id) {
      const lbl = doc.querySelector(`label[for="${attrEscape(el.id)}"]`);
      if (lbl && textOf(lbl)) return textOf(lbl);
    }

    const wrap = el.closest && el.closest("label");
    if (wrap && textOf(wrap)) return stripControlText(wrap, el);

    const aria = attr(el, "aria-label");
    if (aria) return aria.trim();

    const labelledBy = attr(el, "aria-labelledby");
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map(id => {
        const node = doc.getElementById(id);
        return node ? textOf(node) : "";
      }).filter(Boolean).join(" ");
      if (text) return text;
    }

    const describedBy = attr(el, "aria-describedby");
    if (describedBy) {
      const text = describedBy.split(/\s+/).map(id => {
        const node = doc.getElementById(id);
        return node ? textOf(node) : "";
      }).filter(Boolean).join(" ");
      if (text && text.length < 140) return text;
    }

    const fieldset = el.closest && el.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend && textOf(legend)) return textOf(legend);
    }

    if (el.placeholder) return `[placeholder: ${el.placeholder}]`;
    if (attr(el, "title")) return attr(el, "title").trim();

    const formItem = el.closest && el.closest([
      ".form-group",
      ".form-field",
      ".field",
      ".question",
      ".row",
      ".ant-form-item",
      ".el-form-item",
      ".mat-form-field",
      ".mat-mdc-form-field",
      ".MuiFormControl-root",
      ".select2-container",
      "tr",
      "li"
    ].join(","));
    if (formItem) {
      const label = formItem.querySelector("label,.label,.control-label,.ant-form-item-label,.el-form-item__label,.mat-label,.MuiFormLabel-root");
      if (label && textOf(label)) return textOf(label);

      const text = containerQuestionText(formItem, el);
      if (text) return text;
    }

    let prev = el.previousElementSibling;
    for (let i = 0; prev && i < 3; i += 1, prev = prev.previousElementSibling) {
      const text = textOf(prev);
      if (text && text.length <= 140) return text;
    }

    if (el.name) return `[name: ${el.name}]`;
    return "(unlabeled)";
  }

  function stripControlText(container, el) {
    const clone = container.cloneNode(true);
    clone.querySelectorAll("input,textarea,select,button,svg").forEach(node => node.remove());
    const text = textOf(clone) || textOf(container).replace(el.value || "", "");
    return text.trim() || "(unlabeled)";
  }

  function containerQuestionText(container, el) {
    const clone = container.cloneNode(true);
    clone.querySelectorAll("input,textarea,select,button,svg,option").forEach(node => node.remove());
    const text = textOf(clone);
    if (!text) return "";
    const ownText = textOf(el);
    const clean = text.replace(ownText, "").replace(/\s+/g, " ").trim();
    return clean.length <= 180 ? clean : "";
  }

  function framePathForDoc(doc, frames) {
    const found = frames.find(frame => frame.doc === doc);
    return found ? found.path : "main";
  }

  function describe(el, frames) {
    const tag = el.tagName ? el.tagName.toLowerCase() : "node";
    const type = attr(el, "type") || attr(el, "role") || "";
    const label = labelFor(el);
    const selector = stableSelector(el);
    const required = requiredMark(el);
    const disabled = isDisabled(el) ? " disabled" : "";
    const hidden = isVisible(el) ? "" : " hidden";
    const frame = framePathForDoc(ownDoc(el), frames);
    const framePart = frame === "main" ? "" : `  frame: ${frame}`;
    return `label="${truncate(label)}"  tag=${tag}${type ? ` type=${type}` : ""}${required}${disabled}${hidden}  selector: ${selector}${framePart}`;
  }

  function formatOptions(options, max = CONFIG.maxOptions) {
    const cleaned = unique(options.map(o => truncate(o, 120))).filter(Boolean);
    if (!cleaned.length) return "";
    const shown = cleaned.slice(0, max);
    const suffix = cleaned.length > max ? ` | ... (${cleaned.length - max} more)` : "";
    return shown.join(" | ") + suffix;
  }

  function selectOptions(select) {
    const out = [];
    Array.from(select.options || []).forEach(option => {
      const text = option.text || attr(option, "label") || option.value || textOf(option);
      if (!text) return;
      if (/^(--\s*)?(select|choose|please select)\s*(--)?$/i.test(text)) return;
      out.push(text);
    });
    return out;
  }

  function selectOptionRecords(select) {
    return Array.from(select.options || []).map((option, index) => {
      const text = option.text || attr(option, "label") || option.value || textOf(option);
      const placeholder = /^(--\s*)?(select|choose|please select)\s*(--)?$/i.test(text || "");
      return {
        index,
        text: truncate(text || "", 160),
        normalized_text: norm(text || ""),
        value: option.value || "",
        label: attr(option, "label"),
        disabled: Boolean(option.disabled),
        selected: Boolean(option.selected),
        placeholder
      };
    }).filter(option => option.text || option.value);
  }

  function datalistOptions(input) {
    const id = attr(input, "list");
    if (!id) return [];
    const list = ownDoc(input).getElementById(id);
    if (!list) return [];
    return Array.from(list.querySelectorAll("option")).map(o => attr(o, "label") || o.value || textOf(o));
  }

  function datalistOptionRecords(input) {
    const id = attr(input, "list");
    if (!id) return [];
    const list = ownDoc(input).getElementById(id);
    if (!list) return [];
    return Array.from(list.querySelectorAll("option")).map((option, index) => ({
      index,
      text: truncate(attr(option, "label") || option.value || textOf(option), 160),
      normalized_text: norm(attr(option, "label") || option.value || textOf(option)),
      value: option.value || "",
      label: attr(option, "label")
    })).filter(option => option.text || option.value);
  }

  function formRecord(el, frames) {
    const form = el.closest && el.closest("form");
    if (!form) return null;
    const forms = Array.from(ownDoc(el).querySelectorAll("form"));
    const info = selectorRecord(form);
    return {
      index: forms.indexOf(form) + 1,
      id: form.id || "",
      name: attr(form, "name"),
      selector: info.selector,
      selector_notes: info.notes,
      frame: framePathForDoc(ownDoc(form), frames)
    };
  }

  function sectionFor(el) {
    const fieldset = el.closest && el.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend && textOf(legend)) return truncate(textOf(legend), 220);
    }

    const labelledContainer = el.closest && el.closest([
      "section",
      "fieldset",
      ".section",
      ".panel",
      ".card",
      ".form-section",
      ".wizard-step",
      ".step",
      ".ant-card",
      ".el-card",
      ".MuiPaper-root"
    ].join(","));
    if (labelledContainer) {
      const heading = labelledContainer.querySelector("h1,h2,h3,h4,h5,h6,legend,[role=heading]");
      if (heading && textOf(heading)) return truncate(textOf(heading), 220);
    }

    let prev = el.previousElementSibling;
    for (let i = 0; prev && i < 8; i += 1, prev = prev.previousElementSibling) {
      if (/^H[1-6]$/.test(prev.tagName || "") && textOf(prev)) return truncate(textOf(prev), 220);
    }
    return "";
  }

  function actionHintFor(el) {
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    const type = (attr(el, "type") || "").toLowerCase();
    const role = (attr(el, "role") || "").toLowerCase();
    if (tag === "select") return "select";
    if (tag === "textarea" || attr(el, "contenteditable") === "true") return "fill";
    if (tag === "input" && type === "file") return "upload";
    if (tag === "input" && type === "radio") return "check";
    if (tag === "input" && type === "checkbox") return "check";
    if (tag === "input" && attr(el, "list")) return "press";
    if (role === "combobox" || (el.matches && el.matches(CUSTOM_WIDGET_SELECTOR))) return "press";
    if (tag === "input") return "fill";
    if (tag === "button" || tag === "a" || role === "button") return "click";
    return "inspect";
  }

  function elementRecord(el, frames, extra = {}) {
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    const selector = selectorRecord(el);
    const required = requiredInfo(el);
    const frame = framePathForDoc(ownDoc(el), frames);
    const type = attr(el, "type") || attr(el, "role") || "";
    const actionHint = actionHintFor(el);
    const dataHint = dataHintForElement(el, actionHint);
    const record = {
      label: truncate(labelFor(el), 240),
      tag,
      type,
      role: attr(el, "role"),
      name: attr(el, "name"),
      id: el.id || "",
      placeholder: el.placeholder || "",
      autocomplete: attr(el, "autocomplete"),
      title: attr(el, "title"),
      aria_label: attr(el, "aria-label"),
      aria_describedby: attr(el, "aria-describedby"),
      required: required.required,
      required_sources: required.sources,
      disabled: isDisabled(el),
      visible: isVisible(el),
      hidden: !isVisible(el),
      checked: tag === "input" && ["checkbox", "radio"].includes((attr(el, "type") || "").toLowerCase()) ? Boolean(el.checked) : undefined,
      multiple: Boolean(el.multiple),
      accept: attr(el, "accept"),
      selector: selector.selector,
      selector_strategy: selector.strategy,
      selector_notes: selector.notes,
      selector_stable: selector.stable,
      frame,
      document_order: documentOrder(el),
      section: sectionFor(el),
      form: formRecord(el, frames),
      action_hint: actionHint,
      data_hint: dataHint,
      suggested_template: dataHint.template,
      review_flags: reviewFlagsForElement(el, actionHint)
    };
    Object.keys(record).forEach(key => record[key] === undefined && delete record[key]);
    return Object.assign(record, extra);
  }

  function elementKey(el) {
    const info = selectorInfo(el);
    if (info.selector !== "(no stable selector)") return `${framePathForDoc(ownDoc(el), cachedFrames)}::${info.selector}`;
    const rect = el.getBoundingClientRect();
    return `${framePathForDoc(ownDoc(el), cachedFrames)}::${el.tagName}:${attr(el, "type")}:${labelFor(el)}:${Math.round(rect.top)}:${Math.round(rect.left)}`;
  }

  function documentOrder(el) {
    try {
      return Array.from(ownDoc(el).querySelectorAll(PAGE_ORDER_SELECTOR)).indexOf(el);
    } catch (_err) {
      return -1;
    }
  }

  function collectFrames() {
    const frames = [{ doc: document, path: "main" }];
    const blocked = [];

    function walk(doc, path) {
      Array.from(doc.querySelectorAll("iframe, frame")).forEach((frame, index) => {
        try {
          const child = frame.contentDocument;
          if (!child) throw new Error("no contentDocument");
          const selector = stableSelector(frame);
          const childPath = `${path} > iframe[${index + 1}] ${selector}`;
          frames.push({ doc: child, path: childPath });
          walk(child, childPath);
        } catch (err) {
          blocked.push(`${path} > iframe[${index + 1}] ${attr(frame, "src") || "(no src)"} (${err.message || err})`);
        }
      });
    }

    walk(document, "main");
    return { frames, blocked };
  }

  function queryAllDocs(frames, selector) {
    const out = [];
    frames.forEach(frame => {
      try {
        frame.doc.querySelectorAll(selector).forEach(el => out.push(el));
      } catch (err) {
        warn(`Could not query ${frame.path}: ${err.message || err}`);
      }
    });
    return out;
  }

  function visibleControls(frames) {
    return queryAllDocs(frames, CONTROL_SELECTOR).filter(isVisible);
  }

  function snapshotVisibleControls(frames) {
    return new Set(visibleControls(frames).map(elementKey));
  }

  function newlyVisibleControls(frames, before) {
    return visibleControls(frames).filter(el => !before.has(elementKey(el)));
  }

  async function sendEscape(doc = document) {
    try {
      const win = doc.defaultView || window;
      doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      doc.dispatchEvent(new win.KeyboardEvent("keyup", { key: "Escape", bubbles: true }));
      if (doc.activeElement && doc.activeElement.blur) doc.activeElement.blur();
    } catch (_err) {
      // Best-effort cleanup only.
    }
    await sleep(80);
  }

  function clickElement(el) {
    const win = ownWin(el);
    try {
      el.scrollIntoView({ block: "center", inline: "nearest" });
    } catch (_err) {
      // ignore
    }
    ["pointerdown", "mousedown", "mouseup", "pointerup", "click"].forEach(type => {
      try {
        el.dispatchEvent(new win.MouseEvent(type, { bubbles: true, cancelable: true, view: win }));
      } catch (_err) {
        // ignore
      }
    });
  }

  function pressKey(el, key) {
    const win = ownWin(el);
    try {
      if (el.focus) el.focus();
      el.dispatchEvent(new win.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
      el.dispatchEvent(new win.KeyboardEvent("keyup", { key, bubbles: true, cancelable: true }));
    } catch (_err) {
      // ignore
    }
  }

  function optionTextsFromContainer(root) {
    if (!root) return [];
    const candidates = Array.from(root.querySelectorAll(OPTION_SELECTOR))
      .concat(root.matches && root.matches(OPTION_SELECTOR) ? [root] : []);
    const options = candidates
      .filter(isVisible)
      .map(el => textOf(el) || attr(el, "title") || attr(el, "aria-label"))
      .filter(text => text && text.length < 200)
      .filter(text => !/^(loading|no data|no results|search)$/i.test(text));
    return unique(options);
  }

  function visibleOptionTexts(frames) {
    return unique(queryAllDocs(frames, OPTION_SELECTOR)
      .filter(isVisible)
      .map(el => textOf(el) || attr(el, "title") || attr(el, "aria-label"))
      .filter(text => text && text.length < 200)
      .filter(text => !/^(loading|no data|no results|search)$/i.test(text)));
  }

  function validationMessages(frames) {
    const seen = new Set();
    const out = [];
    queryAllDocs(frames, ERROR_SELECTOR)
      .filter(isVisible)
      .forEach(node => {
        const text = truncate(textOf(node) || attr(node, "aria-label") || attr(node, "title"), 500);
        if (!text || seen.has(norm(text))) return;
        seen.add(norm(text));
        out.push(Object.assign(elementRecord(node, frames, {
          text,
          action_hint: "inspect",
          data_hint: { path: "", template: "", confidence: "none", reason: "validation message", kind: "manual" }
        }), { text }));
      });
    return out;
  }

  async function probeCustomWidget(el, frames) {
    const doc = ownDoc(el);
    const before = new Set(visibleOptionTexts(frames));
    const controlled = attr(el, "aria-controls") || attr(el, "aria-owns");
    let options = [];
    let source = "";

    if (controlled) {
      controlled.split(/\s+/).forEach(id => {
        const container = doc.getElementById(id);
        options = options.concat(optionTextsFromContainer(container));
      });
      if (options.length) source = `aria-controls=${controlled}`;
    }

    if (!options.length && el.tagName && el.tagName.toLowerCase() === "input") {
      options = options.concat(datalistOptions(el));
      if (options.length) source = "datalist";
    }

    if (!options.length && CONFIG.probeCustomDropdowns && isVisible(el) && !isDisabled(el)) {
      try {
        clickElement(el);
        await sleep(CONFIG.waitMs);
        let after = visibleOptionTexts(collectFrames().frames);
        after = after.filter(text => !before.has(text));
        if (!after.length) {
          pressKey(el, "ArrowDown");
          await sleep(CONFIG.waitMs);
          after = visibleOptionTexts(collectFrames().frames).filter(text => !before.has(text));
        }
        options = options.concat(after);
        if (options.length) source = "opened overlay";
      } catch (err) {
        warn(`Custom widget probe failed for ${stableSelector(el)}: ${err.message || err}`);
      } finally {
        await sendEscape(doc);
      }
    }

    return { options: unique(options), source };
  }

  function controlSummary(el, frames) {
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    if (tag === "select") {
      const opts = formatOptions(selectOptions(el));
      return `${describe(el, frames)}${opts ? `\n       options: ${opts}` : ""}`;
    }
    if (tag === "input" && attr(el, "list")) {
      const opts = formatOptions(datalistOptions(el));
      return `${describe(el, frames)}${opts ? `\n       datalist options: ${opts}` : ""}`;
    }
    return describe(el, frames);
  }

  function radioQuestion(first) {
    const fieldset = first.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend && textOf(legend)) return textOf(legend);
    }
    const formItem = first.closest(".form-group,.field,.question,.row,.ant-form-item,.el-form-item,tr,li");
    if (formItem) {
      const text = containerQuestionText(formItem, first);
      if (text) return text;
    }
    return "";
  }

  function radioGroups(frames) {
    const radios = queryAllDocs(frames, "input[type=radio]").filter(isVisible);
    const groups = new Map();
    radios.forEach(radio => {
      const key = `${framePathForDoc(ownDoc(radio), frames)}::${radio.name || stableSelector(radio)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(radio);
    });
    return Array.from(groups.values());
  }

  function checkboxGroupContainer(checkbox) {
    let node = checkbox.parentElement;
    for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
      const boxes = Array.from(node.querySelectorAll("input[type=checkbox]")).filter(isVisible);
      if (boxes.length >= 2 && boxes.length <= 12) return node;
    }
    return null;
  }

  function checkboxGroupQuestion(container, first) {
    if (!container) return "";
    const legend = container.querySelector("legend");
    if (legend && textOf(legend)) return textOf(legend);
    const heading = container.querySelector("h1,h2,h3,h4,h5,h6,[role=heading],.question,.label,.control-label,.ps-label");
    if (heading && textOf(heading) && !containerContainsOnlyOptionLabel(heading, first)) {
      return textOf(heading);
    }
    const text = containerQuestionText(container, first);
    return text && text.length <= 240 ? text : "";
  }

  function containerContainsOnlyOptionLabel(node, first) {
    const option = labelFor(first);
    const text = textOf(node);
    return option && norm(text) === norm(option);
  }

  function checkboxGroups(frames) {
    const checkboxes = queryAllDocs(frames, "input[type=checkbox]").filter(isVisible);
    const groups = new Map();
    checkboxes.forEach(checkbox => {
      const container = checkboxGroupContainer(checkbox);
      if (!container) return;
      const key = elementKey(container);
      if (!groups.has(key)) groups.set(key, { container, boxes: [] });
      groups.get(key).boxes.push(checkbox);
    });
    return Array.from(groups.values())
      .filter(group => group.boxes.length >= 2)
      .filter(group => {
        const labels = group.boxes.map(labelFor).map(norm).join(" | ");
        return /(yes|no|decline|prefer not|do not want|do not wish|disability|veteran)/.test(labels);
      });
  }

  function checkboxGroupKind(group) {
    const labels = group.boxes.map(labelFor).map(norm);
    const joined = labels.join(" | ");
    const hasYes = labels.some(label => /^yes\b/.test(label) || label === "yes");
    const hasNo = labels.some(label => /^no\b/.test(label) || label === "no");
    const hasDecline = /(decline|prefer not|do not want|do not wish)/.test(joined);
    const raceLike = /(asian|white|black|african|hawaiian|pacific|american indian|alaska native|two or more)/.test(joined);
    if (!raceLike && ((hasYes && hasNo) || hasDecline)) return "exclusive_choice_likely";
    return "multi_select_likely";
  }

  function checkboxGroupScope(group, frames) {
    const names = unique(group.boxes.map(box => attr(box, "name")).filter(Boolean));
    if (names.length === 1) return `input[type=checkbox][name="${attrEscape(names[0])}"]`;
    const info = selectorInfo(group.container);
    if (info.selector && info.selector !== "(no stable selector)") {
      return `${info.selector} input[type=checkbox]`;
    }
    return "";
  }

  function checkboxLabel(checkbox) {
    return labelFor(checkbox);
  }

  function safeSelectProbeOptions(select) {
    return Array.from(select.options || [])
      .filter(option => !option.disabled)
      .filter(option => option.value !== select.value)
      .filter(option => REVEAL_WORDS.test(option.text || attr(option, "label") || option.value || textOf(option)))
      .slice(0, 6);
  }

  async function probeTrigger(trigger, frames, before, action) {
    try {
      await action();
      await sleep(CONFIG.waitMs);
      const freshFrames = collectFrames().frames;
      const newControls = newlyVisibleControls(freshFrames, before);
      return newControls;
    } catch (err) {
      warn(`Conditional probe failed for ${stableSelector(trigger)}: ${err.message || err}`);
      return [];
    }
  }

  async function restoreRadio(group, original) {
    if (original && original.isConnected && !original.checked) {
      try {
        clickElement(original);
      } catch (_err) {
        // ignore
      }
    }
    await sleep(100);
  }

  async function probeConditionals(frames) {
    if (!CONFIG.probeConditionals) return [];
    const findings = [];
    let probes = 0;

    for (const group of radioGroups(frames)) {
      const original = group.find(r => r.checked);
      for (const radio of group) {
        if (probes >= CONFIG.maxConditionalTriggers) return findings;
        if (isDisabled(radio)) continue;
        const label = labelFor(radio);
        if (!REVEAL_WORDS.test(label) && !REVEAL_WORDS.test(radioQuestion(radio))) continue;
        const before = snapshotVisibleControls(collectFrames().frames);
        probes += 1;
        const newControls = await probeTrigger(radio, frames, before, async () => clickElement(radio));
        if (newControls.length) {
          findings.push({
            trigger: `radio "${truncate(label)}" in "${truncate(radioQuestion(radio) || radio.name || "(unnamed)")}"`,
            selector: stableSelector(radio),
            controls: newControls
          });
        }
        await restoreRadio(group, original);
      }
    }

    const checkboxes = queryAllDocs(frames, "input[type=checkbox]").filter(isVisible);
    for (const checkbox of checkboxes) {
      if (probes >= CONFIG.maxConditionalTriggers) return findings;
      if (isDisabled(checkbox)) continue;
      const label = checkboxLabel(checkbox);
      if (!REVEAL_WORDS.test(label)) continue;
      const original = checkbox.checked;
      const before = snapshotVisibleControls(collectFrames().frames);
      probes += 1;
      const newControls = await probeTrigger(checkbox, frames, before, async () => clickElement(checkbox));
      if (newControls.length) {
        findings.push({
          trigger: `checkbox "${truncate(label)}"`,
          selector: stableSelector(checkbox),
          controls: newControls
        });
      }
      if (checkbox.checked !== original) clickElement(checkbox);
      await sleep(100);
    }

    if (CONFIG.probeNativeSelectConditionals) {
      const selects = queryAllDocs(frames, "select").filter(isVisible);
      for (const select of selects) {
        if (probes >= CONFIG.maxConditionalTriggers) return findings;
        if (isDisabled(select)) continue;
        const original = select.value;
        for (const option of safeSelectProbeOptions(select)) {
          if (probes >= CONFIG.maxConditionalTriggers) return findings;
          const before = snapshotVisibleControls(collectFrames().frames);
          probes += 1;
          const newControls = await probeTrigger(select, frames, before, async () => {
            const win = ownWin(select);
            select.value = option.value;
            select.dispatchEvent(new win.Event("input", { bubbles: true }));
            select.dispatchEvent(new win.Event("change", { bubbles: true }));
          });
          if (newControls.length) {
            findings.push({
              trigger: `select "${truncate(labelFor(select))}" -> "${truncate(textOf(option) || option.value)}"`,
              selector: stableSelector(select),
              controls: newControls
            });
          }
          const win = ownWin(select);
          select.value = original;
          select.dispatchEvent(new win.Event("input", { bubbles: true }));
          select.dispatchEvent(new win.Event("change", { bubbles: true }));
          await sleep(100);
        }
      }
    }

    return findings;
  }

  function isLikelyModalButton(button) {
    const text = textOf(button) || attr(button, "aria-label") || attr(button, "title");
    const type = (attr(button, "type") || "").toLowerCase();
    const href = attr(button, "href");
    const onclick = attr(button, "onclick");
    if (!text) return false;
    if (isDisabled(button)) return false;
    if (type === "submit") return false;
    if (NAV_WORDS.test(text)) return false;
    if (href && href !== "#" && !href.startsWith("#") && !/^javascript:/i.test(href)) return false;
    if (attr(button, "aria-haspopup") || attr(button, "aria-controls")) return true;
    if (attr(button, "data-toggle") || attr(button, "data-bs-toggle")) return true;
    if (/modal|dialog|popup|lookup|search/i.test(onclick)) return true;
    return REVEAL_WORDS.test(text);
  }

  async function closeLikelyDialog(frames) {
    await sendEscape(document);
    await sleep(100);
    const closeButtons = queryAllDocs(frames, [
      "[aria-label='Close']",
      "[aria-label='close']",
      "button.close",
      ".modal button[data-dismiss]",
      ".modal button[data-bs-dismiss]",
      "button"
    ].join(",")).filter(isVisible).filter(btn => /^(close|cancel|done|ok)$/i.test(textOf(btn) || attr(btn, "aria-label")));
    if (closeButtons.length) {
      try {
        clickElement(closeButtons[0]);
        await sleep(120);
      } catch (_err) {
        // ignore
      }
    }
  }

  async function probeModalButtons(frames) {
    if (!CONFIG.probeModalButtons) return [];
    const buttons = queryAllDocs(frames, "button,input[type=button],a,[role=button],.link-type").filter(isVisible);
    const triggers = buttons.filter(isLikelyModalButton).slice(0, CONFIG.maxModalButtonTriggers);
    const findings = [];

    for (const button of triggers) {
      const before = snapshotVisibleControls(collectFrames().frames);
      const beforeDialogs = queryAllDocs(collectFrames().frames, DIALOG_SELECTOR).filter(isVisible).length;
      try {
        clickElement(button);
        await sleep(CONFIG.waitMs + 150);
        const freshFrames = collectFrames().frames;
        const newControls = newlyVisibleControls(freshFrames, before);
        const dialogs = queryAllDocs(freshFrames, DIALOG_SELECTOR).filter(isVisible).length;
        if (newControls.length || dialogs > beforeDialogs) {
          findings.push({
            trigger: `"${truncate(textOf(button) || attr(button, "aria-label"))}"`,
            selector: stableSelector(button),
            dialogOpened: dialogs > beforeDialogs,
            controls: newControls
          });
        }
        await closeLikelyDialog(freshFrames);
      } catch (err) {
        warn(`Modal button probe failed for ${stableSelector(button)}: ${err.message || err}`);
      }
    }
    return findings;
  }

  function section(title) {
    log(title);
  }

  function logControlList(items, frames, indent = "  ") {
    items.forEach((el, i) => {
      const summary = controlSummary(el, frames).split("\n");
      log(`${indent}[${i + 1}] ${summary[0]}`);
      summary.slice(1).forEach(line => log(`${indent}    ${line.trim()}`));
    });
  }

  // -- extraction starts here ------------------------------------------------

  const collected = collectFrames();
  let cachedFrames = collected.frames;
  const report = {
    schema_version: 2,
    tool: "form-extractor",
    url: location.href,
    title: document.title,
    captured_at: new Date().toISOString(),
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      device_pixel_ratio: window.devicePixelRatio || 1
    },
    config: Object.assign({}, CONFIG),
    frames: {
      read: cachedFrames.map(frame => frame.path),
      blocked: collected.blocked
    },
    buttons: [],
    controls: {
      text_inputs: [],
      native_selects: [],
      datalist_inputs: [],
      file_uploads: [],
      radio_groups: [],
      checkbox_groups: [],
      checkboxes: [],
      custom_widgets: [],
      hidden_controls: []
    },
    findings: {
      modal_fields: [],
      conditional_fields: [],
      visible_dialogs: [],
      validation_messages: []
    },
    playbook_guidance: {
      value_sources: {
        applicant_facts: "Use canonical paths such as person_name.*, address_and_contact.*, education.*, work_history.*, documents.*.",
        reusable_application_answers: "Use app_answers.* for referral, salary, work authorization, sponsorship, demographics, prior-employer, related-employee, and conflict questions.",
        site_specific_answers: "Use answers.<site>_* only for true platform-specific questions with no portable applicant meaning."
      },
      equivalences: "Use canonical values in playbooks. If a live option wording is missing, run with --screenshot-dir and promote equivalence-gap.json via tools/accept_equivalence_gap.py.",
      hidden_controls: "Do not draft active steps from hidden_controls unless a conditional/modal finding identifies the trigger that reveals them.",
      final_submit: "Do not encode the final submit click while submission_mode is human. End the playbook with pause_for_user."
    },
    warnings: [],
    authoring_notes: []
  };

  log("");
  log("FORM EXTRACTOR - paste output to Codex");
  log("======================================");
  log("");
  log("URL:", location.href);
  log("Title:", document.title);
  log("Captured at:", new Date().toISOString());
  log("");

  section("-- PLAYBOOK DRAFTING RULES -------------------------------------------");
  log("  - Use canonical profile paths for applicant facts and app_answers.* for reusable application answers.");
  log("  - Use native select: for real <select> controls; the runner handles deterministic equivalences at runtime.");
  log("  - Use press: only for custom combobox/typeahead widgets that are not native <select> controls.");
  log("  - For radio groups and exclusive checkbox choice groups, prefer pick: with the provided scope.");
  log("  - Do not turn hidden/collapsed controls into active steps unless this report says a trigger revealed them.");
  log("  - Do not encode the final submit click. End the playbook with pause_for_user for applicant review and submission.");
  log("  - If a live option wording is missing later, use equivalence-gap.json with tools/accept_equivalence_gap.py.");
  log("");

  if (collected.blocked.length) {
    section("-- IFRAMES NOT READABLE ------------------------------------------------");
    collected.blocked.forEach((item, i) => log(`  [${i + 1}] ${item}`));
    log("");
  }

  if (cachedFrames.length > 1) {
    section("-- SAME-ORIGIN FRAMES READ --------------------------------------------");
    cachedFrames.slice(1).forEach((frame, i) => log(`  [${i + 1}] ${frame.path}`));
    log("");
  }

  const errors = validationMessages(cachedFrames);
  if (errors.length) {
    section("-- VISIBLE VALIDATION / ERROR MESSAGES -------------------------------");
    report.findings.validation_messages = errors;
    errors.forEach((item, i) => {
      const framePart = item.frame === "main" ? "" : `  frame: ${item.frame}`;
      log(`  [${i + 1}] "${truncate(item.text, 260)}"  selector: ${item.selector}${framePart}`);
    });
    log("");
  }

  const buttons = queryAllDocs(cachedFrames, "button,input[type=button],input[type=submit],input[type=reset],a,[role=button],.link-type")
    .filter(isVisible)
    .filter(button => textOf(button) || attr(button, "aria-label") || attr(button, "title") || attr(button, "value"));
  if (buttons.length) {
    section("-- BUTTONS / LINKS ----------------------------------------------------");
    buttons.forEach((button, i) => {
      const text = truncate(textOf(button) || attr(button, "aria-label") || attr(button, "title") || attr(button, "value"));
      const type = attr(button, "type");
      const hints = [];
      if (isLikelyModalButton(button)) hints.push("likely reveal/modal trigger");
      if (NAV_WORDS.test(text) || /submit/i.test(type)) hints.push("navigation/save/review ordering");
      if (FINAL_SUBMIT_WORDS.test(text)) hints.push("final-submit risk; keep commented");
      const hint = hints.length ? `  ${hints.join("; ")}` : "";
      const frame = framePathForDoc(ownDoc(button), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      report.buttons.push(elementRecord(button, cachedFrames, {
        text,
        value: attr(button, "value"),
        href: attr(button, "href"),
        likely_modal_trigger: isLikelyModalButton(button),
        likely_navigation_or_submit: NAV_WORDS.test(text) || /submit/i.test(type),
        recommended: /submit|finish|delete|remove/i.test(text) ? "review before adding click step" : "click"
      }));
      log(`  [${i + 1}] "${text}"${type ? ` type=${type}` : ""}${hint}  selector: ${stableSelector(button)}${framePart}`);
    });
    log("");
  }

  const textInputs = queryAllDocs(cachedFrames, [
    "input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset])",
    "textarea",
    "[contenteditable=true]"
  ].join(",")).filter(isVisible).filter(el => attr(el, "role") !== "combobox");
  if (textInputs.length) {
    section("-- TEXT INPUTS / TEXTAREAS ------------------------------------------");
    report.controls.text_inputs = textInputs.map(el => elementRecord(el, cachedFrames));
    logControlList(textInputs, cachedFrames);
    log("");
  }

  const selects = queryAllDocs(cachedFrames, "select").filter(isVisible);
  if (selects.length) {
    section("-- NATIVE DROPDOWNS (<select>) ---------------------------------------");
    report.controls.native_selects = selects.map(select => {
      const options = selectOptionRecords(select);
      return elementRecord(select, cachedFrames, {
        options,
        option_count: options.filter(option => !option.placeholder).length,
        equivalence_context: labelFor(select),
        review_flags: options.length > 50
          ? unique(reviewFlagsForElement(select, "select").concat(["long_option_list_verify_applicant_value_exists"]))
          : reviewFlagsForElement(select, "select")
      });
    });
    logControlList(selects, cachedFrames);
    selects.forEach((select, i) => {
      const optionCount = selectOptionRecords(select).filter(option => !option.placeholder).length;
      if (optionCount > 50) {
        log(`  [${i + 1}] note: long option list (${optionCount} options). Verify applicant-specific values such as school/employer exist before running.`);
      }
    });
    log("");
  }

  const datalistInputs = queryAllDocs(cachedFrames, "input[list]").filter(isVisible);
  if (datalistInputs.length) {
    section("-- DATALIST INPUTS ----------------------------------------------------");
    report.controls.datalist_inputs = datalistInputs.map(input => elementRecord(input, cachedFrames, {
      datalist_id: attr(input, "list"),
      options: datalistOptionRecords(input)
    }));
    logControlList(datalistInputs, cachedFrames);
    log("");
  }

  const files = queryAllDocs(cachedFrames, "input[type=file]");
  if (files.length) {
    section("-- FILE UPLOADS ------------------------------------------------------");
    files.forEach((file, i) => {
      const hidden = isVisible(file) ? "" : " hidden";
      const accept = attr(file, "accept");
      const multiple = file.multiple ? " multiple" : "";
      const frame = framePathForDoc(ownDoc(file), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      report.controls.file_uploads.push(elementRecord(file, cachedFrames));
      log(`  [${i + 1}] label="${truncate(labelFor(file))}"${hidden}${multiple}${accept ? ` accept=${accept}` : ""}  selector: ${stableSelector(file)}${framePart}`);
    });
    log("");
  }

  const groups = radioGroups(cachedFrames);
  if (groups.length) {
    section("-- RADIO GROUPS ------------------------------------------------------");
    groups.forEach((group, i) => {
      const first = group[0];
      const question = radioQuestion(first);
      const options = group.map(labelFor);
      const frame = framePathForDoc(ownDoc(first), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      const scope = first.name ? `input[type=radio][name="${attrEscape(first.name)}"]` : stableSelector(first);
      report.controls.radio_groups.push({
        question: truncate(question || "", 240),
        name: first.name || "",
        frame,
        scope,
        section: sectionFor(first),
        required: group.some(radio => requiredInfo(radio).required),
        action_hint: "pick",
        options: group.map(radio => elementRecord(radio, cachedFrames, {
          option_label: truncate(labelFor(radio), 180),
          option_value: attr(radio, "value")
        }))
      });
      log(`  [${i + 1}] group name="${first.name || "(unnamed)"}"${question ? `  question="${truncate(question)}"` : ""}${framePart}`);
      log(`       scope: ${scope}`);
      log(`       options: ${formatOptions(options)}`);
    });
    log("");
  }

  const checkboxChoiceGroups = checkboxGroups(cachedFrames);
  if (checkboxChoiceGroups.length) {
    section("-- CHECKBOX CHOICE GROUPS --------------------------------------------");
    log("  These are checkbox sets that may behave like radio groups. Prefer pick: only when exclusive_choice_likely is correct.");
    checkboxChoiceGroups.forEach((group, i) => {
      const first = group.boxes[0];
      const question = checkboxGroupQuestion(group.container, first);
      const options = group.boxes.map(labelFor);
      const frame = framePathForDoc(ownDoc(first), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      const scope = checkboxGroupScope(group, cachedFrames);
      const kind = checkboxGroupKind(group);
      report.controls.checkbox_groups.push({
        question: truncate(question || "", 240),
        frame,
        scope,
        section: sectionFor(first),
        group_kind: kind,
        exclusive_likely: kind === "exclusive_choice_likely",
        required: group.boxes.some(checkbox => requiredInfo(checkbox).required),
        action_hint: kind === "exclusive_choice_likely" ? "pick" : "check",
        options: group.boxes.map(checkbox => elementRecord(checkbox, cachedFrames, {
          option_label: truncate(labelFor(checkbox), 180),
          option_value: attr(checkbox, "value")
        }))
      });
      log(`  [${i + 1}] ${kind}${question ? `  question="${truncate(question)}"` : ""}${framePart}`);
      if (scope) log(`       scope: ${scope}`);
      log(`       options: ${formatOptions(options)}`);
    });
    log("");
  }

  const checkboxes = queryAllDocs(cachedFrames, "input[type=checkbox]").filter(isVisible);
  if (checkboxes.length) {
    section("-- CHECKBOXES -------------------------------------------------------");
    checkboxes.forEach((checkbox, i) => {
      const frame = framePathForDoc(ownDoc(checkbox), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      report.controls.checkboxes.push(elementRecord(checkbox, cachedFrames, {
        value: attr(checkbox, "value")
      }));
      log(`  [${i + 1}] label="${truncate(labelFor(checkbox))}"${checkbox.checked ? " checked" : ""}${requiredMark(checkbox)}  selector: ${stableSelector(checkbox)}${framePart}`);
    });
    log("");
  }

  let customWidgets = queryAllDocs(cachedFrames, CUSTOM_WIDGET_SELECTOR)
    .filter(isVisible)
    .filter(el => !(el.tagName && el.tagName.toLowerCase() === "select"))
    .filter(el => !el.closest("select"));
  const seenWidgets = new Set();
  customWidgets = customWidgets.filter(el => {
    const root = el.closest(".ant-select,.el-select,.mat-select,.mat-mdc-select,.select2-container,.react-select__control,[role=combobox]") || el;
    const key = elementKey(root);
    if (seenWidgets.has(key)) return false;
    seenWidgets.add(key);
    return true;
  }).slice(0, CONFIG.maxCustomWidgets);

  if (customWidgets.length) {
    section("-- CUSTOM DROPDOWNS / COMBOBOXES ------------------------------------");
    for (let i = 0; i < customWidgets.length; i += 1) {
      const widget = customWidgets[i];
      const probe = await probeCustomWidget(widget, cachedFrames);
      cachedFrames = collectFrames().frames;
      const frame = framePathForDoc(ownDoc(widget), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      report.controls.custom_widgets.push(elementRecord(widget, cachedFrames, {
        options: probe.options.map((text, index) => ({
          index,
          text: truncate(text, 160),
          normalized_text: norm(text)
        })),
        option_source: probe.source || "",
        action_hint: "press",
        recommended: "press with value '<option text>, Enter' or '<option text>, Tab'"
      }));
      log(`  [${i + 1}] label="${truncate(labelFor(widget))}"  role=${attr(widget, "role") || "(none)"}  selector: ${stableSelector(widget)}${framePart}`);
      const opts = formatOptions(probe.options);
      if (opts) log(`       options (${probe.source || "found"}): ${opts}`);
      if (!opts) log("       options: (none found; try opening this widget manually and rerun extractor)");
      log("       playbook hint: use press: with this selector if it is not a native <select>");
    }
    log("");
  }

  if (CONFIG.includeHiddenControls) {
    const hiddenControls = queryAllDocs(cachedFrames, CONTROL_SELECTOR)
      .filter(el => !isVisible(el))
      .filter(el => !(el.tagName && el.tagName.toLowerCase() === "input" && attr(el, "type") === "hidden"))
      .slice(0, CONFIG.maxHiddenControls);
    if (hiddenControls.length) {
      section("-- HIDDEN / COLLAPSED CONTROLS PRESENT IN DOM -----------------------");
      log("  These may be conditional fields, inactive wizard pages, or backing inputs for custom widgets.");
      report.controls.hidden_controls = hiddenControls.map(el => elementRecord(el, cachedFrames));
      hiddenControls.forEach((el, i) => {
        const summary = controlSummary(el, cachedFrames).split("\n");
        log(`  [${i + 1}] ${summary[0]}`);
        summary.slice(1).forEach(line => log(`      ${line.trim()}`));
      });
      log("");
    }
  }

  const modalFindings = await probeModalButtons(cachedFrames);
  cachedFrames = collectFrames().frames;
  if (modalFindings.length) {
    section("-- MODAL / POPUP FIELDS DISCOVERED BY CLICKING SAFE TRIGGERS ---------");
    modalFindings.forEach((finding, i) => {
      report.findings.modal_fields.push({
        trigger: finding.trigger,
        selector: finding.selector,
        dialog_opened: Boolean(finding.dialogOpened),
        controls: finding.controls.map(control => elementRecord(control, cachedFrames))
      });
      log(`  [${i + 1}] trigger ${finding.trigger}  selector: ${finding.selector}${finding.dialogOpened ? "  dialog opened" : ""}`);
      if (finding.controls.length) {
        finding.controls.forEach((control, j) => log(`       [${j + 1}] ${controlSummary(control, cachedFrames).replace(/\n/g, "\n           ")}`));
      } else {
        log("       no new controls captured; if a native file picker opened, use upload with the visible file input/button");
      }
    });
    log("");
  }

  const conditionalFindings = await probeConditionals(cachedFrames);
  cachedFrames = collectFrames().frames;
  if (conditionalFindings.length) {
    section("-- CONDITIONAL FIELDS DISCOVERED BY PROBING OPTIONS ------------------");
    conditionalFindings.forEach((finding, i) => {
      report.findings.conditional_fields.push({
        trigger: finding.trigger,
        selector: finding.selector,
        controls: finding.controls.map(control => elementRecord(control, cachedFrames))
      });
      log(`  [${i + 1}] after ${finding.trigger}  selector: ${finding.selector}`);
      finding.controls.forEach((control, j) => log(`       [${j + 1}] ${controlSummary(control, cachedFrames).replace(/\n/g, "\n           ")}`));
    });
    log("");
  } else if (CONFIG.probeConditionals) {
    section("-- CONDITIONAL FIELDS ------------------------------------------------");
    log("  No new fields appeared from the safe radio/checkbox/select probes.");
    log("  If the site has conditionals behind custom dropdown options, manually choose Yes/Other/Add and rerun this extractor.");
    log("");
  }

  const visibleDialogs = queryAllDocs(cachedFrames, DIALOG_SELECTOR).filter(isVisible);
  if (visibleDialogs.length) {
    section("-- CURRENTLY VISIBLE DIALOGS / OVERLAYS ------------------------------");
    visibleDialogs.forEach((dialog, i) => {
      const frame = framePathForDoc(ownDoc(dialog), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
      report.findings.visible_dialogs.push(elementRecord(dialog, cachedFrames, {
        text: truncate(textOf(dialog), 500)
      }));
      log(`  [${i + 1}] "${truncate(textOf(dialog), 220)}"  selector: ${stableSelector(dialog)}${framePart}`);
    });
    log("");
  }

  report.warnings = unique(warnings);
  if (warnings.length) {
    section("-- WARNINGS ----------------------------------------------------------");
    unique(warnings).forEach((item, i) => log(`  [${i + 1}] ${item}`));
    log("");
  }

  report.authoring_notes = [
    "Native <select> fields can use select: with canonical applicant values; deterministic equivalences and salary ranges are resolved at runtime.",
    "Custom dropdowns usually need press: with the selector, option text, then Enter/Tab.",
    "File inputs can use upload: directly, even when hidden.",
    "Radio groups and exclusive checkbox choice groups include scope candidates for pick: steps.",
    "Hidden controls are informational only unless they were discovered behind a recorded trigger.",
    "Visible validation messages are captured separately; fix the relevant earlier step rather than drafting steps against an error page.",
    "Rerun extractor after manually picking each Yes/Other/Add conditional path if needed.",
    "In human-submission mode, never encode the final submit click; end with pause_for_user."
  ];
  section("-- PLAYBOOK AUTHORING NOTES ------------------------------------------");
  report.authoring_notes.forEach(note => log(`  - ${note}`));
  log("");

  report.frames.read = cachedFrames.map(frame => frame.path);
  report.summary = {
    buttons: report.buttons.length,
    text_inputs: report.controls.text_inputs.length,
    native_selects: report.controls.native_selects.length,
    datalist_inputs: report.controls.datalist_inputs.length,
    file_uploads: report.controls.file_uploads.length,
    radio_groups: report.controls.radio_groups.length,
    checkbox_groups: report.controls.checkbox_groups.length,
    checkboxes: report.controls.checkboxes.length,
    custom_widgets: report.controls.custom_widgets.length,
    hidden_controls: report.controls.hidden_controls.length,
    modal_findings: report.findings.modal_fields.length,
    conditional_findings: report.findings.conditional_fields.length,
    visible_dialogs: report.findings.visible_dialogs.length,
    validation_messages: report.findings.validation_messages.length
  };

  if (CONFIG.includeMachineJson) {
    section("-- MACHINE-READABLE JSON --------------------------------------------");
    log("PLAYBOOK_EXTRACT_JSON_START");
    log(JSON.stringify(report, null, 2));
    log("PLAYBOOK_EXTRACT_JSON_END");
    log("");
  }

  const output = lines.join("\n");
  window.__PLAYBOOK_EXTRACTOR_RESULT__ = report;
  window.__PLAYBOOK_EXTRACTOR_OUTPUT__ = output;
  console.log(output);

  const copyResult = await copyTextToClipboard(output);
  if (copyResult.ok) {
    console.log(`\nOutput copied to clipboard via ${copyResult.method} - paste it to Codex.`);
  } else {
    console.log("\nAutomatic clipboard copy failed. A copy panel was added to the page.");
    console.log("You can also run: copy(window.__PLAYBOOK_EXTRACTOR_OUTPUT__)");
  }
})();
