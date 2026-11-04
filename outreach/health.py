"""Pre-flight checks run before any push or activation."""
from dataclasses import dataclass

from .instantly import ACCOUNT_STATUS, InstantlyError

PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass
class Result:
    name: str
    level: str
    detail: str


def check_health(client, settings, campaign=None):
    results = []
    try:
        accounts = {a["email"].lower(): a for a in client.list_accounts()}
    except InstantlyError as exc:
        return [Result("API reachable", FAIL, str(exc))]
    results.append(Result("API reachable", PASS, f"{len(accounts)} mailbox(es) in workspace"))

    for email in settings.sending_accounts:
        acc = accounts.get(email.lower())
        name = f"mailbox {email}"
        if not acc:
            results.append(Result(name, FAIL, "not connected in Instantly"))
            continue
        status = acc.get("status")
        label = ACCOUNT_STATUS.get(status, f"code {status}")
        results.append(Result(name, PASS if status == 1 else FAIL, f"status {label}"))
        warm = acc.get("warmup_status")
        score = acc.get("stat_warmup_score")
        if warm == 1:
            results.append(Result(f"warmup {email}", PASS, f"warmup on, score {score}"))
        else:
            results.append(Result(f"warmup {email}", WARN,
                                  "warmup off: fine for a small test to your own addresses, "
                                  "warm a new mailbox for 2 to 4 weeks before real outreach"))
        limit = acc.get("daily_limit")
        if isinstance(limit, int) and limit > settings.daily_cap:
            results.append(Result(f"mailbox cap {email}", WARN,
                                  f"mailbox allows {limit}/day; campaign cap of "
                                  f"{settings.daily_cap}/day is the limit that applies here"))
        else:
            results.append(Result(f"mailbox cap {email}", PASS, f"{limit}/day"))

    if campaign is not None:
        cap = campaign.get("daily_limit")
        if cap is None or cap > settings.daily_cap:
            results.append(Result("campaign daily cap", FAIL,
                                  f"campaign daily_limit is {cap}, settings allow {settings.daily_cap}"))
        else:
            results.append(Result("campaign daily cap", PASS, f"{cap}/day"))
        senders = {e.lower() for e in campaign.get("email_list", [])}
        unknown = senders - {e.lower() for e in settings.sending_accounts}
        if unknown:
            results.append(Result("campaign senders", FAIL,
                                  "campaign sends from mailboxes not in settings: " + ", ".join(sorted(unknown))))
    return results


def blocking(results):
    return [r for r in results if r.level == FAIL]
