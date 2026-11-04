import json
from types import SimpleNamespace

import pytest

from outreach.config import DEFAULT_UNSUBSCRIBE, Settings
from outreach.leads import Lead

UNSUB = DEFAULT_UNSUBSCRIBE


@pytest.fixture
def settings():
    return Settings(
        campaign_name="Test campaign", sender_name="Sam Carter", sender_company="Carter Automation",
        offer="I set up simple systems that turn website and WhatsApp orders into one daily order sheet",
        call_to_action="Would a 15 minute call next week be useful?",
        sending_accounts=["sam@outreach.example.com"], daily_cap=5,
    )


@pytest.fixture
def lead():
    return Lead(email="jo@bakery.example.com", first_name="Jo", company="Riverside Bakery",
                consent_basis="asked at food fair", role="Owner",
                notes="Asked at the Leeds food fair about taking wholesale orders online.")


def good_draft(**over):
    d = {
        "subject_1": "Wholesale orders after the food fair",
        "body_1": ("Hi Jo,\n\nYou asked at the Leeds food fair about taking wholesale orders online. "
                   "I set up simple systems that turn website and WhatsApp orders into one daily order sheet, "
                   "so nobody retypes orders by hand.\n\nWould a 15 minute call next week be useful?\n\nSam\n\n"
                   + UNSUB),
        "body_2": "Hi Jo,\n\nJust a quick nudge on my note about wholesale orders. Happy to keep it short.\n\nSam\n\n"
                  + UNSUB,
        "facts_used": [{"field": "notes", "value": "Leeds food fair"}],
        "unsure": False, "unsure_reason": "",
    }
    d.update(over)
    return d


class FakeClaude:
    """Stands in for anthropic.Anthropic(): returns queued replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, SimpleNamespace):
            return reply
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="thinking", thinking="..."),
                                        SimpleNamespace(type="text", text=text)])


class FakeInstantly:
    """In-memory stand-in for InstantlyClient used by push, health, replies and CLI tests."""

    def __init__(self, accounts=None):
        self.accounts = accounts if accounts is not None else [
            {"email": "sam@outreach.example.com", "status": 1, "warmup_status": 1,
             "stat_warmup_score": 98, "daily_limit": 5}]
        self.campaigns = {}
        self.leads = {}
        self.received = []
        self.log = []
        self.fail_add = set()

    def _rec(self, *call):
        self.log.append(call)

    def list_accounts(self):
        self._rec("GET", "accounts")
        return self.accounts

    def create_campaign(self, payload):
        self._rec("POST", "campaigns")
        cid = f"camp-{len(self.campaigns) + 1}"
        self.campaigns[cid] = dict(payload, id=cid, status=0)
        return self.campaigns[cid]

    def get_campaign(self, cid):
        self._rec("GET", f"campaigns/{cid}")
        return self.campaigns[cid]

    def activate_campaign(self, cid):
        self._rec("POST", f"campaigns/{cid}/activate")
        self.campaigns[cid]["status"] = 1

    def pause_campaign(self, cid):
        self._rec("POST", f"campaigns/{cid}/pause")
        self.campaigns[cid]["status"] = 2

    def delete_campaign(self, cid):
        self._rec("DELETE", f"campaigns/{cid}")
        del self.campaigns[cid]

    def campaign_analytics(self, cid):
        self._rec("GET", "campaigns/analytics")
        return [{"leads_count": len(self.leads), "emails_sent_count": len(self.leads)}]

    def add_lead(self, cid, lead):
        self._rec("POST", "leads")
        from outreach.instantly import InstantlyError
        if lead["email"] in self.fail_add:
            raise InstantlyError(400, "bad lead", "leads")
        for existing in self.leads.values():
            if existing["email"] == lead["email"]:
                return existing  # Instantly returns the existing lead
        lid = f"lead-{len(self.leads) + 1}"
        self.leads[lid] = dict(lead, id=lid, campaign=cid, status=1)
        return self.leads[lid]

    def list_leads(self, cid):
        self._rec("POST", "leads/list")
        return [v for v in self.leads.values() if v["campaign"] == cid]

    def delete_lead(self, lid):
        self._rec("DELETE", f"leads/{lid}")
        del self.leads[lid]

    def list_emails(self, campaign_id=None, email_type=None):
        self._rec("GET", "emails")
        return self.received

    def writes(self):
        return [c for c in self.log if c[0] != "GET" and c[1] != "leads/list"]
