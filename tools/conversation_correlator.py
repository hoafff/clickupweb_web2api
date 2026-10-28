"""Asynchronous correlation of authorized Brain WebSocket AI start/reply events.

This is an in-memory, per-workspace event correlator. It does NOT send requests
to ClickUp, authenticate, or infer an unobserved token-stream protocol.

A successful result means a chatCommentCreated event was correlated to an
aiConversationStarted event, not that a final generation marker was observed.
Instantiate a separate correlator per authenticated tenant/workspace; never
share one global instance across accounts.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import time
from typing import Any, Callable

from tools.brain_event_decoder import _changed_fields, _event, parse_rich_text


class CorrelationError(RuntimeError):
    """A correlation failed; intentionally excludes opaque identifiers."""


class ConversationMismatchError(CorrelationError):
    pass


class CorrelationExpiredError(CorrelationError):
    pass


class CorrelatorClosedError(CorrelationError):
    pass


@dataclass(frozen=True)
class CorrelatedComment:
    """Contains private message content and identifiers; never log implicitly."""

    ai_result_id: str
    conversation_id: str | None
    text: str
    started_utc: str | None
    created_utc: str


@dataclass
class _Record:
    result_id: str
    touched: float
    conversation_id: str | None = None
    started_utc: str | None = None
    created_utc: str | None = None
    text: str | None = None
    has_start: bool = False
    has_comment: bool = False
    error: CorrelationError | None = None
    waiters: list[asyncio.Future[CorrelatedComment]] = field(default_factory=list)


def _opaque_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        value = str(value)
        if 0 < len(value) <= 256:
            return value
    return None


class ConversationEventCorrelator:
    """Reconciles interleaved and out-of-order WS events by ai_result_id.

    Feed events and await results on the SAME asyncio event loop. No I/O occurs.
    The event cache is TTL/boundary-limited, but eviction/expiry takes place
    on ingest, wait, or explicit prune: there is no background sweeper.
    """

    def __init__(
        self,
        *,
        scope_id: str,
        ttl_seconds: float = 900,
        max_records: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not scope_id.strip():
            raise ValueError("scope_id is required")
        if ttl_seconds <= 0 or max_records <= 0:
            raise ValueError("ttl_seconds and max_records must be positive")
        self.scope_id = scope_id  # Never serialize/log scope IDs.
        self.ttl_seconds = ttl_seconds
        self.max_records = max_records
        self._clock = clock
        self._records: OrderedDict[str, _Record] = OrderedDict()
        self._closed = False
        self._counts: dict[str, int] = {}

    def _count(self, category: str) -> None:
        self._counts[category] = self._counts.get(category, 0) + 1

    def _fail(self, record: _Record, error: CorrelationError) -> None:
        record.error = error
        for waiter in record.waiters:
            if not waiter.done():
                waiter.set_exception(error)
        record.waiters.clear()

    def _get(self, result_id: str) -> _Record:
        record = self._records.get(result_id)
        if record is None:
            while len(self._records) >= self.max_records:
                _, victim = self._records.popitem(last=False)
                self._fail(victim, CorrelationExpiredError("event cache capacity exceeded"))
                self._count("evicted")
            record = _Record(result_id=result_id, touched=self._clock())
            self._records[result_id] = record
        else:
            record.touched = self._clock()
            self._records.move_to_end(result_id)
        return record

    def prune(self) -> int:
        """Expire idle records; no background task. Call periodically in service."""
        now = self._clock()
        expired = [
            key for key, rec in self._records.items()
            if now - rec.touched >= self.ttl_seconds
        ]
        for key in expired:
            rec = self._records.pop(key)
            self._fail(rec, CorrelationExpiredError("event correlation expired"))
            self._count("expired")
        return len(expired)

    @staticmethod
    def _result(record: _Record) -> CorrelatedComment:
        assert record.has_start and record.has_comment
        assert record.text is not None and record.created_utc is not None
        return CorrelatedComment(
            ai_result_id=record.result_id,
            conversation_id=record.conversation_id,
            text=record.text,
            started_utc=record.started_utc,
            created_utc=record.created_utc,
        )

    def _resolve_if_ready(self, record: _Record) -> None:
        if record.error is not None or not (record.has_start and record.has_comment):
            return
        reply = self._result(record)
        for waiter in record.waiters:
            if not waiter.done():
                waiter.set_result(reply)
        record.waiters.clear()
        self._count("matched")

    def _conversation(self, record: _Record, incoming: str | None) -> bool:
        if incoming is None:
            return True
        if record.conversation_id is not None and incoming != record.conversation_id:
            self._fail(record, ConversationMismatchError("conversation ID mismatch"))
            self._count("mismatches")
            return False
        record.conversation_id = incoming
        return True

    def ingest(self, ws_record: dict[str, Any]) -> str:
        """Feed a trace-form WS frame; returns a safe classification, no IDs.

        Only received messages can complete a result. Unknown/user events are
        ignored. Duplicate starts/comments do not overwrite accepted content.
        """
        if self._closed:
            raise CorrelatorClosedError("correlator closed")
        self.prune()
        if ws_record.get("direction") == "sent":
            return "ignored_sent"
        event = _event(ws_record)
        if event is None:
            return "ignored"
        name = event.get("name")
        timestamp = ws_record.get("timestamp_utc")
        timestamp = timestamp if isinstance(timestamp, str) else ""

        if name == "aiConversationStarted":
            payload = event.get("payload")
            if not isinstance(payload, dict):
                return "ignored"
            result_id = _opaque_id(payload.get("ai_result_id"))
            if result_id is None:
                return "ignored"
            record = self._get(result_id)
            if record.error is not None:
                return "error"
            if not self._conversation(record, _opaque_id(payload.get("conversation_id"))):
                return "mismatch"
            if record.has_start:
                return "duplicate_start"
            record.has_start = True
            record.started_utc = timestamp
            self._count("started")
            self._resolve_if_ready(record)
            return "started"

        if name == "chatCommentCreated":
            fields = _changed_fields(event)
            result_id = _opaque_id(fields.get("ai_result_id"))
            if result_id is None:
                return "ignored_user_comment"
            text = parse_rich_text(fields.get("comment"))
            if text is None:
                self._count("invalid_comment")
                return "invalid_comment"
            record = self._get(result_id)
            if record.error is not None:
                return "error"
            if not self._conversation(record, _opaque_id(fields.get("conversation_id"))):
                return "mismatch"
            if record.has_comment:
                if record.text != text:
                    self._fail(record, CorrelationError("conflicting duplicate AI comment"))
                    self._count("conflicts")
                    return "conflict"
                return "duplicate_comment"
            record.has_comment = True
            record.text = text
            record.created_utc = timestamp
            self._count("comments")
            self._resolve_if_ready(record)
            return "reply_created" if record.has_start else "reply_buffered"

        return "ignored"

    async def wait_for_created(
        self,
        ai_result_id: str,
        *,
        conversation_id: str | None = None,
        timeout: float = 60.0,
    ) -> CorrelatedComment:
        """Await a correlated reply-created event (NOT a final stream event).

        Independent concurrent waiters are supported. Timeout or cancellation
        of one waiter does not cancel the others, or discard a late reply.
        """
        if self._closed:
            raise CorrelatorClosedError("correlator closed")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        key = _opaque_id(ai_result_id)
        if key is None:
            raise ValueError("invalid ai_result_id")
        self.prune()
        record = self._get(key)
        if record.error is not None:
            raise record.error
        if not self._conversation(record, _opaque_id(conversation_id)):
            assert record.error is not None
            raise record.error
        if record.has_start and record.has_comment:
            return self._result(record)

        future: asyncio.Future[CorrelatedComment] = asyncio.get_running_loop().create_future()
        record.waiters.append(future)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            if future in record.waiters:
                record.waiters.remove(future)

    def statistics(self) -> dict[str, int]:
        """Only safe integer counters, never prompt, IDs or raw payload."""
        return {**self._counts, "cached_records": len(self._records)}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for record in self._records.values():
            self._fail(record, CorrelatorClosedError("correlator closed"))
        self._records.clear()
