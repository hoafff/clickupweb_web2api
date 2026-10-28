#!/usr/bin/env python3
"""Offline metadata-only audit for possible Brain generation-completion signals.

Reads an AUTHORIZED PRIVATE JSONL WS trace from the researcher's local machine.
Does not connect to ClickUp, submit messages or print raw frames/content/IDs.
All output keys are hardcoded; output values are aggregate integer counts.

This tool finds POSSIBLE terminal markers. They are NOT a verified end-of-
generation protocol. See docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

MAX_BYTES = 50 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
KNOWN_EVENT_NAMES = frozenset({
    "aiConversationStarted",
    "chatCommentCreated",
    "chatCommentUpdated",
    "aiConversationCompleted",
    "aiConversationFinished",
    "aiResponseCompleted",
    "aiResponseFinished",
    "aiResultCompleted",
    "aiResultFinished",
    "aiGenerationCompleted",
    "aiGenerationFinished",
    "aiStreamCompleted",
})
TERMINAL_CANDIDATE_NAMES = frozenset({
    "aiConversationCompleted",
    "aiConversationFinished",
    "aiResponseCompleted",
    "aiResponseFinished",
    "aiResultCompleted",
    "aiResultFinished",
    "aiGenerationCompleted",
    "aiGenerationFinished",
    "aiStreamCompleted",
})
TERMINAL_STATUS_VALUES = frozenset({
    "completed", "complete", "finished", "done", "stopped",
})
# Use only these static keys in emitted JSON; never user-controlled names/values.
COUNT_KEYS = (
    "jsonl_records",
    "inbound_websocket_frames",
    "malformed_jsonl_records",
    "oversize_line_records",
    "non_event_frames",
    "ai_conversation_started",
    "chat_comment_created",
    "chat_comment_updated",
    "terminal_event_name_candidates",
    "terminal_status_value_candidates",
    "other_event_frames",
)


def audit_records(records) -> dict[str, int | str]:
    counts = Counter({k: 0 for k in COUNT_KEYS})
    for record in records:
        counts["jsonl_records"] += 1
        if record is None:
            counts["malformed_jsonl_records"] += 1
            continue
        if record is False:
            counts["oversize_line_records"] += 1
            continue
        if not isinstance(record, dict):
            counts["non_event_frames"] += 1
            continue
        if record.get("kind") != "ws_frame_content" or record.get("direction") == "sent":
            continue
        counts["inbound_websocket_frames"] += 1
        data = record.get("payload")
        event = data.get("data", {}).get("event") if isinstance(data, dict) and isinstance(data.get("data"), dict) else None
        if not isinstance(event, dict):
            counts["non_event_frames"] += 1
            continue
        name = event.get("name")
        # Name is untrusted: compare ONLY to hardcoded constants. Never print
        # an unknown name or the raw event's values.
        if name == "aiConversationStarted":
            counts["ai_conversation_started"] += 1
        elif name == "chatCommentCreated":
            counts["chat_comment_created"] += 1
        elif name == "chatCommentUpdated":
            counts["chat_comment_updated"] += 1
        elif name in TERMINAL_CANDIDATE_NAMES:
            counts["terminal_event_name_candidates"] += 1
        else:
            counts["other_event_frames"] += 1
        if isinstance(name, str) and name.startswith("ai"):
            payload = event.get("payload")
            if isinstance(payload, dict):
                status = payload.get("status")
                if isinstance(status, str) and status.lower() in TERMINAL_STATUS_VALUES:
                    counts["terminal_status_value_candidates"] += 1
    return {
        **{k: counts[k] for k in COUNT_KEYS},
        "interpretation": (
            "Possible completion indicators only; no matched final-generation "
            "signal is established by these counts. Unknown events are not "
            "printed. A zero count does not prove completion is absent."
        ),
    }


def iter_local_jsonl(path: Path):
    with path.open("rb") as file:
        amount = 0
        for raw in file:
            amount += len(raw)
            if amount > MAX_BYTES:
                raise ValueError("Private trace exceeds the local size limit.")
            if len(raw) > MAX_LINE_BYTES:
                yield False
                continue
            try:
                yield json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                yield None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "private_trace", type=Path,
        help="Local private WS JSONL trace (NEVER upload this to GitHub/chat)",
    )
    args = parser.parse_args(argv)
    try:
        report = audit_records(iter_local_jsonl(args.private_trace))
    except (OSError, ValueError):
        print("Cannot audit local private trace; check its path and file size.", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
