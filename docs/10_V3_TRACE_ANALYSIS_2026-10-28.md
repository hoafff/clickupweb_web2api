# ClickUp Brain² — V3 trace analysis (2026-10-28)

> Nguồn: ba file người dùng cung cấp: `brain_v3_meta.jsonl`, `brain_v3_private_content.jsonl`, `brain_v3_summary.json`. **Chỉ commit tổng hợp kỹ thuật**. Không đưa JSONL thô, nội dung chat, identifiers, cookies, tokens, workspace data vào Git. Phân tích này là quan sát **một phiên** với account nghiên cứu; chưa có một Brain² direct HTTP inference API được chứng minh.

## 1. Tổng quan được xác minh

- UTC timeline: 2026-10-28 05:34:39–05:40:26 (~347 giây; UTC+7: 12:34–12:40).
- 4,046 events gồm 1,270 HTTP request, 1,262 response, 1,262 requestfinished, 8 failed, 235 WS frame, 1 WS open, **8 manual markers**.
- Private capture: 602 records = 163 HTTP request JSON, 212 HTTP response JSON, 219 WebSocket JSON frames, 8 markers.
- `brain_v3_summary.json` tạo bởi PowerShell `>` có encoding **UTF-16 LE**. JSON vẫn hợp lệ khi đọc với UTF-16, không phải lỗi dữ liệu.
- `/ws` thấy các event names: `aiConversationStarted` (8), `chatCommentCreated` (16), `chatCommentEdited` (13), `chatLastReadAtUpdated` (49), `badgeCountUpdated` (49), `notification` (41). Các frame khác có heartbeat và method dạng comment/view. Số lượng cụ thể lấy từ `ws_frame_content` đã parse; không mặc định chúng là token stream.

## 2. Marker lặp không làm hỏng log

Phải phân đoạn theo **thứ tự marker**, không chỉ group bằng label (vì `opus_low` và `opus_auto` lặp). Bảng ở đây tách thành pha `#1`–`#8`; timestamp chỉ cho biết vùng quan sát, không phải thời điểm chính xác backend chọn model.

| Pha | UI marker | HTTP request chat ứng viên | WS `aiConversationStarted` | Model + effort theo telemetry khi **gửi** |
|---|---|---|---:|---|
| #1 | `max_first` | POST `/comments/view/{opaque}`, 201 | 1 | `brain` |
| #2 | `max_followup` | POST `/comments/comment/{opaque}`, 201 | 1 | `brain` |
| #3 | `opus_switch` | POST `/comments/comment/{opaque}`: **1 failed**, **1 returned 201** | 1 | `claude-opus-5-5`, `medium` |
| #4 | `opus_auto` | POST `/comments/view/{opaque}`, 201 | 1 | Chỉ thấy chọn `claude-opus-5-5`; không có đủ telemetry của sự kiện **use** để xác nhận effort |
| #5 | `opus_low` lần 1 | POST `/comments/view/{opaque}`, 201 | 1 | UI click `low`, nhưng sự kiện **use** báo `brain`, không đủ chứng cứ request đã chạy Opus Low |
| #6 | `opus_low` lần 2 | POST `/comments/view/{opaque}`, 201 | 1 | `claude-opus-5-5`, `low` |
| #7 | `opus_medium` | POST `/comments/view/{opaque}`, 201 | 1 | `claude-opus-5-5`, `medium` |
| #8 | `opus_auto` lần 2 | POST `/comments/view/{opaque}`, 201 | 1 | `claude-opus-5-5`, `auto` |

**Kết luận:** bấm lại mark là đúng hướng xử lý. Giữ lại pha #6 và #8 làm mẫu quan sát cho Low và Auto; #5 là **misconfigured/inconclusive sample**. Pha #3 là ví dụ có failure + retry/success; không thể quy lỗi chắc chắn cho backend, mạng hay UI từ metadata này.

## 3. Cơ chế quan sát được, confidence

### A — JSON persistence/command

HTTP `POST /comment-service/v3/workspaces/{id}/comments/view/{opaque}` xuất hiện cho tin nhắn đầu tiên ở các chat mới. Lượt tiếp theo hoặc đổi model trong conversation dùng `POST /comment-service/v3/workspaces/{id}/comments/comment/{opaque}`. Request JSON chứa top-level `comment`, `comment_type_data.query`, `parent`, `root_parent_id`, `root_parent_type` và vài trường đồng bộ.

**Confidence: High** về tương quan thao tác UI ↔ POST comment trong phiên này. **Chưa** chứng minh đó là inference endpoint trực tiếp hay đủ để tái tạo Brain API.

### B — WebSocket lifecycle

Quan sát `aiConversationStarted` 8 lần, **mỗi marker pha một lần**, với các field dạng opaque `conversation_id`, `ai_result_id`, `invoke_comment_id` trong `event.payload`. Có `chatCommentCreated` và `chatCommentEdited` ở các pha; event khác gồm notifications và badge updates.

`chatCommentCreated` có `version_event_data.changes[]` chứa field `comment`, `conversation_id`, `ai_result_id`, `idempotency_key` trong một số event. `chatCommentEdited` có `changes: []` trong bản ghi. Không có bằng chứng WS frames này chứa **delta token streaming**; có thể là signals đồng bộ conversation/comments.

**Confidence: High** về event names và schema trong phiên; **Unknown** về toàn bộ transport AI content.

### C — Model and Thinking Effort

Ở HTTP telemetry `POST /v1/t` (host analytics), các keys `properties.aiModel` và `properties.reasoningLevel` cho thấy:

- Max: `aiModel: brain`.
- Claude Opus 5.5: `aiModel: claude-opus-5-5`.
- Thinking options: `reasoningLevel: low/medium/auto`.
- Hành động `use open ai feature` được dùng để phân biệt **đã gửi** với chỉ `click ai modal item`.

Có `comment_threads[].thread_ai_models[].models[]` và `comments[].data.comment_type_data.model` trong một số responses, gồm `auto` hoặc `claude-opus-5-5`. Các trường này là metadata quan sát được, **không chứng minh** bản thân request tạo AI dùng cùng tên key. Không dùng telemetry endpoint để gọi chat.

**Confidence: High** cho frontend telemetry model/effort; **medium/unknown** cho model execution và effort wire contract.

### D — Missing pieces

- Chưa xác định chuẩn request/response tạo nội dung AI hoàn chỉnh và model-routing contract.
- Không thấy response `text/event-stream` trong metadata host clickup.com; **không chứng minh hệ thống không stream** (có thể ở transport khác / background).
- Chưa có bằng chứng về usage token, tool routing, memory, file attachments.
- Không kiểm thử API replay/direct-client; trạng thái adapter: **NOT IMPLEMENTED**.

## 4. Correlation IDs phát hiện event vượt qua marker

Đã đối chiếu **trong bộ nhớ**, không đưa giá trị ID ra ngoài, các trường:
- `aiConversationStarted.event.payload.ai_result_id`, `conversation_id`;
- `chatCommentCreated.event.version_event_data.changes[].field/after` khi `field` là `ai_result_id` hoặc `conversation_id`.

Kết quả: **7/8** `aiConversationStarted` tìm thấy `chatCommentCreated` cùng `ai_result_id` và `conversation_id` **trong đúng khoảng pha**, trường hợp còn lại **không mất**: sự kiện liên quan được ghi trong pha **kế tiếp**.

Chi tiết: lượt bắt đầu ở `opus_low#5` lúc **05:38:25.569 UTC**, còn `chatCommentCreated` tương ứng được ghi lúc **05:38:59.085 UTC**, **sau marker `opus_low#6`** (05:38:56.579 UTC). Vì vậy marker không phải boundary hoàn tất bất đồng bộ; chỉ dùng timestamp để gom WS events có thể gán sai. **Cần join theo ID trong bộ nhớ** rồi mới xuất báo cáo đã bỏ IDs.

**Điều này nâng mức tin cậy** rằng WebSocket đảm nhiệm các sự kiện lifecycle AI ↔ comment; nhưng `chatCommentCreated` vẫn không đủ bằng chứng chứng minh đây là delta-token stream hay đã kết thúc suy luận.

## 5. Kiểm tra bảo mật

Dù tracer có best-effort redaction, JSON private có thể vẫn chứa **analytics writeKey, user/workspace IDs, conversation IDs, message text và metadata**. Tuyệt đối không commit file private JSONL hay gửi công khai. Bản V4 nên bổ sung redaction `writeKey`, thông tin định danh và bộ xuất báo cáo chỉ chứa key paths + các giá trị model/effort cần nghiên cứu. Cần review cả file summary trước khi public vì masked URL có thể chứa các đoạn path không ngẫu nhiên.

## 6. Next priorities

1. Mở rộng analyzer để tự gắn `label#n` theo marker occurrence, nhận diện `click` vs `use`, HTTP failure vs 201, các WS AI lifecycle events.
2. So sánh response/WS event chain cùng `conversation_id` và `ai_result_id` chỉ trong bộ nhớ cục bộ; **không công bố opaque IDs**.
3. Kiểm chứng model effort có truyền qua schema của chat hay chỉ được lưu vào cấu hình UI/session trước đó; không suy diễn từ telemetry.
4. Thiết kế **adapter sau khi xác nhận** contract/scope; chưa tuyên bố API Brain² chạy được.
