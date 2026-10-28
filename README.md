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
- [ ] Chạy tracer với phiên ClickUp được cấp quyền, thu bằng chứng đã redacted.
- [ ] Xác nhận endpoint, payload, transport, conversation identifiers và chọn model qua thực nghiệm.
- [ ] Xây và test adapter theo schema đã xác nhận.
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
