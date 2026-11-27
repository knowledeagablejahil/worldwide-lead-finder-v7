/**
 * ElevateBiz360 V7: adds LinkedIn company page discovery columns to EXISTING data.
 * Replace your existing Apps Script source and deploy a NEW VERSION of the
 * same Web app deployment. Keep its /exec URL, secret and target Sheet ID.
 * Incoming leads can update their original row by the stable Lead ID.
 */
const SHEET_ID = __SHEET_ID__;
const SHARED_SECRET = __SHARED_SECRET__;
const VERSION = 7;
const TAB_NAME = 'Partnership Leads';
const BASE_COLS = [
  'Country', 'City', 'Business Name', 'Category', 'Website', 'Business Email',
  'Email Source', 'Email Check', 'Phone', 'Phone Format Check',
  'Phone Website Match', 'Firm Size', 'Partnership Priority', 'Score',
  'UAE Mention (checked pages)', 'OSM Listing', 'Website Pages Checked',
  'Collected At (UTC)', 'Review Notes'
];
const EXTRA_COLS = [
  'Contact Category', 'Contact Verification', 'Partnership Fit',
  'Fit Evidence', 'Next Action', 'Workflow Queue',
  'LinkedIn Company Page', 'LinkedIn Match Status', 'LinkedIn Evidence',
  'LinkedIn Search Provider', 'LinkedIn Checked At (UTC)'
];
const SYNC_COL = 'Synced At (UTC)';
const HEADERS = ['Lead ID'].concat(BASE_COLS, [SYNC_COL], EXTRA_COLS);

function reply_(object) {
  return ContentService.createTextOutput(JSON.stringify(object))
    .setMimeType(ContentService.MimeType.JSON);
}
function safe_(value, col) {
  if (col === 'Score') {
    const n = Number(value);
    return Number.isFinite(n) ? n : '';
  }
  const text = String(value == null ? '' : value).slice(0, 1500)
    .replace(/[\u0000-\u001F\u007F]/g, ' ');
  // Formula injection protections for mapped data; retain literal +44 numbers.
  return /^[=+\-@\t\r\n]/.test(text) ? "'" + text : text;
}
function letter_(number) {
  let s = '';
  while (number > 0) { number--; s = String.fromCharCode(65 + number % 26) + s; number = Math.floor(number / 26); }
  return s;
}
// Explicit clickable hyperlink on the master row. No formula evaluation.
function makeLinkedInClickable_(sheet, rowNumber, headers, value) {
  const col = headers.indexOf('LinkedIn Company Page') + 1;
  if (!col || typeof value !== 'string') return;
  const url = value.trim();
  if (!/^https:\/\/www\.linkedin\.com\/company\/[a-z0-9_-]{2,100}\/$/i.test(url)) return;
  sheet.getRange(rowNumber, col).setRichTextValue(
    SpreadsheetApp.newRichTextValue().setText(url).setLinkUrl(url).build());
}
function ensureMaster_(ss) {
  let sheet = ss.getSheetByName(TAB_NAME);
  if (!sheet) sheet = ss.insertSheet(TAB_NAME);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
    sheet.setFrozenRows(1);
  }
  let headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  // Fail safely if the V3 core was manually moved, to avoid corrupting data.
  const expected = ['Lead ID'].concat(BASE_COLS, [SYNC_COL]);
  if (expected.some((value, i) => headers[i] !== value)) {
    throw new Error('Existing header order changed: restore V3 Lead ID / core headers before syncing');
  }
  for (const name of EXTRA_COLS) {
    if (headers.indexOf(name) === -1) {
      const at = headers.length + 1;
      sheet.getRange(1, at).setValue(name);
      headers.push(name);
    }
  }
  sheet.getRange(1, 1, 1, headers.length)
    .setBackground('#23324e').setFontColor('#ffffff').setFontWeight('bold');
  sheet.setFrozenRows(1);
  return {sheet: sheet, headers: headers};
}
function ensureViews_(ss, headers) {
  const sourceRange = "'" + TAB_NAME + "'!A:" + letter_(headers.length);
  const queueLetter = letter_(headers.indexOf('Workflow Queue') + 1);
  for (const name of ['Ready for Outreach', 'Needs Contact Research', 'Hold']) {
    let target = ss.getSheetByName(name);
    if (!target) {
      target = ss.insertSheet(name);
      const escaped = name.replace(/'/g, "''");
      const formula = '=IFERROR(QUERY(' + sourceRange + ',"select * where ' +
        queueLetter + ' = \'' + escaped + '\'",1),' +
        "'" + TAB_NAME + "'!A1:" + letter_(headers.length) + '1)';
      target.getRange(1, 1).setFormula(formula);
      target.setFrozenRows(1);
    }
    // Update only the formula the app itself created. Never overwrite user views.
    if (target.getRange(1,1).getFormula().startsWith("=IFERROR(QUERY('Partnership Leads'!")) {
      const escaped = name.replace(/'/g, "''");
      const formula = '=IFERROR(QUERY(' + sourceRange + ',"select * where ' +
        queueLetter + ' = \'' + escaped + '\'",1),' +
        "'" + TAB_NAME + "'!A1:" + letter_(headers.length) + '1)';
      target.getRange(1,1).setFormula(formula);
    }
    // Custom user-maintained sheets are left intact.
  }
}
function doPost(e) {
  let lock, locked = false;
  try {
    if (!e || !e.postData || !e.postData.contents || e.postData.contents.length > 250000)
      return reply_({ok:false,error:'Empty or oversized request',version:VERSION});
    const body = JSON.parse(e.postData.contents);
    if (typeof body.secret !== 'string' || body.secret !== SHARED_SECRET)
      return reply_({ok:false,error:'Incorrect connection secret',version:VERSION});
    const ss = SpreadsheetApp.openById(SHEET_ID);
    if (body.action === 'ping')
      return reply_({ok:true,version:VERSION,sheet_id:SHEET_ID,sheet_name:ss.getName()});
    if (body.action !== 'upsert' || !Array.isArray(body.rows) || body.rows.length > 25)
      return reply_({ok:false,error:'Invalid action or batch; maximum 25 rows',version:VERSION});
    lock = LockService.getScriptLock();
    locked = lock.tryLock(20000);
    if (!locked) return reply_({ok:false,error:'Sheet busy; retry',version:VERSION});
    const state = ensureMaster_(ss);
    const sheet = state.sheet;
    const headers = state.headers;
    const n = sheet.getLastRow();
    const existingIds = n > 1 ? sheet.getRange(2,1,n-1,1).getDisplayValues().map(x => String(x[0])) : [];
    const locations = new Map(existingIds.map((x,i) => [x,i+2]));
    const additions = [], accepted = [], changes = [];
    const now = new Date().toISOString();
    for (const item of body.rows) {
      const id = String(item && item.id || '').toLowerCase();
      if (!/^[0-9a-f]{64}$/.test(id) || !item.data || typeof item.data !== 'object') continue;
      const vals = {};
      for (const col of BASE_COLS.concat(EXTRA_COLS)) vals[col] = safe_(item.data[col], col);
      vals[SYNC_COL] = now;
      if (locations.has(id)) {
        changes.push({index: locations.get(id), values: vals});
      } else {
        const index = n + additions.length + 1;
        locations.set(id, index);
        additions.push(headers.map(col => col === 'Lead ID' ? id : (vals[col] == null ? '' : vals[col])));
      }
      accepted.push(id);
    }
    if (additions.length) {
      sheet.getRange(n+1,1,additions.length,headers.length).setValues(additions);
      for (let i=0; i<additions.length; i++) {
        makeLinkedInClickable_(sheet,n+1+i,headers,String(additions[i][headers.indexOf('LinkedIn Company Page')] || ''));
      }
    }
    const baseStart = 2;
    const extraPositions = EXTRA_COLS.map(c => headers.indexOf(c)+1);
    const extraContiguous = extraPositions.every((p,i) => p === extraPositions[0]+i);
    for (const change of changes) {
      const r = change.index, values = change.values;
      sheet.getRange(r,baseStart,1,BASE_COLS.length).setValues([BASE_COLS.map(c=>values[c])]);
      sheet.getRange(r,headers.indexOf(SYNC_COL)+1).setValue(now);
      if (extraContiguous)
        sheet.getRange(r,extraPositions[0],1,EXTRA_COLS.length).setValues([EXTRA_COLS.map(c=>values[c])]);
      else EXTRA_COLS.forEach((c,i)=>sheet.getRange(r,extraPositions[i]).setValue(values[c]));
      makeLinkedInClickable_(sheet,r,headers,String(values['LinkedIn Company Page'] || ''));
    }
    ensureViews_(ss,headers);
    SpreadsheetApp.flush();
    return reply_({ok:true,version:VERSION,accepted_ids:accepted,inserted:additions.length,
                   updated:changes.length,sheet_id:SHEET_ID});
  } catch (error) {
    return reply_({ok:false,version:VERSION,error:String(error && error.message || error).slice(0,250)});
  } finally { if (lock && locked) lock.releaseLock(); }
}
