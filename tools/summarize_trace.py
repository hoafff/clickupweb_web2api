#!/usr/bin/env python3
"""Summarize the redacted JSONL produced by tools/trace_browser.py.

Does not send data over the network, call an external model, or open credentials.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json
import statistics
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "network_events.jsonl"


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Trace not found: {path}")
    result: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fp:
        for line_number, raw in enumerate(fp, 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON line {line_number}: {error}") from error
            if not isinstance(obj, dict) or "kind" not in obj:
                raise ValueError(f"Expected event object at line {line_number}")
            result.append(obj)
    return result


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    request_by_id: dict[str, dict[str, Any]] = {}
    ws_by_id: dict[str, dict[str, Any]] = {}
    kinds: Counter[str] = Counter()

    for event in events:
        kind = event.get("kind", "unknown")
        kinds[kind] += 1

        if kind == "http_request":
            request_by_id[str(event.get("request_id"))] = {
                "method": event.get("method", ""),
                "url": event.get("url", ""),
                "resource_type": event.get("resource_type", ""),
                "json_key_paths": event.get("json_key_paths", []),
                "status": None,
                "content_type": "",
                "duration_ms": None,
                "completed": False,
            }
        elif kind in ("http_response", "http_finished", "http_failed"):
            obj = request_by_id.get(str(event.get("request_id")))
            if obj is None:
                # A trace file may have been appended to across recorder runs.
                continue
            if kind == "http_response":
                obj["status"] = event.get("status")
                obj["content_type"] = event.get("content_type", "")
            elif kind == "http_finished":
                obj["duration_ms"] = event.get("duration_ms")
                obj["completed"] = True
            elif kind == "http_failed":
                obj["duration_ms"] = event.get("duration_ms")
                obj["completed"] = False

        elif kind == "ws_open":
            ws_by_id[str(event.get("websocket_id"))] = {
                "url": event.get("url", ""),
                "sent": 0,
                "received": 0,
                "total_bytes_sent": 0,
                "total_bytes_received": 0,
                "closed": False,
            }
        elif kind == "ws_frame":
            obj = ws_by_id.get(str(event.get("websocket_id")))
            if obj is None:
                continue
            direction = event.get("direction")
            length = event.get("payload_length") or 0
            if direction == "sent":
                obj["sent"] += 1
                obj["total_bytes_sent"] += length
            elif direction == "received":
                obj["received"] += 1
                obj["total_bytes_received"] += length
        elif kind == "ws_close":
            obj = ws_by_id.get(str(event.get("websocket_id")))
            if obj is not None:
                obj["closed"] = True

    endpoints: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "status_codes": Counter(),
            "content_types": Counter(),
            "resource_types": Counter(),
            "request_json_keys": set(),
            "latency_ms": [],
            "unfinished": 0,
        }
    )
    for req in request_by_id.values():
        key = (req["method"], req["url"])
        item = endpoints[key]
        item["count"] += 1
        if req["status"] is not None:
            item["status_codes"][str(req["status"])] += 1
        if req["content_type"]:
            item["content_types"][req["content_type"]] += 1
        if req["resource_type"]:
            item["resource_types"][req["resource_type"]] += 1
        item["request_json_keys"].update(req["json_key_paths"])
        if isinstance(req["duration_ms"], (float, int)):
            item["latency_ms"].append(req["duration_ms"])
        if not req["completed"]:
            item["unfinished"] += 1

    http_summary = []
    for (method, url), obj in endpoints.items():
        durations = obj["latency_ms"]
        http_summary.append(
            {
                "method": method,
                "url": url,
                "count": obj["count"],
                "status_codes": dict(obj["status_codes"]),
                "content_types": dict(obj["content_types"]),
                "resource_types": dict(obj["resource_types"]),
                "request_json_keys": sorted(obj["request_json_keys"])[:80],
                "mean_latency_ms": (
                    round(statistics.mean(durations)) if durations else None
                ),
                "unfinished": obj["unfinished"],
            }
        )
    http_summary.sort(key=lambda item: (-item["count"], item["url"], item["method"]))

    ws_summary = []
    for obj in ws_by_id.values():
        ws_summary.append(obj)
    ws_summary.sort(key=lambda obj: obj["url"])

    return {
        "total_events": len(events),
        "event_types": dict(kinds),
        "http_request_count": len(request_by_id),
        "http_endpoints": http_summary,
        "websockets": ws_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--json", action="store_true", help="Print machine-readable aggregate")
    args = parser.parse_args()

    try:
        result = aggregate(load_events(args.trace.expanduser()))
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Events: {result['total_events']} | HTTP requests: {result['http_request_count']}")
    print(f"Event types: {result['event_types']}")
    print("\nHTTP candidates (grouped method + redacted URL):")
    for item in result["http_endpoints"][: max(0, args.top)]:
        print(f"  {item['method']:7s} {item['count']:4d}x {item['url']}")
        print(
            f"    statuses={item['status_codes']} types={item['content_types']}"
            f" latency_mean={item['mean_latency_ms']}ms unfinished={item['unfinished']}"
        )
        if item["request_json_keys"]:
            print("    JSON schema keys: " + ", ".join(item["request_json_keys"][:20]))

    print(f"\nWebSocket sessions: {len(result['websockets'])}")
    for item in result["websockets"][: max(0, args.top)]:
        print(
            f"  {item['url']}: sent={item['sent']} received={item['received']}"
            f" bytes={item['total_bytes_sent']}/{item['total_bytes_received']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
