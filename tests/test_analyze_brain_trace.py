"""Offline tests for repeated marker and model/effort trace attribution."""

import unittest

from tools.analyze_brain_trace import summarize


def event(kind, ts, **fields):
    return {"kind": kind, "timestamp_utc":f"2026-10-28T05:00:{ts:02d}+00:00", **fields}


def telemetry(ts, model, effort):
    return event(
        "http_request_content", ts, url="https://io.web.clickup.com/v1/t",
        payload={
            "data": {
                "event": "use open ai feature",
                "properties": {"aiModel": model, "reasoningLevel": effort},
            }
        },
    )


class TraceAnalyzerTests(unittest.TestCase):
    def test_identical_marker_names_remain_distinct_phases(self):
        meta = [
            event("manual_marker", 1, label="opus_low"),
            event("http_request", 2, request_id="r1"),
            event("http_response", 3, request_id="r1", status=201),
            event("http_finished", 4, request_id="r1"),
            event("manual_marker", 10, label="opus_low"),
            event("http_request", 11, request_id="r2"),
            event("http_response", 12, request_id="r2", status=201),
            event("http_finished", 13, request_id="r2"),
        ]
        content = [
            event(
                "http_request_content", 2, request_id="r1",
                url="https://frontdoor.clickup.com/comment-service/x/comments/view/{token}",
            ),
            telemetry(5, "brain", None),
            event(
                "http_request_content", 11, request_id="r2",
                url="https://frontdoor.clickup.com/comment-service/x/comments/view/{token}",
            ),
            telemetry(14, "claude-opus-5-5", "low"),
        ]
        result = summarize(meta, content)
        self.assertEqual(result["phase_count_excluding_unmarked"], 2)
        phases = result["phases"]
        self.assertEqual(phases[1]["marker"], "opus_low")
        self.assertEqual(phases[2]["marker"], "opus_low")
        self.assertEqual(phases[1]["chat_commands"][0]["http_status"], 201)
        self.assertEqual(phases[2]["chat_commands"][0]["http_status"], 201)
        self.assertEqual(phases[1]["generation_telemetry"][0]["model"], "brain")
        self.assertEqual(phases[2]["generation_telemetry"][0]["model"], "claude-opus-5-5")
        self.assertEqual(phases[2]["generation_telemetry"][0]["effort"], "low")

    def test_failed_then_succeeded_in_same_phase(self):
        meta = [
            event("manual_marker", 1, label="opus_switch"),
            event("http_failed", 4, request_id="fail"),
            event("http_response", 8, request_id="ok", status=201),
            event("http_finished", 9, request_id="ok"),
        ]
        content = [
            event(
                "http_request_content", 2, request_id="fail",
                url="https://frontdoor.clickup.com/comment-service/x/comments/comment/{id}",
            ),
            event(
                "http_request_content", 6, request_id="ok",
                url="https://frontdoor.clickup.com/comment-service/x/comments/comment/{id}",
            ),
            event(
                "ws_frame_content", 9,
                payload={"data": {"event": {"name": "aiConversationStarted"}}},
            ),
        ]
        result = summarize(meta, content)
        phase = result["phases"][1]
        self.assertEqual(phase["chat_commands"][0]["request_outcome"], "http_failed")
        self.assertIsNone(phase["chat_commands"][0]["http_status"])
        self.assertEqual(phase["chat_commands"][1]["http_status"], 201)
        self.assertEqual(phase["ws_events"]["aiConversationStarted"], 1)

    def test_ai_result_event_crosses_marker_boundary_without_leaking_id(self):
        meta = [
            event("manual_marker", 1, label="opus_low"),
            event("manual_marker", 10, label="opus_low"),
        ]
        content = [
            event(
                "ws_frame_content", 5,
                payload={"data": {
                    "event": {"name": "aiConversationStarted",
                              "payload": {"ai_result_id": "secret-result-123"}}
                }},
            ),
            event(
                "ws_frame_content", 12,
                payload={"data": {
                    "event": {"name": "chatCommentCreated",
                              "version_event_data": {
                                  "changes": [
                                      {"field": "ai_result_id",
                                       "after": "secret-result-123"}
                                  ]
                              }}
                }},
            ),
        ]
        report = summarize(meta, content)
        self.assertEqual(report["matched_ai_start_to_comment_created"], 1)
        self.assertEqual(
            report["cross_marker_correlations"],
            [{"started_phase": 1, "event_phase": 2, "event": "chatCommentCreated"}],
        )
        self.assertNotIn("secret-result-123", str(report))

    def test_model_selection_is_parsed_from_query(self):
        from tools.analyze_brain_trace import extract_chat_wire_options
        entry = {"payload": {"data": {"comment_type_data": {
            "query": "/?selectedModel=claude-opus-5-5&selectedReasoningLevel=low"
        }}}}
        result = extract_chat_wire_options(entry)
        self.assertEqual(result["selected_model"], "claude-opus-5-5")
        self.assertEqual(result["selected_effort"], "low")

    def test_default_effort_is_not_inferred(self):
        from tools.analyze_brain_trace import extract_chat_wire_options
        entry = {"payload": {"data": {"comment_type_data": {
            "query": "/?selectedModel=auto"
        }}}}
        result = extract_chat_wire_options(entry)
        self.assertEqual(result["selected_model"], "auto")
        self.assertIsNone(result["selected_effort"])
        self.assertFalse(result["selected_effort_present"])

    def test_telemetry_output_whitelists_known_values(self):
        meta = [event("manual_marker", 1, label="max_first")]
        content = [telemetry(2, "private-secret-identifier", "private-secret-identifier")]
        result = summarize(meta, content)
        self.assertEqual(result["phases"][1]["generation_telemetry"], [])

if __name__ == "__main__":
    unittest.main()
