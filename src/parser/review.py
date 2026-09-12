"""Conservative, reproducible triage. Classification never discards evidence."""
import re


def classify(row):
    text = re.sub(r'\s+', ' ', row['text']).strip()
    if row['reason'] == 'existing ORS series membership':
        return dict(category='series_membership', disposition='expected_scope',
                    explanation='Moves existing provisions into a series; does not itself create new statutory text.')
    if (re.match(r'Notwithstanding the transfer of duties, functions and powers\b', text)
            and re.search(r'continue in effect until superseded or repealed by rules\b', text)
            or re.match(r'If any provision of sections?\b', text)
            and 'does not affect the validity of any action' in text
            or re.match(r'\(1\) On or before\b', text)
            and 'shall report to the Governor' in text
            and re.search(r'if sections? .+ are not repealed on\b', text)):
        return dict(category='incidental_repeal_reference', disposition='expected_scope',
                    explanation='Continuity, severability, or reporting language mentions repeal without directing an ORS repeal.')
    # Only inspect the operative instruction before replacement text begins.
    instruction = text.split('amended to read:', 1)[0]
    instruction = re.sub(r'^If (?:House|Senate) Bill \d+ becomes law,\s*', '', instruction)
    instruction = re.sub(r'^(?:Repeals\.\s*)?\(\d+\)\s*', '', instruction)
    if re.match(r'Sections?\s+\d', instruction, re.I) and not re.search(r'\band ORS\s+\d', instruction):
        return dict(category='session_law_provision', disposition='expected_scope',
                    explanation='Targets an Act section, not a directly identified ORS section. Further temporal linking is needed.')
    if re.match(r'.+?\. Section \d[^.]*, chapter \d+, Oregon Laws \d{4}', instruction):
        return dict(category='session_law_provision', disposition='expected_scope',
                    explanation='Captioned instruction targets a session-law provision; incidental ORS citations are not direct targets.')
    return dict(category='unresolved', disposition='review_required',
                explanation='The supported instruction patterns do not establish a safe direct-ORS action. Inspect the original source.')
