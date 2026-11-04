"""Campaign settings, loaded from a JSON file (see samples/campaign.example.json)."""
import json
from dataclasses import dataclass, field, fields

DEFAULT_UNSUBSCRIBE = "If you'd rather not hear from me, reply \"unsubscribe\" and I won't email you again."


@dataclass
class Settings:
    campaign_name: str
    sender_name: str
    sender_company: str
    offer: str
    call_to_action: str
    sending_accounts: list
    daily_cap: int = 5
    timezone: str = "Europe/London"
    window_from: str = "09:00"
    window_to: str = "17:00"
    send_days: list = field(default_factory=lambda: [1, 2, 3, 4, 5])  # 0 = Sunday
    follow_up_delay: int = 3
    follow_up_unit: str = "days"
    unsubscribe_line: str = DEFAULT_UNSUBSCRIBE
    max_cap: int = 50  # hard ceiling: refuse a daily_cap above this

    def __post_init__(self):
        if not self.sending_accounts:
            raise ValueError("sending_accounts must list at least one connected mailbox")
        if not 1 <= int(self.daily_cap) <= self.max_cap:
            raise ValueError(f"daily_cap must be between 1 and {self.max_cap}")
        if self.follow_up_unit not in ("minutes", "hours", "days"):
            raise ValueError("follow_up_unit must be minutes, hours or days")
        if "unsubscribe" not in self.unsubscribe_line.lower():
            raise ValueError("unsubscribe_line must tell the reader how to unsubscribe")

    def sender_text(self):
        """Everything the model is allowed to say about the sender, as one string."""
        return " ".join([self.sender_name, self.sender_company, self.offer, self.call_to_action])


def load_settings(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    known = {f.name for f in fields(Settings)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    return Settings(**raw)
