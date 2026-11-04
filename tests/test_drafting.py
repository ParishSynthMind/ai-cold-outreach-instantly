from types import SimpleNamespace

from outreach.drafting import Drafter, build_prompt, parse_json
from tests.conftest import FakeClaude, good_draft


def test_prompt_has_lead_facts_but_not_email_or_consent(settings, lead):
    p = build_prompt(lead, settings)
    assert "Leeds food fair" in p and "Carter Automation" in p
    assert lead.email not in p and "consent" not in p


def test_parse_json_variants():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": "x\ny"}') == {"a": "x\ny"}  # raw newline tolerated


def test_good_draft_first_time(settings, lead):
    fake = FakeClaude([good_draft()])
    draft, check = Drafter(fake, settings).draft(lead)
    assert check.clean and draft["subject_1"].startswith("Wholesale")
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert "unsubscribe" in call["system"]


def test_invalid_json_then_fixed(settings, lead):
    fake = FakeClaude(["not json at all", good_draft()])
    draft, check = Drafter(fake, settings).draft(lead)
    assert check.clean and len(fake.calls) == 2
    assert "not valid JSON" in fake.calls[1]["messages"][0]["content"]


def test_failed_checks_are_sent_back_on_retry(settings, lead):
    bad = good_draft(subject_1="Orders — idea")
    fake = FakeClaude([bad, good_draft()])
    draft, check = Drafter(fake, settings).draft(lead)
    assert check.clean
    assert "em or en dash" in fake.calls[1]["messages"][0]["content"]


def test_still_bad_after_retry_is_flagged_not_dropped(settings, lead):
    bad = good_draft(subject_1="Orders — idea")
    draft, check = Drafter(FakeClaude([bad, bad]), settings).draft(lead)
    assert draft is not None and not check.ok


def test_two_unparseable_replies_give_error(settings, lead):
    draft, check = Drafter(FakeClaude(["nope", "still nope"]), settings).draft(lead)
    assert draft is None and "not valid JSON" in check.errors[0]


def test_cut_off_reply_is_retried(settings, lead):
    cut = SimpleNamespace(stop_reason="max_tokens", content=[SimpleNamespace(type="text", text='{"subject_1": "')])
    draft, check = Drafter(FakeClaude([cut, good_draft()]), settings).draft(lead)
    assert check.clean
