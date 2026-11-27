# ElevateBiz360 — Worldwide Partnership Lead Finder V7

**Upgraded from V6:** Adds independent web search for LinkedIn **company** pages (not LinkedIn personal profiles) to the existing worldwide partnership prospecting application. All existing V6 features remain: 91 countries/markets, the company-formation-only consultancy filter, accounting/real estate/law firms, CSV/XLSX exports, SQLite auto-save, separate Stop Search and Stop Sync controls, Google Sheets upsert by stable Lead ID, and website-based email/phone discovery.

## Upgrade without losing your work

1. Stop any running V6 search, contact-research or sync worker. Closing Chrome alone does not stop detached workers. Keep your existing local data folder untouched.
2. Extract this V7 ZIP into a **new** folder (not the existing V6 folder).
3. Open the new `europe_partner_finder` folder and double-click **run_windows.bat**. The launcher installs any missing Python dependencies. Navigate to http://localhost:8501 if your browser does not open automatically.
4. Your original SQLite database, uploaded-lead history and Google Sheet URL are reused. No CSV upload, copy, or new Google spreadsheet is needed.

### One required Google Apps Script upgrade

**V7 adds five columns to Google Sheets, so the V4/V6 Apps Script receiver MUST be upgraded before Google sync can continue.** Previous versions do not understand the new fields. V7 refuses to mark local leads synced until the receiver confirms version 7.

1. Open **Connect live Google Sheets** in V7. Your current Google Sheet and deployed `/exec` URL should already be shown.
2. Copy the **generated V7 Google Apps Script code** displayed inside the app (it embeds your existing sheet ID and locally stored secret).
3. In your *existing* Google Sheet select **Extensions → Apps Script**, replace the previous code with the generated V7 code, and **Save**.
4. Select **Deploy → Manage deployments → Edit (pencil) → Version: New version → Deploy**. Keep the existing Web app deployment and URL; **do not create a new deployment**.
5. Return to V7, click **Verify Google receiver is V7**, then **Sync all saved leads now** or **Resume Sync**. The `Partnership Leads` tab will gain the LinkedIn columns automatically. Existing rows are updated via Lead ID, not duplicated. LinkedIn company-page URLs are made clickable in the master tab.

The app's Google receiver code contains a shared secret: keep it private. Google Sheets sync is optional; local Excel, CSV and SQLite continue saving if Google is unavailable.

## Finding LinkedIn company pages — new and existing leads

**New searches:** The sidebar includes **Search for LinkedIn company pages during new scans** (enabled by default) and a configurable search limit (default 40 lookups per run). Each qualified lead is checked by searching a public search index for an indexed LinkedIn organization page. Searches are independent of whether the business website contains a LinkedIn link. The first 40 qualified leads are searched by default, not necessarily all leads in a large run.

**Already saved leads:** Expand **Find LinkedIn company pages for saved businesses** under the results, select 5–100 leads, and click **Find LinkedIn company pages**. This works for businesses that have **no website**, as long as their business name exists. The search runs as a separate background job and saves each completed result to SQLite/CSV/Excel, then syncs changed rows to Google. Click **Stop LinkedIn Search** to stop after the current query, preserving unfinished work. Recheck previously attempted pages by ticking **Recheck already searched/matched LinkedIn pages**.

### Search providers

- **Default: Bing RSS web search**, no API key. It searches externally indexed public web results, not the business's website alone. This is **best effort**, not guaranteed: Bing may block or rate-limit automated requests or may not index a particular company page. The app shows **Search unavailable** or **Not found**, rather than inventing a profile.
- **Optional: Brave Search API**, using an API key supplied and stored locally by the user in the sidebar's **LinkedIn web search provider** section. Consult Brave's API pricing; even tiers with free credits may require billing setup. The key is not exported to Google Sheets or included with lead data. You can remove it from Settings. Both search providers are deliberately rate-limited and use a configurable cap to avoid excess requests.

**The program never logs into LinkedIn, scrapes LinkedIn pages, automates a LinkedIn account, or collects personal profiles.** LinkedIn restricts unauthorized scraping and automated account activity. It only uses links and snippets indexed by general web search engines, plus link evidence from public official websites/OSM.

### Added export and Google Sheet columns

1. `LinkedIn Company Page` — normalized clickable `https://www.linkedin.com/company/.../` URL, when found.
2. `LinkedIn Match Status` — e.g. `Official website + indexed search match`, `Strong indexed match — review`, `Possible company match — review`, `Not found`, `Search unavailable`.
3. `LinkedIn Evidence` — name/location match hints and search result title, not proof of ownership.
4. `LinkedIn Search Provider` — Bing RSS, Brave Search API, official website or OpenStreetMap.
5. `LinkedIn Checked At (UTC)` — timestamp for a performed lookup.

The dashboard has a **LinkedIn Pages** tab and a LinkedIn filter (all / found / missing / review). Existing eight A1–D contact-availability categories remain unchanged because LinkedIn is a *separate* outreach method; a matching search result is not proof that the company operates the account.

## Saved files on Windows

The saved data is outside the application ZIP and remains under:

`%LOCALAPPDATA%\ElevateBiz360\EuropeanPartnerFinder\`

- `partner_leads.sqlite3` — authoritative recovery data.
- `partner_leads_live.xlsx` — country-wise Excel file, rewritten after each completed lead.
- `partner_leads_live.csv` — live CSV export.

If Excel is open, Windows may lock it; close the workbook and press **Refresh Excel/CSV files**. Local SQLite stays saved even when the laptop sleeps, but **the actual searches and sync cannot run while the computer is off or asleep**.

## Practical limitations and compliance

- OSM data and company website information are incomplete. LinkedIn page search may return an incorrect same-name firm: review the company, location, website, and service category before outreach.
- Search result snippets are not independently verified LinkedIn data. Only official-site linkage plus indexed result agreement merits the strongest label; even that is not proof of ownership.
- `Valid phone numbering format` does **not** mean the line is active; MX records do **not** confirm email delivery; company size is estimated cautiously.
- The company-formation filter keeps unrelated management, IT and marketing consultants out of new qualified searches; existing legacy leads remain for verification.
- Follow national direct-marketing rules, GDPR/ePrivacy when applicable, and professional referral restrictions for legal/accounting firms. © OpenStreetMap contributors (ODbL).

## Local offline tests

Run `py -m unittest discover -s tests -v` from the program folder. The included tests cover data migration, social URL validation, independent search engine results, false matches, throttled-provider failures, exports, LinkedIn recheck queue, Google Sheet upserts, stop/resume, and previous V6 behavior. **The live Bing/Brave, LinkedIn indexing, and real Google deployment are not testable offline**, so perform a small 5-lead test after installing.
