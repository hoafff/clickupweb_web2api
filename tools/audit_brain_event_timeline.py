#!/usr/bin/env python3
"""Third-pass metadata-only timing/shape audit of a PRIVATE Brain WS trace.

No HTTP requests, browser access, or extraction of raw chat content.
Return ONLY fixed-key aggregate integers and a constant interpretation.
Event names, account/conversation IDs, timestamps, prompts and credentials
must NEVER be emitted, logged, serialized or included in exception output.

Crucial: chatCommentEdited carries no ai_result_id in the observed dataset.
Temporal proximity to a reply does NOT prove the edit concerns that reply or
that it indicates end-of-generation. This is research, not a completion gate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from tools.audit_brain_completion_metadata import iter_local_jsonl
from tools.audit_brain_completion_deep import _changes, _safe_id

# Fixed schema prevents untrusted event-name/payload contents from escaping.
FIELDS = (
    "inbound_event_frames",
    "ai_start_events",
    "ai_reply_created_events",
    "chat_comment_edited_events",
    "edited_with_payload_dict",
    "edited_with_version_data_dict",
    "edited_with_changes_array",
    "edited_with_nonempty_changes",
    "edited_with_top_level_status_key",
    "edited_with_payload_status_key",
    "edited_while_any_ai_start_pending",
    "edited_before_first_ai_reply",
    "edited_after_prior_ai_reply",
    "edited_with_valid_timestamp",
    "edited_within_2s_after_prior_ai_reply",
    "edited_2_to_10s_after_prior_ai_reply",
    "edited_10_to_30s_after_prior_ai_reply",
    "edited_more_than_30s_after_prior_ai_reply",
    "edited_without_comparable_prior_ai_reply_timestamp",
    "other_chat_events",
    "other_chat_typing_hint",
    "other_chat_conversation_hint",
    "other_chat_comment_hint",
    "other_chat_status_or_state_hint",
    "other_chat_other_hint",
    "matched_ai_start_reply_timestamps",
    "matched_ai_latency_under_1s",
    "matched_ai_latency_1_to_5s",
    "matched_ai_latency_5_to_30s",
    "matched_ai_latency_over_30s",
    "matched_ai_negative_or_unordered_timestamps",
    "ai_created_without_matching_start_timestamp",
)


def _utc_time(raw) -> datetime | None:
    if not isinstance(raw, str) or len(raw) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, OverflowError, ValueError):
        return None


def _event(record) -> dict | None:
    if not isinstance(record, dict) or record.get("kind") != "ws_frame_content":
        return None
    if record.get("direction") == "sent":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    return event if isinstance(event, dict) else None


def _chat_group(name: str) -> str:
    """Mutually exclusive buckets; tests must never print name itself."""
    lower = name.lower()
    if "typing" in lower or "stream" in lower:
        return "other_chat_typing_hint"
    if "conversation" in lower:
        return "other_chat_conversation_hint"
    if "comment" in lower:
        return "other_chat_comment_hint"
    if "status" in lower or "state" in lower:
        return "other_chat_status_or_state_hint"
    return "other_chat_other_hint"


def audit_timeline(records) -> dict[str, int | str]:
    count = Counter({key: 0 for key in FIELDS})
    started: dict[str, datetime | None] = {}
    pending: set[str] = set()
    have_ai_reply = False
    latest_ai_reply_time: datetime | None = None

    for record in records:
        event = _event(record)
        if event is None:
            continue
        count["inbound_event_frames"] += 1
        timestamp = _utc_time(record.get("timestamp_utc"))
        name = event.get("name")
        if name == "aiConversationStarted":
            count["ai_start_events"] += 1
            payload = event.get("payload")
            rid = _safe_id(payload.get("ai_result_id")) if isinstance(payload, dict) else None
            if rid is not None:
                if rid not in started:
                    started[rid] = timestamp
                    pending.add(rid)
        elif name == "chatCommentCreated":
            rid = _safe_id(_changes(event).get("ai_result_id"))
            if rid is not None:
                count["ai_reply_created_events"] += 1
                have_ai_reply = True
                latest_ai_reply_time = timestamp
                if rid in started:
                    pending.discard(rid)
                start_timestamp = started.get(rid)
                if start_timestamp is not None and timestamp is not None:
                    count["matched_ai_start_reply_timestamps"] += 1
                    delta = (timestamp - start_timestamp).total_seconds()
                    if delta < 0:
                        count["matched_ai_negative_or_unordered_timestamps"] += 1
                    elif delta < 1:
                        count["matched_ai_latency_under_1s"] += 1
                    elif delta < 5:
                        count["matched_ai_latency_1_to_5s"] += 1
                    elif delta <= 30:
                        count["matched_ai_latency_5_to_30s"] += 1
                    else:
                        count["matched_ai_latency_over_30s"] += 1
                else:
                    count["ai_created_without_matching_start_timestamp"] += 1
        elif name == "chatCommentEdited":
            count["chat_comment_edited_events"] += 1
            payload = event.get("payload")
            if isinstance(payload, dict):
                count["edited_with_payload_dict"] += 1
                if "status" in payload:
                    count["edited_with_payload_status_key"] += 1
            if "status" in event:
                count["edited_with_top_level_status_key"] += 1
            version = event.get("version_event_data")
            if isinstance(version, dict):
                count["edited_with_version_data_dict"] += 1
                changes = version.get("changes")
                if isinstance(changes, list):
                    count["edited_with_changes_array"] += 1
                    if changes:
                        count["edited_with_nonempty_changes"] += 1
            if pending:
                count["edited_while_any_ai_start_pending"] += 1
            if not have_ai_reply:
                count["edited_before_first_ai_reply"] += 1
            else:
                count["edited_after_prior_ai_reply"] += 1
            if timestamp is not None:
                count["edited_with_valid_timestamp"] += 1
            if timestamp is None or latest_ai_reply_time is None:
                count["edited_without_comparable_prior_ai_reply_timestamp"] += 1
            else:
                delta = (timestamp - latest_ai_reply_time).total_seconds()
                if delta < 0:
                    count["edited_without_comparable_prior_ai_reply_timestamp"] += 1
                elif delta <= 2:
                    count["edited_within_2s_after_prior_ai_reply"] += 1
                elif delta <= 10:
                    count["edited_2_to_10s_after_prior_ai_reply"] += 1
                elif delta <= 30:
                    count["edited_10_to_30s_after_prior_ai_reply"] += 1
                else:
                    count["edited_more_than_30s_after_prior_ai_reply"] += 1
        elif isinstance(name, str) and name.startswith("chat"):
            count["other_chat_events"] += 1
            count[_chat_group(name)] += 1

    return {
        **{key: count[key] for key in FIELDS},
        "interpretation": (
            "Observational, metadata-only and NOT a verified generation "
            "completion protocol. Edited events without correlated AI result "
            "IDs cannot be attributed to a particular reply, regardless of "
            "their timestamp proximity. No raw event names or IDs are exported."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "private_trace", type=Path,
        help="Local authorized JSONL only; do NOT upload or share source trace.",
    )
    args = parser.parse_args(argv)
    try:
        summary = audit_timeline(iter_local_jsonl(args.private_trace))
    except (OSError, ValueError, UnicodeError):
        print("Unable to analyze the local private trace.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
