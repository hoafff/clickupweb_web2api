#!/usr/bin/env python3
"""Analyze ClickUp Brain research markers without emitting prompts, IDs or secrets.

Reads LOCAL metadata and opt-in private JSONL captures. Produces aggregate
observations only: phase index, event counts, HTTP outcomes, and known model /
effort telemetry values. The source capture is never written to GitHub.

Usage:
  python tools/analyze_brain_trace.py artifacts/brain_v3_meta.jsonl artifacts/brain_v3_private_content.jsonl
  python tools/analyze_brain_trace.py ... --json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

VALID_LABEL = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
KNOWN_EFFORTS = {"auto", "low", "medium", "high", "extra_high"}
KNOWN_MODELS = {"brain", "claude-opus-5-5", "claude-opus-5",
                "gemini-4-argon", "gpt-6.1-sol", "gpt-6.1-terra"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open(encoding="utf-8-sig") as fp:
        for lineno, line in enumerate(fp, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}, line {lineno}: invalid JSON") from exc
            if not isinstance(event, dict) or "kind" not in event:
                raise ValueError(f"{path.name}, line {lineno}: expected event object")
            events.append(event)
    return events


def utc_timestamp(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(event["timestamp_utc"]))


def ordered_phases(meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases = [{"index": 0, "label": "unmarked", "timestamp_utc": None}]
    for event in meta:
        if event.get("kind") != "manual_marker":
            continue
        label = str(event.get("label", ""))
        label = label if VALID_LABEL.fullmatch(label) else "invalid_marker"
        phases.append({
            "index": len(phases),
            "label": label,
            "timestamp_utc": str(event["timestamp_utc"]),
        })
    return phases


def assign_phase(event: dict[str, Any], phases: list[dict[str, Any]]) -> int:
    event_time = utc_timestamp(event)
    index = 0
    for phase in phases[1:]:
        if event_time >= datetime.fromisoformat(str(phase["timestamp_utc"])):
            index = int(phase["index"])
        else:
            break
    return index


def chat_command(url: str) -> str | None:
    if "/comment-service/" not in url:
        return None
    if "/comments/view/" in url:
        return "new_chat_command"
    if "/comments/comment/" in url:
        return "continue_chat_command"
    return None


def _ws_event_name(record: dict[str, Any]) -> str | None:
    if record.get("kind") != "ws_frame_content":
        return None
    data = record.get("payload", {}).get("data")
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    name = event.get("name") if isinstance(event, dict) else None
    return name if name in {
        "aiConversationStarted", "chatCommentCreated", "chatCommentEdited",
        "chatLastReadAtUpdated", "notification", "badgeCountUpdated",
    } else None


def _telemetry(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("kind") != "http_request_content":
        return None
    if not str(record.get("url", "")).endswith("/v1/t"):
        return None
    body = record.get("payload", {}).get("data")
    if not isinstance(body, dict):
        return None
    props = body.get("properties")
    if not isinstance(props, dict):
        return None
    event_type = body.get("event")
    if event_type not in {"use open ai feature", "click ai modal item",
                          "trigger manual ai use", "interact with manual ai modal"}:
        return None
    model = props.get("aiModel")
    effort = props.get("reasoningLevel")
    return {
        "event": event_type,
        "model": model if model in KNOWN_MODELS else None,
        "effort": effort if effort in KNOWN_EFFORTS else None,
    }


def summarize(
    meta: list[dict[str, Any]],
    content: list[dict[str, Any]],
) -> dict[str, Any]:
    phases = ordered_phases(meta)
    http_status = {
        str(e.get("request_id")): int(e["status"])
        for e in meta
        if e.get("kind") == "http_response" and isinstance(e.get("status"), int)
    }
    http_outcomes = {
        str(e.get("request_id")): e.get("kind")
        for e in meta
        if e.get("kind") in {"http_finished", "http_failed"}
    }
    summaries: list[dict[str, Any]] = []
    for phase in phases:
        summaries.append({
            "index": phase["index"], "marker": phase["label"],
            "timestamp_utc": phase["timestamp_utc"],
            "chat_commands": [],
            "ws_events": {},
            "generation_telemetry": [],
            "selection_telemetry": [],
        })

    ws_counts: dict[int, Counter] = defaultdict(Counter)
    # Opaque IDs are used ONLY for in-memory event correlation, not returned.
    started_by_result: dict[str, int] = {}
    comment_created: list[tuple[str, int]] = []
    for record in content:
        try:
            i = assign_phase(record, phases)
        except (ValueError, KeyError):
            continue
        kind = record.get("kind")
        if kind == "http_request_content":
            command = chat_command(str(record.get("url", "")))
            if command is not None:
                rid = str(record.get("request_id"))
                summaries[i]["chat_commands"].append({
                    "command": command, "http_status": http_status.get(rid),
                    "request_outcome": http_outcomes.get(rid, "unknown"),
                })
        name = _ws_event_name(record)
        if name is not None:
            ws_counts[i][name] += 1
            data = record.get("payload", {}).get("data", {})
            evt = data.get("event", {}) if isinstance(data, dict) else {}
            if isinstance(evt, dict) and name == "aiConversationStarted":
                raw = evt.get("payload", {})
                result_id = raw.get("ai_result_id") if isinstance(raw, dict) else None
                if isinstance(result_id, (str, int)) and str(result_id):
                    started_by_result[str(result_id)] = i
            elif isinstance(evt, dict) and name == "chatCommentCreated":
                version_data = evt.get("version_event_data", {})
                changes = version_data.get("changes", []) if isinstance(version_data, dict) else []
                if isinstance(changes, list):
                    for item in changes:
                        if isinstance(item, dict) and item.get("field") == "ai_result_id":
                            result_id = item.get("after")
                            if isinstance(result_id, (str, int)) and str(result_id):
                                comment_created.append((str(result_id), i))

        telem = _telemetry(record)
        if telem is not None:
            target = ("generation_telemetry"
                      if telem["event"] == "use open ai feature"
                      else "selection_telemetry")
            if telem["model"] is not None or telem["effort"] is not None:
                summaries[i][target].append(telem)

    for i, counts in ws_counts.items():
        summaries[i]["ws_events"] = dict(counts)

    across_marker = []
    matched = 0
    matched_pairs = set()
    for result_id, emitted_phase in comment_created:
        started_phase = started_by_result.get(result_id)
        if started_phase is None:
            continue
        pair = (started_phase, emitted_phase)
        if (result_id, emitted_phase) in matched_pairs:
            continue
        matched_pairs.add((result_id, emitted_phase))
        matched += 1
        if started_phase != emitted_phase:
            across_marker.append({
                "started_phase": started_phase,
                "event_phase": emitted_phase,
                "event": "chatCommentCreated",
            })

    return {
        "matched_ai_start_to_comment_created": matched,
        "cross_marker_correlations": across_marker,
        "meta_event_count": len(meta),
        "private_event_count": len(content),
        "phase_count_excluding_unmarked": len(phases) - 1,
        "note": "Telemetry reflects frontend observations, not confirmed upstream model execution.",
        "phases": summaries,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("metadata", type=Path)
    p.add_argument("private_content", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    try:
        report = summarize(load_jsonl(args.metadata), load_jsonl(args.private_content))
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"Events: {report['meta_event_count']}; "
          f"private records: {report['private_event_count']}; "
          f"markers: {report['phase_count_excluding_unmarked']}")
    for item in report["cross_marker_correlations"]:
        print(f"Cross-marker AI correlation: phase #{item['started_phase']}"
              f" → phase #{item['event_phase']} ({item['event']})")
    for phase in report["phases"][1:]:
        print(f"\n#{phase['index']} {phase['marker']}")
        for cmd in phase["chat_commands"]:
            print(f"  {cmd['command']} → HTTP {cmd['http_status']} ({cmd['request_outcome']})")
        print(f"  AI start events: {phase['ws_events'].get('aiConversationStarted', 0)}")
        if phase["generation_telemetry"]:
            print("  Generation telemetry (not model execution proof):")
            for item in phase["generation_telemetry"]:
                print(f"    model={item['model'] or 'unknown'}, effort={item['effort'] or 'unknown'}")
        else:
            print("  No qualifying generation telemetry in this phase")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
