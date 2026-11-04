import pytest

from outreach.approval import ApprovalError, Queue, render_review_page
from outreach.validate import validate_draft
from tests.conftest import good_draft


def add(queue, lead, settings, draft):
    queue.add(lead, draft, validate_draft(draft, lead, settings))


def test_clean_is_pending_and_flagged_needs_closer_look(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    add(q, lead, settings, good_draft())
    assert q.find(lead.email)["status"] == "pending"
    assert not q.add(lead, good_draft(), validate_draft(good_draft(), lead, settings))  # no duplicates


def test_approve_and_persist(tmp_path, settings, lead):
    path = str(tmp_path / "q.json")
    q = Queue(path)
    add(q, lead, settings, good_draft())
    q.approve(lead.email, "reviewer", settings)
    q.save()
    again = Queue(path)
    item = again.find(lead.email)
    assert item["status"] == "approved" and item["decided_by"] == "reviewer" and item["decided_at"]


def test_flagged_needs_accept_warnings(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    add(q, lead, settings, good_draft(unsure=True, unsure_reason="thin"))
    assert q.find(lead.email)["status"] == "flagged"
    with pytest.raises(ApprovalError, match="accept-warnings"):
        q.approve(lead.email, "r", settings)
    assert q.approve_all_clean("r", settings) == []
    q.approve(lead.email, "r", settings, accept_warnings=True)
    assert q.find(lead.email)["status"] == "approved"


def test_errors_block_approval_even_with_accept_warnings(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    add(q, lead, settings, good_draft(subject_1="Hi — there"))
    with pytest.raises(ApprovalError, match="still fails"):
        q.approve(lead.email, "r", settings, accept_warnings=True)


def test_edited_draft_is_checked_again(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    add(q, lead, settings, good_draft(subject_1="Hi — there"))
    q.find(lead.email)["draft"]["subject_1"] = "Wholesale orders"  # a person fixes it in queue.json
    q.approve(lead.email, "r", settings)
    assert q.find(lead.email)["errors"] == []


def test_reject_and_unknown(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    add(q, lead, settings, good_draft())
    q.reject(lead.email, "r")
    with pytest.raises(ApprovalError, match="already rejected"):
        q.approve(lead.email, "r", settings)
    with pytest.raises(ApprovalError, match="not in the queue"):
        q.approve("nobody@example.com", "r", settings)


def test_cannot_reject_pushed(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    add(q, lead, settings, good_draft())
    q.find(lead.email)["status"] = "pushed"
    with pytest.raises(ApprovalError):
        q.reject(lead.email, "r")


def test_review_page_escapes_and_masks(tmp_path, settings, lead):
    q = Queue(str(tmp_path / "q.json"))
    d = good_draft()
    d["body_2"] = "<script>alert(1)</script>"
    add(q, lead, settings, d)
    html = open(render_review_page(q, str(tmp_path / "r.html"), mask=lambda e: "MASKED")).read()
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert lead.email not in html and "MASKED" in html
    assert "Nothing is sent until a person approves it" in html
