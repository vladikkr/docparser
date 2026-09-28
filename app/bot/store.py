"""Persistent bot state: who is a client, how much of the trial is left.

Kept as a small JSON file so the bot has no extra service to run. Writes go
through a temporary file to avoid corrupting the state if the process dies
mid-write.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BotUser:
    """One Telegram account that has written to the bot."""

    user_id: int
    username: str | None = None
    first_name: str | None = None
    created_at: str = field(default_factory=_now)
    # Documents already parsed. Counts against the trial while `approved` is False.
    documents_used: int = 0
    # Set by the owner from the admin chat; lifts the trial limit entirely.
    approved: bool = False
    # Set when the client hit the trial limit and was asked to pay.
    payment_requested_at: str | None = None
    last_seen_at: str = field(default_factory=_now)

    @property
    def trial_limit(self) -> int:
        return settings.TELEGRAM_TRIAL_LIMIT

    @property
    def trial_left(self) -> int:
        if self.approved:
            return -1  # unlimited
        return max(0, self.trial_limit - self.documents_used)

    @property
    def has_access(self) -> bool:
        return self.approved or self.trial_left > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserStore:
    """JSON-file backed user registry."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.TELEGRAM_STATE_FILE
        self._users: dict[int, BotUser] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            # A damaged state file must not stop the bot from starting; the
            # clients simply get a fresh trial.
            return
        for user_id, data in raw.get("users", {}).items():
            try:
                self._users[int(user_id)] = BotUser(**data)
            except TypeError:
                continue

    def _save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        payload = {"users": {str(k): v.to_dict() for k, v in self._users.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def get(self, user_id: int) -> BotUser:
        """Return the user, creating the record on first contact."""
        with _LOCK:
            return self._get_unlocked(user_id)

    def _get_unlocked(self, user_id: int) -> BotUser:
        """get() without locking, for callers that already hold the lock."""
        user = self._users.get(user_id)
        if user is None:
            user = BotUser(user_id=user_id)
            self._users[user_id] = user
            self._save()
        return user

    def touch(self, user: BotUser, username: str | None, first_name: str | None) -> BotUser:
        """Refresh the cached profile so greetings stay correct after a rename."""
        with _LOCK:
            changed = False
            if username and user.username != username:
                user.username, changed = username, True
            if first_name and user.first_name != first_name:
                user.first_name, changed = first_name, True
            user.last_seen_at = _now()
            if changed:
                self._save()
            return user

    def consume_document(self, user_id: int) -> BotUser:
        """Record one parsed document against the trial."""
        with _LOCK:
            user = self._get_unlocked(user_id)
            user.documents_used += 1
            user.last_seen_at = _now()
            self._save()
            return user

    def mark_payment_requested(self, user_id: int) -> None:
        with _LOCK:
            user = self._get_unlocked(user_id)
            user.payment_requested_at = _now()
            self._save()

    def approve(self, user_id: int, approved: bool = True) -> BotUser:
        with _LOCK:
            user = self._get_unlocked(user_id)
            user.approved = approved
            if approved:
                user.payment_requested_at = None
            self._save()
            return user

    def all_users(self) -> list[BotUser]:
        with _LOCK:
            return sorted(self._users.values(), key=lambda u: u.created_at)
