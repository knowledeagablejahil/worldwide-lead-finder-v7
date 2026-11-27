"""Public-index lookup of LinkedIn COMPANY pages (not LinkedIn scraping).

Queries a general web search index: Bing RSS by default, or the licensed Brave
Search API when the user supplies their own key. Never logs in to LinkedIn,
fetches its pages, scrapes individuals, or assumes a similar name is a match.
"""
from __future__ import annotations

import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlparse, unquote

import requests

BING_ENDPOINT = 'https://www.bing.com/search'
BRAVE_ENDPOINT = 'https://api.search.brave.com/res/v1/web/search'
UA = 'ElevateBiz360-PartnerFinder/7.0 (company-page link discovery via public search indexes)'
LINKEDIN_COLUMNS = [
    'LinkedIn Company Page', 'LinkedIn Match Status', 'LinkedIn Evidence',
    'LinkedIn Search Provider', 'LinkedIn Checked At (UTC)',
]
NOISE = frozenset('the and of group limited ltd llc inc incorporated gmbh ag sarl sa bv b v llp plc co company corporation corp services service international pty private pvt fze fzco sp z oo'.split())
SEARCH_GAP = 1.1
_last_search_at = 0.0


def company_url(value: str) -> str:
    """Accept only actual LinkedIn organization pages, never personal profiles."""
    url = str(value or '').strip()
    if not url:
        return ''
    if not url.startswith(('https://','http://')):
        url = 'https://' + url.lstrip('/')
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        if host not in ('linkedin.com', 'www.linkedin.com'):
            return ''
        path = unquote(parsed.path).strip('/')
        match = re.fullmatch(r'company/([\w-]{2,100})/?', path, re.I)
        if not match or match.group(1).lower() in ('search','jobs','login','signup','people','feed'):
            return ''
        return 'https://www.linkedin.com/company/' + match.group(1).lower() + '/'
    except ValueError:
        return ''


def from_osm(tags: dict | None) -> str:
    if not isinstance(tags, dict):
        return ''
    for field in ('contact:linkedin','linkedin','social:linkedin','contact:linkedin:company'):
        found = company_url(str(tags.get(field,'') or ''))
        if found:
            return found
    return ''


def from_official_site(links: list[str]) -> str:
    for url in links or []:
        clean = company_url(url)
        if clean:
            return clean
    return ''


def tokens(text: str) -> list[str]:
    ascii_text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii','ignore').decode('ascii').lower()
    bits = re.findall(r'[a-z0-9]+', ascii_text)
    return [s for s in bits if len(s)>1 and s not in NOISE]


def evaluate(result: dict, row: dict) -> tuple[float,str]:
    url = company_url(result.get('url',''))
    if not url:
        return 0.0, 'Not a LinkedIn company page'
    name = str(row.get('Business Name') or '')
    wanted = set(tokens(name))
    if not wanted:
        return 0.0, 'No usable company name'
    slug = url.split('/company/',1)[1].strip('/')
    heading = str(result.get('title') or '')
    # Description may mention another company; require name overlap in heading or slug.
    found_name = set(tokens(heading.split('|')[0].split(' - LinkedIn')[0])) | set(tokens(slug))
    overlap = len(wanted & found_name)/len(wanted)
    if overlap < 0.70:
        return 0.0, 'Company name differs'
    # A one-word generic name is never high-confidence without strong context.
    score = 0.35 + 0.42 * overlap
    context = ' '.join([heading, str(result.get('description') or '')]).casefold()
    city = str(row.get('City') or '').casefold()
    country = str(row.get('Country') or '').casefold()
    if city and city in context:
        score += .13
    if country and country in context:
        score += .10
    if len(wanted) == 1:
        score = min(score,.68)
    return min(score,1.0), f'Name overlap {overlap:.0%}; city/country from indexed snippet only'


def _throttle():
    global _last_search_at
    delta = time.monotonic() - _last_search_at
    if _last_search_at and delta < SEARCH_GAP:
        time.sleep(SEARCH_GAP - delta)
    _last_search_at = time.monotonic()


def _bing(query: str) -> list[dict]:
    _throttle()
    response = requests.get(BING_ENDPOINT, params={'q':query, 'format':'rss'},
                            timeout=(7,18), headers={'User-Agent':UA,'Accept':'application/rss+xml,application/xml,text/xml'})
    response.raise_for_status()
    if len(response.content) > 700_000:
        raise RuntimeError('Search response too large')
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise RuntimeError('Bing RSS returned invalid XML; search provider may be blocking automated requests') from exc
    if root.tag != 'rss':
        raise RuntimeError('Bing did not return an RSS search feed (rate-limited or unsupported)')
    results=[]
    for item in root.findall('./channel/item')[:10]:
        results.append({'url':item.findtext('link',''), 'title':item.findtext('title',''),
                        'description':re.sub(r'<[^>]+>',' ',item.findtext('description',''))})
    return results


def _brave(query: str, api_key: str) -> list[dict]:
    _throttle()
    response = requests.get(BRAVE_ENDPOINT, params={'q':query, 'count':10, 'safesearch':'moderate'},
                            headers={'X-Subscription-Token':api_key, 'Accept':'application/json', 'User-Agent':UA},
                            timeout=(7,18))
    response.raise_for_status()
    results = response.json().get('web',{}).get('results',[])
    return [{'url':x.get('url',''), 'title':x.get('title',''),
             'description':x.get('description','')} for x in results[:10]]


def search_company(row: dict, *, api_key: str = '', site_links: list[str] | None = None,
                   osm_tags: dict | None = None) -> dict:
    """Look beyond company websites using an actual web search engine.

    URL found via official website/OSM is corroboration, not a substitute for
    the independent search. Do not guess or fabricate URLs on search failures.
    """
    from datetime import datetime, timezone
    checked = datetime.now(timezone.utc).isoformat(timespec='seconds')
    provider = 'Brave Search API' if api_key else 'Bing RSS search'
    official = from_official_site(site_links or [])
    osm = from_osm(osm_tags)
    name = str(row.get('Business Name') or '').strip()
    city = str(row.get('City') or '').strip()
    country = str(row.get('Country') or '').strip()
    # Quote name and city; include country in natural terms, results only from indexed pages.
    query = f'site:linkedin.com/company/ "{name[:100].replace(chr(34), "").strip()}" "{city[:60]}" {country[:60]}'
    query = ' '.join(query.split())
    fields = {'LinkedIn Company Page':'', 'LinkedIn Match Status':'Not found',
              'LinkedIn Evidence':'No matching company page in returned search results',
              'LinkedIn Search Provider':provider, 'LinkedIn Checked At (UTC)':checked}
    if not name:
        fields['LinkedIn Match Status']='Not searched — missing company name'
        return fields
    try:
        results = _brave(query,api_key) if api_key else _bing(query)
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        fields.update({'LinkedIn Match Status':'Search unavailable',
                       'LinkedIn Evidence':f'Web search failed: {str(exc)[:140]}'})
        # A first-party link can still be kept, labelled as such, not as search-confirmed.
        known=official or osm
        if known:
            fields.update({'LinkedIn Company Page':known,
                           'LinkedIn Match Status':'Official-site link' if official else 'OSM link — review',
                           'LinkedIn Evidence':'Website outbound link' if official else 'OSM contact:linkedin tag',
                           'LinkedIn Search Provider':'Official website' if official else 'OpenStreetMap'})
        return fields
    ranked=[]
    for item in results:
        clean=company_url(item.get('url',''))
        if not clean:
            continue
        confidence, why=evaluate(item,row)
        if confidence:
            if clean == official:
                confidence+=.5
            elif clean == osm:
                confidence+=.15
            ranked.append((confidence,clean,why,item))
    if ranked:
        ranked.sort(key=lambda t:(-t[0],t[1]))
        score,url,why,item=ranked[0]
        # Avoid choosing between near-equal but different companies.
        ambiguous = len(ranked)>1 and ranked[1][1]!=url and (score-ranked[1][0])<.12
        if url == official:
            status='Official website + indexed search match'
        elif ambiguous or score < .81:
            status='Possible company match — review'
        else:
            status='Strong indexed match — review'
        fields.update({'LinkedIn Company Page':url,'LinkedIn Match Status':status,
                       'LinkedIn Evidence':why + ('; multiple close matches' if ambiguous else '') +
                              f'; indexed title: {str(item.get("title", ""))[:110]}'})
    elif official or osm:
        fields.update({'LinkedIn Company Page':official or osm,
                       'LinkedIn Match Status':'Official-site link' if official else 'OSM link — review',
                       'LinkedIn Evidence':'Website outbound company link; no indexed match' if official else 'OpenStreetMap company link; no indexed match'})
    return fields
