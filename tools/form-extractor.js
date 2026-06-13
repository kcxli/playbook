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
    includeHiddenControls: true
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

  const REVEAL_WORDS = /(?:\b(yes|other|add|attach|upload|choose|browse|search|lookup|select|new|more|edit|details?|explain|specify|current|previous|former|relative|family|felony|visa|sponsor|employee|reference|education|degree|employer|position)\b|是|否|其他|添加|上传|选择|浏览|搜索|查找|新增|更多|编辑|详情|说明|当前|以前|曾经|亲属|家属|家庭|签证|资助|雇员|员工|推荐|教育|学位|雇主|职位|岗位|附件|简历|证明|文件)/i;
  const NAV_WORDS = /(?:\b(next|continue|submit|save|apply|register|login|log in|sign in|sign up|create account|finish|done|cancel|delete|remove|close|back|previous|home|logout|sign out|send verification|email)\b|下一步|继续|提交|保存|申请|注册|登录|登入|完成|取消|删除|移除|关闭|返回|上一步|首页|退出|发送|邮箱|邮件)/i;

  // -- small utilities -------------------------------------------------------

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
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

  function requiredMark(el) {
    return el.required || attr(el, "aria-required") === "true" ? " required" : "";
  }

  function unique(arr) {
    return Array.from(new Set(arr.filter(Boolean)));
  }

  function truncate(text, max = 160) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > max ? clean.slice(0, max - 3) + "..." : clean;
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

    function result(selector, extraNotes = []) {
      return { selector, notes: notes.concat(extraNotes).filter(Boolean) };
    }

    if (el.id) {
      const id = el.id;
      const idSelector = `#${cssEscape(id)}`;
      const uniqueId = countInDoc(doc, idSelector) === 1;
      const volatile = looksVolatile(id);
      if (uniqueId && !volatile) return result(idSelector);

      const suffix = stableSuffix(id);
      if (suffix) {
        const suffixSelector = `[id$="${attrEscape(suffix)}"]`;
        const count = countInDoc(doc, suffixSelector);
        if (count === 1) {
          return result(suffixSelector, [`id looked volatile: ${id}`]);
        }
        if (count > 1) notes.push(`id looked volatile and suffix matched ${count}: ${id}`);
      }
      if (uniqueId) return result(idSelector, [`id may be volatile: ${id}`]);
    }

    for (const name of ["data-testid", "data-test", "data-qa", "data-cy", "data-automation-id"]) {
      const value = attr(el, name);
      if (!value) continue;
      const selector = `[${name}="${attrEscape(value)}"]`;
      if (countInDoc(doc, selector) === 1) return result(selector);
    }

    if (el.name) {
      const nameSelector = `[name="${attrEscape(el.name)}"]`;
      const tagNameSelector = `${tag}[name="${attrEscape(el.name)}"]`;
      if (countInDoc(doc, nameSelector) === 1) return result(nameSelector);
      if (countInDoc(doc, tagNameSelector) === 1) return result(tagNameSelector);
      notes.push(`name is shared by ${countInDoc(doc, nameSelector)} elements`);
    }

    const aria = attr(el, "aria-label");
    if (aria) {
      const selector = `[aria-label="${attrEscape(aria)}"]`;
      if (countInDoc(doc, selector) === 1) return result(selector);
    }

    if (el.placeholder) {
      const selector = `${tag}[placeholder="${attrEscape(el.placeholder)}"]`;
      if (countInDoc(doc, selector) === 1) return result(selector);
    }

    const type = attr(el, "type");
    if (tag === "input" && type) {
      const label = labelFor(el);
      if (label && label !== "(unlabeled)") {
        const lit = xpathLiteral(label);
        const xpath = `xpath=//label[contains(normalize-space(.), ${lit})]/following::input[@type=${xpathLiteral(type)}][1]`;
        return result(xpath, notes.concat(["XPath from nearby label"]));
      }
    }

    const text = truncate(textOf(el), 80);
    if ((tag === "button" || attr(el, "role") === "button" || tag === "a") && text) {
      const lit = xpathLiteral(text);
      return result(`xpath=(//*[self::button or self::a or @role='button'][contains(normalize-space(.), ${lit})])[1]`);
    }

    const classes = Array.from(el.classList || [])
      .filter(c => !/^(ng-|js-|is-|has-|active|focus|selected|open|show|disabled|valid|invalid|touched|dirty|pristine|css-|sc-)/.test(c))
      .filter(c => c.length < 48)
      .slice(0, 3);
    if (classes.length) {
      for (let i = classes.length; i >= 1; i -= 1) {
        const clsSelector = `${tag}.${classes.slice(0, i).map(cssEscape).join(".")}`;
        if (countInDoc(doc, clsSelector) === 1) return result(clsSelector);
      }
    }

    const label = labelFor(el);
    if (label && label !== "(unlabeled)") {
      return result(`xpath=(//*[contains(normalize-space(.), ${xpathLiteral(label)})]//${tag} | //*[contains(normalize-space(.), ${xpathLiteral(label)})]/following::${tag}[1])[1]`, notes.concat(["fallback XPath from visible label"]));
    }

    return result("(no stable selector)", notes);
  }

  function stableSelector(el) {
    const info = selectorInfo(el);
    return info.notes.length ? `${info.selector}  note: ${info.notes.join("; ")}` : info.selector;
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

  function datalistOptions(input) {
    const id = attr(input, "list");
    if (!id) return [];
    const list = ownDoc(input).getElementById(id);
    if (!list) return [];
    return Array.from(list.querySelectorAll("option")).map(o => attr(o, "label") || o.value || textOf(o));
  }

  function elementKey(el) {
    const info = selectorInfo(el);
    if (info.selector !== "(no stable selector)") return `${framePathForDoc(ownDoc(el), cachedFrames)}::${info.selector}`;
    const rect = el.getBoundingClientRect();
    return `${framePathForDoc(ownDoc(el), cachedFrames)}::${el.tagName}:${attr(el, "type")}:${labelFor(el)}:${Math.round(rect.top)}:${Math.round(rect.left)}`;
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

  log("");
  log("FORM EXTRACTOR - paste output to Codex");
  log("======================================");
  log("");
  log("URL:", location.href);
  log("Title:", document.title);
  log("Captured at:", new Date().toISOString());
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

  const buttons = queryAllDocs(cachedFrames, "button,input[type=button],input[type=submit],input[type=reset],a,[role=button],.link-type")
    .filter(isVisible)
    .filter(button => textOf(button) || attr(button, "aria-label") || attr(button, "title") || attr(button, "value"));
  if (buttons.length) {
    section("-- BUTTONS / LINKS ----------------------------------------------------");
    buttons.forEach((button, i) => {
      const text = truncate(textOf(button) || attr(button, "aria-label") || attr(button, "title") || attr(button, "value"));
      const type = attr(button, "type");
      const hint = isLikelyModalButton(button) ? "  likely reveal/modal trigger" : "";
      const frame = framePathForDoc(ownDoc(button), cachedFrames);
      const framePart = frame === "main" ? "" : `  frame: ${frame}`;
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
    logControlList(textInputs, cachedFrames);
    log("");
  }

  const selects = queryAllDocs(cachedFrames, "select").filter(isVisible);
  if (selects.length) {
    section("-- NATIVE DROPDOWNS (<select>) ---------------------------------------");
    logControlList(selects, cachedFrames);
    log("");
  }

  const datalistInputs = queryAllDocs(cachedFrames, "input[list]").filter(isVisible);
  if (datalistInputs.length) {
    section("-- DATALIST INPUTS ----------------------------------------------------");
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
      log(`  [${i + 1}] group name="${first.name || "(unnamed)"}"${question ? `  question="${truncate(question)}"` : ""}${framePart}`);
      log(`       scope: ${scope}`);
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
      log(`  [${i + 1}] "${truncate(textOf(dialog), 220)}"  selector: ${stableSelector(dialog)}${framePart}`);
    });
    log("");
  }

  if (warnings.length) {
    section("-- WARNINGS ----------------------------------------------------------");
    unique(warnings).forEach((item, i) => log(`  [${i + 1}] ${item}`));
    log("");
  }

  section("-- PLAYBOOK AUTHORING NOTES ------------------------------------------");
  log("  - Native <select> fields can use `select:` with the exact option text above.");
  log("  - Custom dropdowns usually need `press:`: focus selector, type option text, then Enter/Tab.");
  log("  - File inputs can use `upload:` directly, even when this report says hidden.");
  log("  - Radio/checkbox groups include a `scope:` candidate for `pick:` steps.");
  log("  - For conditionals, rerun this extractor after manually picking each Yes/Other/Add path if needed.");
  log("  - Never enable a final submit click until a human has reviewed the filled application.");
  log("");

  const output = lines.join("\n");
  console.log(output);

  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(output);
      console.log("\nOutput copied to clipboard - paste it to Codex.");
    } catch (_err) {
      console.log("\nClipboard copy failed - select the output above manually.");
    }
  } else {
    console.log("\nSelect the output above and copy it manually.");
  }
})();
