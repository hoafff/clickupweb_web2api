# 02 — ClickUp Brain²: phạm vi, bằng chứng và giả thuyết giao thức

> **28/10/2026.** Người thực hiện cho biết có **ủy quyền nghiên cứu Web → API**. Tài liệu này chuyển từ quyết định “chờ official endpoint” sang **kế hoạch kiểm chứng thực nghiệm**, nhưng không nhận việc đã được ủy quyền là bằng chứng tự thân về nội dung/phạm vi chấp thuận. Cần ghi rõ scope của phía cấp quyền trong nhật ký nội bộ.

## Quan sát đã có

- Ảnh #1: URL `app.clickup.com/.../ai/brain`, Brain², Ask, Agents, Skills, Memory, recent chats và selector `Max`.
- Ảnh #2: selector đang mở, thấy `Brain² Max`, `Claude Opus 5.5`, `Claude Opus 5`, `Gemini 4 Argon`, `GPT-6.1 Sol`, `GPT-6.1 Terra`, `Show more`. **Chưa quan sát các model bên dưới Show more.**
- [ClickUp chọn AI model](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model): có thể đổi model giữa một conversation, giữ conversation history và Workspace context.
- [ClickUp Brain Help](https://help.clickup.com/hc/en-us/articles/28401383762455-Chat-with-Brain): có Skills, context/mentions và một số khả năng gắn attachment tùy model/plan.
- Không ảnh nào chứa DevTools Network hoặc response body. **Chưa thể xác định URL endpoint, HTTP method, headers bắt buộc, body schema, event protocol hoặc stable model ID.**

## Cơ chế phải bóc tách

### 1. Vòng đời chat

Đo 4 lượt được lặp lại: (a) mở trang, (b) chat đầu với Max, (c) chat tiếp cùng hội thoại, (d) đổi model và chat tiếp. Gắn timestamp UI `T0`–`Tn` để so sánh với Network. Phân biệt request khởi tạo page, lấy workspace/memory, gửi prompt, stream phản hồi và lưu chat history.

### 2. Model selection

Với mỗi label UI, so sánh **chỉ một biến** (model) giữa 2 lượt chat có cùng input vô hại. Phân tích thay đổi ở URL, JSON fields và header *không nhạy cảm*. Ghi rõ `selected_label`, `resolved_model_field` (nếu có), `response_reported_model` (nếu có), `fallback` và trạng thái kiểm chứng. **Không suy đoán Brain Max tương ứng model bên ngoài nào.**

### 3. Conversation state

Cần xác định có `conversation_id`, `message_id`, `parent_id`, `turn_id`, continuation cursor hoặc các token state khác hay không, bằng cách so sánh **schema đã loại dữ liệu nhạy cảm** của lượt #1/#2/new chat. Trạng thái cuộc chat gốc có thể nằm ở server, browser hoặc kết hợp. Không tự đặt tên field rồi tuyên bố giống thực tế.

### 4. Streaming

Phân loại `text/event-stream`, `application/x-ndjson`, `fetch` streaming binary, WebSocket hoặc polling từ bằng chứng. Với SSE: xác nhận event delimiter, fields, termination và error; với WebSocket: phân biệt frame server/client và message shapes; với fetch: chunk decoder. Đọc response với giới hạn an toàn và mask prompt/ID/token.

### 5. Auth/session

Đánh dấu loại auth (cookie/OAuth/CSRF/Bearer nếu giao thức thể hiện), thứ tự phát sinh và điều kiện hết hạn. Credential chỉ xử lý trong profile/secret store nội bộ được phép; **không đưa secret hoặc HAR gốc vào repository public**. Tracer mặc định **không lưu header hay body**.

### 6. Workspace features

Quan sát khả năng chọn context, Skills, Memory, Agents, upload file và deep mode. Không tự xem chúng là cùng một endpoint với text chat; mỗi khả năng cần matrix riêng và scope phù hợp.

## Phân loại bằng chứng

| Nút hỏi | Trạng thái | Bước kiểm chứng |
|---|---|---|
| Menu multi-model | UI-confirmed | Xem Show more và ghi label chính xác |
| Model switch giữa chat | Documented | Test thủ công trong Workspace nghiên cứu |
| Public chat REST API cho Brain² | Unknown | Tìm developer docs và hỏi nhà cung cấp |
| Private request tạo chat tồn tại | Unknown | Browser DevTools request correlation |
| Transport SSE/WS/JSON | Unknown | Network timeline + framing |
| Stable model ID mapping | Unknown | Thử 2 model, diff payload |
| Conversation ID/parent ID | Unknown | Diff first-turn vs continuation |
| Auth refresh semantics | Unknown | Quan sát session hợp lệ và lỗi có kiểm soát |
| Quota và server-side concurrency | Unknown | Xác nhận từ allowance/docs/traces, không stress vô hạn |
| Brain Max là fixed provider | Unknown | Không suy diễn label thành provider ID |

## Kiểm soát phạm vi nghiên cứu

Người dùng xác nhận được ủy quyền nghiên cứu. Điều đó **cho phép lập kế hoạch kỹ thuật**, thay vì chặn mọi phương án trực tiếp. Tuy nhiên [ClickUp Terms](https://clickup.com/terms) có điều khoản riêng về reverse engineering và private API: phạm vi ủy quyền cần được nhà cung cấp hoặc bên có đủ thẩm quyền xác lập; quyền sở hữu Workspace không tự động miễn trừ mọi điều khoản. Nghiên cứu không được giả định có quyền vượt scope, né anti-bot hay vượt quota.

Các ràng buộc không phải “giới hạn nhân tạo” được giữ lại: cô lập tài khoản/Workspace nghiên cứu, bảo vệ secrets, giới hạn tốc độ theo thực tế, lưu bằng chứng đã redacted, không công bố payload khách hàng và không làm gián đoạn dịch vụ.

## Tiêu chí hoàn tất feasibility

- Có mapping UI action → request → response bằng quan sát thực tế.
- Có ít nhất 2 model được đo (Max + 1 model ngoài) và một hội thoại chuyển model.
- Có schema redacted và mẫu nhận dạng transport, end-of-stream, lỗi, metadata.
- Có giả thuyết session được đánh dấu đã chứng minh/bác bỏ.
- Có quyết định kỹ thuật rõ: `browser-ui-adapter`, `protocol-adapter` hoặc `official-api-fallback` dựa trên bằng chứng và phạm vi sử dụng được phép.

Kết quả triển khai đầu tiên sẽ là **research tooling + evidence**, chưa tự gắn nhãn “ClickUp Brain API hoạt động” cho tới khi đã test.
