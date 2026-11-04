"""Checks every AI draft before a human sees it.

errors   -> the draft cannot be approved until it is fixed
warnings -> the draft is flagged so the reviewer looks closely, but may approve it
"""
import re
from dataclasses import dataclass, field

DASHES = ("—", "–")  # em dash, en dash
SUBJECT_MAX = 60
BODY1_WORDS = (35, 130)
BODY2_WORDS = (12, 80)
URL_RE = re.compile(r"(https?://\S+|www\.\S+|\b[\w-]+\.(com|co|io|ai|net|org|uk|ae)\b)", re.I)
NUMBER_RE = re.compile(r"\d[\d,.%]*")
PLACEHOLDER_RE = re.compile(r"(\{\{|\}\}|\[[A-Z][A-Za-z ]+\]|<[A-Z_]+>)")
SPAMMY = ("guarantee", "risk-free", "risk free", "act now", "100%", "no obligation", "limited time",
          "click here", "winner", "cash", "urgent")
# Capitalised words that are fine without appearing in the lead row
COMMON_CAPS = {
    "i", "i'm", "i've", "i'd", "i'll", "hi", "hello", "hey", "thanks", "thank", "best", "cheers",
    "regards", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "ai", "email", "ps", "p.s.", "ok", "re", "if", "would",
    "worth", "happy", "quick", "just", "no", "yes", "a", "the", "and", "or", "so", "but",
    "unsubscribe",
}


@dataclass
class Check:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    @property
    def clean(self):
        return not self.errors and not self.warnings


def _words(text):
    return len(re.findall(r"[A-Za-z0-9'’]+", text))


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def validate_draft(draft, lead, settings):
    """draft: dict with subject_1, body_1, body_2, facts_used, unsure, unsure_reason."""
    c = Check()
    for key in ("subject_1", "body_1", "body_2"):
        if not isinstance(draft.get(key), str) or not draft[key].strip():
            c.errors.append(f"{key} missing or empty")
    if c.errors:
        return c

    subject, b1, b2 = draft["subject_1"].strip(), draft["body_1"].strip(), draft["body_2"].strip()
    allowed = _norm(" ".join(lead.facts().values()) + " " + settings.sender_text())
    unsub = settings.unsubscribe_line.strip()

    if len(subject) > SUBJECT_MAX:
        c.errors.append(f"subject is {len(subject)} chars (max {SUBJECT_MAX})")
    if "\n" in subject:
        c.errors.append("subject has a line break")

    for name, text in (("subject_1", subject), ("body_1", b1), ("body_2", b2)):
        if any(d in text for d in DASHES):
            c.errors.append(f"{name} contains an em or en dash")
        if PLACEHOLDER_RE.search(text):
            c.errors.append(f"{name} contains an unfilled placeholder")
        for m in URL_RE.finditer(text):
            if _norm(m.group(0)).rstrip(".,") not in allowed:
                c.errors.append(f"{name} has a link not in the lead row: {m.group(0)}")
        for m in NUMBER_RE.finditer(text):
            token = m.group(0).rstrip(".,")
            if token and not re.search(r"(?<![\d.])" + re.escape(token) + r"(?![\d])", allowed):
                c.errors.append(f"{name} has a number not in the lead row: {token}")
        low = text.lower()
        for phrase in SPAMMY:
            if phrase in low:
                c.warnings.append(f"{name} uses spam-trigger wording: '{phrase}'")

    for name, text, (lo, hi) in (("body_1", b1, BODY1_WORDS), ("body_2", b2, BODY2_WORDS)):
        if not text.endswith(unsub):
            c.errors.append(f"{name} must end with the unsubscribe line")
        n = _words(text.replace(unsub, ""))
        if not lo <= n <= hi:
            c.errors.append(f"{name} is {n} words (allowed {lo}-{hi})")

    if _norm(lead.first_name) not in _norm(b1):
        c.warnings.append("body_1 does not use the lead's first name")

    facts = draft.get("facts_used") or []
    if not isinstance(facts, list):
        c.errors.append("facts_used must be a list")
        facts = []
    row = lead.as_dict()
    for fact in facts:
        fld = (fact or {}).get("field", "")
        val = _norm((fact or {}).get("value", ""))
        if fld not in row or fld in ("email", "consent_basis"):
            c.errors.append(f"facts_used names an unknown field: {fld!r}")
        elif not val or val not in _norm(row[fld]):
            c.errors.append(f"facts_used value is not in the lead's {fld}: {fact.get('value')!r}")

    # Proper nouns the lead row does not support: flag for a human, do not guess.
    body_wo_unsub = (b1 + "\n" + b2).replace(unsub, "")
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body_wo_unsub):
        tokens = re.findall(r"[A-Za-z][A-Za-z'’&-]*", sentence)
        for tok in tokens[1:]:
            if tok[0].isupper() and tok.lower() not in COMMON_CAPS and tok.lower() not in allowed:
                c.warnings.append(f"name or term not in the lead row: '{tok}'")

    if draft.get("unsure"):
        c.warnings.append(f"model was unsure: {draft.get('unsure_reason') or 'no reason given'}")

    c.warnings = list(dict.fromkeys(c.warnings))
    c.errors = list(dict.fromkeys(c.errors))
    return c
