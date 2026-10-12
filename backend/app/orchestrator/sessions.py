"""Conversation memory: recent turns and the shared founder profile.

Kept in memory and mirrored to data/sessions/<id>.json so a restart keeps
the profile. n8n passes the same session_id (e.g. the Telegram chat id) on
every message from the same founder.
"""

import json
import re
import threading
import uuid

from app.config import settings
from app.schemas.agents import FounderProfile, Turn

MAX_TURNS = 12


class Session:
    def __init__(self, session_id: str, history: list[Turn] | None = None, profile: FounderProfile | None = None) -> None:
        self.session_id = session_id
        self.history = history or []
        self.profile = profile or FounderProfile()

    def add(self, role: str, content: str) -> None:
        self.history.append(Turn(role=role, content=content))
        self.history = self.history[-MAX_TURNS:]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._dir = settings.data_dir / "sessions"

    def _path(self, session_id: str):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80]
        return self._dir / f"{safe}.json"

    def get(self, session_id: str | None) -> Session:
        session_id = session_id or uuid.uuid4().hex
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            path = self._path(session_id)
            session = Session(session_id)
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    session = Session(
                        session_id,
                        [Turn.model_validate(t) for t in data.get("history", [])],
                        FounderProfile.model_validate(data.get("profile", {})),
                    )
                except (OSError, ValueError):
                    pass
            self._sessions[session_id] = session
            return session

    def save(self, session: Session) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "history": [t.model_dump() for t in session.history],
            "profile": session.profile.model_dump(),
        }
        self._path(session.session_id).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


store = SessionStore()
