"""Create the Instantly campaign and push approved leads to it.

Order of checks for each lead: approved in the queue -> not on the local
suppression list -> never pushed before (local ledger) -> Instantly's own
skip_if_in_workspace as a second guard.
"""
import logging
from dataclasses import dataclass, field

from .instantly import InstantlyError

log = logging.getLogger(__name__)

STATE_CAMPAIGN = "campaign_id"


def campaign_payload(settings):
    days = {str(d): d in settings.send_days for d in range(7)}
    return {
        "name": settings.campaign_name,
        "campaign_schedule": {"schedules": [{
            "name": "Sending window",
            "timing": {"from": settings.window_from, "to": settings.window_to},
            "days": days,
            "timezone": settings.timezone,
        }]},
        "sequences": [{"steps": [
            {"type": "email", "delay": settings.follow_up_delay, "delay_unit": settings.follow_up_unit,
             "variants": [{"subject": "{{subject_1}}", "body": "{{body_1}}"}]},
            # empty subject = sent as a reply in the same thread
            {"type": "email", "delay": 0, "variants": [{"subject": "", "body": "{{body_2}}"}]},
        ]}],
        "email_list": list(settings.sending_accounts),
        "daily_limit": settings.daily_cap,
        "stop_on_reply": True,
        "stop_on_auto_reply": False,
        "text_only": True,
        "open_tracking": False,
        "link_tracking": False,
        "insert_unsubscribe_header": True,
    }


def lead_payload(item):
    lead, draft = item["lead"], item["draft"]
    return {
        "email": lead["email"],
        "first_name": lead["first_name"],
        "last_name": lead.get("last_name", ""),
        "company_name": lead["company"],
        "website": lead.get("website", ""),
        "custom_variables": {
            "subject_1": draft["subject_1"].strip(),
            "body_1": to_html(draft["body_1"]),
            "body_2": to_html(draft["body_2"]),
        },
    }


def to_html(text):
    """Instantly stores bodies as HTML; keep paragraphs and line breaks."""
    import html as _html
    paras = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    return "".join("<div>" + _html.escape(p, quote=False).replace("\n", "<br>") + "</div><div><br></div>"
                   for p in paras)[: -len("<div><br></div>")]


@dataclass
class PushReport:
    campaign_id: str = None
    created_campaign: bool = False
    pushed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # (email, reason)
    failed: list = field(default_factory=list)  # (email, error)
    dry_run: bool = False


def ensure_campaign(client, store, settings, dry_run=False):
    cid = store.get(STATE_CAMPAIGN)
    if cid:
        return cid, False
    if dry_run:
        return "(new)", True
    created = client.create_campaign(campaign_payload(settings))
    store.set(STATE_CAMPAIGN, created["id"])
    log.info("created campaign %s", created["id"])
    return created["id"], True


def push_approved(client, store, queue, settings, dry_run=False):
    report = PushReport(dry_run=dry_run)
    approved = queue.by_status("approved")
    ready = []
    for item in approved:
        email = item["email"]
        if store.is_suppressed(email):
            report.skipped.append((email, "on suppression list"))
        elif store.was_pushed(email):
            report.skipped.append((email, "already pushed"))
            item["status"] = "pushed"
        else:
            ready.append(item)
    if not ready:
        report.campaign_id = store.get(STATE_CAMPAIGN)
        return report

    report.campaign_id, report.created_campaign = ensure_campaign(client, store, settings, dry_run)
    for item in ready:
        email = item["email"]
        if dry_run:
            report.pushed.append(email)
            continue
        try:
            resp = client.add_lead(report.campaign_id, lead_payload(item))
        except InstantlyError as exc:
            report.failed.append((email, str(exc)))
            continue
        lead_id = resp.get("id") if isinstance(resp, dict) else None
        if not lead_id:
            # Instantly skipped it (already in the workspace): record so we never retry it
            report.skipped.append((email, "Instantly says it is already in the workspace"))
        else:
            report.pushed.append(email)
        store.record_push(email, report.campaign_id, lead_id)
        item["status"] = "pushed"
    return report
