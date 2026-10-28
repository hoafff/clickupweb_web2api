# 08 — Phân tích trace ClickUp Brain² ngày 28/10/2026

**Nguồn:** `network_events.jsonl` do chủ Workspace cung cấp sau khi thao tác chat trên phiên trình duyệt được ủy quyền. **Không commit file raw**; báo cáo này chỉ ghi metadata tổng hợp, không ghi Workspace ID, Conversation ID, cookie, session token hoặc prompt cá nhân.

## 1. Phạm vi và số liệu đo

| Chỉ tiêu | Quan sát |
|---|---|
| Time UTC | 2026-10-28 05:07:31 → 05:14:41 |
| Giờ Việt Nam | 12:07:31 → 12:14:41 |
| Tổng events | 3.437 |
| HTTP requests / responses / finished / failed | 1.115 / 1.114 / 1.114 / 1 |
| Unique (method, redacted URL) trong source trace | 587 |
| HTTP response 200 / 201 / 206 / 404 / 401 | 1.087 / 20 / 3 / 3 / 1 |
| WebSocket open | 1 |
| WS frames sent / received | 17 / 75 |
| WS bytes sent / received | 1.457 / 100.799 (độ dài frame theo tracer) |
| `text/event-stream` response nhìn thấy trong trace | 0 |
| Browser/CDN JS responses | Nhiều (809 `text/javascript`) |

**Nguồn bằng chứng:** dữ liệu `http_request`, `http_response`, `http_finished`, `ws_open`, `ws_frame` trong trace. Counter dựa trên metadata, không chứng minh backend không dùng SSE: tracer lọc host `clickup.com` và không capture stream body.

## 2. Ứng viên request liên quan Brain chat

Hai request có thời điểm trùng lượt gửi chat trong screenshot:

| Local time | Method | Redacted path | HTTP | Request JSON key paths đáng chú ý |
|---|---|---|---|---|
| 12:14:08 | POST | `/comment-service/v3/workspaces/{id}/comments/view/{id}` | 201 JSON | `comment`, `comment[].text`, `comment_type_data`, `comment_type_data.query`, `parent`, `root_parent_id`, `comment_date` |
| 12:14:26 | POST | `/comment-service/v3/workspaces/{id}/comments/comment/{id}` | 201 JSON | Cùng nhóm key path như trên |

Sau lượt đầu có `POST /comments/delta/0`, và sau cả hai lượt có `POST /comments/bulk`, `PUT /comments/last_read_at` / WebSocket frames. Các request `comment-service` có khả năng thực hiện **ghi/lưu lượt chat**; cần kiểm chứng với payload thực (chỉ bên trong môi trường nghiên cứu), vì screenshot + metadata **không thể chứng minh** chúng gọi model inference.

## 3. Kết nối WebSocket ứng viên

```text
wss://frontdoor-prod-ap-southeast-1-1.clickup.com/ws
```

- 1 WS được mở vào 12:13:26 (lúc UI đang tải).
- Có outgoing frame ngay trước khoảng 12:14:08 và 12:14:25; các inbound frame kế tiếp đồng thời với thao tác gửi chat.
- Payload text nhưng logger chỉ lưu length. **Chưa biết** các frame này là streaming tokens, comment updates, presence, notification hay realtime status.
- Tổng 75 inbound frames, ~100 KB được tracer thống kê; **không đồng nhất** với AI-generated output.

## 4. Endpoint phân biệt với Brain chat

- `GET /ai/v1/workspaces/{id}/recentPrompts`: xuất hiện một lần khi mở UI (12:13:36). Có thể là prompt gợi ý/gần đây; **không** xác nhận là endpoint tạo câu trả lời.
- `/chat/v1/workspaces/{id}/chat/rooms*`: xuất hiện nhiều lần trong startup; có thể thuộc ClickUp Chat room, không suy diễn là Brain chat.
- `/entitlements/`, `/billing_usage/rules/ai_tools_usage`: scope/usage metadata, không phải bằng chứng model inference.
- `io.web.clickup.com` telemetry; các JS/CSS CDN không tính như inference API.

## 5. Nhận định mức độ tin cậy

| Giả thuyết | Bằng chứng | Confidence |
|---|---|---|
| Hai lượt chat tạo hai `POST comment-service` | Timestamp, schema fields và screenshot UI | **Medium–High** |
| Chat được persisted theo comment thread | View first turn + comment reply + delta/bulk | **Medium** |
| Model reply phân phối qua shared WS | WS frames đồng thời với chat; chưa có frame nội dung | **Low–Medium** |
| Protocol SSE | Chưa thấy response `text/event-stream` | **Unknown**, không chứng minh phủ định |
| Model selector wire ID của Max/Opus | Trace không ghi giá trị body | **Unknown** |
| Direct HTTP proxy có thể hoạt động | Chưa có transport/auth/response contract | **Not verified** |

## 6. Điểm cần kiểm chứng ngay

1. Chạy **trace thứ hai** chỉ sau khi đăng nhập xong; dùng marker tách từng hành động: `max_first`, `max_followup`, `opus_switch`.
2. Quan sát tại DevTools Network những request `comment-service`, xem **schema** request/response và cách xác nhận/đồng bộ reply; **không đưa token, nội dung chat cá nhân hay raw HAR lên repo**.
3. Đo WS frame **structure only** bằng tracer mới khi đã được cho phép, để xác định frame type/channels và candidate event.
4. So sánh first-turn `/comments/view/{id}` vs continuation `/comments/comment/{id}`.
5. Nếu response thực sự qua WS, xác định correlation ID / event type / end event, không gán mặc định WS = AI output.
6. Đo thay model UI nhưng **không gửi** và sau đó **có gửi** để tìm model selection được lưu client hay wire.

## 7. Cập nhật trạng thái

**Đã hoàn thành:** Static survey, tool setup, user thực nghiệm mạng 1 lần, tìm 2 candidates và 1 WS candidate.

**Chưa hoàn thành:** xác định JSON value schema, model IDs, auth lifecycle, response transport, end-event, adapter runtime.

**Bước tiếp:** thu trace v2 + DevTools evidence đã redacted, rồi implement `CommentTransport` và event decoder dựa trên schema đã quan sát. **Không invent endpoint inference mới**.

> Bảo mật: log cũ có path ID dạng ngắn chữ+số chưa được mask bởi tracer phiên đầu. Báo cáo này đã thay các giá trị đó bằng `{id}`. Cần cải tiến `sanitize_url` trước lần capture tiếp theo.
