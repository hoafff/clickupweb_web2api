# 03 — Kiến trúc tham chiếu và kế hoạch proof-of-concept

**Trạng thái:** Thiết kế dự kiến, không phải bằng chứng về ClickUp private API. Có 2 đường rõ ràng: (A) official API/MCP + LLM tự cấp và (B) Brain² nếu có giấy phép/giao diện chính thức được ClickUp cung cấp.

## Sơ đồ luồng

    Client (OpenAI-like SDK / app)
                  |
          API gateway (auth + quota)
                  |
          Request validator
                  |
          ModelRegistry / SessionStore
                  |
            Adapter interface
              /            \
       Official             Future explicitly
       MCP / REST           authorized Brain adapter
          |                       |
     Tool executor           Authorized protocol
          |                       |
          +-------> Normalized response/events
                           |
                    JSON or SSE formatter

**Không có adapter private ClickUp được cài đặt trong repo.**

## Tách thành phần

- **Gateway**: tự cấp API key nội bộ, permission checks, per-client rate limits, request-id, strict JSON schema, CORS tùy triển khai, log redaction.
- **ModelRegistry**: alias công khai, display label, provider, capability, trạng thái khả dụng, thời điểm xác minh. Không khai báo model chưa được phép / chưa được hỗ trợ.
- **SessionStore**: hội thoại, mapping người dùng/Workspace, scope, lịch sử, timestamp, active model; mã hóa dữ liệu nhạy cảm, TTL, xóa phiên.
- **ProviderAdapter**: contract abstract gồm `list_models`, `chat`, `chat_stream`, `capabilities`, `health`. Chỉ implement nếu có API chính thức được phép.
- **ContextResolver**: dùng ClickUp MCP/REST tools được ủy quyền; lọc scope và không gửi dữ liệu Workspace nếu không được yêu cầu/quyền.
- **ResponseFormatter**: OpenAI-compatible JSON và SSE; báo model **được sử dụng thực tế**, không phỏng đoán.
- **Audit / Observability**: latency/HTTP status/error class, token usage **chỉ nếu được provider báo**; không log prompts và nội dung Workspace theo mặc định.

## API contract đề xuất (MVP chỉ chính thức)

| Method | Path | Ý nghĩa |
|---|---|---|
| GET | /healthz | Liveness process |
| GET | /readyz | Readiness adapter/service; không đồng nghĩa model external đang khỏe |
| GET | /v1/models | Danh sách model **thực sự khả dụng** |
| POST | /v1/chat/completions | Chạy một lượt chat có chọn model; stream tùy adapter |
| DELETE | /v1/conversations/{id} | Xóa conversation của người gọi, theo quyền |

Request mẫu **chỉ là contract thiết kế**, không gọi ClickUp Brain:

    {
      "model": "configured-provider-model",
      "messages": [
        {"role": "user", "content": "Tóm tắt các việc đang quá hạn của tôi"}
      ],
      "stream": false,
      "metadata": {"context_source": "clickup_mcp"}
    }

### Multi-model compatibility

- Client gửi alias rõ ràng và nhận đúng model/provider ứng với alias.
- Một user có thể đổi model theo từng turn; gateway giữ `local_conversation_id` + lịch sử (nếu provider không tự duy trì).
- Một conversation có thể được nhiều provider xử lý nhưng **history không được tự động gửi sang provider ngoài** nếu chưa được phép; ghi rõ chính sách data-sharing.
- Nên tách `selection_requested`, `selection_resolved`, `selection_reported` để phát hiện fallback hoặc auto-routing.
- Nếu user yêu cầu model không khả dụng, trả `400 invalid_model` hoặc `403 model_not_enabled`, **không tự dùng model khác**.
- Nếu model Max là chế độ điều phối nội bộ không có public endpoint, không ánh xạ giả thành tên model của một hãng khác.

### Lỗi

| Tình huống | Public HTTP | Error code nội bộ | Hành động |
|---|---|---|---|
| Body/model không hợp lệ | 400 | invalid_model / invalid_request | Sửa request |
| Thiếu API key gateway | 401 | unauthenticated | Cấp khóa |
| Model/scope không được phép | 403 | permission_denied | Kiểm tra permission |
| Conversation không thuộc user | 404 | not_found | Không làm lộ tenant |
| Quota/quá nhiều lượt | 429 | rate_limited | Retry-After nếu có, backoff |
| Lỗi provider | 502 | upstream_error | Không retry vô hạn |
| Provider mất khả dụng | 503 | upstream_unavailable | Circuit breaker |
| Timeout | 504 | upstream_timeout | Deadline/hủy upstream |

Streaming bị ngắt **sau khi header 200 đã trả** phải gửi event lỗi theo schema định nghĩa hoặc đóng stream, không giả rằng HTTP status có thể đổi thành 5xx.

## Kế hoạch thử nghiệm được phép

### Phase 0 — Ràng buộc và khả năng (chưa code private adapter)

- Đọc điều khoản và tài liệu sản phẩm, xác minh phương án / quyền của từng chức năng.
- Liệt kê model theo menu thực tế; chỉ lưu **tên hiển thị** và capability, không thu token/cookie.
- Tách điều gì thuộc Brain² và điều gì thuộc ClickUp Public API/MCP.

### Phase 1 — Mock adapter (offline)

- Fixture có JSON answer, SSE deltas, completion, lỗi 401/403/429/502.
- ModelRegistry có các model giả, test chọn model, chuyển giữa turn, fallback explicit vs implicit.
- Nhiều request cùng conversation phải khóa/queue theo session.

### Phase 2 — Authorized integration

- ClickUp MCP OAuth + REST official theo phạm vi được cấp.
- LLM provider API của chủ sở hữu, tách rõ ràng khỏi ClickUp Brain².
- Kiểm tra ACL, quy tắc retention, stream, tool calls, multi-model.
- Xác minh các chức năng đã làm được và ghi rõ chức năng không tương đương Brain².

### Phase 3 — Brain² (chỉ nếu được ClickUp cấp phép)

- Nhận tài liệu API/partner agreement hoặc approval scope, auth, quota, supported models.
- Viết adapter bám contract được phép, kiểm thử 2+ model, conversation switch và persistence.
- Không dùng bypass CAPTCHA/anti-bot, không vượt rate limit, không lưu credential vào GitHub.

## Acceptance criteria

1. `/v1/models` chỉ công bố các model thực sự được adapter kích hoạt.
2. Mỗi completion báo đúng resolved model; test chuyển model trong cùng local conversation.
3. Không rò rỉ credential, prompt, dữ liệu Workspace qua logs và lỗi.
4. SSE hợp lệ, xử lý disconnect/cancel, idle timeout và upstream 429.
5. Authn/authz, tenant isolation, khóa chống concurrent race theo conversation.
6. Không gọi Brain² bằng đường không có phép. Documentation ghi rõ khác biệt so với UI gốc.

## Đề xuất triển khai

Python FastAPI + httpx, pydantic, pytest; Redis/Postgres nếu cần nhiều worker; Docker cho server vận hành độc lập máy cá nhân. Với cloud, secret đưa vào manager/env server-side (không đặt trong GitHub Actions log). Có thể chọn Go nếu mục tiêu hiệu năng cao; hiệu năng không giải quyết được tính hợp lệ của quyền truy cập hay hạn mức ClickUp.
