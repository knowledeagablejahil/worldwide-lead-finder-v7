"""OSM lead discovery, cautious public-site enrichment, and CSV export.

A source match, phone-number format, or MX record is NOT proof that a contact
is live or that a firm is small. These distinctions are intentionally preserved.
"""
from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import re
import socket
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import dns.resolver
try:
    import phonenumbers
except ImportError:  # Helpful when reviewing the source before installing requirements
    phonenumbers = None
import requests
from bs4 import BeautifulSoup

from markets import CATEGORIES, MARKETS
from formation_filter import CATEGORY as FORMATION_CATEGORY, map_evidence, clearly_other_consultancy, website_evidence

USER_AGENT = "ElevateBiz360-WorldwidePartnerFinder/7.0 (public business contacts; polite low-volume research)"
OVERPASS_ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_TTL = 3 * 24 * 3600

# Large chain screening is intentionally a candidate filter, not a company-size database.
LARGE_BRANDS = [
    "deloitte", "pricewaterhousecoopers", "pwc", "kpmg", "ernst & young",
    "ey global", "grant thornton", "mazars", "forvis", "bdo", "baker tilly",
    "rsm international", "jll", "jones lang lasalle", "cbre", "savills",
    "colliers", "knight frank", "cushman", "re/max", "remax", "century 21",
    "keller williams", "exp realty", "engel & völkers", "engel & volkers",
]
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,24}", re.I)
EXCLUDED_EMAIL_PREFIXES = ("noreply@", "no-reply@", "privacy@", "abuse@", "webmaster@")
GENERIC_EMAIL_PREFIXES = ("info@", "contact@", "office@", "enquiries@", "inquiries@", "hello@", "mail@", "reception@", "admin@")
EXPORT_COLUMNS = [
    "Country", "City", "Business Name", "Category", "Website", "Business Email",
    "Email Source", "Email Check", "Phone", "Phone Format Check", "Phone Website Match",
    "Firm Size", "Partnership Priority", "Score", "UAE Mention (checked pages)",
    "OSM Listing", "Website Pages Checked", "Collected At (UTC)", "Review Notes",
]
from quality import NEW_COLUMNS
from linkedin_discovery import LINKEDIN_COLUMNS, from_osm, search_company
EXPORT_COLUMNS += NEW_COLUMNS + LINKEDIN_COLUMNS


def _safe_cache_read(key: str):
    path = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")
    try:
        if time.time() - path.stat().st_mtime < CACHE_TTL:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _safe_cache_write(key: str, value):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_query(lat: float, lon: float, radius_km: int, categories: list[str]) -> str:
    # Only map values are allowed, preventing arbitrary user input inside Overpass regex.
    tags = sorted({x for category in categories for x in CATEGORIES[category]})
    office_types = "|".join(re.escape(tag) for tag in tags)
    return (
        f'[out:json][timeout:40];\n'
        f'(nwr(around:{int(radius_km)*1000},{lat:.6f},{lon:.6f})'
        f'["office"~"^({office_types})$"];);\n'
        'out center tags;'
    )


def query_city(country: str, city: str, radius_km: int, categories: list[str]) -> list[dict]:
    coords = MARKETS[country]["cities"][city]
    query = build_query(*coords, radius_km, categories)
    cache_key = f"overpass:{country}:{city}:{query}"
    data = _safe_cache_read(cache_key)
    if data is None:
        failures = []
        for endpoint in OVERPASS_ENDPOINTS:
            for delay in (0, 3):
                if delay:
                    time.sleep(delay)
                try:
                    response = requests.post(
                        endpoint,
                        data={"data": query},
                        headers={"User-Agent": USER_AGENT},
                        timeout=(12, 65),
                    )
                    response.raise_for_status()
                    data = response.json()
                    if "elements" not in data:
                        raise ValueError("Unexpected response without Overpass elements")
                    _safe_cache_write(cache_key, data)
                    break
                except (requests.RequestException, ValueError) as exc:
                    failures.append(f"{endpoint}: {str(exc)[:110]}")
            if data is not None:
                break
        if data is None:
            raise RuntimeError("Overpass request failed. Try a smaller radius or later. " + "; ".join(failures[-2:]))

    out = []
    valid_types = {t for group in categories for t in CATEGORIES[group]}
    for item in data["elements"]:
        tags = item.get("tags", {})
        name = str(tags.get("name") or tags.get("brand") or "").strip()
        office = tags.get("office", "")
        if not name or office not in valid_types:
            continue
        category = next((c for c in categories if office in CATEGORIES[c]), "")
        url = tags.get("contact:website") or tags.get("website") or tags.get("url") or ""
        email = tags.get("contact:email") or tags.get("email") or ""
        phone = tags.get("contact:phone") or tags.get("phone") or tags.get("contact:mobile") or ""
        out.append({
            "Country": country, "City": city, "Business Name": name,
            "Category": category, "Website": normalize_url(url),
            "Business Email": first_email(email), "Email Source": "OpenStreetMap" if first_email(email) else "",
            "Phone": str(phone).split(";")[0].strip(),
            "OSM Listing": f'https://www.openstreetmap.org/{item["type"]}/{item["id"]}',
            "_osm_tags": tags,
        })
    return out


def normalize_url(url: str) -> str:
    url = str(url or "").strip().split(";")[0].strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urlparse(url)
    return url if parts.scheme in ("http", "https") and parts.hostname else ""


def first_email(value: str) -> str:
    found = EMAIL_RE.findall(str(value or "").replace("%40", "@"))
    return found[0].lower() if found else ""


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _public_hostname(host: str) -> bool:
    if not host or host in ("localhost", "local") or host.endswith((".local", ".internal", ".onion")):
        return False
    try:
        addresses = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        return bool(addresses) and all(
            ipaddress.ip_address(a[4][0]).is_global for a in addresses
        )
    except (OSError, ValueError):
        return False


def _get_public(url: str, timeout: int = 12) -> requests.Response | None:
    # Check every redirect to avoid OSM-listed URLs reaching private/local services.
    for _ in range(3):
        if not url.startswith(("http://", "https://")) or not _public_hostname(_hostname(url)):
            return None
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT},
                                    timeout=(6, timeout), allow_redirects=False,
                                    stream=True)
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("Location", ""))
                response.close()
                continue
            if response.status_code != 200:
                response.close()
                return None
            content_type = response.headers.get("Content-Type", "").lower()
            content_length = int(response.headers.get("Content-Length", "0") or 0)
            if "text/html" not in content_type or content_length > 800_000:
                response.close()
                return None
            # Constrain downloaded pages. requests streaming is still subject to network timeout.
            response._content = response.raw.read(800_001, decode_content=True)
            response.close()
            if len(response.content) > 800_000:
                return None
            return response
        except (requests.RequestException, ValueError, OSError):
            return None
    return None


_robots_cache: dict[str, tuple[RobotFileParser | None, float]] = {}


def _can_fetch(url: str) -> tuple[bool, float]:
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if not _public_hostname(parts.hostname or ""):
        return False, 0
    if origin not in _robots_cache:
        robots_url = origin + "/robots.txt"
        try:
            res = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=(5, 8), allow_redirects=False)
            if res.status_code == 404:
                _robots_cache[origin] = (None, 1.0)
            elif res.status_code == 200:
                parser = RobotFileParser()
                parser.parse(res.text.splitlines())
                _robots_cache[origin] = (parser, max(float(parser.crawl_delay(USER_AGENT) or 1.0), 1.0))
            else:
                _robots_cache[origin] = (None, -1.0)  # fail closed
        except requests.RequestException:
            _robots_cache[origin] = (None, -1.0)
    parser, delay = _robots_cache[origin]
    return delay >= 0 and (parser is None or parser.can_fetch(USER_AGENT, url)), max(delay, 0)


def site_enrichment(url: str, *, check_formation: bool = False) -> dict:
    """Public HTML only, robots-aware, at most three pages; no search engine scraping.

    When checking incorporation services, prioritize a service-specific link
    found on the official homepage over the generic /about page.
    """
    url = normalize_url(url)
    empty = {"emails": [], "phones": [], "pages": [], "uae_mention": "Not checked",
             "size_hint": "", "formation_phrase": "", "formation_url": "", "linkedin_links": []}
    if not url or _hostname(url) in ("facebook.com", "linkedin.com", "instagram.com", "x.com"):
        return empty
    candidates = [url, urljoin(url, "/contact"), urljoin(url, "/about")]
    localized = ["/kontakt", "/contacto", "/contatti", "/contactez-nous", "/impressum"]
    candidates += [urljoin(url, x) for x in localized]
    emails, phones, pages, combined_text = set(), set(), [], []
    linkedin_links = set()
    attempted = set()
    home_host = _hostname(url)
    formation_phrase, formation_url = '', ''
    index = 0
    while index < len(candidates) and len(pages) < 3 and len(attempted) < 6:
        page = candidates[index]
        index += 1
        if page in attempted or _hostname(page) != home_host:
            continue
        attempted.add(page)
        allowed, delay = _can_fetch(page)
        if not allowed:
            continue
        response = _get_public(page)
        if response is None:
            continue
        pages.append(page)
        soup = BeautifulSoup(response.content, "html.parser")
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            from linkedin_discovery import company_url
            company_link = company_url(urljoin(page, href))
            if company_link:
                linkedin_links.add(company_link)
            if href.startswith("mailto:"):
                e = first_email(href[7:].split("?")[0])
                if e:
                    emails.add(e)
            if href.startswith("tel:"):
                phones.add(href[4:].split("?")[0].strip())
        text = soup.get_text(" ", strip=True)
        combined_text.append(text[:20_000].lower())
        for e in EMAIL_RE.findall(text):
            e = e.lower().strip(". ,;:")
            if not e.startswith(EXCLUDED_EMAIL_PREFIXES):
                emails.add(e)
        if check_formation:
            phrase = website_evidence(text[:60_000])
            if phrase and not formation_phrase:
                formation_phrase, formation_url = phrase, page
            # Service pages are frequently more reliable than the footer or About page.
            # Only one extra service URL is searched, on the same official hostname.
            if len(pages) == 1 and not formation_phrase:
                service_links = []
                for anchor in soup.find_all("a", href=True):
                    destination = urljoin(page, anchor.get("href", ""))
                    text_and_path = anchor.get_text(" ", strip=True) + " " + urlparse(destination).path
                    if (_hostname(destination) == home_host and
                        website_evidence(text_and_path.replace('-', ' '))):
                        service_links.append(destination)
                if service_links:
                    candidates.insert(index, service_links[0])
        time.sleep(min(delay, 2.0))
    joined = " ".join(combined_text)
    hint = ""
    if any(phrase in joined for phrase in ("independent firm", "boutique law firm", "boutique consultancy", "family-run", "owner-managed", "small team")):
        hint = "Smaller-firm wording on website (unverified)"
    uae_words = ("dubai", "united arab emirates", "abu dhabi", "uae company formation", "company setup in uae")
    return {
        "emails": sorted(emails), "phones": sorted(phones), "pages": pages,
        "uae_mention": "Mention found" if any(word in joined for word in uae_words) else ("Not found in checked pages" if pages else "Not checked"),
        "size_hint": hint,
        "formation_phrase": formation_phrase,
        "formation_url": formation_url,
        "linkedin_links": sorted(linkedin_links),
    }


def email_status(email: str) -> str:
    if not email:
        return "Missing"
    parts = email.split("@")
    if len(parts) != 2 or not EMAIL_RE.fullmatch(email):
        return "Invalid syntax"
    try:
        mx = dns.resolver.resolve(parts[1], "MX", lifetime=3)
        return "Valid syntax + MX (delivery NOT verified)" if len(mx) else "No MX found"
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return "No MX found"
    except (dns.exception.DNSException, OSError):
        return "MX check inconclusive"


def normalized_phone(phone: str, country_code: str) -> tuple[str, str]:
    if not phone:
        return "", "Missing"
    if phonenumbers is None:
        return phone, "Phone check unavailable — install requirements"
    phone = re.split(r"\s+(?:ext\.?|extension|x)\s*\d+", phone, maxsplit=1, flags=re.I)[0]
    try:
        parsed = phonenumbers.parse(phone, country_code)
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        if phonenumbers.is_valid_number(parsed):
            return e164, "Valid numbering format (NOT active-line verified)"
        return e164, "Invalid or unassigned numbering format"
    except phonenumbers.NumberParseException:
        return phone, "Could not parse"


def _website_email_choice(emails: list[str], website: str) -> str:
    domain = _hostname(website)
    safe = [e for e in emails if not e.startswith(EXCLUDED_EMAIL_PREFIXES)]
    safe.sort(key=lambda e: (
        not (e.split("@")[-1] == domain or domain.endswith("." + e.split("@")[-1])),
        not e.startswith(GENERIC_EMAIL_PREFIXES),
        e,
    ))
    return safe[0] if safe else ""


def is_large_chain(name: str) -> bool:
    clean = re.sub(r"[^a-z0-9/& +]", " ", name.lower()).strip()
    return any(re.search(r"(?<![a-z])" + re.escape(b) + r"(?![a-z])", clean) for b in LARGE_BRANDS)


def deduplicate(rows: list[dict]) -> list[dict]:
    """Do not drop different firms just because they share a generic/social website."""
    unique = {}
    for row in rows:
        name = re.sub(r"\W+", "", row["Business Name"].casefold())
        key = (row["Country"], row["City"], name)
        old = unique.get(key)
        if not old or sum(bool(old.get(k)) for k in ("Website", "Business Email", "Phone")) < sum(bool(row.get(k)) for k in ("Website", "Business Email", "Phone")):
            unique[key] = row
    return list(unique.values())


def refine(rows: list[dict], max_websites: int, callback=None, exclude_large=True,
           on_row=None, on_skip=None, should_stop=None,
           linkedin_search_limit=0, linkedin_api_key='') -> list[dict]:
    output = []
    enriched_sites = 0
    searched_linkedin = 0
    enriched_cache = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    for idx, row in enumerate(rows):
        if should_stop and should_stop():
            break
        row = dict(row)
        name, website = row["Business Name"], row["Website"]
        formation_scan = row.get("Category") == FORMATION_CATEGORY
        if formation_scan and clearly_other_consultancy(name, row.get("_osm_tags")):
            if on_skip:
                on_skip(row)
            continue
        if exclude_large and is_large_chain(name):
            if on_skip:
                on_skip(row)
            continue
        country_code = MARKETS[row["Country"]]["country_code"]
        info = {"emails": [], "phones": [], "pages": [], "uae_mention": "Not checked",
                "size_hint": "", "formation_phrase": "", "formation_url": "", "linkedin_links": []}
        cache_key = (_hostname(website), formation_scan)
        if website and cache_key[0] and (cache_key in enriched_cache or enriched_sites < max_websites):
            if cache_key not in enriched_cache:
                try:
                    enriched_cache[cache_key] = site_enrichment(website, check_formation=formation_scan)
                except Exception:
                    enriched_cache[cache_key] = info
                enriched_sites += 1
            info = enriched_cache[cache_key]
        if formation_scan:
            osm_match = map_evidence(name, row.get("_osm_tags"))
            web_match = info.get("formation_phrase", "")
            if web_match:
                row["Service Qualification"] = "Website evidence"
                row["Service Evidence"] = f"{web_match} · {info.get('formation_url', '')}"
            elif row.get("Service Qualification") == "Website evidence" and row.get("Service Evidence"):
                # Website may be unavailable on a later contact-only recheck.
                # Preserve previously collected qualifying evidence.
                pass
            elif osm_match:
                row["Service Qualification"] = "OSM evidence — needs website confirmation"
                row["Service Evidence"] = f"{osm_match} · {row.get('OSM Listing', '')}"
            elif str(row.get("Service Qualification") or '').startswith('OSM evidence') and row.get("Service Evidence"):
                pass
            else:
                # Do not send generic consultants into the qualified partnership database.
                # This includes sites not inspected because the configured limit was reached.
                if on_skip:
                    on_skip(row)
                continue
        website_email = _website_email_choice(info["emails"], website)
        existing_email = row.get("Business Email", "")
        if website_email:
            row["Business Email"] = website_email
            row["Email Source"] = "Website listed in OSM (public page)"
        elif existing_email:
            row["Email Source"] = "OpenStreetMap"
        row["Email Check"] = email_status(row.get("Business Email", ""))
        normalized_osm, osm_status = normalized_phone(row.get("Phone", ""), country_code)
        web_phones = [normalized_phone(p, country_code) for p in info["phones"]]
        valid_web_phones = [p for p, status in web_phones if status.startswith("Valid numbering")]
        if normalized_osm and normalized_osm in valid_web_phones:
            row["Phone"] = normalized_osm
            row["Phone Format Check"] = osm_status
            row["Phone Website Match"] = "Yes, same number on listed website"
        elif not normalized_osm and valid_web_phones:
            row["Phone"] = valid_web_phones[0]
            row["Phone Format Check"] = "Valid numbering format (NOT active-line verified)"
            row["Phone Website Match"] = "Found on listed website"
        else:
            row["Phone"] = normalized_osm
            row["Phone Format Check"] = osm_status
            row["Phone Website Match"] = "Not confirmed"
        row["Firm Size"] = info["size_hint"] or "Not verified — manual review needed"
        row["UAE Mention (checked pages)"] = info["uae_mention"]
        row["Website Pages Checked"] = "; ".join(info["pages"])
        row["Collected At (UTC)"] = today
        # Search independently using a public search index, not just the firm's
        # existing website. Saving happens after every lead, even on failed searches.
        tagged_link = from_osm(row.get('_osm_tags'))
        if (searched_linkedin < linkedin_search_limit and
                not (should_stop and should_stop())):
            row.update(search_company(row, api_key=linkedin_api_key,
                        site_links=info.get('linkedin_links', []), osm_tags=row.get('_osm_tags')))
            searched_linkedin += 1
        elif tagged_link and not row.get('LinkedIn Company Page'):
            row['LinkedIn Company Page'] = tagged_link
            row['LinkedIn Match Status'] = 'OSM link — review'
            row['LinkedIn Evidence'] = 'LinkedIn organization URL from OSM tags (independent search not run)'
            row['LinkedIn Search Provider'] = 'OpenStreetMap'
        row["Review Notes"] = "Not proof of independent ownership, firm size, email deliverability, or live phone service"
        if formation_scan:
            row["Review Notes"] += "; Incorporation evidence: " + row["Service Evidence"]
        score = (20 if website else 0) + (20 if row.get("Business Email") else 0)
        score += (10 if row["Email Check"].startswith("Valid syntax + MX") else 0)
        score += (20 if row["Phone Website Match"] != "Not confirmed" else 0)
        score += (10 if row["Phone Format Check"].startswith("Valid numbering") else 0)
        score += (10 if info["size_hint"] else 0)
        score += (10 if info["uae_mention"] == "Not found in checked pages" else 0)
        row["Score"] = score
        row["Partnership Priority"] = "High" if score >= 70 else ("Medium" if score >= 45 else "Low")
        row.pop("_osm_tags", None)
        from quality import classify
        row = classify(row)
        output.append(row)
        if on_row:
            on_row(row)  # persist after EVERY processed lead, not when the whole batch finishes
        if callback:
            callback(idx + 1, len(rows), enriched_sites)
    return sorted(output, key=lambda r: (r["Country"], -r["Score"], r["Business Name"]))


def csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # Protect spreadsheet applications against CSV formula injection.
        safe_row = {k: ("'" + str(row.get(k, "")) if str(row.get(k, "")).startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else row.get(k, "")) for k in EXPORT_COLUMNS}
        writer.writerow(safe_row)
    return output.getvalue().encode("utf-8-sig")
