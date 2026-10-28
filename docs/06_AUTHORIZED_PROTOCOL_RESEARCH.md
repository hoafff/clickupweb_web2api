# 06 — Playbook khảo sát protocol Web → API trên ClickUp Brain²

**Phạm vi:** nghiên cứu dựa trên ủy quyền do người thực hiện xác nhận, chỉ đối với Workspace / tài khoản được cấp quyền. Tài liệu phân tích cách tạo bằng chứng kỹ thuật, không công bố một ClickUp endpoint chưa được chứng minh.

## I. Trình tự quan sát

1. Tạo profile Chromium nghiên cứu riêng và bật Network tab trong DevTools. Dùng `Preserve log` nếu muốn xem request giữa các navigation; chọn filter `Fetch/XHR` rồi kiểm tra cả `WS` và `Other` (stream không phải luôn XHR).
2. Thực hiện từng thao tác UI có đánh số: load Brain; gửi prompt #1; tiếp cùng chat #2; new chat; đổi model; dùng Skills; stop; xem lại history.
3. Khi xác định group request liên quan tới send/receive, ghi **method, route (mask ID), content type, status, thời lượng, top-level schema keys, request/response correlation**. Quan sát frames/streaming để tìm transport.
4. Chạy lại cùng prompt với hai model và so sánh request schema, state và response. Kiểm tra model ID có thực sự khác, có thể là config/agent field thay vì `model` trực tiếp.
5. Thử conversation mới vs continuation để tìm server-issued conversation ID và message parent/response ID.
6. Thử các trường hợp cancel/error trong test account (không load testing vô hạn), ghi protocol error mapping.

### Mức độ bằng chứng

- **Observed UI:** tên nút/model, hành vi hiển thị.
- **Observed network:** route, method, event timing, content-type, field shape trong phiên thực nghiệm.
- **Confirmed protocol:** hành vi lặp lại được trên ≥2 lượt, có fixture redacted, mapping request/response và model switch.
- **Hypothesis:** chưa đủ dữ liệu; giữ nhãn này.

## II. Sơ đồ chu kỳ request

```text
UI: select model
    | possible config/entitlement requests
UI: send prompt
    | request issued
    | -> response headers / HTTP status
    | -> JSON / SSE / streamed fetch / WS / polling
    | -> final event / stream closes / UI marks completed
UI: continue conversation
    | state reference changes or retains
UI: switch model and continue
    | compare model selection and state handling
```

Đừng lấy URL request từ screenshot làm endpoint; route có thể chứa opaque identifiers thay đổi giữa người dùng. Thử phân biệt:
- request `GET config/models` hoặc permission/options từ frontend;
- request tạo conversation;
- request gửi message/turn;
- request stream/poll output;
- request save/load history;
- request cancel;
- request upload;
- request tool action/agent.

## III. Capture với tracer trong repo

```bash
pip install -r requirements-research.txt
python -m playwright install chromium
python tools/trace_browser.py --url https://app.clickup.com/
python tools/summarize_trace.py artifacts/network_events.jsonl
```

- Tracer dùng **persistent browser profile** tại `.local/browser-profile` để đăng nhập thủ công; profile chứa thông tin nhạy cảm và nằm trong `.gitignore`.
- Dữ liệu xuất: HTTP `request`, `response`, `requestfinished`, `requestfailed`; WebSocket `open`, `framesent`, `framereceived`, `close`; event timestamp, route **đã mask**, HTTP status, content type, request JSON **key paths**, frame length (không nội dung).
- Tool **không** tự login, không tạo request replay, không đọc raw body hoặc header/token, không chụp HAR. Thiết kế này cho phép xác định các endpoint ứng viên mà không công bố dữ liệu tài khoản.
- Khi cần phân tích schema/values thực: dùng DevTools trong môi trường nghiên cứu, lưu ở kho an toàn theo scope ủy quyền; chỉ chuyển **schema/fixture đã mask** vào repo.
- Có thể bật `--hosts clickup.com,api.example.com` khi transport hợp lệ có host khác; mặc định chỉ theo dõi clickup.com và subdomain.

## IV. So sánh protocol có kiểm soát

Thiết lập một test matrix, mỗi lần chỉ đổi một biến:

| Case | Chat | Model | Prompt | Điều quan sát |
|---|---|---|---|---|
| T01 | New | Max | `ping` | First-turn endpoint, model/mode, message ID |
| T02 | Continue T01 | Max | `pong` | Conversation reference, parent state |
| T03 | New | Claude Opus 5.5 | `ping` | Model selection diff |
| T04 | Continue T03 | GPT-6.1 Sol | `pong` | Mid-chat switch + history continuity |
| T05 | New | Gemini 4 Argon | `ping` | Model family diff |
| T06 | New | Max | `ping` | Variability / nonce filtering |

Một field chỉ có thể được coi là model selector nếu thay đúng model khiến field đổi có quy luật qua nhiều lượt. Không chép cookies, CSRF, opaque auth headers vào mã nguồn.

## V. Streaming protocol decoder

Nếu là SSE: `text/event-stream`, lines `event:`, `data:`, `id:`, blank-line delimiter; có thể có nhiều dòng data/event. Nếu là chunked fetch: decode UTF-8 incremental và kiểm tra delimiting; nếu WebSocket: check frames, direction, format, final marker. Xác nhận ở upstream thay vì suy từ việc UI gõ chữ dần.

```text
stream lifecycle
CONNECT -> HEADERS -> DELTA* -> FINAL -> CLOSE
                  \-> ERROR -> CLOSE
                  \-> CANCEL -> CLOSE
```

Các biến cần lưu: `conversation_ref`, `response_ref`, `event_type`, `delta/content`, `finish_reason`, `usage`, `model_ref`, `tool_call`; chỉ dùng **tên field thực quan sát được**, schema trên là normalized target.

## VI. State/auth lifecycle

- Phân biệt auth credential (bí mật) với conversation references (opaque state).
- Kiểm tra UI có refresh auth khi 401, redirect login ở 403, hay revoke session khác.
- Không hardcode browser cookie vào proxy; thiết kế session vault/refresh strategy tương ứng giao thức thực.
- Khi transport đòi browser context, benchmark BrowserNetworkAdapter và BrowserUIAdapter trước khi quyết định HTTP direct.
- 429/timeout/5xx phải có retry có giới hạn, exponential backoff và idempotency awareness (không resend prompt vô tình).
- Scope không bao gồm né CAPTCHA/WAF, lấy credential bên thứ ba hoặc vượt service quota trừ khi phía cấp quyền có test arrangement riêng; không cần các kỹ thuật đó để chứng minh request schema.

## VII. Chuyển thành API

Sau khi có protocol contract thực nghiệm:
1. Viết `ProviderAdapter` độc lập gateway; tests bằng mock fixture đã sanitize.
2. Thiết kế `ModelRegistry` từ dynamic menu, không giả định label = API ID.
3. Implement `POST /v1/chat/completions` không stream, rồi SSE adapter.
4. Lưu conversation ID per caller; khóa đồng thời từng chat.
5. Thêm `GET /v1/models` trả chỉ những model đã kiểm chứng.
6. Test model switching, 401/403/429, disconnect, retries, failover, credentials removal và regression.

## VIII. Những điều chưa được xác minh tính đến 28/10/2026

Endpoint/host ClickUp thực dùng cho chat, payload field names, Bearer/CSRF semantics, SSE hay WebSocket, model IDs của Brain², streaming contract, tool invocation, multi-model fallback. **Không nên viết code phụ thuộc vào giá trị chưa thu được.**

## Tham chiếu

- [Playwright Python — Network](https://playwright.dev/python/docs/network)
- [Playwright Python — Request event lifecycle](https://playwright.dev/python/docs/api/class-request)
- [Playwright Python — WebSocket](https://playwright.dev/python/docs/api/class-websocket)
- [MDN — SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- [ClickUp model selector](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model)
