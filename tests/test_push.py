from outreach.approval import Queue
from outreach.push import STATE_CAMPAIGN, campaign_payload, lead_payload, push_approved, to_html
from outreach.store import Store
from outreach.validate import validate_draft
from tests.conftest import FakeInstantly, good_draft


def setup(tmp_path, settings, lead, approve=True):
    store = Store(str(tmp_path / "db.sqlite"))
    q = Queue(str(tmp_path / "q.json"))
    q.add(lead, good_draft(), validate_draft(good_draft(), lead, settings))
    if approve:
        q.approve(lead.email, "r", settings)
    return store, q


def test_campaign_payload(settings):
    p = campaign_payload(settings)
    assert p["daily_limit"] == 5 and p["email_list"] == ["sam@outreach.example.com"]
    assert p["text_only"] and p["stop_on_reply"] and p["insert_unsubscribe_header"]
    assert not p["open_tracking"] and not p["link_tracking"]
    steps = p["sequences"][0]["steps"]
    assert steps[0]["variants"][0] == {"subject": "{{subject_1}}", "body": "{{body_1}}"}
    assert steps[0]["delay"] == 3 and steps[0]["delay_unit"] == "days"
    assert steps[1]["variants"][0]["subject"] == ""  # follow-up stays in the same thread
    days = p["campaign_schedule"]["schedules"][0]["days"]
    assert days["0"] is False and days["1"] is True and days["6"] is False


def test_lead_payload_and_html(tmp_path, settings, lead):
    _, q = setup(tmp_path, settings, lead)
    p = lead_payload(q.find(lead.email))
    assert p["company_name"] == "Riverside Bakery"
    assert set(p["custom_variables"]) == {"subject_1", "body_1", "body_2"}
    assert to_html("Hi Jo,\n\nI'm \"here\" <b>\nline") == \
        "<div>Hi Jo,</div><div><br></div><div>I'm \"here\" &lt;b&gt;<br>line</div>"


def test_nothing_pushed_without_approval(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead, approve=False)
    api = FakeInstantly()
    report = push_approved(api, store, q, settings)
    assert report.pushed == [] and api.writes() == []


def test_push_creates_campaign_once_and_adds_lead(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead)
    api = FakeInstantly()
    report = push_approved(api, store, q, settings)
    assert report.created_campaign and report.pushed == [lead.email]
    assert store.get(STATE_CAMPAIGN) == "camp-1" and store.was_pushed(lead.email)
    assert q.find(lead.email)["status"] == "pushed"
    # second run: nothing to do, no new campaign
    report2 = push_approved(api, store, q, settings)
    assert report2.pushed == [] and len(api.campaigns) == 1


def test_suppressed_lead_never_reaches_api(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead)
    store.suppress(lead.email, "bounced", "instantly")
    api = FakeInstantly()
    report = push_approved(api, store, q, settings)
    assert report.skipped == [(lead.email, "on suppression list")] and api.log == []


def test_ledger_blocks_duplicates_even_if_queue_is_reset(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead)
    api = FakeInstantly()
    push_approved(api, store, q, settings)
    q.find(lead.email)["status"] = "approved"  # someone re-approves by hand
    report = push_approved(api, store, q, settings)
    assert report.skipped == [(lead.email, "already pushed")]
    assert sum(1 for c in api.log if c[1] == "leads") == 1


def test_dry_run_makes_no_write_calls(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead)
    api = FakeInstantly()
    report = push_approved(api, store, q, settings, dry_run=True)
    assert report.pushed == [lead.email] and api.log == []
    assert not store.was_pushed(lead.email) and q.find(lead.email)["status"] == "approved"


def test_failed_add_is_reported_and_retryable(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead)
    api = FakeInstantly()
    api.fail_add.add(lead.email)
    report = push_approved(api, store, q, settings)
    assert report.failed and not store.was_pushed(lead.email)
    assert q.find(lead.email)["status"] == "approved"


def test_instantly_skip_without_id_is_recorded(tmp_path, settings, lead):
    store, q = setup(tmp_path, settings, lead)
    api = FakeInstantly()
    api.add_lead = lambda cid, payload: {}
    report = push_approved(api, store, q, settings)
    assert report.skipped and store.was_pushed(lead.email)
