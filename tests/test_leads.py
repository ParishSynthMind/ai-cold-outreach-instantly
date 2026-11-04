import pytest

from outreach.leads import load_leads


def write(tmp_path, text):
    p = tmp_path / "leads.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_sample_file_loads_and_rejects_bad_rows():
    res = load_leads("samples/leads.example.csv")
    assert [lead.first_name for lead in res.leads] == ["Jo", "Priya", "Alex"]
    reasons = {r[2] for r in res.rejected}
    assert reasons == {"invalid email", "no consent_basis"}


def test_missing_required_column(tmp_path):
    with pytest.raises(ValueError, match="consent_basis"):
        load_leads(write(tmp_path, "email,first_name,company\na@b.co,A,B\n"))


def test_emails_normalised_and_duplicates_dropped(tmp_path):
    res = load_leads(write(tmp_path, "Email,First_Name,Company,Consent_Basis\n"
                                     " Jo@Example.COM ,Jo,Co,opted in\njo@example.com,Jo,Co,opted in\n"))
    assert [lead.email for lead in res.leads] == ["jo@example.com"]
    assert res.rejected == [(3, "jo@example.com", "duplicate in file")]


def test_missing_name_or_company(tmp_path):
    res = load_leads(write(tmp_path, "email,first_name,company,consent_basis\na@b.co,,Co,ok\n"))
    assert res.rejected[0][2] == "missing first_name or company"


def test_facts_exclude_email_and_consent():
    lead = load_leads("samples/leads.example.csv").leads[0]
    facts = lead.facts()
    assert "email" not in facts and "consent_basis" not in facts
    assert facts["company"] == "Riverside Bakery"
