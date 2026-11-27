"""Conservative lead categorization. Presence is distinct from verification.

Classifications are inferred from collected public information, NOT from a
commercial firm-size or phone-line verification service.
"""
from __future__ import annotations
import re

NEW_COLUMNS = [
    'Contact Category', 'Contact Verification', 'Partnership Fit',
    'Fit Evidence', 'Next Action', 'Workflow Queue'
]

CODES = {
    (True, True, True): ('A1', 'Complete'),
    (True, True, False): ('A2', 'Email + Website'),
    (True, False, True): ('A3', 'Phone + Website'),
    (False, True, True): ('B1', 'Email + Phone'),
    (False, True, False): ('B2', 'Email Only'),
    (False, False, True): ('B3', 'Phone Only'),
    (True, False, False): ('C1', 'Website Only'),
    (False, False, False): ('D', 'No Contact'),
}


def classify(row: dict) -> dict:
    """Return a copy with actionable labels. Safe to re-run on saved V2/V3 rows."""
    result = dict(row)
    website = bool(str(row.get('Website') or '').strip())
    email = bool(str(row.get('Business Email') or '').strip())
    phone = bool(str(row.get('Phone') or '').strip())
    code, label = CODES[(website, email, phone)]
    result['Contact Category'] = f'{code} – {label}'

    em_status = str(row.get('Email Check') or '')
    ph_status = str(row.get('Phone Format Check') or '')
    src = str(row.get('Email Source') or '')
    match = str(row.get('Phone Website Match') or '')
    em_syntax = bool(email and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', str(row.get('Business Email') or '')))
    email_invalid = email and (not em_syntax or em_status.startswith(('Invalid', 'No MX found')))
    phone_invalid = phone and (ph_status.startswith(('Invalid', 'Could not parse')))
    email_official = email and ('public page' in src.lower() or 'official website' in src.lower())
    phone_official = phone and (match.startswith('Yes, same number') or match.startswith('Found on listed website'))
    number_format = phone and ph_status.startswith('Valid numbering format')
    email_format = email and (em_status.startswith('Valid syntax + MX') or em_syntax)

    if not email and not phone:
        verification = 'Missing'
    elif email_invalid and (not phone or phone_invalid):
        verification = 'Invalid / needs correction'
    elif phone_invalid and not email:
        verification = 'Invalid / needs correction'
    elif email_official or phone_official:
        verification = 'Official website source match (not active verified)'
    elif (email_format and not email_invalid) or (number_format and not phone_invalid):
        verification = 'Format check only (not active verified)'
    else:
        verification = 'Unverified'
    result['Contact Verification'] = verification

    from engine import is_large_chain
    name = str(row.get('Business Name') or '')
    smaller = 'smaller-firm wording' in str(row.get('Firm Size') or '').casefold()
    category = str(row.get('Category') or '')
    if is_large_chain(name):
        fit, evidence = 'Low', 'Recognized international chain; firm size not independently verified'
    elif smaller and category:
        fit, evidence = 'High', 'Website uses smaller-firm language; ownership and size still unverified'
    elif category and (website or email or phone):
        fit, evidence = 'Medium', 'Relevant sector with contact/listing evidence; small independent status not confirmed'
    else:
        fit, evidence = 'Unknown', 'Insufficient public evidence to assess size or referral potential'
    result['Partnership Fit'] = fit
    result['Fit Evidence'] = evidence

    email_usable = email and not email_invalid
    phone_usable = phone and not phone_invalid
    if fit == 'Low':
        queue, next_action = 'Hold', 'Review chain / suitability'
    elif email_usable or phone_usable:
        queue = 'Ready for Outreach'
        next_action = 'Email + call' if email_usable and phone_usable else ('Email' if email_usable else 'Call')
    elif website:
        queue, next_action = 'Needs Contact Research', 'Research official website contact page'
    elif email or phone:
        queue, next_action = 'Needs Contact Research', 'Correct or verify contact details'
    else:
        queue, next_action = 'Hold', 'No contact found; review OSM listing manually'
    result['Workflow Queue'] = queue
    result['Next Action'] = next_action

    # V6 company-formation gate: contact completeness does not establish that a
    # generic consultant helps incorporate other businesses. Existing V2–V5
    # generic consultant rows stay saved but are held until verified.
    from formation_filter import CATEGORY as formation_category, LEGACY_CATEGORY
    if category in (formation_category, LEGACY_CATEGORY):
        qualification = str(row.get('Service Qualification') or '')
        evidence = str(row.get('Service Evidence') or '').strip()
        if category == LEGACY_CATEGORY:
            result['Service Qualification'] = 'Legacy — not assessed'
            result['Partnership Fit'] = 'Unknown'
            result['Fit Evidence'] = 'Legacy general consultancy listing; company formation services not established'
            result['Workflow Queue'] = 'Needs Service Verification' if website else 'Hold'
            result['Next Action'] = 'Check whether firm provides company incorporation / registration'
            result['Partnership Priority'] = 'Pending service verification'
        elif qualification == 'Website evidence':
            result['Service Qualification'] = qualification
            result['Partnership Fit'] = 'High' if smaller else 'Medium'
            result['Fit Evidence'] = 'Website mentions company formation / incorporation services: ' + evidence
            # Ready for Outreach is still contingent on usable contact details.
            result['Workflow Queue'] = queue
            result['Next Action'] = next_action
        elif qualification.startswith('OSM evidence'):
            result['Service Qualification'] = qualification
            result['Partnership Fit'] = 'Unknown'
            result['Fit Evidence'] = 'Possible company-formation provider based on OSM listing only: ' + evidence
            result['Workflow Queue'] = 'Needs Service Verification'
            result['Next Action'] = 'Verify incorporation services on official website before outreach'
            result['Partnership Priority'] = 'Pending service verification'
        else:
            result['Service Qualification'] = 'Not verified'
            result['Partnership Fit'] = 'Unknown'
            result['Fit Evidence'] = 'No specific evidence of company-formation / incorporation services'
            result['Workflow Queue'] = 'Needs Service Verification' if website else 'Hold'
            result['Next Action'] = 'Verify company incorporation services'
            result['Partnership Priority'] = 'Pending service verification'
    else:
        result['Service Qualification'] = ''
    return result
