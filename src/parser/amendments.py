"""Operative-clause actions and deterministic style-aware lexical tokens."""
import re

from .cache import digest

ORS = r"\d{1,3}[A-Z]?\.\d{3,4}(?!\d)"
CLAUSE = re.compile(r"(?m)^\s*SECTION\s+(\d+[a-zA-Z]?)\s*\.\s*")
LEXEME = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)


def token_stream(doc):
    tokens, depth = [], 0
    for m in LEXEME.finditer(doc.text):
        word = m[0]
        if word == "[":
            depth += 1
            operation = "MARKER"
        elif word == "]":
            if not depth:
                raise ValueError("unmatched legislative deletion bracket")
            depth -= 1
            operation = "MARKER"
        elif depth:
            operation = "DELETE"
        else:
            # A word may contain both unchanged and added characters. Splitting
            # at style transitions preserves the old spelling as well as new.
            start = m.start()
            operation = 'ADD' if any(doc.styles[start]) else 'KEEP'
            for pos in range(start + 1, m.end()):
                next_operation = 'ADD' if any(doc.styles[pos]) else 'KEEP'
                if next_operation != operation:
                    tokens.append(dict(ordinal=len(tokens), operation=operation,
                                       text=doc.text[start:pos], start=start, end=pos))
                    start, operation = pos, next_operation
            tokens.append(dict(ordinal=len(tokens), operation=operation,
                               text=doc.text[start:m.end()], start=start, end=m.end()))
            continue
        tokens.append({"ordinal": len(tokens), "operation": operation, "text": word,
                       "start": m.start(), "end": m.end()})
    if depth:
        raise ValueError("unterminated legislative deletion bracket")
    return tokens


def parse_session(doc, source_url, expected_year=None, special_session=None):
    text = doc.text
    bill = re.search(r"\b(HB|SB)\s+(\d+)\b|\bBallot\s+Measure\s+(?:No\.\s*)?(\d+)\b", text, re.I)
    # The title/body can cite earlier Oregon Laws at a wrapped line start.
    # Only the publication masthead, before the bill citation, states identity.
    masthead = text[:bill.start()] if bill else text
    headers = list(re.finditer(r"(?mi)^[ \t]*(?:(?:Chapter|Chap\.)\s+\d+\s+)?OREGON\s+LAWS\s+((?:18|19|20|21)\d{2})([^\n]*)", masthead))
    years = {int(m[1]) for m in headers}
    if len(years) != 1:
        raise ValueError(f"ambiguous/missing session-law header: {source_url}")
    year = years.pop()
    if expected_year is not None and year != expected_year:
        raise ValueError(f"session year mismatch: {year} != {expected_year}")
    from .identity import ORDINALS
    printed_sessions = set()
    for header in headers:
        match = re.search(r'(?:(first|second|third|fourth|fifth|\d+)(?:st|nd|rd|th)?\s+)?(special|regular)\s+session', header[2], re.I)
        if match:
            if match[2].lower() == 'regular':
                printed_sessions.add(0)
            elif match[1]:
                value = match[1].lower()
                printed_sessions.add(ORDINALS.get(value) or int(value))
            elif special_session is None:
                raise ValueError('special session header has no ordinal; supply special_session in manifest')
            elif special_session == 0:
                raise ValueError('special session source conflicts with regular session manifest')
    if len(printed_sessions) > 1 or (printed_sessions and special_session is not None and special_session not in printed_sessions):
        raise ValueError('conflicting special-session identity')
    special_session = next(iter(printed_sessions)) if printed_sessions else (special_session or 0)
    chapter = re.search(r"\b(?:CHAPTER|Chap\.)\s+(\d+)\b", text, re.I)
    if chapter is None or bill is None:
        raise ValueError(f"missing session chapter or bill identity: {source_url}")
    bill_number = f"{bill[1].upper()} {bill[2]}" if bill[1] else f"Ballot Measure {bill[3]}"
    clauses = list(CLAUSE.finditer(text))
    if not clauses:
        raise ValueError(f"no operative SECTION clauses: {source_url}")
    if len({c[1] for c in clauses}) != len(clauses):
        raise ValueError(f'duplicate operative SECTION identity: {source_url}')
    clause_bodies = {clause[1]: doc.slice(clause.end(), clauses[i+1].start() if i+1 < len(clauses) else len(text))
                     for i, clause in enumerate(clauses)}
    for number, body in list(clause_bodies.items()):
        end_note = re.search(r'(?m)^\s*(?:NOTE:|Approved by the Governor\b|Filed in the office of Secretary\b|Effective date\b)', body.text)
        if end_note:
            clause_bodies[number] = body.slice(0, end_note.start())
    actions, diagnostics = [], []
    for i, clause in enumerate(clauses):
        end = clauses[i+1].start() if i+1 < len(clauses) else len(text)
        content = doc.slice(clause.end(), end)
        # Explanatory reviser's notes and approval footers are not enacted text.
        note = re.search(r'(?m)^\s*(?:NOTE:|Approved by the Governor\b|Filed in the office of Secretary\b|Effective date\b)', content.text)
        if note:
            content = content.slice(0, note.start())
        prefix = re.sub(r"\s+", " ", content.text).strip()
        action, targets, body_start = None, [], 0
        amend = re.match(rf"ORS\s+({ORS})(?:,.*?)?\s+is\s+amended\s+to\s+read\s*:", prefix)
        repeal = re.match(r"(?:Repeals\.\s*)?ORS\s+(.+?)\s+(?:is|are)\s+repealed\b", prefix)
        if amend:
            action, targets = "AMEND", [amend[1]]
            marker = re.search(r"amended\s+to\s+read\s*:", content.text)
            body_start = marker.end()
        elif repeal:
            target_text = repeal[1]
            # Do not expand ranges by inventing non-existent ORS section numbers.
            if re.search(r"\bto\b", target_text):
                diagnostics.append({"clause": clause[1], "reason": "repeal range requires an edition roster", "text": prefix})
                continue
            # Accept a list of ORS identifiers only; subordinate act citations
            # and their incidental ORS references need separate review.
            remainder = re.sub(ORS, '', target_text)
            if re.sub(r'\b(?:and|ORS)\b|[,\s]', '', remainder):
                diagnostics.append({'clause': clause[1], 'reason': 'mixed repeal targets require review', 'text': prefix})
                continue
            action, targets = "REPEAL", re.findall(ORS, target_text)
        elif re.search(r"\b(?:is|are)\s+added\s+to\s+and\s+made\s+a\s+part\s+of\b", prefix):
            # The provision's future ORS number is often assigned editorially.
            # The receiving series is not the new section's identifier.
            action, targets = "ADD", [None]
        elif re.match(rf"ORS\s+({ORS})\s+is\s+(?:created|added|enacted)\b", prefix):
            action, targets = "ADD", [re.match(rf"ORS\s+({ORS})", prefix)[1]]
        elif re.search(r"\b(?:amended to read|repealed)\b", prefix[:1000]):
            diagnostics.append({"clause": clause[1], "reason": "non-ORS or unsupported operative target", "text": prefix})
        if action:
            diff = content.slice(body_start)
            if action == "ADD" and targets == [None]:
                subject = re.split(r'\s+(?:is|are)\s+added\s+to\s+and\s+made\s+a\s+part\s+of\b', prefix, maxsplit=1)[0]
                membership = re.search(r'(?:^|\band\s+)Sections?\s+(\d+[A-Za-z]?(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+|\s+to\s+)\d+[A-Za-z]?)*)'
                    r'(?:\s+of\s+this\s+\d{4}\s+Act)?(?=\s+and\s+ORS\b|\s*$)', subject, re.I)
                if re.search(r'\bORS\b', subject):
                    diagnostics.append(dict(clause=clause[1], reason='existing ORS series membership', text=prefix))
                if membership:
                    numbers = []
                    for part in re.split(r",\s*|\s+and\s+", membership[1]):
                        part = part.strip()
                        span = re.fullmatch(r"(\d+)\s+to\s+(\d+)", part)
                        if span:
                            numbers.extend(str(n) for n in range(int(span[1]), int(span[2]) + 1))
                        elif re.fullmatch(r"\d+[a-zA-Z]?", part):
                            numbers.append(part)
                        else:
                            raise ValueError(f"unsupported ADD section list: {membership[1]}")
                    for added_number in dict.fromkeys(numbers):
                        if added_number not in clause_bodies:
                            raise ValueError(f"ADD refers to missing act section {added_number}")
                        added_body = clause_bodies[added_number]
                        # A series-membership clause can include provisions that
                        # amend existing ORS; those already have direct actions.
                        if re.match(r"\s*ORS\s+.+?\b(?:is\s+amended\s+to\s+read|(?:is|are)\s+repealed)\b", added_body.text, re.S):
                            continue
                        added_tokens = token_stream(added_body)
                        for token in added_tokens:
                            token["operation"] = "ADD"
                        identity = f"{year}:{special_session}:{chapter[1]}:{added_number}:ADD:uncodified"
                        actions.append({"id": digest(identity.encode()), "bill_number": bill_number,
                            "session_year": year, "affected_ors_section": None, "action_type": "ADD",
                            "raw_diff_text": added_body.text, "tokens": added_tokens,
                            "session_law_chapter": int(chapter[1]), "session_law_section": added_number,
                            "special_session": special_session, "source_url": source_url,
                            "token_text": added_body.text})
                    continue
                if not re.search(r'\bORS\b', subject):
                    diagnostics.append(dict(clause=clause[1], reason='unsupported ADD reference', text=prefix))
                # Membership changes to existing sections are not newly enacted
                # text; retain the clause as evidence, not a fictitious ADD row.
                continue
            tokens = token_stream(diff) if action in ("AMEND", "ADD") else []
            if action == 'AMEND':
                label = re.match(r'\s*'+re.escape(targets[0])+r'\.\s*', diff.text)
                if label:
                    for token in tokens:
                        if token['end'] <= label.end():
                            token['operation'] = 'KEEP'
            if action == "ADD":
                for token in tokens:
                    token["operation"] = "ADD"
            for target in targets:
                identity = f"{year}:{special_session}:{chapter[1]}:{clause[1]}:{action}:{target or 'uncodified'}"
                actions.append({"id": digest(identity.encode()), "bill_number": bill_number,
                                "session_year": year, "affected_ors_section": target,
                                "action_type": action, "raw_diff_text": diff.text,
                                "tokens": tokens, "session_law_chapter": int(chapter[1]),
                                "session_law_section": clause[1], "special_session": special_session,
                                "source_url": source_url,
                                "token_text": diff.text})
    return {"actions": actions, "diagnostics": diagnostics, "session_year": year,
            "bill_number": bill_number, "session_law_chapter": int(chapter[1])}
