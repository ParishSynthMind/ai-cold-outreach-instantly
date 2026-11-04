from outreach.validate import validate_draft
from tests.conftest import UNSUB, good_draft


def test_clean_draft_passes(settings, lead):
    c = validate_draft(good_draft(), lead, settings)
    assert c.ok and c.clean, (c.errors, c.warnings)


def test_missing_fields(settings, lead):
    c = validate_draft({"subject_1": "x"}, lead, settings)
    assert "body_1 missing or empty" in c.errors


def test_em_dash_and_en_dash_rejected(settings, lead):
    d = good_draft(subject_1="Orders — quick idea")
    d["body_2"] = d["body_2"].replace("Happy", "Happy – really")
    errs = validate_draft(d, lead, settings).errors
    assert "subject_1 contains an em or en dash" in errs
    assert "body_2 contains an em or en dash" in errs


def test_unsubscribe_line_required(settings, lead):
    d = good_draft(body_2="Hi Jo,\n\nJust a nudge on my note about wholesale orders, happy to keep it short.\n\nSam")
    assert "body_2 must end with the unsubscribe line" in validate_draft(d, lead, settings).errors


def test_long_subject(settings, lead):
    assert any("subject is" in e for e in validate_draft(good_draft(subject_1="x" * 61), lead, settings).errors)


def test_invented_number_rejected_but_known_number_ok(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("so nobody", "saving 12 hours a week, so nobody")
    errs = validate_draft(d, lead, settings).errors
    assert "body_1 has a number not in the lead row: 12" in errs
    # 15 comes from the call to action, so it is allowed; "1" is not matched inside "15"
    assert not any(": 15" in e for e in errs)


def test_single_digit_not_matched_inside_bigger_number(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("so nobody", "in 1 week, so nobody")
    assert "body_1 has a number not in the lead row: 1" in validate_draft(d, lead, settings).errors


def test_invented_link_rejected(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("so nobody", "see https://example.org/demo, so nobody")
    assert any("link not in the lead row" in e for e in validate_draft(d, lead, settings).errors)


def test_placeholder_rejected(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("Hi Jo", "Hi {{first_name}}")
    assert "body_1 contains an unfilled placeholder" in validate_draft(d, lead, settings).errors


def test_word_limits(settings, lead):
    d = good_draft(body_2="Hi Jo, nudge.\n\n" + UNSUB)
    assert any(e.startswith("body_2 is") for e in validate_draft(d, lead, settings).errors)
    d = good_draft(body_1="Hi Jo, " + "word " * 140 + "\n\n" + UNSUB)
    assert any(e.startswith("body_1 is") for e in validate_draft(d, lead, settings).errors)


def test_facts_used_must_match_lead_row(settings, lead):
    d = good_draft(facts_used=[{"field": "notes", "value": "Manchester trade show"}])
    assert any("not in the lead's notes" in e for e in validate_draft(d, lead, settings).errors)
    d = good_draft(facts_used=[{"field": "revenue", "value": "big"}])
    assert any("unknown field" in e for e in validate_draft(d, lead, settings).errors)
    d = good_draft(facts_used=[{"field": "consent_basis", "value": "food fair"}])
    assert any("unknown field" in e for e in validate_draft(d, lead, settings).errors)


def test_unknown_proper_noun_is_flagged_not_rejected(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("so nobody", "like we did for Greggs, so nobody")
    c = validate_draft(d, lead, settings)
    assert c.ok and not c.clean
    assert "name or term not in the lead row: 'Greggs'" in c.warnings


def test_unsure_model_is_flagged(settings, lead):
    c = validate_draft(good_draft(unsure=True, unsure_reason="thin notes"), lead, settings)
    assert c.ok and "model was unsure: thin notes" in c.warnings


def test_spammy_wording_flagged(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("so nobody", "guaranteed results, so nobody")
    assert any("spam-trigger" in w for w in validate_draft(d, lead, settings).warnings)


def test_first_name_missing_flagged(settings, lead):
    d = good_draft()
    d["body_1"] = d["body_1"].replace("Hi Jo,", "Hello,")
    assert "body_1 does not use the lead's first name" in validate_draft(d, lead, settings).warnings
