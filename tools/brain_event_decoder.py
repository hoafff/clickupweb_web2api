#!/usr/bin/env python3
"""Decode ClickUp Brain WebSocket chat events in an authorized *local* trace.

Observed schema (28 Oct 2026):
- event.name == aiConversationStarted -> event.payload.ai_result_id/conversation_id
- event.name == chatCommentCreated -> event.version_event_data.changes[]
  with fields comment (JSON string of rich-text blocks) and sometimes ai_result_id.
- chatCommentEdited was observed without changes in the provided trace.

Default CLI exports only counts, lengths and timings: never prompts, answer text
or session/conversation IDs. --export-replies explicitly creates a PRIVATE file
under artifacts/ for local investigation; never commit or share raw payloads.

This decoder reads an offline trace; it is not an authenticated ClickUp client.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import statistics
from typing import Any


@dataclass(frozen=True)
class BrainReply:
    ai_result_id: str
    conversation_id: str | None
    text: str
    started_utc: str | None
    created_utc: str
    elapsed_seconds: float | None


def _event(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("kind") != "ws_frame_content":
        return None
    data = record.get("payload", {}).get("data")
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    return event if isinstance(event, dict) else None


def _changed_fields(event: dict[str, Any]) -> dict[str, Any]:
    detail = event.get("version_event_data")
    if not isinstance(detail, dict):
        return {}
    changes = detail.get("changes", [])
    if not isinstance(changes, list):
        return {}
    return {
        change["field"]: change.get("after")
        for change in changes
        if isinstance(change, dict) and isinstance(change.get("field"), str)
    }


def parse_rich_text(raw: Any) -> str | None:
    """Decode rich-text JSON as plain text, never execute/render HTML.

    Return None for invalid input; empty text is valid and distinct from None.
    """
    if not isinstance(raw, str) or len(raw) > 4_000_000:
        return None
    try:
        blocks = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(blocks, list) or len(blocks) > 10_000:
        return None
    chunks: list[str] = []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            return None
        chunks.append(block["text"])
    return "".join(chunks)


def _timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def reconstruct(records: list[dict[str, Any]]) -> tuple[list[BrainReply], dict[str, Any]]:
    """Correlate AI starts and AI reply comment creation by opaque IDs in memory.

    The returned BrainReply objects contain potentially sensitive data; the
    default report exposes only numerical aggregates.
    """
    starts: dict[str, tuple[str, str | None]] = {}
    reply_events: list[tuple[str, str | None, str, str]] = []
    user_comments = 0
    ai_comments = 0
    edited_count = 0

    for record in records:
        event = _event(record)
        if event is None:
            continue
        name = event.get("name")
        if name == "aiConversationStarted":
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            aid = payload.get("ai_result_id")
            if isinstance(aid, str) and aid:
                cid = payload.get("conversation_id")
                starts[aid] = (
                    str(record.get("timestamp_utc", "")),
                    cid if isinstance(cid, str) else None,
                )
        elif name == "chatCommentCreated":
            fields = _changed_fields(event)
            text = parse_rich_text(fields.get("comment"))
            if text is None:
                continue
            aid = fields.get("ai_result_id")
            if isinstance(aid, str) and aid:
                ai_comments += 1
                cid = fields.get("conversation_id")
                reply_events.append((
                    aid, cid if isinstance(cid, str) else None,
                    text, str(record.get("timestamp_utc", "")),
                ))
            else:
                user_comments += 1
        elif name == "chatCommentEdited":
            edited_count += 1

    replies: list[BrainReply] = []
    matched_count = 0
    conversation_mismatches = 0
    for aid, cid, text, created in reply_events:
        start, started_cid = starts.get(aid, (None, None))
        elapsed = None
        if start is not None:
            matched_count += 1
            t0, t1 = _timestamp(start), _timestamp(created)
            if t0 is not None and t1 is not None:
                elapsed = round((t1 - t0).total_seconds(), 3)
            if started_cid is not None and cid != started_cid:
                conversation_mismatches += 1
        replies.append(BrainReply(
            ai_result_id=aid, conversation_id=cid, text=text,
            started_utc=start, created_utc=created, elapsed_seconds=elapsed,
        ))

    durations = [r.elapsed_seconds for r in replies if r.elapsed_seconds is not None]
    report = {
        "ai_started_count": len(starts),
        "ai_reply_created_count": ai_comments,
        "user_comment_created_count": user_comments,
        "ai_reply_matched_count": matched_count,
        "conversation_mismatch_count": conversation_mismatches,
        "chat_comment_edited_events": edited_count,
        "reply_text_lengths": [len(r.text) for r in replies],
        "start_to_created_seconds": [r.elapsed_seconds for r in replies],
        "latency_min_seconds": min(durations) if durations else None,
        "latency_median_seconds": round(statistics.median(durations), 3) if durations else None,
        "latency_max_seconds": max(durations) if durations else None,
        "note": (
            "Times are intervals between observed WS events, NOT total generation "
            "duration. chatCommentCreated may contain a finished message, but "
            "streaming deltas/completion protocol have not been established."
        ),
    }
    return replies, report


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise ValueError(f"JSONL line {number} is not an object")
            records.append(parsed)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_capture", type=Path)
    parser.add_argument("--json", action="store_true", help="Print safe statistical report")
    parser.add_argument(
        "--export-replies", type=Path, default=None,
        help="Explicitly save recovered reply text to PRIVATE local artifacts",
    )
    args = parser.parse_args()
    try:
        replies, report = reconstruct(load_jsonl(args.private_capture))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    if args.export_replies is not None:
        destination = args.export_replies.resolve()
        # Avoid accidental source code publication.
        if "artifacts" not in destination.parts:
            parser.error("Reply output must be within a private artifacts/ directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Do not include opaque IDs; source capture remains the authority.
        output = [{"created_utc": r.created_utc, "text": r.text} for r in replies]
        destination.write_text(json.dumps(output, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"PRIVATE reply text written locally: {destination}")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for k, v in report.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
