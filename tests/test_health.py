from outreach.health import FAIL, PASS, WARN, blocking, check_health
from outreach.instantly import InstantlyError
from tests.conftest import FakeInstantly


def levels(results):
    return {r.name: r.level for r in results}


def test_healthy_mailbox(settings):
    res = check_health(FakeInstantly(), settings)
    assert not blocking(res)
    assert levels(res)["warmup sam@outreach.example.com"] == PASS


def test_missing_and_broken_mailboxes_block(settings):
    res = check_health(FakeInstantly(accounts=[]), settings)
    assert levels(res)["mailbox sam@outreach.example.com"] == FAIL
    bad = FakeInstantly(accounts=[{"email": "sam@outreach.example.com", "status": -1, "warmup_status": 0,
                                   "daily_limit": 30}])
    res = check_health(bad, settings)
    lv = levels(res)
    assert lv["mailbox sam@outreach.example.com"] == FAIL
    assert lv["warmup sam@outreach.example.com"] == WARN
    assert lv["mailbox cap sam@outreach.example.com"] == WARN


def test_campaign_cap_above_settings_blocks(settings):
    res = check_health(FakeInstantly(), settings, campaign={"daily_limit": 50, "email_list": []})
    assert levels(res)["campaign daily cap"] == FAIL


def test_campaign_sending_from_unknown_mailbox_blocks(settings):
    res = check_health(FakeInstantly(), settings,
                       campaign={"daily_limit": 5, "email_list": ["other@example.com"]})
    assert levels(res)["campaign senders"] == FAIL


def test_api_down_blocks(settings):
    api = FakeInstantly()

    def boom():
        raise InstantlyError(401, "Unauthorized", "accounts")
    api.list_accounts = boom
    res = check_health(api, settings)
    assert blocking(res) and "401" in res[0].detail
