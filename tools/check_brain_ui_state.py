#!/usr/bin/env python3
"""Observe opt-in Brain UI control metadata through the existing LOCAL Gateway.

--snapshot: single read-only observation, no ClickUp prompt.
--watch: read-only polling; start a separate benign request in another shell.
--drive-router: EXPLICITLY submit ONE benign text prompt through local 9Router
                while watching metadata, may consume account allowance.

Never print raw UI labels, chat text, URLs, tokens, IDs or upstream errors.
This does not establish a final-generation signal or alter Gateway behavior.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

if __package__ in (None, ""):
    _root = Path(__file__).resolve().parents[1]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from tools.brain_ui_state_probe import sanitize_ui_snapshot, BOOLEAN_FIELDS, COUNT_FIELDS
from tools.check_9router_path import (
    MODEL, KEY_FILE as ROUTER_KEYFILE, read_key, chat_once,
    reject_reused_upstream_key, RouterPathError,
)
from tools.send_gateway_request import DEFAULT_KEY_FILE, load_key, LocalClientError

PROBE_PATH = "/v1/research/ui-state"
RESEARCH_END_MARKER = "UI_RESEARCH_END"
RESEARCH_PROMPT = (
    "Write six numbered paragraphs explaining HTTP versus WebSocket for "
    "software engineers. Include practical examples, at least two sentences "
    "per paragraph. End your answer with exactly " + RESEARCH_END_MARKER + "."
)


class ResearchProbeError(Exception):
    """Static failure summaries only, never raw HTTP response bodies."""


def get_snapshot(*, port: int, key: str, timeout: float = 4.0) -> dict:
    if not 1024 <= port <= 65535:
        raise ResearchProbeError("Gateway port must be 1024..65535.")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{PROBE_PATH}",
        headers={"Authorization": "Bearer " + key},
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            payload = response.read(4096)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ResearchProbeError(
                "UI research endpoint disabled. Restart Gateway with "
                "--router-mode --ui-research after pulling latest code."
            ) from exc
        raise ResearchProbeError(
            f"Gateway UI probe HTTP {exc.code}; check Gateway login/key."
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ResearchProbeError("Cannot reach local Gateway UI probe.") from exc
    try:
        return sanitize_ui_snapshot(json.loads(payload.decode("utf-8")))
    except (ValueError, UnicodeError) as exc:
        raise ResearchProbeError("Gateway UI probe returned invalid safe metadata.") from exc


def summarise(samples: list[dict], failures: int) -> dict:
    counts = Counter()
    for item in samples:
        for field in BOOLEAN_FIELDS:
            if item[field]:
                counts[field + "_sample_count"] += 1
        for field in COUNT_FIELDS:
            if item[field] > 0:
                counts[field + "_nonzero_samples"] += 1
        if item["stop_candidate_count"] > 0 and item["page_is_brain"]:
            counts["stop_control_hint_samples"] += 1
        if item["generating_candidate_count"] > 0 and item["page_is_brain"]:
            counts["generating_control_hint_samples"] += 1
    distinct = {
        tuple((f, item[f]) for f in BOOLEAN_FIELDS + COUNT_FIELDS)
        for item in samples
    }
    return {
        "samples": len(samples),
        "failed_samples": failures,
        "different_snapshot_shapes": len(distinct),
        **{f + "_sample_count": counts[f + "_sample_count"] for f in BOOLEAN_FIELDS},
        **{f + "_nonzero_samples": counts[f + "_nonzero_samples"] for f in COUNT_FIELDS},
        "stop_control_hint_samples": counts["stop_control_hint_samples"],
        "generating_control_hint_samples": counts["generating_control_hint_samples"],
        **observe_transitions(samples),
        "interpretation": (
            "Candidate UI controls only. A stop/busy label does not prove "
            "generation is active, and its disappearance is NOT a verified "
            "upstream end-of-generation signal."
        ),
    }


def classify_router_failure(error: RouterPathError) -> dict:
    """Return ONLY static categories and a numeric HTTP status (never raw body)."""
    reason = str(error)
    match = re.search(r"\b9Router HTTP ([4-5][0-9]{2})\b", reason)
    if match:
        return {
            "router_error_category": "http_error",
            "router_http_status": int(match.group(1)),
        }
    if "timed out" in reason.lower():
        category = "client_read_timeout"
    elif "Cannot reach local 9Router" in reason:
        category = "router_transport_failure"
    elif "Chat Completion" in reason or "Expected JSON" in reason:
        category = "unexpected_router_response"
    else:
        category = "other_router_client_failure"
    return {
        "router_error_category": category,
        "router_http_status": None,
    }


def observe_transitions(samples: list[dict]) -> dict:
    """Count coarse Stop appearance/disappearance without timestamps/content."""
    states = [bool(s["stop_near_composer_count"] > 0) for s in samples]
    return {
        "stop_appearance_transitions": sum(
            not a and b for a, b in zip(states, states[1:])
        ),
        "stop_disappearance_transitions": sum(
            a and not b for a, b in zip(states, states[1:])
        ),
        "stop_visible_first_sample": states[0] if states else None,
        "stop_visible_last_sample": states[-1] if states else None,
        "stop_ever_visible": any(states),
    }


def classify_stop_timing(
    timed_samples: list[tuple[float, bool]],
    router_finished_at: float,
) -> dict[str, bool | int | None]:
    """Relate observed Stop hints to 9Router *client return*, NOT AI completion.

    Only monotonic timestamps and boolean metadata are used. A Stop exit before
    this return is not proof of a server generation-complete event.
    """
    before = [state for stamp, state in timed_samples if stamp <= router_finished_at]
    after = [state for stamp, state in timed_samples if stamp > router_finished_at]
    return {
        "ui_samples_before_router_return": len(before),
        "ui_samples_after_router_return": len(after),
        "stop_seen_before_router_return": any(before),
        "stop_disappearance_before_router_return": any(
            prior and not current for prior, current in zip(before, before[1:])
        ),
        "stop_visible_last_sample_before_router_return": (
            before[-1] if before else None
        ),
        "stop_seen_after_router_return": any(after),
    }


def safe_research_reply_metrics(reply: str) -> dict[str, int | bool]:
    """Check a literal public test suffix without exposing answer content."""
    return {
        "router_reply_characters": len(reply),
        "router_reply_has_expected_suffix": reply.rstrip().endswith(
            RESEARCH_END_MARKER
        ),
    }


def collect(*, port: int, key: str, samples: int, interval: float,
            stop_event: threading.Event | None = None,
            post_samples: int = 0,
            on_sample: Callable[[dict], None] | None = None,
            ) -> tuple[list[dict], int]:
    seen: list[dict] = []
    failures = 0
    tail = 0
    for index in range(samples):
        if stop_event is not None and stop_event.is_set():
            tail += 1
            if tail > post_samples:
                break
        try:
            snapshot = get_snapshot(port=port, key=key)
            seen.append(snapshot)
            if on_sample is not None:
                on_sample(snapshot)
        except ResearchProbeError:
            failures += 1
        if index + 1 < samples:
            time.sleep(interval)
    return seen, failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--snapshot", action="store_true", help="One read-only snapshot")
    group.add_argument("--watch", action="store_true", help="Read-only repeated snapshots")
    group.add_argument("--drive-router", action="store_true",
                       help="ONE actual benign 9Router request while observing UI")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--router-port", type=int, default=20128)
    p.add_argument("--samples", type=int, default=50)
    p.add_argument("--interval", type=float, default=0.35)
    p.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    p.add_argument("--router-key-file", type=Path, default=ROUTER_KEYFILE)
    args = p.parse_args(argv)
    if not 1 <= args.samples <= 480 or not 0.2 <= args.interval <= 3:
        p.error("--samples must be 1..480 and --interval must be 0.2..3.")
    try:
        key = load_key(args.key_file)
        # Require a read-only baseline before optionally consuming AI credits.
        baseline = get_snapshot(port=args.port, key=key)
        if args.drive_router and not baseline["page_is_brain"]:
            raise ResearchProbeError(
                "Browser is not on ClickUp Brain; open Brain before sending "
                "the optional research prompt."
            )
        if args.snapshot or (not args.watch and not args.drive_router):
            print(json.dumps(baseline, indent=2))
            print("UI hints are NOT generation-complete evidence.")
            return 0

        if args.watch:
            samples, failures = collect(
                port=args.port, key=key, samples=args.samples, interval=args.interval,
            )
            print(json.dumps(summarise(samples, failures), indent=2))
            return 0

        router_key = read_key(args.router_key_file)
        if router_key is None:
            raise ResearchProbeError(
                "9Router caller key missing; create it in 9Router dashboard "
                "and store in .local/ninerouter.key."
            )
        # Never send using the upstream Gateway key as the inbound 9Router key.
        reject_reused_upstream_key(router_key)
        stop = threading.Event()
        outcome: dict = {}
        timed_stop_samples: list[tuple[float, bool]] = []

        def note_sample(snapshot: dict) -> None:
            # Private local memory only. Do not save timestamps or content.
            timed_stop_samples.append((
                time.monotonic(), snapshot["stop_near_composer_count"] > 0,
            ))

        def watcher():
            observed, failures = collect(
                port=args.port, key=key, samples=args.samples,
                interval=args.interval, stop_event=stop, post_samples=5,
                on_sample=note_sample,
            )
            outcome["summary"] = summarise([baseline, *observed], failures)

        worker = threading.Thread(target=watcher, daemon=True)
        worker.start()
        failure = None
        reply_metrics = None
        request_started = time.monotonic()
        try:
            answer, _ = chat_once(
                model=MODEL, port=args.router_port, key=router_key,
                prompt=RESEARCH_PROMPT, stream=False,
            )
            reply_metrics = safe_research_reply_metrics(answer)
        except RouterPathError as exc:
            failure = classify_router_failure(exc)
        finally:
            # Capture BEFORE watcher tail samples; the router call has
            # returned (or failed) at this point.
            router_finished_at = time.monotonic()
            duration = round(router_finished_at - request_started, 2)
            stop.set()
            worker.join(timeout=min(20.0, args.samples * args.interval + 8))
        if "summary" not in outcome:
            raise ResearchProbeError("UI sample thread did not finish cleanly.")
        report = outcome["summary"]
        report.update(classify_stop_timing(
            timed_stop_samples, router_finished_at,
        ))
        report["router_request_elapsed_seconds"] = duration
        report["router_request_outcome"] = "error" if failure else "success"
        if failure:
            report.update(failure)
        else:
            report.update(reply_metrics)
        # Observe the UI once MORE after the HTTP caller finished or failed.
        # This is critical when sampling ended before an upstream timeout.
        try:
            after = get_snapshot(port=args.port, key=key)
            report["post_request_snapshot_ok"] = True
            report["post_request_stop_near_composer"] = (
                after["stop_near_composer_count"] > 0
            )
            report["post_request_composer_visible"] = after["composer_visible"]
        except ResearchProbeError:
            report["post_request_snapshot_ok"] = False
            report["post_request_stop_near_composer"] = None
            report["post_request_composer_visible"] = None
        print(json.dumps(report, indent=2))
        if failure:
            raise ResearchProbeError(
                "9Router routed request failed; see the SAFE category/status "
                "above. Do NOT retry blindly: the UI prompt may have been sent."
            )
        print(
            "9Router text request returned; reply character count:",
            reply_metrics["router_reply_characters"],
        )
        print("No generation completion was inferred from UI metadata.")
        return 0
    except (ResearchProbeError, LocalClientError, RouterPathError) as exc:
        print("UI research: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
