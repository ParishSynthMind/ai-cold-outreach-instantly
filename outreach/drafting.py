"""Claude writes one first email and one follow-up per lead, as strict JSON."""
import json
import logging
import re

from .validate import validate_draft

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5-5"

SYSTEM = """You write short, plain cold emails for a small business owner. You only use facts you are given.

Rules:
- Use ONLY facts from the LEAD and SENDER blocks. Never invent numbers, results, clients, names, mutual contacts, compliments, or anything about the lead's business that is not written there.
- If the lead's notes are thin or unclear, write a simple honest email and set "unsure" to true with a reason. Do not fill gaps with guesses.
- First email: 50 to 110 words, greeting with the first name, one specific line drawn from the lead's notes or role, what the sender offers in one sentence, the call to action, sign off with the sender's first name.
- Follow-up: 20 to 60 words, a polite short nudge in the same thread, no new claims.
- Subject: under 50 characters, lower key, no clickbait, no emojis.
- Plain English, friendly, not salesy. No em dashes or en dashes. No links. No placeholders.
- Both bodies must end with this exact line on its own line: {unsubscribe}
- In "facts_used", list every lead fact you relied on as {{"field": <lead field name>, "value": <exact text copied from that field>}}.

Reply with JSON only, no prose, in exactly this shape:
{{"subject_1": "...", "body_1": "...", "body_2": "...", "facts_used": [{{"field": "...", "value": "..."}}], "unsure": false, "unsure_reason": ""}}"""


class DraftError(Exception):
    pass


def build_prompt(lead, settings):
    sender = {
        "name": settings.sender_name,
        "company": settings.sender_company,
        "offer": settings.offer,
        "call_to_action": settings.call_to_action,
    }
    return (
        "LEAD:\n" + json.dumps(lead.facts(), indent=1, ensure_ascii=False)
        + "\n\nSENDER:\n" + json.dumps(sender, indent=1, ensure_ascii=False)
    )


def parse_json(text):
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    if not text.startswith("{") and "{" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    try:
        data = json.loads(text, strict=False)
    except ValueError as exc:
        raise DraftError(f"model reply was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DraftError("model reply was not a JSON object")
    return data


class Drafter:
    def __init__(self, client, settings, model=MODEL, max_tokens=4000):
        self.client = client  # anthropic.Anthropic() or a fake with .messages.create
        self.settings = settings
        self.model = model
        self.max_tokens = max_tokens

    def _ask(self, lead, extra=""):
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM.format(unsubscribe=self.settings.unsubscribe_line),
            messages=[{"role": "user", "content": build_prompt(lead, self.settings) + extra}],
        )
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise DraftError("model reply was cut off (max_tokens)")
        return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "text") == "text")

    def draft(self, lead):
        """Returns (draft dict or None, Check). One retry, telling the model what failed."""
        try:
            draft = parse_json(self._ask(lead))
        except DraftError as exc:
            log.warning("draft for %s: %s, retrying", _mask(lead.email), exc)
            draft = None
        check = validate_draft(draft, lead, self.settings) if draft else None
        if draft is None or not check.ok:
            problems = check.errors if check else ["your reply was not valid JSON"]
            extra = "\n\nYour previous answer failed these checks, fix them:\n- " + "\n- ".join(problems)
            try:
                draft = parse_json(self._ask(lead, extra))
            except DraftError as exc:
                from .validate import Check
                return None, Check(errors=[str(exc)])
            check = validate_draft(draft, lead, self.settings)
        return draft, check


def _mask(email):
    user, _, domain = email.partition("@")
    return (user[:1] + "***@" + domain) if domain else "***"
