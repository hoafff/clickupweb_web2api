# ClickUp Brain² — Web → API Research

> **Trạng thái (28/10/2026):** **Live auto-send E2E PASS** trên phiên ClickUp Brain² được phép: Playwright tự nhập/click Send, nhận `OK` qua WebSocket. Đã xác minh **localhost FastAPI JSON facade: live HTTP → browser → WebSocket → response `OK` PASS**, dùng request JSON UTF-8 trên Windows PowerShell. Chưa có gateway cloud, streaming token hoặc direct inference API được xác minh. Dữ liệu browser profile và credential chỉ ở máy người nghiên cứu.

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
- [x] Xây và kiểm thử offline conversation correlator; replay V3 thực tế đạt 8/8.
- [x] Triển khai Browser Adapter prototype (manual + opt-in CSS send), kiểm thử offline bằng fake WS/UI.
- [x] Kiểm thử live Browser Adapter (manual UI send → WS reply) với phiên được ủy quyền: nhận 1/1 reply "OK".
- [x] Bổ sung read-only DOM inspector; đã xác minh nút Send trong DOM thực tế.
- [x] Xác minh editor + Send selector từ DOM thực tế sau khi nhập bản nháp (11 → 12 nearby buttons).
- [x] Auto-send Playwright trên ClickUp live PASS: 1/1 `OK`, 15 WebSocket JSON frames, không click tay.
- [x] Tạo FastAPI JSON facade localhost, auth Bearer, đơn request, mock tests trên Windows/Linux.
- [x] Live HTTP→Playwright→ClickUp→WS→JSON response E2E: request UTF-8 trên Windows PowerShell trả về `OK`.
- [x] Authenticated `/v1/session/diagnostics` so sánh conversation IDs trong bộ nhớ, **không lộ ID** (mock CI).
- [x] Chạy 2 HTTP prompts live liên tiếp: `ALPHA` → `You asked me to say ALPHA.`, `same_conversation_pairs=1`, `different_conversation_pairs=0`.
- [x] Thêm tùy chọn `--require-session`: claim-once owner token, strict conversation continuity (mock/CI).
- [ ] Live E2E strict owner mode và nghiên cứu UI tạo new chat riêng.
- [ ] Streaming/SSE, model switch tự động, quota/usage, multi-session và cloud hosting.

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

`--mode auto --confirm-send --composer-selector ... --send-selector ...` cũng đã có nhưng **chưa kiểm thử DOM thật**; chỉ sử dụng khi tự xác minh CSS selector trên Browser. Không suy diễn selector từ ảnh hoặc trace network. CI chỉ kiểm thử offline mock trên Ubuntu/Windows; **live manual/auto-send đã được kiểm chứng; HTTP gateway live, streaming và server-side model execution chưa xác minh**.


## Live Browser Adapter đã PASS — chuẩn bị auto-send

Người thực hiện đã chạy `browser_adapter.py --mode manual` trên Chromium đăng nhập ClickUp và nhận `SUCCESS`: 1 WS connection, 12 JSON WS frames, 1/1 matched AI reply, nội dung `OK`. Đây là kiểm chứng receiving path **live**, khác với offline replay; **không** chứng minh auto-send đã chạy hoặc có server/gateway API độc lập.

Để nhận diện composer và nút Send từ DOM **không chụp nội dung chat**, xem [hướng dẫn inspector](docs/14_UI_SELECTOR_INSPECTION.md):

```powershell
git pull
.\.venv\Scripts\python.exe tools\inspect_brain_ui.py
```

Mở đúng ClickUp Brain UI, nhấn ENTER trong terminal. Tool in `visible_editors` và `nearby_buttons` kèm vị trí `rect`, `aria-label`, `placeholder`, `data-testid` và CSS selector được kiểm tra unique. **Không tự động gửi tin nhắn.** User cần kiểm tra lại selector trong trình duyệt trước khi dùng `browser_adapter.py --mode auto --confirm-send`. Không gửi browser profile, cookie hoặc dữ liệu workspace riêng tư.


### Ghi nhận editor/Send sau khi có bản nháp (hai lần đọc DOM)

Kết quả inspector từ người nghiên cứu: editor duy nhất `div[contenteditable="true"]` (`stable=false`), model dropdown có `data-test="content-assistant-model-selector-dropdown__trigger"`. **Send chưa xuất hiện khi ô nhập trống**. Không dùng nút micro, attachment hay model dropdown làm Send.

Chế độ mới **không gửi tin, không đọc prompt**. Đóng Chromium cũ, chạy:

```powershell
git pull
.\.venv\Scripts\python.exe tools\inspect_brain_ui.py --after-draft
```

Nhấn Enter trong **PowerShell** lần 1 khi editor trống. Gõ `OK` trong editor của **Chromium**, **đừng Enter/click Send trên web**. Quay lại PowerShell nhấn Enter lần 2. Chỉ gửi output của `difference`, `visible_editors` và `nearby_buttons_after_draft` đã kiểm tra dữ liệu riêng tư. Tool so sánh nút mới xuất hiện/nút được enable, vẫn phải xác minh icon Send bằng mắt.

`_send_via_ui()` cũng đã được sửa để **điền prompt trước rồi mới chờ nút Send hiện lên**, và từ chối click khi selector không đúng duy nhất/visible/enabled. Auto-send chưa được xác thực live.

### Verified Send button — one-message auto E2E test

Đã quan sát **Send hiện lên sau khi nhập text**, với `data-test=refinement-prompt-submit-button`, `aria-label=Send`, `type=submit`; editor `div[contenteditable=true]`. Auto mode đã thêm fail-closed checks cho đúng các thuộc tính này và không click trước khi nút xuất hiện. Sau đó người nghiên cứu đã chạy auto E2E live thành công (1/1 reply `OK`).

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\browser_adapter.py --mode auto --confirm-send --composer-selector 'div[contenteditable="true"]' --send-selector 'button[data-test="refinement-prompt-submit-button"]' --timeout 120 --show-reply
```

Đóng Chromium cũ, mở Brain Ask trong Chromium mới, để trống editor. Nhấn Enter trong PowerShell ở bước arm, sau đó nhập `Trả lời đúng một từ: OK` khi chương trình hỏi prompt rồi nhấn Enter. **Không tự click Send bằng tay**; script sẽ fill và submit 1 lần. Nếu DOM thay đổi, tool dừng với thông báo lỗi. Xem [kết quả DOM và hướng dẫn](docs/14_UI_SELECTOR_INSPECTION.md).


## Local HTTP JSON gateway POC — ready for live acceptance test

**Đã xác nhận trong phiên ClickUp thực:** `browser_adapter.py --mode auto` tự điền prompt `Trả lời đúng một từ: OK`, click Send rồi nhận `OK` (15 WS JSON frames, matched 1/1). Code local FastAPI mới [`tools/local_gateway.py`](tools/local_gateway.py) + [hướng dẫn cài/kiểm thử](docs/15_LOCAL_HTTP_GATEWAY.md) dùng UI adapter này để cung cấp `POST /v1/chat/completions`. **ĐÃ kiểm thử HTTP gateway live với phiên ClickUp thật: trả lời `OK` sau khi gửi JSON UTF-8.**

Không hỗ trợ stream, system prompt, history JSON, đổi model qua API hay token usage. `model="clickup-ui-current"` nghĩa là model/effort đang chọn **trong browser**, không phải model ID riêng của ClickUp. Chỉ một request tại một thời điểm, key Bearer độc lập, listen `127.0.0.1`. Đây là **local thử nghiệm đã PASS một lượt live**, chưa thể chạy 24/7 trên cloud và chưa có session isolation.

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements-gateway.txt

New-Item -ItemType Directory -Force .local | Out-Null
if (-not (Test-Path .local\gateway.key)) {
  .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))" |
    Set-Content -Encoding Ascii .local\gateway.key
}
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787
```

Đóng Chromium tracer/inspector/adapter cũ trước. Khi browser mới mở, vào ClickUp Brain Ask, chọn model/effort, xong nhấn ENTER ở PowerShell để server listen. Trong **PowerShell thứ hai**:

```powershell
cd E:\Toolss\clickuptoapi
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
$headers = @{ Authorization = "Bearer $env:CLICKUP_GATEWAY_API_KEY" }
$body = @{
  model = "clickup-ui-current"
  messages = @(@{ role = "user"; content = "Trả lời đúng một từ: OK" })
  stream = $false
} | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1: transmit UTF-8 bytes, not a string body.
$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri "http://127.0.0.1:8787/v1/chat/completions" -Method Post -Headers $headers -ContentType "application/json; charset=utf-8" -Body $utf8Body
```

`.local/gateway.key` là plaintext **nhạy cảm**, đã được `.gitignore` loại trừ; không chia sẻ/upload nó. Kết quả người nghiên cứu đã xác nhận: `$response.choices[0].message.content` trả về `OK`. Chưa kiểm thử multi-turn, headless hoặc server cloud.


### Windows PowerShell HTTP 400: JSON body parse error

Nếu server đã báo `LOCAL API ready` nhưng `Invoke-RestMethod` trả `{"detail":"There was an error parsing the body"}` với prompt tiếng Việt, khả năng cao payload JSON được gửi với encoding không phải UTF-8 (cụ thể bytes của request lỗi **chưa được thu**). **Không cần khởi động lại gateway**: tạo `$utf8Body = [Text.Encoding]::UTF8.GetBytes($body)` và gửi bằng `-Body $utf8Body -ContentType 'application/json; charset=utf-8'` như ví dụ trên.

Sau `git pull`, có thể dùng luôn helper cho PowerShell 5.1/7:

```powershell
.\tools\send_gateway_request.ps1
# Hoặc truyền prompt Unicode trong terminal:
.\tools\send_gateway_request.ps1 -Prompt 'Trả lời đúng một từ: OK'
```

Script đọc key từ `.local/gateway.key`, không in key/prompt, truyền JSON UTF-8 dạng **byte array**; chỉ in nội dung câu trả lời. Nếu execution policy không cho chạy `.ps1`, ưu tiên **Python client** bên dưới, hoặc dùng `$utf8Body` trực tiếp; không cần thay đổi policy toàn máy. Xem [troubleshooting đầy đủ](docs/15_LOCAL_HTTP_GATEWAY.md).


## Live Gateway E2E — VERIFIED (28/10/2026)

Người nghiên cứu đã giữ Chromium và FastAPI ở `http://127.0.0.1:8787`, gửi `POST /v1/chat/completions` với `model=clickup-ui-current`, một message `role=user` chứa tiếng Việt, `stream=false`, xác thực Bearer. Lần đầu: request lỗi JSON body parsing trên Windows PowerShell. Sau khi đổi sang:

```powershell
$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($body)
$response = Invoke-RestMethod -Uri "http://127.0.0.1:8787/v1/chat/completions" -Method Post -Headers $headers -ContentType "application/json; charset=utf-8" -Body $utf8Body
$response.choices[0].message.content
```

Terminal trả về chính xác `OK`. Điều này xác minh **một lượt local HTTP → Playwright UI send → WS reply-created → HTTP JSON response**, không chứng minh độ bền 24/7, khôi phục phiên, streaming, multi-turn hay model switching qua HTTP. Xem [biên bản nghiệm thu và deployment gates](docs/16_LIVE_HTTP_ACCEPTANCE_AND_DEPLOYMENT_GATES.md).


### Session diagnostics để kiểm tra context giữa các request (mới)

[Roadmap cloud và tiêu chí nghiệm thu](docs/16_LIVE_HTTP_ACCEPTANCE_AND_DEPLOYMENT_GATES.md). Gateway có `GET /v1/session/diagnostics` yêu cầu Bearer key, **chỉ trả số lần reply + same/different conversation**, không trả ID hay nội dung:

```powershell
# Sau git pull, phải khởi động lại gateway để nạp code mới.
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
$headers = @{ Authorization = "Bearer $env:CLICKUP_GATEWAY_API_KEY" }
Invoke-RestMethod http://127.0.0.1:8787/v1/session/diagnostics -Headers $headers
```

Đây là công cụ chuẩn bị cho kiểm thử **hai HTTP prompts liên tiếp**: check liệu WS `conversation_id` có giống nhau sau mỗi response, **không** kiểm chứng model nhớ nội dung. Endpoint đã kiểm tra mock; dữ liệu live cho multi-turn chưa có. Không công khai gateway hay profile.


### Windows PowerShell `PSSecurityException` — Python client không cần .ps1

Người nghiên cứu đã thử hai lệnh `.\tools\send_gateway_request.ps1`, nhưng Windows **chặn file script trước khi gửi HTTP** (`running scripts is disabled on this system`). `/v1/session/diagnostics` trả `completed_replies: 0, last_relation: unobserved` vì chưa có lượt nào gửi thành công trên tiến trình gateway vừa bật. Không phải lỗi ClickUp hoặc WebSocket.

Đã bổ sung [`tools/send_gateway_request.py`](tools/send_gateway_request.py), Python stdlib client chỉ kết nối **127.0.0.1**, gửi JSON UTF-8 bytes, đọc app key từ `.local/gateway.key`, không in key hoặc raw payload. Dùng **PowerShell 2**, giữ gateway **PowerShell 1** tiếp tục chạy:

```powershell
cd E:\Toolss\clickuptoapi
git pull

.\.venv\Scripts\python.exe tools\send_gateway_request.py --prompt "Reply with the word ALPHA only."
.\.venv\Scripts\python.exe tools\send_gateway_request.py --prompt "What word did I ask you to say in my previous message?"
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

Không dùng `Set-ExecutionPolicy` hoặc mở Terminal Administrator. Với gateway đang chạy, **không cần restart** chỉ vì thêm Python client. Chờ câu trả lời request 1 xong rồi mới gửi request 2. Diagnostics nếu có 2 phản hồi thành công sẽ cho biết `last_relation=same/different/unknown`; không trả conversation ID thật. Cùng `conversation_id` **không đồng nghĩa chứng minh trí nhớ model**. Nếu gateway trả 502 / 503, xem lại browser, không tự động gửi lại prompt vì nó có thể đã được submit.


## Sticky conversation confirmed + exclusive owner mode (G-03)

[**Full findings, security model and live commands**](docs/17_STICKY_CONTEXT_EXCLUSIVE_SESSION.md). Trong live HTTP test **2 request liên tiếp**, Brain trả lời `ALPHA` và `You asked me to say ALPHA.`; `/v1/session/diagnostics` xác nhận `last_relation=same` với `same_conversation_pairs=1`. **Mỗi request API hiện KHÔNG tự tạo chat mới.**

Đã thêm **optional strict mode** để tránh client khác gửi nhầm vào cùng browser conversation. Legacy mode (không có `--require-session`) vẫn giữ nguyên cho một người dùng local. Strict mode dùng một owner capability độc lập với ClickUp token, claim một lần; không phải multi-user isolation hoàn chỉnh. **Đã PASS live 2 lượt HTTP**: claim thành công, `ALPHA` → `You asked me to say ALPHA.`, diagnostics `same=1`.

```powershell
# PowerShell 1: dừng gateway cũ và đóng Chromium; pull rồi khởi động lại
cd E:\Toolss\clickuptoapi
git pull
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --require-session
```

Đăng nhập/mở Brain² và nhấn Enter khi được hỏi, sau đó **PowerShell 2**:

```powershell
cd E:\Toolss\clickuptoapi
.\.venv\Scripts\python.exe tools\send_gateway_request.py --claim-session
.\.venv\Scripts\python.exe tools\send_gateway_request.py --prompt "Reply with the word ALPHA only."
.\.venv\Scripts\python.exe tools\send_gateway_request.py --prompt "What word did I ask you to say in my previous message?"
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

Python client không cần `.ps1` nên không gặp PowerShell ExecutionPolicy. Owner capability được lưu ở `.local/browser-owner.key` (plaintext, Git-ignored); không commit, tải lên, tiết lộ. **Nếu đã claim trong một gateway cũ**, cần dừng gateway và kiểm tra trạng thái, rồi xóa file token cũ trước khi tạo phiên mới — không ghi đè khi worker đang chạy. Chỉ kiểm thử trong session nghiên cứu của bạn. Không mở port public hoặc triển khai cloud trước khi có cách tạo chat mới/re-auth và session isolation thực sự.


### Fix Chromium luôn mở Workspace Overview thay vì Brain²

**Nguyên nhân gốc:** Gateway trước đó mặc định `--url https://app.clickup.com/`, dẫn tới trang Overview. Bản mới nhớ URL Brain đã xác minh trong `.local/brain-start-url.txt` và **tự mở thẳng Brain** ở lần khởi động kế tiếp. File này chỉ chứa đường dẫn `/WORKSPACE_ID/ai/brain`, tuyệt đối **không** lưu `?conversationId=...` hay auth/cookie. Không commit `.local/`.

Cập nhật `git pull`, dừng gateway cũ bằng `Ctrl+C`, đóng Chromium đó rồi khởi động lại. **Lần đầu sau cập nhật** nếu chưa có file nhớ URL có thể vẫn mở Overview; bạn vào Brain² Ask như bình thường và nhấn Enter tại terminal để lưu. **Lần tiếp theo** đã tự vào Brain. Nếu muốn đi thẳng ngay lần đầu:

```powershell
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --require-session --url 'https://app.clickup.com/<WORKSPACE_ID>/ai/brain'
```

Tự điền `WORKSPACE_ID` từ URL Brain trên trình duyệt của bạn, không thêm `?conversationId`. Đây là Brain landing route, không khôi phục một chat cụ thể. Cơ chế API owner token vẫn hoạt động như trước. Khi restart gateway mới, token `.local/browser-owner.key` của worker cũ sẽ không dùng lại được: dừng worker cũ và xóa **riêng file owner key cũ** trước khi `--claim-session` lại. **Giữ nguyên** `.local/gateway.key` và `.local/browser-profile/` (lưu session trình duyệt).

Xem [hướng dẫn và kiểm chứng](docs/17_STICKY_CONTEXT_EXCLUSIVE_SESSION.md).


## 9Router / OpenAI-compatible basic text mode (optional)

**NEW:** [`--router-mode`](docs/18_9ROUTER_BASIC_COMPAT.md) giữ nguyên các chế độ legacy và `--require-session` đã chạy live trước đó. Đây là một worker **riêng** cho 9Router trên cùng máy; **chưa kiểm thử kết nối 9Router thực tế**, nhưng JSON / buffered SSE và cô lập hội thoại đã qua mock CI.

Mục tiêu: **text chat qua OpenAI Chat Completions**, không phải drop-in replacement cho Codex/Claude Code đầy đủ tool-calling. 9Router custom provider phải ở cùng máy chạy Chromium/gateway, cấu hình Base URL là `http://127.0.0.1:8787/v1`, model ID `clickup-ui-current`, API type `Chat Completions`, Authorization Bearer dùng `.local/gateway.key`.

```powershell
# PowerShell 1: dừng gateway cũ, giữ nguyên .local/gateway.key + browser profile.
cd E:\Toolss\clickuptoapi
git pull
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --router-mode
```

Mở Brain trong Chromium và nhấn ENTER để bật server, sau đó PowerShell 2:

```powershell
.\.venv\Scripts\python.exe tools\check_router_compat.py
.\.venv\Scripts\python.exe tools\check_router_compat.py --stream
.\.venv\Scripts\python.exe tools\check_router_compat.py --history
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

`--router-mode` tự điều hướng tới Brain landing **mỗi request** để tách chat thay vì trộn lịch sử. Các messages có role khác `user` được **đóng gói thành transcript văn bản**, không có quyền system/developer thật. `stream=true` trả **SSE buffered một lần sau khi nhận phản hồi**; không streaming token realtime. Tool calling/multimodal/tùy chọn sampling/model switch không hỗ trợ và trả 422, token usage không bị bịa. **Không kết hợp `--router-mode` với `--require-session`** vì provider thông thường không gửi header owner đặc biệt. Không expose Internet và không dùng nhiều tài khoản.

Mốc tiếp theo: phải kiểm thử smoke test live trên ClickUp và sau đó tạo provider node trong 9Router dashboard. Toàn bộ hướng dẫn và giới hạn: [docs/18_9ROUTER_BASIC_COMPAT.md](docs/18_9ROUTER_BASIC_COMPAT.md).


### 9Router smoke test — live JSON/history PASS, SSE CLI false negative fixed

Trên ClickUp Browser Gateway live, người nghiên cứu đã chạy `check_router_compat.py`: JSON text trả `OK`, `--history` trả `ALPHA`; `--diagnostics` cho `completed_replies=3`, `same_conversation_pairs=0`, `different_conversation_pairs=2`. Ba request đã tạo ba reply/conversation khác nhau. **Lượt SSE smoke ban đầu báo fail nhưng vẫn tăng completed_replies**, nên cần kiểm tra client/parser thay vì kết luận Brain không trả lời.

**Nguyên nhân đã phát hiện trong code:** smoke CLI convert `response.headers` thành `dict` rồi tìm key `"X-Stream-Mode"`, trong khi Uvicorn gửi lowercase `"x-stream-mode"`. Đã sửa bằng chuẩn hóa tên HTTP header về lowercase, thêm regression tests với **synthetic HTTP server** trên Windows/Linux. **SSE live retry chưa được xác nhận.**

Không cần restart gateway vì fix nằm ở tool CLI. PowerShell 2:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\check_router_compat.py --stream
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

Lưu ý: `--stream` tạo một **prompt thật** và có thể tốn hạn mức. API trả SSE **buffered**, không có token streaming realtime. Sau khi test thành công mới chuyển sang kiểm chứng node Custom OpenAI Compatible trong 9Router trên **cùng máy**, xem [hướng dẫn](docs/18_9ROUTER_BASIC_COMPAT.md).


## 9Router-through-ClickUp end-to-end — next live milestone

Router-mode in ClickUp Gateway **đã PASS trên máy thật**: JSON `OK`, history `ALPHA`, SSE buffered `OK`, diagnostics `completed_replies=4`, `different_conversation_pairs=3`. **Chưa có bằng chứng request đi qua 9Router cổng 20128.**

Đã thêm [`tools/check_9router_path.py`](tools/check_9router_path.py) và [test HTTP loopback](tests/test_check_9router_path.py), dùng **một 9Router client API key riêng** với Gateway upstream key; không dùng file `.ps1`, không in secrets.

Sau khi thêm node OpenAI Compatible trong dashboard của 9Router đang chạy trên **cùng Windows host** (Prefix `brain`, Base URL `http://127.0.0.1:8787/v1`, API type `Chat Completions`, model `clickup-ui-current`), nhớ **tạo API-key connection cho node** chứ không chỉ bấm Check. PowerShell 2:

```powershell
cd E:\Toolss\clickuptoapi
git pull
# Nếu 9Router yêu cầu API key phía client, lấy từ 9Router API Keys dashboard:
.\.venv\Scripts\python.exe tools\check_9router_path.py --save-key

# Không gọi model, không tốn ClickUp credits
.\.venv\Scripts\python.exe tools\check_9router_path.py --models-only

# Mỗi lệnh sau sẽ gửi MỘT tin thật qua 9Router → Gateway → Brain
.\.venv\Scripts\python.exe tools\check_9router_path.py
.\.venv\Scripts\python.exe tools\check_9router_path.py --stream
```

`--save-key` sử dụng `getpass` và lưu riêng `.local/ninerouter.key` (Git-ignored), **không** lấy `.local/gateway.key` thay thế. Nếu 9Router local cho phép không cần key thì bỏ qua `--save-key`. Kết quả kỳ vọng `brain/clickup-ui-current` xuất hiện trong `/v1/models` của 9Router và test in `9Router -> Brain Gateway -> ClickUp: PASS`. **Cập nhật:** lượt kiểm thử JSON qua 9Router **đã PASS live**; SSE/history xuyên 9Router và reply dài chưa xác minh. Các client coding agent cần tool calling/real-time streaming còn chưa được hỗ trợ.

**Bảo mật:** 9Router từng có các lỗi bypass xác thực trên phiên bản cũ (ví dụ CVE-2026-55641 và CVE-2026-56681, đã có bản vá). Chỉ bind 9Router và Gateway vào loopback, xác minh phiên bản hiện hành và tránh tunnel/public exposure. 9Router trong Docker/cloud không thể dùng `127.0.0.1:8787` để đến Gateway trên máy Windows. Xem [doc 18](docs/18_9ROUTER_BASIC_COMPAT.md) và [GitHub Advisory](https://github.com/advisories/GHSA-86m2-fcxq-5q7c).


## 9Router port 20128 returns 401 — diagnostics (2026-10-28)

**Actual result:** `GET /v1/models` on 9Router advertises `brain/clickup-ui-current` (94 models total), but JSON/SSE `POST /v1/chat/completions` returned HTTP **401**. Direct ClickUp Gateway port 8787 has already passed JSON, SSE, history and separate-conversation live tests. Model discovery alone does **not** prove that a 9Router key can call chat.

**Do not blindly change Gateway or ClickUp credentials.** Added a safe 401 error classifier in `tools/check_9router_path.py` and numeric Gateway HTTP diagnostics (`http_chat_received`, `http_chat_401`, `http_chat_2xx`, `http_chat_other_errors`) to identify the rejecting layer without logging prompts/keys. Synthetic Windows/Linux tests cover both features.

**First try without gateway restart** (PowerShell 2):

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\check_9router_path.py
```

If it reports `invalid_api_key`, check the **9Router API key issued from its Endpoints/API Keys page**, which is **different** from the upstream Gateway key saved in 9Router's custom provider connection. You can recreate the local `.local/ninerouter.key` (and only that file) using `Remove-Item .local\ninerouter.key` followed by `check_9router_path.py --save-key`.

**More conclusive:** To use the new Gateway counters, stop/restart PowerShell 1's Gateway **after** `git pull`; run `send_gateway_request.py --diagnostics` before/after exactly one 9Router JSON request. If `http_chat_received` stays 0, 9Router rejected before forwarding; if it increments with `http_chat_401`, the **upstream connection key** in 9Router is wrong. Full commands, warnings and decision tree: [docs/19_9ROUTER_401_DIAGNOSTICS.md](docs/19_9ROUTER_401_DIAGNOSTICS.md). **Updated 2026-10-28:** 9Router→Brain JSON Chat Completions **LIVE PASS** after creating a separate 9Router client key. Older 401 text retained here for troubleshooting only.


### Khắc phục xác thực 9Router 401 khi dùng trùng key ở hai tầng

**Đã xác định lỗi cấu hình phía client:** người nghiên cứu dùng đúng cùng một giá trị `.local/gateway.key` làm upstream API key trong provider Bulk của 9Router **và** downstream client key trong `.local/ninerouter.key`. 9Router chat báo `401 invalid_api_key`. Hai khóa có hai vai trò khác nhau: 9Router cần **phát hành client API key bằng chính dashboard của 9Router**; import upstream key không cấp quyền client tự động.

Giữ nguyên upstream `.local/gateway.key` và browser profile. Vào 9Router (cổng 20128) → **API Keys / Endpoints → API Keys**, tạo và sao chép một **client key mới**, rồi chạy ở PowerShell 2:

```powershell
cd E:\Toolss\clickuptoapi
git pull
Remove-Item .local\ninerouter.key
.\.venv\Scripts\python.exe tools\check_9router_path.py --save-key
.\.venv\Scripts\python.exe tools\check_9router_path.py
```

Tool sẽ dừng **trước khi gửi request** nếu hai file key vẫn trùng nhau và không in giá trị key. 9Router client key do dashboard cấp vẫn cần đúng tiến trình đang nghe tại `127.0.0.1:20128`. Xem [diagnostics chi tiết](docs/19_9ROUTER_401_DIAGNOSTICS.md).


## Live 9Router JSON E2E — VERIFIED, next compatibility tests

**User-confirmed 2026-10-28:** after installing a separately issued 9Router client key, the actual `tools/check_9router_path.py` request through `127.0.0.1:20128` returned `9Router -> Brain Gateway -> ClickUp: PASS` and `Reply preview: OK` (3 characters). This proves the **basic JSON path** `9Router → Brain Gateway → signed-in Playwright → ClickUp Brain² → HTTP JSON` for a short prompt.

**Live 9Router route verified:** JSON, buffered `stream=true` SSE, multi-message transcript-as-text and a 606-character response (threshold-only). Still **unverified:** true generation-complete signalling, native tool calling, robust session recovery or cloud operation. These should not be described as production-ready or Codex/Claude Code replacements. Gateway port 8787 has independently passed buffered SSE/history/isolated-chat tests.

The 9Router smoke client now supports additional **opt-in** test flags, tested against mock HTTP in Windows/Linux CI. On PowerShell 2, **keep both 9Router and the `--router-mode` Gateway running**, then:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\check_9router_path.py --stream
.\.venv\Scripts\python.exe tools\check_9router_path.py --history
.\.venv\Scripts\python.exe tools\check_9router_path.py --prompt "Write five numbered sentences about HTTP and WebSocket, at least 15 words each." --min-reply-chars 200
```

Each request sends real ClickUp traffic; `--min-reply-chars` is a heuristic, **not** proof of true answer completion. More evidence, boundaries and next work: [docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md](docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md). Keep `.local/ninerouter.key` (9Router caller) and `.local/gateway.key` (Gateway upstream) distinct and private.


## 9Router extended live acceptance — SSE, history and long response PASSED

**Verified user terminal results (2026-10-28):**

| Test through 9Router :20128 | Outcome |
|---|---|
| `check_9router_path.py --stream` | `PASS`, SSE buffered, `OK`, 3 characters |
| `check_9router_path.py --history` | `PASS`, JSON `ALPHA`, 6 characters |
| Long prompt, `--min-reply-chars 200` | `PASS`, 606-character response |

The third test checks response **length**, not that the final sentence finished. Source audit confirms `chatCommentCreated` is a reply-created event, NOT a proven model-completion marker. SSE `[DONE]` is the HTTP wrapper's buffered end, not actual upstream generation completion. `finish_reason=null` remains intentional.

**New optional client-side end-marker test:** `check_9router_path.py --expect-suffix END_BRAIN_TEST` compares the end of the actual returned reply with an explicit test sentinel in the prompt. A match is stronger end-to-end transport evidence but still does not prove a terminal model event. After `git pull`, keep 9Router and Gateway running (no restart required):

```powershell
.\.venv\Scripts\python.exe tools\check_9router_path.py --prompt "Write five sentences explaining HTTP and WebSocket. At the very end write END_BRAIN_TEST and nothing after it." --min-reply-chars 200 --expect-suffix END_BRAIN_TEST
```

The new request may consume upstream allowance. See [live acceptance and remaining completion research](docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md).

**Next engineering gates:** independently verify an actual UI/WS generation-complete signal, controlled browser recovery/re-login, then test genuine function/tool calls before treating this as a coding-agent backend. Current local-only text gateway is operational, but not production/cloud ready.


## Live 9Router end-marker acceptance (2026-10-28)

The user ran an actual 9Router :20128 → local Gateway :8787 → ClickUp Brain² request with **`--min-reply-chars 200 --expect-suffix END_BRAIN_TEST`**. Observed `9Router -> Brain Gateway -> ClickUp: PASS`, `Expected response suffix observed`, **668 characters**, JSON. This is strong end-to-end proof that the **requested trailing marker** was transported. It **does not** prove an upstream end-of-generation signal. The `chatCommentCreated` event only proves creation of a matching reply comment; `finish_reason=null` and buffered-only SSE remain correct.

New **offline, read-only, metadata-only** audit tool `tools/audit_brain_completion_metadata.py` helps investigate which known candidate completion indicators appear in a *private authorized local WS capture*. It emits only fixed-key counters and never prints raw private messages, IDs, cookies or tokens. The audit does not send ClickUp requests, alter the browser, or validate a completion protocol. For an existing local private capture:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\audit_brain_completion_metadata.py artifacts\brain_v3_private_content.jsonl
```

If the trace file is missing, no additional action is required; never upload it to GitHub, ChatGPT, 9Router or CI. A zero candidate count is inconclusive. Detailed live acceptance: [docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md](docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md). Next goals remain verified completion state, controlled browser session recovery, and real tool-call interoperability rather than declaring a production-ready coding-agent backend.


## WS completion research: 602 private trace records analyzed (2026-10-28)

**Live local first-pass metadata:** 602 JSONL records, 203 inbound WS frames, 8 `aiConversationStarted`, 16 `chatCommentCreated`, 27 non-event inbound frames, 152 other events, 0 recognized terminal names/status values, 0 malformed records. This is **not** evidence that ClickUp has no terminal event. An AI start isn't the same as a completed AI response, and created comments can include user comments.

**Source-audit finding:** earlier `brain_event_decoder.py` handles `chatCommentEdited` but first-pass `audit_brain_completion_metadata.py` counted only `chatCommentUpdated`. A zero updated count missed potential edited events.

Added the **offline, read-only, privacy-safe second-pass** [`tools/audit_brain_completion_deep.py`](tools/audit_brain_completion_deep.py). It classifies those events and the remaining unknown family buckets and matches AI result IDs **only in memory**. Its output contains predefined numeric counters and constant interpretation text, not private prompts/IDs or arbitrary WS names. For the EXISTING authorized local trace:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\audit_brain_completion_deep.py artifacts\brain_v3_private_content.jsonl
```

No Gateway/9Router restart and no new ClickUp prompts are required. **Share only the aggregate JSON counters**, never the original `.jsonl` or browser profile. Whether `chatCommentEdited` occurs *after* the AI reply or signals completion still needs independent evidence. Do not change `finish_reason=null` or buffered-SSE behavior based on these heuristics. Detailed research log: [docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md](docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md).


## WebSocket completion research: live 8/8 start-to-comment correlation

Researcher-confirmed second-pass audit of private local trace (2026-10-28): 602 rows / 203 inbound WS frames; 8 AI starts, 16 chat comments (8 with AI IDs, 8 without); **8/8 AI IDs matched**, 13 `chatCommentEdited` events with neither AI result IDs nor changed comment fields; 49 unknown chat-family events, 90 uncategorized. **No verified final-generation signal**. The 13 edits are NOT proven AI terminal markers.

Added a non-invasive, **local-only, metadata-only** `tools/audit_brain_event_timeline.py` and synthetic tests to examine event shapes, temporal proximity and safe name-family counters. It does not print raw IDs, unknown event names, timestamps, prompts, credentials or response text. This checks *hypotheses*, never upgrades the Gateway's `finish_reason=null` or buffered-SSE semantics.

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\audit_brain_event_timeline.py artifacts\brain_v3_private_content.jsonl
```

No browser restart or AI request. Keep the trace PRIVATE; only share the resulting counter JSON. Evidence and caveats: [docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md](docs/20_9ROUTER_LIVE_JSON_ACCEPTANCE.md).
