import pytest
import requests
import responses

from outreach.instantly import BASE_URL, USER_AGENT, InstantlyClient, InstantlyError, PlanLimitError

KEY = "test-key-123"


def client(**kw):
    return InstantlyClient(KEY, sleep=lambda s: None, **kw)


@responses.activate
def test_headers_have_bearer_and_custom_user_agent():
    responses.get(BASE_URL + "accounts", json={"items": [{"email": "a@x.co"}]})
    assert client().list_accounts() == [{"email": "a@x.co"}]
    h = responses.calls[0].request.headers
    assert h["Authorization"] == "Bearer " + KEY
    assert h["User-Agent"] == USER_AGENT and "python-requests" not in h["User-Agent"]


def test_key_not_in_repr_and_required():
    assert KEY not in repr(client())
    with pytest.raises(ValueError):
        InstantlyClient("")


@responses.activate
def test_retries_429_then_succeeds_honouring_retry_after():
    waits = []
    responses.get(BASE_URL + "campaigns/c1", status=429, headers={"Retry-After": "2"}, json={})
    responses.get(BASE_URL + "campaigns/c1", status=503, json={})
    responses.get(BASE_URL + "campaigns/c1", json={"id": "c1"})
    c = InstantlyClient(KEY, sleep=waits.append)
    assert c.get_campaign("c1") == {"id": "c1"}
    assert waits[0] == 2 and len(waits) == 2 and c.calls == 3


@responses.activate
def test_gives_up_after_max_attempts():
    for _ in range(3):
        responses.get(BASE_URL + "accounts", status=500, json={"message": "boom"})
    with pytest.raises(InstantlyError) as e:
        client(max_attempts=3).list_accounts()
    assert e.value.status == 500 and len(responses.calls) == 3


@responses.activate
def test_400_not_retried():
    responses.post(BASE_URL + "campaigns", status=400, json={"message": "body/name is required"})
    with pytest.raises(InstantlyError, match="name is required"):
        client().create_campaign({})
    assert len(responses.calls) == 1


@responses.activate
def test_cloudflare_1010_explained():
    responses.get(BASE_URL + "accounts", status=403, body="error code: 1010")
    with pytest.raises(InstantlyError, match="User-Agent"):
        client().list_accounts()


@responses.activate
def test_plan_limit_is_its_own_error():
    responses.post(BASE_URL + "campaigns/c1/activate", status=402,
                   json={"message": "Please upgrade your plan to activate campaigns"})
    with pytest.raises(PlanLimitError):
        client().activate_campaign("c1")


@responses.activate
def test_network_error_retried():
    responses.get(BASE_URL + "accounts", body=requests.ConnectionError("down"))
    responses.get(BASE_URL + "accounts", json={"items": []})
    assert client().list_accounts() == []


@responses.activate
def test_add_lead_sends_campaign_and_workspace_guard():
    responses.post(BASE_URL + "leads", json={"id": "l1"})
    client().add_lead("c1", {"email": "a@x.co", "custom_variables": {"body_1": "hi"}})
    body = responses.calls[0].request.body
    assert b'"campaign": "c1"' in body and b'"skip_if_in_workspace": true' in body


@responses.activate
def test_list_leads_paginates():
    responses.post(BASE_URL + "leads/list", json={"items": [{"id": 1}], "next_starting_after": "cur"})
    responses.post(BASE_URL + "leads/list", json={"items": [{"id": 2}]})
    assert [x["id"] for x in client().list_leads("c1")] == [1, 2]
    assert b'"starting_after": "cur"' in responses.calls[1].request.body


@responses.activate
def test_list_emails_filters():
    responses.get(BASE_URL + "emails", json={"items": [{"id": "e1"}]})
    assert client().list_emails(campaign_id="c1", email_type="received") == [{"id": "e1"}]
    url = responses.calls[0].request.url
    assert "campaign_id=c1" in url and "email_type=received" in url


@responses.activate
def test_delete_with_empty_body():
    responses.delete(BASE_URL + "campaigns/c1", body=b"")
    assert client().delete_campaign("c1") == {}
