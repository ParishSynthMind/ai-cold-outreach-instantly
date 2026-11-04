from outreach.replies import classify, html_to_text, poll_replies, strip_quoted, sync_lead_statuses, write_report
from outreach.store import Store
from tests.conftest import FakeClaude, FakeInstantly


def received(eid, sender, text=None, html=None):
    body = {}
    if text:
        body["text"] = text
    if html:
        body["html"] = html
    return {"id": eid, "from_address_email": sender, "subject": "Re: hi", "timestamp_email": "2026-11-04T06:00:00Z",
            "body": body}


def test_strip_quoted_and_html():
    t = "Not right now, maybe in March.\n\nOn Tue, 3 Nov 2026 Sam wrote:\n> Hi Jo\n> long pitch"
    assert strip_quoted(t) == "Not right now, maybe in March."
    assert html_to_text("<div>Yes please</div><div>call me&nbsp;Tuesday</div>").split() == \
        ["Yes", "please", "call", "me", "Tuesday"]


def test_classify_labels():
    assert classify(FakeClaude([{"label": "interested", "reason": "asks for a call"}]), "yes") == \
        ("interested", "asks for a call")
    assert classify(FakeClaude([{"label": "spam"}]), "x")[0] == "unclear"
    assert classify(FakeClaude(["garbage"]), "x")[0] == "unclear"


def test_poll_classifies_new_replies_once_and_suppresses_unsubscribes(tmp_path):
    store = Store(str(tmp_path / "db"))
    api = FakeInstantly()
    api.received = [
        received("e1", "jo@bakery.example.com", text="Please remove me from your list."),
        received("e2", "priya@loaf.example.com", html="<div>Sounds good, can we talk Thursday?</div>"),
        received("e3", "sam@outreach.example.com", text="our own sent copy"),
        received("e4", "lee@deli.example.com", text=""),
    ]
    claude = FakeClaude([{"label": "unsubscribe", "reason": "asks to be removed"},
                         {"label": "interested", "reason": "wants a call"}])
    new = poll_replies(api, claude, store, "c1", own_senders=["sam@outreach.example.com"])
    assert [(r["lead_email"], r["label"]) for r in new] == [
        ("jo@bakery.example.com", "unsubscribe"), ("priya@loaf.example.com", "interested"),
        ("lee@deli.example.com", "unclear")]
    assert store.is_suppressed("jo@bakery.example.com") and not store.is_suppressed("priya@loaf.example.com")
    assert "Thursday" in claude.calls[1]["messages"][0]["content"]
    assert poll_replies(api, FakeClaude([]), store, "c1", own_senders=["sam@outreach.example.com"]) == []


def test_bounces_and_unsubscribes_from_instantly_are_suppressed(tmp_path):
    store = Store(str(tmp_path / "db"))
    api = FakeInstantly()
    api.leads = {"l1": {"email": "a@x.co", "campaign": "c1", "status": -1},
                 "l2": {"email": "b@x.co", "campaign": "c1", "status": -2},
                 "l3": {"email": "c@x.co", "campaign": "c1", "status": 1}}
    assert sync_lead_statuses(api, store, "c1") == [("a@x.co", "bounced"), ("b@x.co", "unsubscribed")]
    assert sync_lead_statuses(api, store, "c1") == []  # already on the list


def test_report(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.record_reply("e1", "jo@x.co", "Re", "2026-11-04", "not_now", "maybe | later", "text")
    store.suppress("b@x.co", "bounced", "instantly")
    path = str(tmp_path / "r.md")
    counts = write_report(store, path, mask=lambda e: "M@x")
    text = open(path).read()
    assert counts["not_now"] == 1 and "maybe / later" in text and "jo@x.co" not in text
    assert "Suppression list (1)" in text
