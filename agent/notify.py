"""Telegram-meldingen. Zonder TELEGRAM_BOT_TOKEN doet dit niets (stil).

Het chatnummer hoeft niet ingesteld te worden: stuur je bot één bericht, dan haalt de agent
het chatnummer op via getUpdates en bewaart het. TELEGRAM_CHAT_ID mag ook vast ingesteld worden.
"""
from __future__ import annotations

import html
import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class Notifier:
    def __init__(self, db, token: str | None = None, chat_id: str | None = None):
        self.db = db
        self.token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _call(self, method: str, **params):
        r = requests.post(API.format(token=self.token, method=method), json=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def chat_id(self) -> str | None:
        if self._chat:
            return self._chat
        saved = self.db.get("telegram_chat_id")
        if saved:
            self._chat = str(saved)
            return self._chat
        try:  # chatnummer opzoeken uit het eerste bericht dat de gebruiker aan de bot stuurde
            for u in reversed(self._call("getUpdates").get("result", [])):
                chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat")
                if chat and chat.get("type") == "private":
                    self._chat = str(chat["id"])
                    self.db.set("telegram_chat_id", self._chat)
                    return self._chat
        except Exception:
            return None
        return None

    def send(self, text: str, key: str | None = None) -> bool:
        """Stuur een bericht (HTML). `key`: hetzelfde bericht maar één keer versturen."""
        if not self.enabled:
            return False
        if key and self.db.get(f"tg_sent_{key}"):
            return False
        chat = self.chat_id()
        if not chat:
            return False
        try:
            for part in split(text):
                self._call("sendMessage", chat_id=chat, text=part, parse_mode="HTML",
                           disable_web_page_preview=True)
        except Exception as e:  # meldingen mogen de agent nooit laten crashen
            print(f"  Telegram-melding mislukt: {e}")
            return False
        if key:
            self.db.set(f"tg_sent_{key}", True)
        return True


def split(text: str, limit: int = 3900) -> list[str]:
    """Telegram aanvaardt max 4096 tekens: splits op regels (nooit midden in een HTML-tag)."""
    parts, cur = [], ""
    for line in text.split("\n"):
        line = line[:limit]
        if cur and len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    return parts + ([cur] if cur else [])


def esc(s) -> str:
    return html.escape(str(s), quote=False)
