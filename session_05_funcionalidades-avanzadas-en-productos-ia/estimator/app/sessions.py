"""Session state: conversational history and distilled project metadata.

Design notes
------------
- ``ConversationHistory`` is the raw array of messages that travels to the LLM
  API on each call.  It implements a sliding window: when the number of
  (user, assistant) pairs exceeds ``MAX_TURNS``, the oldest pair is dropped.
  The system prompt is never stored here — it is reconstructed on every call
  from the current ``ProjectMetadata``, so it always reflects the latest facts.

- ``ProjectMetadata`` is the set of distilled facts the system has learned about
  the project across turns.  It survives history truncation because it lives in
  a separate structure.  Fields are accumulated (lists) or overwritten (scalars)
  by the LLM extractor after each turn.

- ``SessionStore`` keeps sessions in a plain dict (in-memory, process-local).
  This is intentionally volatile: a service restart loses all sessions.  The
  trade-off is accepted here because the system is not yet connected to a
  persistent backend.  Persistence (SQL / Redis) will be added in a later
  session once the conversational contract is stable.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ProjectMetadata — distilled facts that survive history truncation
# ---------------------------------------------------------------------------


class ProjectMetadata(BaseModel):
    """Distilled facts about the project under estimation.

    Survives history truncation.  Scalars are overwritten when the LLM
    extractor returns a non-None value; lists are accumulated (merged, not
    replaced) so facts from earlier turns are never lost.
    """

    project_name: str | None = None
    assumed_team_size: int | None = None
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str | None = None
    explicit_constraints: list[str] = Field(default_factory=list)
    rejected_options: list[str] = Field(default_factory=list)

    def merge(self, update: "ProjectMetadata") -> "ProjectMetadata":
        """Return a new ProjectMetadata with values from *update* merged in.

        Scalars (project_name, assumed_team_size, agreed_scope) are
        overwritten only when the update provides a non-None value.  Lists
        are merged (union, preserving insertion order, deduplicating by
        lowercased value).
        """

        def _merge_list(existing: list[str], new: list[str]) -> list[str]:
            seen = {v.lower() for v in existing}
            result = list(existing)
            for item in new:
                if item.lower() not in seen:
                    seen.add(item.lower())
                    result.append(item)
            return result

        return ProjectMetadata(
            project_name=update.project_name or self.project_name,
            assumed_team_size=update.assumed_team_size or self.assumed_team_size,
            mentioned_technologies=_merge_list(
                self.mentioned_technologies, update.mentioned_technologies
            ),
            agreed_scope=update.agreed_scope or self.agreed_scope,
            explicit_constraints=_merge_list(
                self.explicit_constraints, update.explicit_constraints
            ),
            rejected_options=_merge_list(self.rejected_options, update.rejected_options),
        )

    def is_empty(self) -> bool:
        """Return True when no fact has been populated yet."""
        return (
            self.project_name is None
            and self.assumed_team_size is None
            and not self.mentioned_technologies
            and self.agreed_scope is None
            and not self.explicit_constraints
            and not self.rejected_options
        )


# ---------------------------------------------------------------------------
# ConversationHistory — sliding-window message buffer
# ---------------------------------------------------------------------------

Message = dict[str, str]  # {"role": "user"|"assistant", "content": "..."}


class ConversationHistory:
    """Sliding-window buffer of (user, assistant) message pairs.

    ``MAX_TURNS`` is the maximum number of *pairs* retained.  When a new pair
    would push the count above the limit, the oldest pair is dropped first.

    The system prompt is never stored here; it is passed separately to the API
    on every call so it always reflects the current ``ProjectMetadata``.
    """

    def __init__(self, max_turns: int = 6) -> None:
        self.max_turns = max_turns
        self._pairs: list[tuple[Message, Message]] = []  # [(user_msg, assistant_msg), ...]

    def append(self, user_content: str, assistant_content: str) -> None:
        """Add a new (user, assistant) pair, evicting the oldest if necessary."""
        if len(self._pairs) >= self.max_turns:
            self._pairs.pop(0)
        self._pairs.append(
            (
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            )
        )

    def to_messages_list(self) -> list[Message]:
        """Return the flat message array ready to pass as ``messages`` to the API."""
        messages: list[Message] = []
        for user_msg, assistant_msg in self._pairs:
            messages.append(user_msg)
            messages.append(assistant_msg)
        return messages

    @property
    def turn_count(self) -> int:
        """Number of (user, assistant) pairs currently stored."""
        return len(self._pairs)


# ---------------------------------------------------------------------------
# Session — top-level container
# ---------------------------------------------------------------------------


class Session:
    """Container for one user session: history + distilled metadata."""

    def __init__(self, session_id: str, max_turns: int = 6) -> None:
        self.session_id = session_id
        self.history = ConversationHistory(max_turns=max_turns)
        self.project_metadata = ProjectMetadata()


# ---------------------------------------------------------------------------
# SessionStore — in-memory registry
# ---------------------------------------------------------------------------


class SessionStore:
    """In-memory registry of active sessions.

    Volatile by design (see module docstring).  Thread-safety is not required
    here because FastAPI runs sync routes in a thread pool but the store is
    accessed only from request handlers — no concurrent modification of the
    same session is expected at this scale.
    """

    def __init__(self, max_turns: int = 6) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_turns = max_turns

    def create(self) -> Session:
        """Create a new session and return it."""
        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id, max_turns=self._max_turns)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Return the session or None if it does not exist."""
        return self._sessions.get(session_id)

    def reset(self, session_id: str) -> Session | None:
        """Delete and recreate a session under the same ID, returning the new one."""
        if session_id not in self._sessions:
            return None
        session = Session(session_id=session_id, max_turns=self._max_turns)
        self._sessions[session_id] = session
        return session
