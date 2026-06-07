/**
 * form-extractor.js
 *
 * Paste into DevTools Console on any job application page.
 * Prints a structured summary you can hand to Claude to draft a playbook.
 *
 * Also available as a one-liner bookmarklet at the bottom of this file.
 */

(function extractForm() {
  const lines = [];
  const log = (...args) => lines.push(args.join(' '));

  // ── helpers ──────────────────────────────────────────────────────────────

  function labelFor(el) {
    // 1. explicit <label for="id">
    if (el.id) {
      const lbl = document.querySelector(`label[for="${el.id}"]`);
      if (lbl) return lbl.innerText.trim();
    }
    // 2. wrapping <label>
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.replace(el.value || '', '').trim();
    // 3. aria-label / aria-labelledby
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.getAttribute('aria-labelledby')) {
      const ref = document.getElementById(el.getAttribute('aria-labelledby'));
      if (ref) return ref.innerText.trim();
    }
    // 4. preceding sibling text / <legend> in fieldset
    const fieldset = el.closest('fieldset');
    if (fieldset) {
      const legend = fieldset.querySelector('legend');
      if (legend) return legend.innerText.trim();
    }
    // 5. placeholder fallback
    if (el.placeholder) return `[placeholder: ${el.placeholder}]`;
    return '(unlabeled)';
  }

  function stableSelector(el) {
    if (el.id) {
      // flag volatile ids (long random-looking segments)
      const volatile = /[a-z0-9]{8,}/i.test(el.id) && !/^[a-zA-Z_-]+$/.test(el.id);
      if (volatile) {
        // try to find a stable suffix
        const parts = el.id.split(/[-_]/);
        const stablePart = parts.slice(-2).join('_');
        return `[id$="${stablePart}"]  ⚠ volatile id, use suffix`;
      }
      return `#${el.id}`;
    }
    if (el.name) return `[name="${el.name}"]`;
    if (el.className) {
      const cls = Array.from(el.classList).filter(c => !/^(ng-|js-|is-|has-)/.test(c)).slice(0, 2).join('.');
      if (cls) return `.${cls}`;
    }
    return '(no stable selector)';
  }

  function optionList(select) {
    return Array.from(select.options)
      .map(o => o.text.trim())
      .filter(t => t && t !== '-- Select --' && t !== 'Select...' && t !== '')
      .join(' | ');
  }

  // ── page info ─────────────────────────────────────────────────────────────

  log('');
  log('╔══════════════════════════════════════════════════════════════╗');
  log('║              FORM EXTRACTOR — paste output to Claude         ║');
  log('╚══════════════════════════════════════════════════════════════╝');
  log('');
  log('URL:', location.href);
  log('Title:', document.title);
  log('');

  // ── buttons ───────────────────────────────────────────────────────────────

  const buttons = Array.from(document.querySelectorAll('button, input[type=button], input[type=submit], a[role=button]'))
    .filter(b => b.offsetParent !== null); // visible only
  if (buttons.length) {
    log('── BUTTONS ──────────────────────────────────────────────────');
    buttons.forEach((b, i) => {
      const text = (b.innerText || b.value || b.getAttribute('aria-label') || '').trim();
      if (text) log(`  [${i + 1}] "${text}"  selector: ${stableSelector(b)}`);
    });
    log('');
  }

  // ── text / email / tel / number / date inputs ─────────────────────────────

  const textInputs = Array.from(document.querySelectorAll(
    'input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]):not([type=submit]):not([type=button])'
  )).filter(el => el.offsetParent !== null);

  if (textInputs.length) {
    log('── TEXT INPUTS ───────────────────────────────────────────────');
    textInputs.forEach((el, i) => {
      log(`  [${i + 1}] label="${labelFor(el)}"  type=${el.type || 'text'}  selector: ${stableSelector(el)}`);
    });
    log('');
  }

  // ── textareas ─────────────────────────────────────────────────────────────

  const textareas = Array.from(document.querySelectorAll('textarea')).filter(el => el.offsetParent !== null);
  if (textareas.length) {
    log('── TEXTAREAS ─────────────────────────────────────────────────');
    textareas.forEach((el, i) => {
      log(`  [${i + 1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);
    });
    log('');
  }

  // ── selects (dropdowns) ───────────────────────────────────────────────────

  const selects = Array.from(document.querySelectorAll('select')).filter(el => el.offsetParent !== null);
  if (selects.length) {
    log('── DROPDOWNS (select) ────────────────────────────────────────');
    selects.forEach((el, i) => {
      log(`  [${i + 1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);
      const opts = optionList(el);
      if (opts) log(`       options: ${opts}`);
    });
    log('');
  }

  // ── file inputs ───────────────────────────────────────────────────────────

  const files = Array.from(document.querySelectorAll('input[type=file]')).filter(el => el.offsetParent !== null);
  if (files.length) {
    log('── FILE UPLOADS ──────────────────────────────────────────────');
    files.forEach((el, i) => {
      log(`  [${i + 1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);
    });
    log('');
  }

  // ── radio groups ──────────────────────────────────────────────────────────

  const radios = Array.from(document.querySelectorAll('input[type=radio]')).filter(el => el.offsetParent !== null);
  if (radios.length) {
    const groups = {};
    radios.forEach(r => {
      const grp = r.name || '(unnamed)';
      if (!groups[grp]) groups[grp] = [];
      const lbl = labelFor(r);
      if (!groups[grp].includes(lbl)) groups[grp].push(lbl);
    });
    log('── RADIO GROUPS ──────────────────────────────────────────────');
    Object.entries(groups).forEach(([name, opts]) => {
      // try to find the question text from a fieldset legend or preceding heading
      const firstRadio = radios.find(r => r.name === name);
      const fieldset = firstRadio && firstRadio.closest('fieldset');
      const question = fieldset ? (fieldset.querySelector('legend') || {}).innerText || '' : '';
      log(`  group name="${name}"${question ? `  question="${question.trim()}"` : ''}`);
      log(`       options: ${opts.join(' | ')}`);
    });
    log('');
  }

  // ── checkboxes ────────────────────────────────────────────────────────────

  const checkboxes = Array.from(document.querySelectorAll('input[type=checkbox]')).filter(el => el.offsetParent !== null);
  if (checkboxes.length) {
    log('── CHECKBOXES ────────────────────────────────────────────────');
    checkboxes.forEach((el, i) => {
      log(`  [${i + 1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);
    });
    log('');
  }

  // ── output ────────────────────────────────────────────────────────────────

  const output = lines.join('\n');
  console.log(output);

  // also copy to clipboard if possible
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(output).then(
      () => console.log('\n✅ Output copied to clipboard — paste it to Claude.'),
      () => console.log('\n⚠ Clipboard copy failed — select the output above manually.')
    );
  } else {
    console.log('\n(Select the output above and copy it manually.)');
  }
})();

// ── BOOKMARKLET (one-liner) ───────────────────────────────────────────────────
//
// To install: create a new bookmark in Chrome/Firefox, paste the line below
// as the URL. Click the bookmark while on any job application page.
//
// javascript:(function(){const lines=[];const log=(...a)=>lines.push(a.join(' '));function labelFor(el){if(el.id){const lbl=document.querySelector(`label[for="${el.id}"]`);if(lbl)return lbl.innerText.trim();}const wrap=el.closest('label');if(wrap)return wrap.innerText.replace(el.value||'','').trim();if(el.getAttribute('aria-label'))return el.getAttribute('aria-label').trim();if(el.getAttribute('aria-labelledby')){const ref=document.getElementById(el.getAttribute('aria-labelledby'));if(ref)return ref.innerText.trim();}const fieldset=el.closest('fieldset');if(fieldset){const legend=fieldset.querySelector('legend');if(legend)return legend.innerText.trim();}if(el.placeholder)return`[placeholder: ${el.placeholder}]`;return'(unlabeled)';}function stableSelector(el){if(el.id){const volatile=/[a-z0-9]{8,}/i.test(el.id)&&!/^[a-zA-Z_-]+$/.test(el.id);if(volatile){const parts=el.id.split(/[-_]/);const stablePart=parts.slice(-2).join('_');return`[id$="${stablePart}"]  ⚠ volatile`;}return`#${el.id}`;}if(el.name)return`[name="${el.name}"]`;return'(no stable selector)';}function optionList(select){return Array.from(select.options).map(o=>o.text.trim()).filter(t=>t&&t!=='-- Select --'&&t!=='Select...'&&t!=='').join(' | ');}log('');log('URL:',location.href);log('Title:',document.title);log('');const buttons=Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a[role=button]')).filter(b=>b.offsetParent!==null);if(buttons.length){log('── BUTTONS');buttons.forEach((b,i)=>{const text=(b.innerText||b.value||b.getAttribute('aria-label')||'').trim();if(text)log(`  [${i+1}] "${text}"  selector: ${stableSelector(b)}`);});log('');}const textInputs=Array.from(document.querySelectorAll('input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]):not([type=submit]):not([type=button])')).filter(el=>el.offsetParent!==null);if(textInputs.length){log('── TEXT INPUTS');textInputs.forEach((el,i)=>{log(`  [${i+1}] label="${labelFor(el)}"  type=${el.type||'text'}  selector: ${stableSelector(el)}`);});log('');}const textareas=Array.from(document.querySelectorAll('textarea')).filter(el=>el.offsetParent!==null);if(textareas.length){log('── TEXTAREAS');textareas.forEach((el,i)=>{log(`  [${i+1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);});log('');}const selects=Array.from(document.querySelectorAll('select')).filter(el=>el.offsetParent!==null);if(selects.length){log('── DROPDOWNS');selects.forEach((el,i)=>{log(`  [${i+1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);const opts=optionList(el);if(opts)log(`       options: ${opts}`);});log('');}const files=Array.from(document.querySelectorAll('input[type=file]')).filter(el=>el.offsetParent!==null);if(files.length){log('── FILE UPLOADS');files.forEach((el,i)=>{log(`  [${i+1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);});log('');}const radios=Array.from(document.querySelectorAll('input[type=radio]')).filter(el=>el.offsetParent!==null);if(radios.length){const groups={};radios.forEach(r=>{const grp=r.name||'(unnamed)';if(!groups[grp])groups[grp]=[];const lbl=labelFor(r);if(!groups[grp].includes(lbl))groups[grp].push(lbl);});log('── RADIO GROUPS');Object.entries(groups).forEach(([name,opts])=>{log(`  group name="${name}"`);log(`       options: ${opts.join(' | ')}`);});log('');}const checkboxes=Array.from(document.querySelectorAll('input[type=checkbox]')).filter(el=>el.offsetParent!==null);if(checkboxes.length){log('── CHECKBOXES');checkboxes.forEach((el,i)=>{log(`  [${i+1}] label="${labelFor(el)}"  selector: ${stableSelector(el)}`);});log('');}const output=lines.join('\n');console.log(output);if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(output).then(()=>console.log('✅ Copied to clipboard'),()=>console.log('⚠ Copy failed'));}})();
