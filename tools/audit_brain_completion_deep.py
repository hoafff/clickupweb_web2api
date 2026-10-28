#!/usr/bin/env python3
"""Offline, privacy-safe second-pass analysis of authorized Brain WS JSONL.

Only emits fixed-key integer counters and a static caveat. It NEVER prints
observed event names, payload values, opaque IDs, reply content, URL or path.
No network/browser use; keep the original trace on your PRIVATE local disk.

Why this exists: the first audit called 152 frames "other" and checked
chatCommentUpdated, but an earlier authorized trace contained
chatCommentEdited. This script distinguishes the event families and
AI-correlated comment creations without confusing comment creation with
verified end-of-generation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    _repo = Path(__file__).resolve().parents[1]
    if str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))

from tools.audit_brain_completion_metadata import (
    iter_local_jsonl,
    TERMINAL_CANDIDATE_NAMES,
    TERMINAL_STATUS_VALUES,
)

# Every emitted key below is hardcoded. All values are numeric, except one
# constant interpretation string. Never print actual event.name strings.
KEYS = (
    "jsonl_records",
    "websocket_inbound_frames",
    "invalid_jsonl_records",
    "oversize_line_records",
    "non_event_inbound_frames",
    "ai_conversation_started_events",
    "chat_comment_created_events",
    "chat_comment_edited_events",
    "chat_comment_updated_events",
    "comment_created_with_ai_result_id",
    "comment_created_without_ai_result_id",
    "comment_edited_with_ai_result_id",
    "comment_edited_with_comment_change",
    "unique_ai_started_ids",
    "unique_ai_created_comment_ids",
    "matching_start_created_id_pairs",
    "created_ai_ids_not_in_starts",
    "started_ai_ids_without_created",
    "known_terminal_named_events",
    "unknown_named_events_with_terminal_hint",
    "terminal_status_in_event_or_payload",
    "terminal_status_in_version_changes",
    "other_ai_prefixed_events",
    "other_chat_prefixed_events",
    "other_comment_prefixed_events",
    "other_message_prefixed_events",
    "other_stream_prefixed_events",
    "other_response_or_generation_prefixed_events",
    "other_uncategorized_events",
)

TERMINAL_HINTS = ("complet", "finish", "end", "stop", "cancel", "terminat")
STATUS_FIELDS = frozenset({"status", "generation_status", "ai_status", "stream_status"})


def _safe_id(value) -> str | None:
    # Never return any ID to a user; IDs are only kept in private sets.
    if isinstance(value, str) and 0 < len(value) <= 256:
        return value
    return None


def _changes(event: dict) -> dict:
    details = event.get("version_event_data")
    if not isinstance(details, dict):
        return {}
    raw = details.get("changes")
    if not isinstance(raw, list):
        return {}
    # Explicit fixed fields only, never dynamic arbitrary keys in output.
    result = {}
    for row in raw[:512]:
        if not isinstance(row, dict):
            continue
        field = row.get("field")
        if field == "ai_result_id" or field == "comment" or field in STATUS_FIELDS:
            result[field] = row.get("after")
    return result


def _terminal_status(value) -> bool:
    return isinstance(value, str) and value.lower() in TERMINAL_STATUS_VALUES


def _other_group(name) -> str:
    if not isinstance(name, str):
        return "other_uncategorized_events"
    n = name.lower()
    if n.startswith("ai"):
        return "other_ai_prefixed_events"
    if n.startswith("chat"):
        return "other_chat_prefixed_events"
    if n.startswith("comment"):
        return "other_comment_prefixed_events"
    if n.startswith("message"):
        return "other_message_prefixed_events"
    if n.startswith("stream"):
        return "other_stream_prefixed_events"
    if n.startswith(("response", "generation")):
        return "other_response_or_generation_prefixed_events"
    return "other_uncategorized_events"


def audit_deep(records) -> dict[str, int | str]:
    counts = Counter({key: 0 for key in KEYS})
    started: set[str] = set()
    created: set[str] = set()

    for record in records:
        counts["jsonl_records"] += 1
        if record is None:
            counts["invalid_jsonl_records"] += 1
            continue
        if record is False:
            counts["oversize_line_records"] += 1
            continue
        if not isinstance(record, dict):
            continue
        if record.get("kind") != "ws_frame_content" or record.get("direction") == "sent":
            continue

        counts["websocket_inbound_frames"] += 1
        payload = record.get("payload")
        data = payload.get("data") if isinstance(payload, dict) else None
        event = data.get("event") if isinstance(data, dict) else None
        if not isinstance(event, dict):
            counts["non_event_inbound_frames"] += 1
            continue

        name = event.get("name")
        changes = _changes(event)
        event_payload = event.get("payload")
        event_payload = event_payload if isinstance(event_payload, dict) else {}
        if name == "aiConversationStarted":
            counts["ai_conversation_started_events"] += 1
            rid = _safe_id(event_payload.get("ai_result_id"))
            if rid is not None:
                started.add(rid)
        elif name == "chatCommentCreated":
            counts["chat_comment_created_events"] += 1
            rid = _safe_id(changes.get("ai_result_id"))
            if rid is not None:
                counts["comment_created_with_ai_result_id"] += 1
                created.add(rid)
            else:
                counts["comment_created_without_ai_result_id"] += 1
        elif name == "chatCommentEdited":
            counts["chat_comment_edited_events"] += 1
            if _safe_id(changes.get("ai_result_id")) is not None:
                counts["comment_edited_with_ai_result_id"] += 1
            if "comment" in changes:
                counts["comment_edited_with_comment_change"] += 1
        elif name == "chatCommentUpdated":
            counts["chat_comment_updated_events"] += 1
        elif isinstance(name, str) and name in TERMINAL_CANDIDATE_NAMES:
            counts["known_terminal_named_events"] += 1
        else:
            counts[_other_group(name)] += 1
            # This is a pattern hint, not a known signal. Never print name.
            if (
                isinstance(name, str)
                and len(name) <= 128
                and any(word in name.lower() for word in TERMINAL_HINTS)
            ):
                counts["unknown_named_events_with_terminal_hint"] += 1

        if _terminal_status(event.get("status")) or _terminal_status(
            event_payload.get("status")
        ):
            counts["terminal_status_in_event_or_payload"] += 1
        if any(
            _terminal_status(value) for field, value in changes.items()
            if field in STATUS_FIELDS
        ):
            counts["terminal_status_in_version_changes"] += 1

    counts["unique_ai_started_ids"] = len(started)
    counts["unique_ai_created_comment_ids"] = len(created)
    counts["matching_start_created_id_pairs"] = len(started & created)
    counts["created_ai_ids_not_in_starts"] = len(created - started)
    counts["started_ai_ids_without_created"] = len(started - created)
    return {
        **{key: counts[key] for key in KEYS},
        "interpretation": (
            "Metadata-only candidate counts, NOT a verified end-of-generation "
            "signal. A comment-created event is not a final model event. "
            "An absent candidate may be outside this capture or use an unknown shape."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "private_trace", type=Path,
        help="Existing local private WS JSONL; NEVER upload or publish the trace.",
    )
    args = parser.parse_args(argv)
    try:
        report = audit_deep(iter_local_jsonl(args.private_trace))
    except (OSError, ValueError, UnicodeError):
        print(
            "Cannot inspect private local trace; check file path and size.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
