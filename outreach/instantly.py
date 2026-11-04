"""Small Instantly API v2 client.

Only the endpoints this project needs. Every request sends a normal User-Agent:
Instantly sits behind Cloudflare, which answers Python's default one with
"error code: 1010" (HTTP 403).
"""
import logging
import random
import time

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.instantly.ai/api/v2/"
USER_AGENT = "ai-cold-outreach-instantly/1.0"

# Lead status codes as returned by GET/POST /leads/list
LEAD_STATUS = {1: "active", 2: "paused", 3: "completed", -1: "bounced", -2: "unsubscribed", -3: "skipped"}
# Account status codes
ACCOUNT_STATUS = {1: "active", 2: "paused", -1: "connection error", -2: "soft bounce error", -3: "sending error"}
CAMPAIGN_STATUS = {0: "draft", 1: "active", 2: "paused", 3: "completed", 4: "running subsequences",
                   -99: "suspended", -1: "accounts unhealthy", -2: "bounce protect"}


class InstantlyError(Exception):
    def __init__(self, status, message, path):
        super().__init__(f"Instantly {status} on {path}: {message}")
        self.status = status
        self.message = message
        self.path = path


class PlanLimitError(InstantlyError):
    """The API refused because the workspace plan does not include the feature."""


PLAN_HINTS = ("upgrade", "plan", "subscription", "trial", "limit reached", "quota")


class InstantlyClient:
    def __init__(self, api_key, base_url=BASE_URL, session=None, max_attempts=4,
                 backoff_base=1.0, sleep=time.sleep, timeout=30):
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.sleep = sleep
        self.timeout = timeout
        self.calls = 0

    def __repr__(self):
        return f"InstantlyClient(base_url={self.base_url!r})"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

    def request(self, method, path, json=None, params=None):
        url = self.base_url + path.lstrip("/")
        for attempt in range(1, self.max_attempts + 1):
            self.calls += 1
            try:
                resp = self.session.request(method, url, headers=self._headers(), json=json,
                                            params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("%s %s network error on attempt %d: %s", method, path, attempt,
                            type(exc).__name__)
                if attempt == self.max_attempts:
                    raise InstantlyError(0, f"network error: {type(exc).__name__}", path) from exc
                self.sleep(self._backoff(attempt))
                continue
            log.info("%s %s -> %s (attempt %d)", method, path, resp.status_code, attempt)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_attempts:
                    raise InstantlyError(resp.status_code, _message(resp), path)
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else self._backoff(attempt)
                self.sleep(min(wait, 60))
                continue
            if resp.status_code >= 400:
                msg = _message(resp)
                if resp.status_code == 403 and "1010" in resp.text:
                    msg = "Cloudflare 1010: request blocked (check the User-Agent header)"
                if resp.status_code in (402, 403) and any(h in msg.lower() for h in PLAN_HINTS):
                    raise PlanLimitError(resp.status_code, msg, path)
                raise InstantlyError(resp.status_code, msg, path)
            if not resp.content:
                return {}
            return resp.json()
        raise AssertionError("unreachable")

    def _backoff(self, attempt):
        base = self.backoff_base * (2 ** (attempt - 1))
        return min(base / 2 + random.uniform(0, base / 2), 30)

    # accounts
    def list_accounts(self):
        return self.request("GET", "accounts", params={"limit": 100}).get("items", [])

    def get_account(self, email):
        return self.request("GET", f"accounts/{email}")

    def warmup_analytics(self, emails):
        return self.request("POST", "accounts/warmup-analytics", json={"emails": list(emails)})

    # campaigns
    def create_campaign(self, payload):
        return self.request("POST", "campaigns", json=payload)

    def get_campaign(self, campaign_id):
        return self.request("GET", f"campaigns/{campaign_id}")

    def activate_campaign(self, campaign_id):
        return self.request("POST", f"campaigns/{campaign_id}/activate", json={})

    def pause_campaign(self, campaign_id):
        return self.request("POST", f"campaigns/{campaign_id}/pause", json={})

    def delete_campaign(self, campaign_id):
        return self.request("DELETE", f"campaigns/{campaign_id}")

    def campaign_analytics(self, campaign_id):
        return self.request("GET", "campaigns/analytics", params={"id": campaign_id})

    # lead lists
    def create_lead_list(self, name):
        return self.request("POST", "lead-lists", json={"name": name})

    def delete_lead_list(self, list_id):
        return self.request("DELETE", f"lead-lists/{list_id}")

    # leads
    def add_lead(self, campaign_id, lead):
        body = dict(lead)
        body["campaign"] = campaign_id
        body["skip_if_in_workspace"] = True
        return self.request("POST", "leads", json=body)

    def list_leads(self, campaign_id, limit=100):
        items, cursor = [], None
        while True:
            body = {"campaign": campaign_id, "limit": limit}
            if cursor:
                body["starting_after"] = cursor
            page = self.request("POST", "leads/list", json=body)
            items.extend(page.get("items", []))
            cursor = page.get("next_starting_after")
            if not cursor or not page.get("items"):
                return items

    def delete_lead(self, lead_id):
        return self.request("DELETE", f"leads/{lead_id}")

    # emails (unibox)
    def list_emails(self, campaign_id=None, email_type=None, limit=100):
        params = {"limit": limit}
        if campaign_id:
            params["campaign_id"] = campaign_id
        if email_type:
            params["email_type"] = email_type
        return self.request("GET", "emails", params=params).get("items", [])


def _message(resp):
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or data)[:300]
    return str(data)[:300]
