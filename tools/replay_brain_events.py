#!/usr/bin/env python3
"""Replay local ClickUp Brain WS trace through ConversationEventCorrelator.

Only prints numerical counters. No conversation IDs, prompts, answers or tokens.
Works on the PRIVATE JSONL from trace_browser.py, without network access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.brain_event_decoder import load_jsonl
from tools.conversation_correlator import ConversationEventCorrelator


def replay(records: list[dict]) -> dict:
    engine = ConversationEventCorrelator(scope_id="offline-local-replay")
    kinds: dict[str, int] = {}
    try:
        for record in records:
            if record.get("kind") != "ws_frame_content":
                continue
            result = engine.ingest(record)
            kinds[result] = kinds.get(result, 0) + 1
        return {
            "processed_ws_frames": sum(kinds.values()),
            "correlation_counters": engine.statistics(),
            "event_classification": kinds,
            "meaning": (
                "matched = paired aiConversationStarted + chatCommentCreated; "
                "not proof of final stream completion, model execution, or "
                "a standalone upstream API"
            ),
        }
    finally:
        engine.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_capture", type=Path)
    parser.add_argument("--expected", type=int, help="Optional expected number of matched results")
    args = parser.parse_args()
    try:
        records = load_jsonl(args.private_capture)
        report = replay(records)
    except (ValueError, OSError, json.JSONDecodeError) as err:
        parser.error(str(err))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    matched = report["correlation_counters"].get("matched", 0)
    if args.expected is not None and matched != args.expected:
        print(f"Expected {args.expected} matches but got {matched}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
