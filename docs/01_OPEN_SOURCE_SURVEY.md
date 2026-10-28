# 01 — Khảo sát mã nguồn mở Web → API

> Cập nhật: 28/10/2026. Đây là **đọc mã nguồn tĩnh** (README, cấu trúc, file nguồn), **chưa chạy thử** các project, chưa thử các endpoint ClickUp nội bộ.

## Bảng so sánh 5 project

| Repo | Cơ chế được quan sát | Bằng chứng trong code | Bài học cho adapter | License |
|---|---|---|---|---|
| [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) | Async HTTP/RPC + trạng thái phiên web | [client.py](https://github.com/HanaokaYuzu/Gemini-API/blob/master/src/gemini_webapi/client.py) init, refresh, watchdog; [chat_mixin.py](https://github.com/HanaokaYuzu/Gemini-API/blob/master/src/gemini_webapi/components/chat_mixin.py) lịch sử hội thoại | Tách session, protocol parser, conversation state | AGPL-3.0 |
| [ntthanh2603/gemini-web-to-api](https://github.com/ntthanh2603/gemini-web-to-api) | Go provider adapter → JSON/SSE API | [provider_interface.go](https://github.com/ntthanh2603/gemini-web-to-api/blob/main/internal/modules/providers/provider_interface.go) Provider/ChatSession; [openai_controller.go](https://github.com/ntthanh2603/gemini-web-to-api/blob/main/internal/modules/openai/openai_controller.go) API và stream; [gemini_chat_session.go](https://github.com/ntthanh2603/gemini-web-to-api/blob/main/internal/modules/providers/gemini_chat_session.go) IDs | Interface, session metadata, output formatter | MIT |
| [Sozbo-Tang/openwebui-chat2api](https://github.com/Sozbo-Tang/openwebui-chat2api) | Browser bootstrap rồi gửi tới **native API** Open WebUI | [chat2api.py](https://github.com/Sozbo-Tang/openwebui-chat2api/blob/main/chat2api.py) login, token cache, refresh-on-401, SSE framing | Dùng API được hỗ trợ thay vì mô phỏng browser toàn thời gian | MIT |
| [Amitk003/chatgpt-web-to-api-expose-reverse-engineering](https://github.com/Amitk003/chatgpt-web-to-api-expose-reverse-engineering) | Hai đường độc lập: DOM automation và direct HTTP protocol | [browser.py](https://github.com/Amitk003/chatgpt-web-to-api-expose-reverse-engineering/blob/main/chatgpt/browser.py); [driver.py](https://github.com/Amitk003/chatgpt-web-to-api-expose-reverse-engineering/blob/main/chatgpt/driver.py); [server/api.py](https://github.com/Amitk003/chatgpt-web-to-api-expose-reverse-engineering/blob/main/server/api.py) | So sánh tính bền UI với trực tiếp protocol; lock phiên để tránh trộn chat | MIT |
| [lanqian528/chat2api](https://github.com/lanqian528/chat2api) | FastAPI router + upstream chat service + streaming | [api/chat2api.py](https://github.com/lanqian528/chat2api/blob/main/api/chat2api.py) StreamingResponse/scheduler; [chatgpt/ChatService.py](https://github.com/lanqian528/chat2api/blob/main/chatgpt/ChatService.py) | Định nghĩa ranh giới router, service, authentication, response mapping | MIT |

**Không sao chép mã nguồn trực tiếp**, vì các dự án có điều kiện license khác nhau; nghiên cứu cách thiết kế ở mức kiến trúc. Việc một repo có thể truy cập giao thức web của một dịch vụ **không** có nghĩa các giao thức đó được nhà cung cấp cho phép khai thác.

## 6 kỹ thuật rút ra

### 1. Kênh giao tiếp (transport)

- **Official HTTP/MCP:** service có hợp đồng chính thức, OAuth hoặc token, endpoint có tài liệu. Ưu tiên.
- **Browser-driven:** tương tác qua UI và đọc kết quả hiển thị; DOM có thể thay đổi; đắt tài nguyên; chỉ trong môi trường được cho phép.
- **Web protocol/RPC:** chuyển payload nội bộ và giải mã response; thường nhanh nhưng dễ gãy khi phiên bản web thay đổi, và có nguy cơ vượt quá quyền sử dụng.

Không có bằng chứng từ các repo trên về cấu trúc wire protocol của ClickUp Brain².

### 2. Xác thực và vòng đời phiên

Model trạng thái tổng quát: `UNCONFIGURED → AUTHENTICATED → EXPIRED → REAUTH_REQUIRED`; phân biệt `401` (auth) với `403` (permission), `429` (rate limit).

Từ source: Gemini-API giữ cookies/access token/refresh task; OpenWebUI bridge xác thực bằng trình duyệt rồi sử dụng native API. Playwright khuyến cáo `storageState` có dữ liệu cho phép tái sử dụng phiên, cần coi như **mật khẩu**. Không commit file này.

### 3. Quản lý hội thoại

Schema nội bộ đề xuất:
`local_conversation_id`, `provider_conversation_id`, `provider_response_id`, `active_model_alias`, `model_label`, `workspace_scope`, `created_at`, `updated_at`.

Chỉ lưu ID opaque do provider **thật sự trả về**. Không khẳng định ClickUp có bất kỳ tên field nào trong schema này. Mỗi conversation nên có lock/bộ điều phối để tránh xung đột.

### 4. Multi-model dispatch (điểm cần lưu ý với ClickUp)

- Không hardcode `Max` thành model duy nhất.
- Trình quản lý `ModelRegistry` ánh xạ tên hiển thị của giao diện với **alias nội bộ** và adapter được phép, không dự đoán upstream model ID.
- `ModelRegistry` lưu nguồn, thời điểm kiểm chứng, quyền sử dụng và trạng thái `available / unavailable / unknown`.
- Client gửi `model`; service phải **thực sự** lựa chọn model đó hoặc trả lỗi rõ. Không âm thầm dùng model khác mà báo như đúng model yêu cầu.
- Có thể đổi model **trong cùng hội thoại**, nhưng phải giữ history và scope; kiểm tra capability từng model (file, ảnh, tìm web, công cụ, streaming).
- Danh sách model động và tùy workspace/gói; model label có thể thay đổi theo thời gian. Xem [ClickUp Help](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model).

### 5. Streaming & event decoder

Chưa biết ClickUp dùng SSE, WebSocket, long polling hay JSON một lần. Cần xác định **trong phạm vi quyền được cấp**, không suy đoán protocol từ screenshot.

Nếu backend hợp lệ trả SSE: giữ `text/event-stream`, ngăn cách sự kiện bằng dòng trống, hỗ trợ nhiều dòng `data:`, stop tại sentinel kết thúc theo contract, hủy luồng khi client disconnect, xử lý dữ liệu UTF-8 phân mảnh. Tham khảo [MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) và `openwebui-chat2api` đoạn SSE passthrough.

### 6. API facade

Một adapter có thể expose `GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions` (JSON/SSE) khi provider hỗ trợ và được cấp phép. Chuẩn hóa lỗi `invalid_model`, `permission_denied`, `upstream_rate_limited`, `upstream_unavailable`, `stream_interrupted`. Có API key gateway độc lập, log redaction, giới hạn concurrency/rate limit phía mình.

## Đánh giá quyết định

| Tiêu chí | Public API/MCP | Browser automation | Web-private HTTP |
|---|---|---|---|
| Rõ quyền truy cập | Cao, theo tài liệu/scope | Cần xem điều khoản và chấp thuận | Cần cho phép rõ ràng |
| Chống thay đổi UI | Cao | Thấp | Thấp–trung bình |
| CPU/RAM | Thấp | Cao | Thấp |
| Streaming | Theo tài liệu | Khó theo dõi đúng delta | Tùy protocol |
| Auth | OAuth/API token hợp lệ | Session trình duyệt nhạy cảm | Token nội bộ nhạy cảm |
| Nhiều model | Nếu nhà cung cấp hỗ trợ | Theo UI được phép | Chưa rõ |
| Khuyến nghị | **MVP chính** | Không dùng với ClickUp khi chưa có phép | Không dùng với ClickUp khi chưa có phép |

## Kết luận

Bài học lớn nhất không phải một đoạn fetch/cookie cụ thể mà là **phân lớp độc lập**: transport → auth → session → model registry → event decoder → OpenAI-compatible facade. Với ClickUp, chọn hướng tích hợp chính thức trước; tiếp tục khảo sát hợp đồng tính năng, không khẳng định một Brain² chat endpoint đã tồn tại.
