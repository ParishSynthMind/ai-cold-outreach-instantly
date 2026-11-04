"""The approval queue. Nothing is pushed to Instantly unless a human approved it here.

Statuses: pending (clean draft), flagged (needs a closer look), approved, rejected, pushed.
The queue is a JSON file you can open and edit; review.html is a read-only page to read
the drafts comfortably. Approving re-runs the checks, so an edited draft is checked again.
"""
import html
import json
import os
from datetime import datetime, timezone

from .leads import Lead
from .validate import validate_draft


class ApprovalError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Queue:
    def __init__(self, path):
        self.path = path
        self.items = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.items = json.load(fh)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.items, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def find(self, email):
        email = email.strip().lower()
        for item in self.items:
            if item["email"] == email:
                return item
        return None

    def add(self, lead, draft, check):
        if self.find(lead.email):
            return False
        status = "pending" if check.clean else "flagged"
        self.items.append({
            "email": lead.email, "lead": lead.as_dict(), "draft": draft, "status": status,
            "errors": check.errors, "warnings": check.warnings, "created_at": _now(),
            "decided_by": None, "decided_at": None,
        })
        return True

    def approve(self, email, reviewer, settings, accept_warnings=False):
        item = self.find(email)
        if not item:
            raise ApprovalError(f"{email} is not in the queue")
        if item["status"] in ("pushed", "rejected"):
            raise ApprovalError(f"{email} is already {item['status']}")
        if not item.get("draft"):
            raise ApprovalError(f"{email} has no draft to approve")
        check = validate_draft(item["draft"], Lead(**item["lead"]), settings)
        item["errors"], item["warnings"] = check.errors, check.warnings
        if check.errors:
            item["status"] = "flagged"
            raise ApprovalError(f"{email} still fails checks: " + "; ".join(check.errors))
        if check.warnings and not accept_warnings:
            item["status"] = "flagged"
            raise ApprovalError(f"{email} is flagged ({'; '.join(check.warnings)}); "
                                "read it, then approve with --accept-warnings")
        item.update(status="approved", decided_by=reviewer, decided_at=_now())
        return item

    def approve_all_clean(self, reviewer, settings):
        done = []
        for item in self.items:
            if item["status"] == "pending":
                try:
                    done.append(self.approve(item["email"], reviewer, settings))
                except ApprovalError:
                    pass
        return done

    def reject(self, email, reviewer):
        item = self.find(email)
        if not item:
            raise ApprovalError(f"{email} is not in the queue")
        if item["status"] == "pushed":
            raise ApprovalError(f"{email} was already pushed")
        item.update(status="rejected", decided_by=reviewer, decided_at=_now())
        return item

    def by_status(self, status):
        return [i for i in self.items if i["status"] == status]

    def counts(self):
        out = {}
        for i in self.items:
            out[i["status"]] = out.get(i["status"], 0) + 1
        return out


def render_review_page(queue, path, mask=None):
    """Write a plain HTML page showing every draft and how to approve or reject it."""
    show = mask or (lambda e: e)
    esc = html.escape
    colours = {"pending": "#2563eb", "flagged": "#b45309", "approved": "#15803d",
               "rejected": "#6b7280", "pushed": "#7c3aed"}
    cards = []
    for item in queue.items:
        d = item.get("draft") or {}
        issues = "".join(f"<li class=err>{esc(e)}</li>" for e in item["errors"])
        issues += "".join(f"<li class=warn>{esc(w)}</li>" for w in item["warnings"])
        cards.append(f"""
<section>
  <div class=head><b>{esc(show(item['email']))}</b> &middot; {esc(item['lead'].get('company', ''))}
    <span class=badge style="background:{colours.get(item['status'], '#444')}">{esc(item['status'])}</span></div>
  {'<ul>' + issues + '</ul>' if issues else '<p class=ok>All checks passed</p>'}
  <h4>Email 1 &middot; {esc(d.get('subject_1', ''))}</h4><pre>{esc(d.get('body_1', ''))}</pre>
  <h4>Follow-up (same thread)</h4><pre>{esc(d.get('body_2', ''))}</pre>
  <code>python -m outreach approve {esc(show(item['email']))}</code>
</section>""")
    counts = ", ".join(f"{k}: {v}" for k, v in sorted(queue.counts().items())) or "empty"
    page = f"""<!doctype html><meta charset=utf-8><title>Outreach approval queue</title>
<style>
body{{font:16px/1.5 -apple-system,Segoe UI,sans-serif;max-width:820px;margin:32px auto;padding:0 16px;color:#111}}
section{{border:1px solid #ddd;border-radius:10px;padding:16px 20px;margin:18px 0}}
.head{{display:flex;gap:8px;align-items:center}}
.badge{{color:#fff;border-radius:6px;padding:1px 8px;margin-left:auto;font-size:13px}}
pre{{white-space:pre-wrap;background:#f7f7f5;padding:12px;border-radius:8px;font:15px/1.5 Georgia,serif}}
.err{{color:#b91c1c}} .warn{{color:#92400e}} .ok{{color:#15803d}} h4{{margin:12px 0 4px}}
code{{background:#eef;padding:2px 6px;border-radius:4px;font-size:13px}}
</style>
<h1>Approval queue</h1><p>{esc(counts)}. Nothing is sent until a person approves it.</p>
{''.join(cards)}"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path
