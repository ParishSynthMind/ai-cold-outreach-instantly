"""Load and check the lead CSV.

Required columns: email, first_name, company, consent_basis.
Optional: last_name, role, website, notes.

consent_basis is required on purpose: every row has to say why this person
can be emailed (opted in, existing customer, asked to be contacted, ...).
Rows without it are rejected, not drafted.
"""
import csv
import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
REQUIRED = ("email", "first_name", "company", "consent_basis")
OPTIONAL = ("last_name", "role", "website", "notes")
FIELDS = REQUIRED + OPTIONAL


@dataclass
class Lead:
    email: str
    first_name: str
    company: str
    consent_basis: str
    last_name: str = ""
    role: str = ""
    website: str = ""
    notes: str = ""

    def as_dict(self):
        return {f: getattr(self, f) for f in FIELDS}

    def facts(self):
        """The fields the model may use, without the address or consent note."""
        return {k: v for k, v in self.as_dict().items() if v and k not in ("email", "consent_basis")}


@dataclass
class LoadResult:
    leads: list = field(default_factory=list)
    rejected: list = field(default_factory=list)  # (row number, email, reason)


def normalise_email(value):
    return (value or "").strip().lower()


def load_leads(path):
    result = LoadResult()
    seen = set()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        for n, row in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            email = normalise_email(row.get("email"))
            reason = None
            if not EMAIL_RE.match(email):
                reason = "invalid email"
            elif email in seen:
                reason = "duplicate in file"
            elif not row.get("consent_basis"):
                reason = "no consent_basis"
            elif not row.get("first_name") or not row.get("company"):
                reason = "missing first_name or company"
            if reason:
                result.rejected.append((n, email, reason))
                continue
            seen.add(email)
            data = {f: row.get(f, "") for f in FIELDS}
            data["email"] = email
            result.leads.append(Lead(**data))
    return result
