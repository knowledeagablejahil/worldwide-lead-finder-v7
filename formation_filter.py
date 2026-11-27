"""Evidence-based screening for company setup / incorporation partners.

OSM's generic office=consulting tag is NOT evidence of incorporation services.
Website text is checked for specific service phrases; an OSM name/description
match is a lead for manual verification, not a confirmed provider.
"""
from __future__ import annotations
import re
import unicodedata

CATEGORY = 'Company Formation & Corporate Services'
LEGACY_CATEGORY = 'Business Consultants'

# These are deliberately specific, not generic 'consultancy', 'business
# services', 'corporate advisory' or 'company' keywords. Extend by country
# after reviewing real misses; avoiding false positives is the priority.
_SERVICE_PHRASES = (
    r'company\s+(?:formation|incorporation|registration\s+services|set[ -]?up|establishment\s+services)',
    r'business\s+(?:setup|set[ -]?up|incorporation|formation|registration\s+services)',
    r'(?:incorporat(?:e|ing)|register|form|establish|set[ -]?up)\s+(?:a\s+|your\s+|new\s+)?(?:company|business|corporation|llc|limited company)',
    r'(?:corporate|company)\s+(?:formation|incorporation)\s+(?:services|agents|specialists)',
    r'company\s+secretarial\s+services',
    r'registered\s+agent\s+services',
    r'creation\s+(?:d\s*[’\']\s*)?entreprises?',
    r'creation\s+de\s+societes?',
    r'constitution\s+(?:de\s+|des\s+|d\s*[’\']\s*)?(?:societes?|entreprises?)',
    r'(?:creer|immatriculer)\s+(?:une?\s+)?(?:societe|entreprise)',
    r'(?:firmen|unternehmens|gesellschafts)grundung',
    r'(?:gmbh|firma|unternehmen)\s+grunden',
    r'(?:constitucion|creacion)\s+de\s+(?:empresas|sociedades)',
    r'(?:crear|constituir|registrar)\s+(?:una?\s+)?(?:empresa|sociedad)',
    r'(?:costituzione|apertura)\s+(?:di\s+)?(?:societa|aziende?)',
    r'(?:bedrijfsoprichting|onderneming\s+oprichten|bedrijf\s+oprichten|bv\s+oprichten)',
    r'(?:constit[uí]icao|abertura)\s+de\s+(?:empresas?|sociedades?)',
    r'(?:zakladanie|rejestracja)\s+(?:spolek|spolki|firmy)',
    r'(?:bolagsbildning|firmastiftelse|firmaetablering)',
    r'(?:sirket\s+kurulusu|sirket\s+kurma)',
    r'(?:تاسيس|تسجيل)\s+الشركات',
    r'(?:公司注册|注册公司|会社設立|会社登記)',
)
_PATTERNS = [re.compile(p, re.I | re.UNICODE) for p in _SERVICE_PHRASES]
_BAD_NAME = re.compile(
    r'\b(?:it|software|digital|marketing|seo|recruitment|human resources|hr|'
    r'engineering|architecture|construction|environmental|medical|healthcare|'
    r'travel|education|education abroad|visa only|management|strategy|business coaching)\b'
    r'.{0,26}\b(?:consult(?:ancy|ing|ant[s]?)|advis(?:or|ory|er))\b', re.I)
# Avoid using a company's mandatory registration-number footer as proof.
_FOOTER = re.compile(r'company\s+registration\s+(?:number|no\.?|id|#)', re.I)
_NEGATED = re.compile(r'\b(?:do not|don\x27t|does not|not|never|no longer|without)\s+(?:provide|offer|handle|do|include)\b', re.I)


def _normalized(text: str) -> str:
    text = str(text or '').casefold().replace('\u00a0', ' ').replace('’', "'")
    text = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


def _specific_match(text: str) -> str:
    normalized = _normalized(text)
    normalized = _FOOTER.sub('', normalized)
    for pattern in _PATTERNS:
        for match in pattern.finditer(normalized):
            lead = normalized[max(0, match.start()-65):match.start()]
            if _NEGATED.search(lead[-48:]):
                continue
            return match.group(0)
    return ''


def map_evidence(name: str, tags: dict | None = None) -> str:
    """Look at a name and OSM service tags, never treat office=consulting as proof."""
    tags = tags or {}
    texts = [name]
    for field in ('description', 'description:en', 'service', 'services',
                  'consulting', 'business', 'company', 'office:description'):
        if tags.get(field):
            texts.append(str(tags[field]))
    return _specific_match(' | '.join(texts))


def clearly_other_consultancy(name: str, tags: dict | None = None) -> bool:
    """Exclude obvious verticals unless a specific formation service is present."""
    if map_evidence(name, tags):
        return False
    joined = ' '.join(str(x) for x in (name, (tags or {}).get('description','')))
    return bool(_BAD_NAME.search(joined))


def website_evidence(page_text: str) -> str:
    return _specific_match(page_text)
