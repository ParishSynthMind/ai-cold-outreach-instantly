"""Command line: python -m outreach <command>."""
import argparse
import getpass
import logging
import os
import re
import sys

from .approval import ApprovalError, Queue, render_review_page
from .config import load_settings
from .health import blocking, check_health
from .instantly import CAMPAIGN_STATUS, LEAD_STATUS, InstantlyClient, InstantlyError
from .leads import load_leads
from .push import STATE_CAMPAIGN, push_approved
from .replies import poll_replies, sync_lead_statuses, write_report
from .secrets import get_secret
from .store import Store

ICON = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}


def mask_email(email):
    user, _, domain = (email or "").partition("@")
    if not domain:
        return email
    return f"{user[:2]}***@{domain}"


class App:
    """Wires settings, store, queue and API clients. Clients are built lazily so
    commands that do not need them (review, approve, suppress) work offline."""

    def __init__(self, args, instantly=None, claude=None):
        self.args = args
        self.settings = load_settings(args.config)
        os.makedirs(args.data_dir, exist_ok=True)
        self.store = Store(os.path.join(args.data_dir, "outreach.db"))
        self.queue = Queue(os.path.join(args.data_dir, "queue.json"))
        self._instantly = instantly
        self._claude = claude
        self.show = mask_email if args.mask else (lambda e: e)

    @property
    def instantly(self):
        if self._instantly is None:
            self._instantly = InstantlyClient(get_secret("INSTANTLY_API_KEY", "instantly-api-key",
                                                         os.environ.get("INSTANTLY_KEYCHAIN_ACCOUNT")))
        return self._instantly

    @property
    def claude(self):
        if self._claude is None:
            import anthropic
            self._claude = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY", "anthropic-api-key"))
        return self._claude

    def out(self, text=""):
        print(text)

    def path(self, name):
        return os.path.join(self.args.data_dir, name)


def cmd_draft(app):
    from .drafting import Drafter
    loaded = load_leads(app.args.leads)
    for row, email, reason in loaded.rejected:
        app.out(f"rejected row {row} ({app.show(email) or 'blank'}): {reason}")
    drafter = Drafter(app.claude, app.settings)
    made = 0
    for lead in loaded.leads[: app.args.limit or None]:
        if app.store.is_suppressed(lead.email):
            app.out(f"skip {app.show(lead.email)}: on suppression list")
            continue
        if app.queue.find(lead.email) or app.store.was_pushed(lead.email):
            app.out(f"skip {app.show(lead.email)}: already drafted or pushed")
            continue
        draft, check = drafter.draft(lead)
        app.queue.add(lead, draft, check)
        app.queue.save()  # save after every lead
        made += 1
        state = "clean" if check.clean else f"FLAGGED ({len(check.errors)} errors, {len(check.warnings)} warnings)"
        app.out(f"drafted {app.show(lead.email)}: {state}")
    page = render_review_page(app.queue, app.path("review.html"), mask=app.show if app.args.mask else None)
    app.out(f"{made} new draft(s). Review them in {page}")
    return 0


def cmd_review(app):
    page = render_review_page(app.queue, app.path("review.html"), mask=app.show if app.args.mask else None)
    for item in app.queue.items:
        subject = (item["draft"] or {}).get("subject_1", "")
        app.out(f"{item['status']:9} {app.show(item['email'])}  {subject}")
        for e in item["errors"]:
            app.out(f"          error: {e}")
        for w in item["warnings"]:
            app.out(f"          check: {w}")
    app.out(f"Review page: {page}")
    return 0


def cmd_approve(app):
    reviewer = app.args.reviewer or getpass.getuser()
    if app.args.all_clean:
        done = app.queue.approve_all_clean(reviewer, app.settings)
        app.queue.save()
        app.out(f"approved {len(done)} clean draft(s); flagged ones need approving one by one")
        return 0
    code = 0
    for email in app.args.emails:
        try:
            app.queue.approve(email, reviewer, app.settings, accept_warnings=app.args.accept_warnings)
            app.out(f"approved {app.show(email)}")
        except ApprovalError as exc:
            app.out(f"not approved: {exc}")
            code = 1
    app.queue.save()
    return code


def cmd_reject(app):
    reviewer = app.args.reviewer or getpass.getuser()
    for email in app.args.emails:
        app.queue.reject(email, reviewer)
        app.out(f"rejected {app.show(email)}")
    app.queue.save()
    return 0


def _campaign(app):
    cid = app.store.get(STATE_CAMPAIGN)
    return app.instantly.get_campaign(cid) if cid else None


EMAIL_IN_TEXT = re.compile(r"[\w.+'-]+@[\w-]+(\.[\w-]+)+")


def print_health(app, results):
    for r in results:
        line = f"[{ICON[r.level]}] {r.name}: {r.detail}"
        app.out(EMAIL_IN_TEXT.sub(lambda m: app.show(m.group(0)), line))


def cmd_health(app):
    results = check_health(app.instantly, app.settings, _campaign(app))
    print_health(app, results)
    return 1 if blocking(results) else 0


def cmd_push(app):
    results = check_health(app.instantly, app.settings, _campaign(app))
    if blocking(results):
        print_health(app, results)
        app.out("push stopped: fix the failed checks first")
        return 1
    report = push_approved(app.instantly, app.store, app.queue, app.settings, dry_run=app.args.dry_run)
    if not app.args.dry_run:
        app.queue.save()
    tag = "[dry run] " if app.args.dry_run else ""
    if report.created_campaign:
        verb = "would create" if app.args.dry_run else "created"
        app.out(f"{tag}{verb} campaign {report.campaign_id} ({app.settings.campaign_name}), "
                f"daily cap {app.settings.daily_cap}")
    for e in report.pushed:
        app.out(f"{tag}{'would push' if app.args.dry_run else 'pushed'} {app.show(e)}")
    for e, why in report.skipped:
        app.out(f"{tag}skipped {app.show(e)}: {why}")
    for e, err in report.failed:
        app.out(f"{tag}FAILED {app.show(e)}: {err}")
    if not (report.pushed or report.skipped or report.failed):
        app.out("nothing approved and waiting to push")
        return 0
    app.out(f"{tag}{len(report.pushed)} pushed, {len(report.skipped)} skipped, {len(report.failed)} failed")
    return 1 if report.failed else 0


def cmd_activate(app):
    cid = app.store.get(STATE_CAMPAIGN)
    if not cid:
        app.out("no campaign yet: push approved leads first")
        return 1
    results = check_health(app.instantly, app.settings, app.instantly.get_campaign(cid))
    print_health(app, results)
    if blocking(results):
        app.out("not activated: fix the failed checks first")
        return 1
    if app.args.dry_run:
        app.out(f"[dry run] would activate campaign {cid}")
        return 0
    app.instantly.activate_campaign(cid)
    camp = app.instantly.get_campaign(cid)
    app.out(f"campaign {cid} is now {CAMPAIGN_STATUS.get(camp.get('status'), camp.get('status'))}")
    return 0


def cmd_pause(app):
    cid = app.store.get(STATE_CAMPAIGN)
    if not cid:
        app.out("no campaign")
        return 1
    app.instantly.pause_campaign(cid)
    app.out(f"campaign {cid} paused")
    return 0


def cmd_sync(app):
    cid = app.store.get(STATE_CAMPAIGN)
    if not cid:
        app.out("no campaign")
        return 1
    for email, status in sync_lead_statuses(app.instantly, app.store, cid):
        app.out(f"suppressed {app.show(email)} ({status} in Instantly)")
    new = poll_replies(app.instantly, app.claude, app.store, cid, own_senders=app.settings.sending_accounts)
    for r in new:
        app.out(f"reply from {app.show(r['lead_email'])}: {r['label']} ({r['reason']})")
    counts = write_report(app.store, app.path("reply-report.md"), mask=app.show if app.args.mask else None)
    app.out(f"{len(new)} new repl(ies). Totals: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    app.out(f"Report: {app.path('reply-report.md')}")
    return 0


def cmd_stats(app):
    cid = app.store.get(STATE_CAMPAIGN)
    if not cid:
        app.out("no campaign")
        return 1
    camp = app.instantly.get_campaign(cid)
    app.out(f"campaign {camp.get('name')}: {CAMPAIGN_STATUS.get(camp.get('status'), camp.get('status'))}, "
            f"daily cap {camp.get('daily_limit')}")
    for row in app.instantly.campaign_analytics(cid) or []:
        keys = ("leads_count", "contacted_count", "emails_sent_count", "reply_count",
                "bounced_count", "unsubscribed_count", "completed_count")
        app.out("  " + ", ".join(f"{k.replace('_count', '')} {row.get(k, 0)}" for k in keys))
    for lead in app.instantly.list_leads(cid):
        app.out(f"  lead {app.show(lead['email'])}: {LEAD_STATUS.get(lead.get('status'), lead.get('status'))}")
    return 0


def cmd_suppress(app):
    if app.args.action == "list":
        for s in app.store.suppressed():
            app.out(f"{app.show(s['email'])}  {s['reason']} ({s['source']}, {s['added_at']})")
        return 0
    if not app.args.email:
        app.out("give an email address")
        return 1
    if app.args.action == "add":
        app.store.suppress(app.args.email, app.args.reason or "manual", "manual")
        app.out(f"suppressed {app.show(app.args.email)}")
    else:
        app.store.unsuppress(app.args.email)
        app.out(f"removed {app.show(app.args.email)} from suppression")
    return 0


def cmd_teardown(app):
    """Pause and delete the campaign and its leads (used after a test run)."""
    cid = app.store.get(STATE_CAMPAIGN)
    if not cid:
        app.out("no campaign")
        return 0
    if not app.args.yes:
        app.out(f"this deletes campaign {cid} and its leads in Instantly; re-run with --yes")
        return 1
    leads = app.instantly.list_leads(cid)
    try:
        app.instantly.pause_campaign(cid)
    except InstantlyError as exc:
        app.out(f"pause: {exc}")
    for lead in leads:
        app.instantly.delete_lead(lead["id"])
        app.out(f"deleted lead {app.show(lead['email'])}")
    app.instantly.delete_campaign(cid)
    app.store.set(STATE_CAMPAIGN, None)
    app.out(f"deleted campaign {cid} (local push ledger and suppression list kept)")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="outreach", description=__doc__)
    p.add_argument("--config", default=os.environ.get("OUTREACH_CONFIG", "campaign.json"))
    p.add_argument("--data-dir", default=os.environ.get("OUTREACH_DATA", "data"))
    p.add_argument("--mask", action="store_true", help="mask email addresses in output")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("draft", help="write drafts for a lead CSV into the approval queue")
    d.add_argument("leads")
    d.add_argument("--limit", type=int, default=0)
    sub.add_parser("review", help="list the queue and write review.html")
    a = sub.add_parser("approve", help="approve drafts (a person must do this)")
    a.add_argument("emails", nargs="*")
    a.add_argument("--all-clean", action="store_true", help="approve every draft that passed all checks")
    a.add_argument("--accept-warnings", action="store_true")
    a.add_argument("--reviewer")
    r = sub.add_parser("reject")
    r.add_argument("emails", nargs="+")
    r.add_argument("--reviewer")
    sub.add_parser("health", help="mailbox, warmup and cap checks")
    for name in ("push", "activate"):
        s = sub.add_parser(name)
        s.add_argument("--dry-run", action="store_true")
    sub.add_parser("pause")
    sub.add_parser("sync", help="poll bounces, unsubscribes and replies; classify; write report")
    sub.add_parser("stats")
    s = sub.add_parser("suppress")
    s.add_argument("action", choices=["add", "remove", "list"])
    s.add_argument("email", nargs="?")
    s.add_argument("--reason")
    t = sub.add_parser("teardown")
    t.add_argument("--yes", action="store_true")
    return p


COMMANDS = {
    "draft": cmd_draft, "review": cmd_review, "approve": cmd_approve, "reject": cmd_reject,
    "health": cmd_health, "push": cmd_push, "activate": cmd_activate, "pause": cmd_pause,
    "sync": cmd_sync, "stats": cmd_stats, "suppress": cmd_suppress, "teardown": cmd_teardown,
}


def main(argv=None, instantly=None, claude=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.command == "approve" and not args.emails and not args.all_clean:
        print("give one or more emails, or --all-clean")
        return 2
    app = App(args, instantly=instantly, claude=claude)
    try:
        return COMMANDS[args.command](app)
    except InstantlyError as exc:
        print(f"Instantly API error: {exc}", file=sys.stderr)
        return 1
    finally:
        app.store.close()


if __name__ == "__main__":
    sys.exit(main())
