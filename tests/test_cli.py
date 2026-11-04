import json
import shutil

from outreach.cli import main, mask_email
from tests.conftest import FakeClaude, FakeInstantly, good_draft


def run(tmp_path, *argv, api=None, claude=None):
    return main(["--config", str(tmp_path / "c.json"), "--data-dir", str(tmp_path / "data"), *argv],
                instantly=api, claude=claude)


def setup_files(tmp_path):
    cfg = json.load(open("samples/campaign.example.json"))
    (tmp_path / "c.json").write_text(json.dumps(cfg))
    shutil.copy("samples/leads.example.csv", tmp_path / "leads.csv")


def test_full_flow(tmp_path, capsys):
    setup_files(tmp_path)
    api = FakeInstantly(accounts=[{"email": "sam@outreach.example.com", "status": 1, "warmup_status": 1,
                                   "daily_limit": 5}])
    drafts = [good_draft()] + [good_draft(unsure=True, unsure_reason="thin")] * 4
    # Jo gets a clean draft; the Jo-shaped drafts fail the checks for the other two leads (retried, then flagged)
    assert run(tmp_path, "draft", str(tmp_path / "leads.csv"), claude=FakeClaude(drafts)) == 0
    out = capsys.readouterr().out
    assert "rejected row 5" in out and "rejected row 6" in out and "FLAGGED" in out

    assert run(tmp_path, "push", api=api) == 0
    assert "nothing approved" in capsys.readouterr().out and api.writes() == []

    assert run(tmp_path, "approve", "--all-clean", "--reviewer", "me") == 0
    assert run(tmp_path, "push", "--dry-run", api=api) == 0
    out = capsys.readouterr().out
    assert "[dry run] would push jo@riverside-bakery.example.com" in out and api.writes() == []

    assert run(tmp_path, "push", api=api) == 0
    assert "pushed jo@riverside-bakery.example.com" in capsys.readouterr().out
    assert run(tmp_path, "activate", api=api) == 0
    assert "is now active" in capsys.readouterr().out

    api.received = [{"id": "e1", "from_address_email": "jo@riverside-bakery.example.com",
                     "body": {"text": "Yes, call me Tuesday."}, "subject": "Re: x"}]
    assert run(tmp_path, "sync", api=api, claude=FakeClaude([{"label": "interested", "reason": "wants call"}])) == 0
    assert "interested" in capsys.readouterr().out
    assert run(tmp_path, "stats", api=api) == 0
    assert run(tmp_path, "teardown", api=api) == 1  # needs --yes
    assert run(tmp_path, "teardown", "--yes", api=api) == 0
    assert api.campaigns == {} and api.leads == {}


def test_activate_refuses_when_mailbox_broken(tmp_path, capsys):
    setup_files(tmp_path)
    api = FakeInstantly()
    api.campaigns["camp-1"] = {"id": "camp-1", "daily_limit": 5, "email_list": ["sam@outreach.example.com"]}
    from outreach.store import Store
    (tmp_path / "data").mkdir()
    st = Store(str(tmp_path / "data" / "outreach.db"))
    st.set("campaign_id", "camp-1")
    st.close()
    api.accounts = [{"email": "sam@outreach.example.com", "status": -3, "daily_limit": 5}]
    assert run(tmp_path, "activate", api=api) == 1
    assert "not activated" in capsys.readouterr().out
    assert api.campaigns["camp-1"].get("status") is None


def test_suppress_commands_and_masking(tmp_path, capsys):
    setup_files(tmp_path)
    assert run(tmp_path, "suppress", "add", "x@y.co", "--reason", "asked") == 0
    assert main(["--config", str(tmp_path / "c.json"), "--data-dir", str(tmp_path / "data"), "--mask",
                 "suppress", "list"]) == 0
    out = capsys.readouterr().out
    assert "x***@y.co" in out and "x@y.co " not in out
    assert mask_email("jo@example.com") == "jo***@example.com"
    assert run(tmp_path, "suppress", "remove", "x@y.co") == 0


def test_approve_needs_target(tmp_path):
    setup_files(tmp_path)
    assert run(tmp_path, "approve") == 2
