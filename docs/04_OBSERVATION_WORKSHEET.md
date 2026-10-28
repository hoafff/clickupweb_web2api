# 04 — Worksheet thực nghiệm Web → API (authorized research)

> Chỉ ghi bằng chứng nghiên cứu trong phạm vi cho phép. **Bằng chứng công khai phải redact**: header Authorization/Cookie/CSRF, URL có query token, nội dung prompt/tài liệu cá nhân, workspace ID, user ID, HAR thô. Có thể inspect toàn bộ payload **nội bộ** nếu scope cho phép và lưu trong kho riêng được bảo vệ.

## Header của từng phiên đo

| Field | Giá trị |
|---|---|
| Thời gian / timezone | |
| Reviewer | |
| Research scope / ticket tham chiếu | |
| Workspace / account type (không đưa ID) | |
| Browser / extension state | |
| Version giao diện (nếu có) | |
| Test case ID | |
| Model UI selected | |
| Status | `Observed / Inferred / Not tested / Failed` |
| Evidence path (đã mask) | |

## Kịch bản đo A — network/transport

| Step | Thao tác UI thủ công | So sánh trong Network |
|---|---|---|
| A0 | Mở Brain, chưa chat | Baseline requests, config/metadata |
| A1 | Prompt đầu tiên với Brain² Max | Request mới, payload keys, response content-type và timing |
| A2 | Prompt thứ 2 cùng chat | Session/turn/cursor thay đổi |
| A3 | New chat + cùng prompt | ID first-turn và session reset |
| A4 | Chọn Claude Opus 5.5 và cùng prompt | Thay đổi model selector field |
| A5 | Chuyển từ Claude sang GPT trong cùng chat | Conversation continuity và state |
| A6 | Bật tùy chọn Skills/attachment trong scope | Request phụ / tool chain |
| A7 | Chờ model trả lời xong | End-of-stream marker, usage/finish_reason |
| A8 | Stop/cancel nếu UI hỗ trợ | Upstream cancel và trạng thái conversation |

**Dùng prompt vô hại**, ví dụ “Trả lời đúng một từ: ping”. Không lấy dữ liệu khách hàng thực nếu không cần thiết.

## Kịch bản đo B — multi-model

Ảnh menu từ người dùng 28/10/2026 hiển thị:

| UI label | Đã thấy | Có phản hồi khi chọn | Model field trên wire | Streaming verified | Ghi chú |
|---|---|---|---|---|---|
| Brain² Max | Có, selected | Not tested | Unknown | Unknown | |
| Claude Opus 5.5 | Có | Not tested | Unknown | Unknown | |
| Claude Opus 5 | Có | Not tested | Unknown | Unknown | |
| Gemini 4 Argon | Có | Not tested | Unknown | Unknown | |
| GPT-6.1 Sol | Có | Not tested | Unknown | Unknown | |
| GPT-6.1 Terra | Có | Not tested | Unknown | Unknown | |
| Model ở Show more | Chưa có ảnh | Not tested | Unknown | Unknown | |

Lưu **UI label** và **wire model ID** riêng nhau. Nếu upstream có auto-routing, ghi cả requested vs resolved vs reported. Không suy đoán ID từ tên nhãn.

## Bảng candidate endpoint (không chèn secret)

| Method | Host/path đã mask | Resource type | UI step | Content-Type | HTTP code | Payload top-level keys | Event protocol | Confidence |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

Với mỗi endpoint ứng viên: xác định lần đầu xuất hiện, quan hệ với những request khác, status, retry behavior, session continuity và lỗi. Không coi bất cứ request XHR nào là endpoint chat chỉ vì xuất hiện cùng lúc với prompt.

## Các giả thuyết cần chứng minh hoặc bác bỏ

- [ ] Mỗi lần gửi prompt tạo một HTTP POST / WS message mới.
- [ ] Response streaming qua SSE / NDJSON / WebSocket / fetch chunks / polling.
- [ ] Cùng conversation dùng stable conversation ID.
- [ ] Thay model giữa chat giữ conversation reference.
- [ ] Provider báo resolved model hoặc chỉ báo selected label.
- [ ] UI lưu recent chat qua API riêng.
- [ ] Có endpoint file upload/attachment tách với chat.
- [ ] Stop generating tạo cancel request hay chỉ hủy reader.
- [ ] 401/403/429 được phản hồi và có retry logic.
- [ ] Có anti-duplication/idempotency key để tránh nhân bản prompt khi retry.
- [ ] UI model picker được tải động từ server theo account/plan.

## Quản lý kết quả

- Chạy tracer metadata: `python tools/trace_browser.py --url https://app.clickup.com/`
- Tổng hợp endpoint: `python tools/summarize_trace.py artifacts/network_events.jsonl`
- Khi cần mở payload thật: DevTools browser research, chỉ lưu tại kho bí mật được duyệt; đưa vào repo **fixture giả hoặc schema đã mask**, không commit HAR/cookie/raw URL/query/token.
- Mỗi kết luận nêu `evidence / observed at / inference / remaining unknowns`.
- Nếu observed protocol khác với giả thuyết, **sửa architecture theo trace** chứ không sửa trace theo mong muốn.

## Exit criteria

Một endpoint/transport được đánh dấu **Verified** chỉ khi có 2+ lượt thử nhất quán, mapping được một thao tác UI cụ thể với request/response, model selection và continuation. Thay đổi UI/version yêu cầu kiểm thử regression.
