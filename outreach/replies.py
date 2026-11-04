"""Poll Instantly for bounces, unsubscribes and replies; classify replies with Claude.

Polling, not webhooks: Instantly only offers webhooks on its higher paid plans,
so this runs on a schedule (cron, launchd) and only looks at what is new.
"""
import html
import json
import logging
import re

from .drafting import MODEL, DraftError, parse_json
from .instantly import LEAD_STATUS

log = logging.getLogger(__name__)

LABELS = ("interested", "not_now", "unsubscribe", "out_of_office", "unclear")
SUPPRESS_LABELS = ("unsubscribe",)

CLASSIFY_SYSTEM = """You sort replies to a sales email. Read the reply and pick ONE label:
- interested: wants to talk, asks a question about the offer, asks for details or a call
- not_now: polite no for now, maybe later, bad timing, already has a provider
- unsubscribe: asks to stop, remove, unsubscribe, not interested at all, or is hostile
- out_of_office: an automatic away or vacation reply
- unclear: anything else, or you are not sure
If the reply mixes a stop request with anything else, choose unsubscribe.
Reply with JSON only: {"label": "...", "reason": "<one short sentence>"}"""


def strip_quoted(text):
    """Drop the quoted original message so only the new reply is classified."""
    out = []
    for line in (text or "").splitlines():
        if re.match(r"^\s*On .+wrote:\s*$", line) or line.strip().startswith("-----Original Message"):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


def html_to_text(value):
    value = re.sub(r"(?i)<br\s*/?>|</(div|p)>", "\n", value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value)


def reply_text(item):
    body = item.get("body") or {}
    text = body.get("text") if isinstance(body, dict) else None
    if not text and isinstance(body, dict) and body.get("html"):
        text = html_to_text(body["html"])
    return strip_quoted(text or item.get("content_preview") or "")


def classify(client, text, model=MODEL):
    msg = client.messages.create(
        model=model, max_tokens=2000, system=CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": "REPLY:\n" + text[:4000]}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "text") == "text")
    try:
        data = parse_json(raw)
    except DraftError:
        return "unclear", "classifier reply was not valid JSON"
    label = data.get("label")
    if label not in LABELS:
        return "unclear", f"classifier gave unknown label {label!r}"
    return label, str(data.get("reason", ""))[:300]


def sync_lead_statuses(client, store, campaign_id):
    """Bounced or unsubscribed leads in Instantly go on the local suppression list."""
    added = []
    for lead in client.list_leads(campaign_id):
        status = LEAD_STATUS.get(lead.get("status"))
        if status in ("bounced", "unsubscribed") and store.suppress(lead["email"], status, "instantly"):
            added.append((lead["email"], status))
    return added


def poll_replies(instantly, claude, store, campaign_id, own_senders=()):
    """Classify every new received email on the campaign. Returns the new rows."""
    own = {e.lower() for e in own_senders}
    new = []
    for item in instantly.list_emails(campaign_id=campaign_id, email_type="received"):
        eid = item.get("id")
        sender = (item.get("from_address_email") or item.get("lead") or "").lower()
        if not eid or store.reply_seen(eid) or sender in own:
            continue
        text = reply_text(item)
        if not text:
            label, reason = "unclear", "empty reply body"
        else:
            label, reason = classify(claude, text)
        store.record_reply(eid, sender, item.get("subject", ""), item.get("timestamp_email")
                           or item.get("timestamp_created"), label, reason, text[:280])
        if label in SUPPRESS_LABELS:
            store.suppress(sender, "replied unsubscribe", "reply")
        new.append({"email_id": eid, "lead_email": sender, "label": label, "reason": reason})
    return new


def write_report(store, path_md, mask=None):
    show = mask or (lambda e: e)
    rows = store.replies()
    counts = {label: 0 for label in LABELS}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    lines = ["# Reply report", "", " | ".join(f"{k}: {v}" for k, v in counts.items()), "",
             "| Received | From | Label | Why |", "|---|---|---|---|"]
    for r in rows:
        why = (r["reason"] or "").replace("|", "/")
        lines.append(f"| {r['received_at'] or ''} | {show(r['lead_email'] or '')} | {r['label']} | {why} |")
    sup = store.suppressed()
    lines += ["", f"## Suppression list ({len(sup)})", ""]
    lines += [f"- {show(s['email'])}: {s['reason']} ({s['source']})" for s in sup] or ["- empty"]
    with open(path_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return counts


def to_json(rows):
    return json.dumps(rows, indent=2)
