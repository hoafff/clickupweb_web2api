# ClickUp Brain² — Web → API Research

> **Trạng thái (28/10/2026):** Đã khảo sát 5 dự án Web → API; chuyển sang **protocol research / implementation-oriented**. Người thực hiện cho biết **đã được ủy quyền nghiên cứu**. Phạm vi kỹ thuật dự kiến: trace hoạt động của Web UI, đối chiếu request/response, giải mã streaming và tạo API facade. **Chưa có endpoint ClickUp Brain² nào được thực nghiệm hoặc xác minh**. Đây chưa phải một proxy Brain² hoàn chỉnh.

## Mục tiêu

Bóc tách cơ chế `ClickUp Brain² Web → API` bằng cách đối chiếu UI với network/protocol trong phiên nghiên cứu được cấp quyền. Giữ riêng ba mô-đun:

1. `research`: nhận diện các request/response liên quan bằng các thao tác UI chủ động; dựng sơ đồ chat, model switch, conversation state, streaming.
2. `provider adapter`: chuyển request OpenAI-like thành protocol **đã được kiểm chứng trong phạm vi nghiên cứu**; xử lý auth/session, model, event decoder, attachments và errors.
3. `gateway`: FastAPI/Go API với `/v1/models`, `/v1/chat/completions` JSON/SSE, multi-user isolation và observability.

**Không đồng nhất** việc có UI model selector với API model ID. Không tự nhận Max = một model cụ thể; phải so sánh thực nghiệm.

## Scope nghiên cứu

Nghiên cứu dùng giả định người thực hiện **có ủy quyền**. Repo không yêu cầu chờ public API mới được lập kế hoạch khảo sát network hay phân tích giao thức. Tác vụ thực thi phải nằm trong phạm vi được ủy quyền, trên tài khoản/workspace được phép và theo các điều kiện của bên cấp quyền.

Có thể tiến hành: network timeline, protocol diff, inspect request schema, streaming analysis, browser automation trong phạm vi được cấp quyền, model selection/replay test, dựng adapter và API-compatible gateway.

Vẫn giữ kỹ thuật bảo vệ: không commit secret/cookie/HAR nguyên bản; không vô hiệu hóa giới hạn dịch vụ, né CAPTCHA/WAF, khai thác tài khoản khác, vượt quyền hay giả mạo thanh toán. **Các giới hạn này khác với việc cấm nghiên cứu giao thức.**

## Danh sách model ghi nhận từ ảnh UI

| Label trong UI (ảnh cung cấp 28/10/2026) | Loại | Trạng thái |
|---|---|---|
| Brain² — Max | ClickUp | Selected trong ảnh |
| Claude Opus 5.5 | Claude | Hiển thị |
| Claude Opus 5 | Claude | Hiển thị |
| Gemini 4 Argon | Gemini | Hiển thị |
| GPT-6.1 Sol | GPT | Hiển thị |
| GPT-6.1 Terra | GPT | Hiển thị |
| Show more | Mở rộng danh sách | Chưa có ảnh toàn bộ |

Đây là **nhãn UI**, không phải upstream `model_id` đã xác minh. Có thể còn model khác phía dưới `Show more`.

## Tài liệu

1. [01 — Open-source survey](docs/01_OPEN_SOURCE_SURVEY.md): 5 dự án, so sánh browser/HTTP/RPC/SSE.
2. [02 — Brain² feasibility](docs/02_CLICKUP_BRAIN_FEASIBILITY.md): dữ liệu xác nhận, giả thuyết và điều cần đo.
3. [03 — Architecture & POC](docs/03_ARCHITECTURE_AND_POC_PLAN.md): triển khai protocol adapter và gateway.
4. [04 — Observation worksheet](docs/04_OBSERVATION_WORKSHEET.md): bảng ghi kết quả thực nghiệm.
5. [05 — Multi-model](docs/05_MULTI_MODEL_SUPPORT.md): dynamic discovery, menu model, switching.
6. [06 — Authorized protocol research](docs/06_AUTHORIZED_PROTOCOL_RESEARCH.md): phương pháp quan sát request/response theo từng lượt chat.
7. [Web public findings](docs/07_PUBLIC_WEB_FINDINGS.md): phân biệt ClickUp Chat API, MCP, Brain² và giới hạn truy cập frontend.
8. [Phân tích trace 28/10](docs/08_TRACE_ANALYSIS_2026-10-28.md): số liệu thực nghiệm, request comment-service, realtime WebSocket và các giả thuyết cần kiểm chứng.
9. [Browser network tracer](tools/trace_browser.py): ví dụ tracer theo dõi metadata đã ẩn thông tin nhạy cảm; chạy trên browser profile riêng.

## Quick start — quan sát phiên Browser

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-research.txt
python -m playwright install chromium
python tools/trace_browser.py --url https://app.clickup.com/
python tools/summarize_trace.py artifacts/network_events.jsonl
```

Trình duyệt mở ở chế độ nhìn thấy được. Đăng nhập bằng tài khoản **được ủy quyền**, thực hiện lần lượt các lượt chat và đổi model bằng tay, sau đó Enter ở terminal để dừng trace. Tracer không đọc nội dung prompt/token và không auto-send. **Browser profile lưu trạng thái đăng nhập nhạy cảm**, chỉ giữ trên máy an toàn và không commit.

## Mốc hoàn thành

- [x] Static open-source survey.
- [x] Chốt mô hình nghiên cứu có ủy quyền, menu multi-model từ ảnh.
- [x] Thiết kế protocol observation và tracer metadata.
- [x] Chạy tracer với phiên ClickUp được cấp quyền, thu bằng chứng đã redacted (V3).
- [x] Xác minh HTTP chat command, selectedModel/selectedReasoningLevel và WS reply-created event trên V3; **chưa xác minh full inference/streaming transport**.
- [x] Xây và kiểm thử offline conversation correlator; **chưa có browser/protocol adapter gửi prompt**.
- [x] Triển khai Browser Adapter prototype (manual + opt-in CSS send), kiểm thử offline bằng fake WS/UI.
- [x] Kiểm thử live Browser Adapter (manual UI send → WS reply) với phiên được ủy quyền: nhận 1/1 reply "OK".
- [x] Bổ sung read-only DOM inspector để khám phá CSS selector; mới kiểm thử fixture/CI.
- [ ] Auto-send Playwright với CSS selector đã xác minh qua DOM thực tế (không đoán nút Send).
- [ ] Demo OpenAI-compatible JSON/SSE, kiểm thử multi-model, quota và tính ổn định.

## Nguồn

[ClickUp chọn model](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model) · [Playwright network](https://playwright.dev/python/docs/network) · [MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) · [ClickUp Terms](https://clickup.com/terms)


## Trace v2 (đổi model theo mốc đánh dấu)

```powershell
# Chỉ chạy từ phiên profile nghiên cứu; tự đăng nhập bằng tài khoản được ủy quyền
python tools/trace_browser.py --url https://app.clickup.com/ --capture-ws-schema --output artifacts/brain_v2.jsonl
# Terminal sau khi browser mở: "mark max_first" (Enter) rồi gửi prompt UI
# Tiếp theo: "mark max_followup" rồi gửi prompt trong cùng hội thoại
# Tiếp theo: "mark opus_switch" rồi chọn Opus và gửi prompt
# Nhấn Enter ở terminal để kết thúc
python tools/summarize_trace.py artifacts/brain_v2.jsonl --json
```

`--capture-ws-schema` là tùy chọn: chỉ lưu **JSON key paths** của WebSocket frame, không lưu giá trị/body. Đã tăng cường mask segment chữ+số dạng opaque IDs trong URL. Marker cho phép liên kết request sau mỗi lần tương tác UI. **Không đẩy file trace hay browser profile lên repo public.**


## Thử nghiệm Thinking Effort và capture JSON (v3)

Ảnh UI cho thấy Claude Opus 5.5 có Thinking Effort `Auto`, `Low`, `Medium`. Để so sánh request giữa các mức này, chạy:

```powershell
git pull
.\.venv\Scripts\python.exe tools\trace_browser.py --url https://app.clickup.com/ --capture-ws-schema --capture-content --output artifacts\brain_v3_meta.jsonl --content-output artifacts\brain_v3_private_content.jsonl
```

Nhập marker trong **PowerShell** trước khi thao tác trên UI, rồi mới gửi prompt. Quy trình:

| Marker | ClickUp action |
|---|---|
| `mark max_first` | New Chat, chọn Max, gửi `Trả lời đúng một từ: OK` |
| `mark max_followup` | Trong chat Max, gửi `Vừa rồi tôi yêu cầu gì?` |
| `mark opus_switch` | Trong cùng chat, đổi sang Opus 5.5 Medium và gửi một tin |
| `mark opus_auto` | New Chat, Opus 5.5 Auto, gửi `Trả lời đúng một từ: OK` |
| `mark opus_low` | New Chat, Opus 5.5 Low, gửi cùng prompt |
| `mark opus_medium` | New Chat, Opus 5.5 Medium, gửi cùng prompt |

**New Chat riêng cho từng effort** giúp loại bớt ảnh hưởng conversation history. Mỗi lần nhập marker rồi Enter, tracer ghi mốc thời gian; tiếp tục thao tác UI bình thường. Đợi đủ phản hồi rồi nhấn Enter trống để kết thúc.

```powershell
.\.venv\Scripts\python.exe tools\summarize_trace.py artifacts\brain_v3_meta.jsonl --json > artifacts\brain_v3_summary.json
```

`brain_v3_meta.jsonl` chứa metadata, `brain_v3_private_content.jsonl` chứa nội dung JSON HTTP/WS/SSE **có redaction theo key**, từ lúc marker đầu tiên. Chỉ capture nội dung JSON text nhỏ hơn giới hạn mặc định 192 KiB/response; không capture file binary/HTML/raw HAR. Bộ lọc secret **không bảo đảm loại hết thông tin nhạy cảm**, đặc biệt các giá trị không có tên trường rõ ràng: giữ file private trên máy, xem lại trước khi chia sẻ và không commit lên GitHub. Tracer không tự login hay gửi prompt.


## Kết quả trace V3 và marker bấm lặp

Xem [báo cáo V3: 8 marker, model/effort và WebSocket](docs/10_V3_TRACE_ANALYSIS_2026-10-28.md). Nếu bấm lại `mark opus_low` hoặc `mark opus_auto`, **không cần capture lại**; dùng tool mới để tách theo lần xuất hiện:

```powershell
git pull
.\.venv\Scripts\python.exe tools\analyze_brain_trace.py artifacts\brain_v3_meta.jsonl artifacts\brain_v3_private_content.jsonl
```

Muốn xuất JSON tổng hợp **không có prompt, conversation ID, token và raw content**:

```powershell
.\.venv\Scripts\python.exe tools\analyze_brain_trace.py artifacts\brain_v3_meta.jsonl artifacts\brain_v3_private_content.jsonl --json > artifacts\brain_v3_analysis.json
```

Kết quả `brain_v3_analysis.json` chứa mỗi pha `#1 ... #8` với HTTP status, event name counts và giá trị `model/effort` đã whitelist, **không** chứa payload gốc. Bản private log V3 đã cung cấp vẫn có thể chứa session/analytics identifiers; giữ private và không commit. Tracer từ bản cập nhật đã tăng che `writeKey`, `session_id`, `sessionId`.


## V3 — Reconstruct reply text from WebSocket (offline)

[Validated event parser and privacy-preserving findings](docs/11_V3_REPLY_EVENT_DECODING.md): correlate `aiConversationStarted` with `chatCommentCreated` by `ai_result_id`, confirm matching `conversation_id`, and decode the rich-text JSON string `comment` in `version_event_data.changes[].after`.

```powershell
git pull
.\.venv\Scripts\python.exe tools\brain_event_decoder.py artifacts\brain_v3_private_content.jsonl
```

The default command prints only event counts, reply lengths and event-to-event timing, no prompt or IDs. For authorized local inspection only, add `--export-replies artifacts\brain_v3_local_replies.json` to write actual text to a **private ignored file**. Do not commit or share this file. The 8/8 reply matches from the V3 trace do **not** establish streaming-delta or a runnable standalone upstream API.


## Async event correlation / V3 offline replay

[State-machine design, tests and known limitations](docs/12_ASYNC_CORRELATOR.md) — `ConversationEventCorrelator` ghép `aiConversationStarted` ↔ `chatCommentCreated` theo `ai_result_id`, xác minh `conversation_id`, không trộn concurrent chats, hỗ trợ timeout, cancellation, duplicate, out-of-order và TTL/cache bounds.

```powershell
git pull
.\.venv\Scripts\python.exe tools\replay_brain_events.py artifacts\brain_v3_private_content.jsonl --expected 8
```

Replay không có network access; chỉ xuất tổng số event/matches. Lần chạy trên trace V3 **chưa được thực hiện trong môi trường GitHub** (dữ liệu riêng tư không commit). Kỳ vọng 8 matches dựa trên decoder V3 người dùng đã chạy thành công. Không đồng nhất `reply_created` với model completion hay token streaming. Gateway và adapter live chưa được triển khai.


## Windows troubleshooting: `ModuleNotFoundError: No module named 'tools'`

Nếu dùng bản cũ của `tools/replay_brain_events.py` và gặp lỗi import khi chạy trực tiếp, có thể dùng module mode từ **thư mục gốc repository**:

```powershell
cd E:\Toolss\clickuptoapi
.\.venv\Scripts\python.exe -m tools.replay_brain_events artifacts\brain_v3_private_content.jsonl --expected 8
```

Đã sửa lỗi gốc: entrypoint `tools/replay_brain_events.py` hiện bootstrap repository root vào Python import path nếu chạy trực tiếp, nên sau `git pull` cả hai cách đều hỗ trợ:

```powershell
git pull
.\.venv\Scripts\python.exe tools\replay_brain_events.py artifacts\brain_v3_private_content.jsonl --expected 8
```

CI chạy **subprocess thực tế** để kiểm thử cả direct-script và `-m` mode trên một trace giả, không cần truy cập ClickUp. Kết quả `matched=8` trên dữ liệu riêng của người dùng vẫn chỉ được xác nhận sau khi người dùng chạy lệnh với file V3 local.


## Browser Adapter — manual E2E smoke test (prototype)

[Hướng dẫn thao tác, trạng thái test và giới hạn](docs/13_BROWSER_ADAPTER_E2E.md). Chạy từ repo root trên Windows, sau khi **đóng trình duyệt/tracer cũ** để không khóa profile:

```powershell
git pull
.\.venv\Scripts\python.exe tools\browser_adapter.py --mode manual --timeout 120
```

Khi Chromium mở: đăng nhập/mở Brain², chọn model, bảo đảm không còn câu trả lời đang chạy. Quay lại PowerShell nhấn ENTER để **arm**. Sau đó gửi **đúng một** tin trong Browser. Adapter lắng nghe `/ws`, ghép `aiConversationStarted` → `chatCommentCreated`, in độ dài văn bản, không in prompt hoặc trả lời. Thêm `--show-reply` nếu muốn hiển thị nội dung trả lời riêng trên console.

`--mode auto --confirm-send --composer-selector ... --send-selector ...` cũng đã có nhưng **chưa kiểm thử DOM thật**; chỉ sử dụng khi tự xác minh CSS selector trên Browser. Không suy diễn selector từ ảnh hoặc trace network. CI chỉ kiểm thử offline mock trên Ubuntu/Windows; **live E2E, API gateway và server-side model execution chưa được xác minh**.


## Live Browser Adapter đã PASS — chuẩn bị auto-send

Người thực hiện đã chạy `browser_adapter.py --mode manual` trên Chromium đăng nhập ClickUp và nhận `SUCCESS`: 1 WS connection, 12 JSON WS frames, 1/1 matched AI reply, nội dung `OK`. Đây là kiểm chứng receiving path **live**, khác với offline replay; **không** chứng minh auto-send đã chạy hoặc có server/gateway API độc lập.

Để nhận diện composer và nút Send từ DOM **không chụp nội dung chat**, xem [hướng dẫn inspector](docs/14_UI_SELECTOR_INSPECTION.md):

```powershell
git pull
.\.venv\Scripts\python.exe tools\inspect_brain_ui.py
```

Mở đúng ClickUp Brain UI, nhấn ENTER trong terminal. Tool in `visible_editors` và `nearby_buttons` kèm vị trí `rect`, `aria-label`, `placeholder`, `data-testid` và CSS selector được kiểm tra unique. **Không tự động gửi tin nhắn.** User cần kiểm tra lại selector trong trình duyệt trước khi dùng `browser_adapter.py --mode auto --confirm-send`. Không gửi browser profile, cookie hoặc dữ liệu workspace riêng tư.
