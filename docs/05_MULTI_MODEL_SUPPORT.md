# 05 — Multi-model research: menu → protocol → API model registry

> **28/10/2026.** Đã có screenshot dropdown Brain² từ người dùng, không chỉ một nút Max. Chưa có capture giao thức và chưa test model thực tế. Mục tiêu là hỗ trợ *toàn bộ model xuất hiện trong account được ủy quyền* qua dynamic discovery, không đóng khung danh sách 5–6 model.

## Menu model đã quan sát (ảnh người dùng)

| UI display label | Family dựa trên nhãn | Trạng thái từ ảnh | Wire model ID |
|---|---|---|---|
| Brain² — Max | Brain²/ClickUp | Đã chọn | **Chưa biết** |
| Claude Opus 5.5 | Claude | Có trong dropdown | **Chưa biết** |
| Claude Opus 5 | Claude | Có trong dropdown | **Chưa biết** |
| Gemini 4 Argon | Gemini | Có trong dropdown | **Chưa biết** |
| GPT-6.1 Sol | GPT | Có trong dropdown | **Chưa biết** |
| GPT-6.1 Terra | GPT | Có trong dropdown | **Chưa biết** |
| `Show more` | Nút mở rộng | Chưa xem phần dưới | N/A |

[ClickUp — Select an AI model](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model) ghi nhận có thể **đổi model giữa cùng hội thoại** mà vẫn giữ history/Workspace context. Tên phiên bản thay đổi theo sản phẩm; source of truth của phiên nghiên cứu phải là UI và bằng chứng traffic.

## Phương pháp xác định model ID

1. Baseline: ghi một cuộc hội thoại cùng prompt ở Max.
2. Chọn một label khác ở UI; gửi prompt tương đương trong **một cuộc chat mới**, so sánh request schema/field values và response metadata. Không suy ra rằng mọi khác biệt đều là model ID.
3. Thử cùng label với 2 câu hỏi để tách nonce/request ID khỏi model ID.
4. Chuyển model trong cùng conversation; xác định có field `model`, `mode`, `agent` hoặc thuộc tính định tuyến khác **theo key thực quan sát được**.
5. Nếu menu được tải động: xác định nguồn dữ liệu capabilities/entitlements trong phạm vi được phép.
6. Chỉ công bố model alias trên gateway khi adapter có bằng chứng `available = true`, kiểm chứng bằng 2 lần request thành công.

## ModelRegistry contract

```json
{
  "alias": "brain-ui:claude-opus-5.5",
  "ui_label": "Claude Opus 5.5",
  "provider_family": "claude",
  "wire_selection": null,
  "supports_streaming": "unknown",
  "supports_files": "unknown",
  "supports_tools": "unknown",
  "available": false,
  "verified_at": null,
  "evidence": []
}
```

Trên đây là **alias gateway ví dụ** và wire_selection **chưa biết**, không phải data trả từ ClickUp. Khi có bằng chứng thực nghiệm, adapter sẽ điền wire_selection từ trace và trả `available=true` sau kiểm thử.

## Multi-turn & model switching

```text
new conversation
  -> send(model = Max)
  -> receive conversation_ref / output
  -> send(model = Claude, continuation_ref = prior)
  -> verify whether history/context remains
  -> send(model = GPT, continuation_ref = prior)
  -> verify selected and (if provider emits it) resolved model
```

Cần test:
- Model switch có cần new HTTP endpoint không?
- Có `conversation_id`, `parent_message_id` hoặc một opaque token được update?
- Giao diện có tự chọn model khác khi quota/allowance thay đổi không?
- Skills, Memory, file attachment, search context có giống nhau giữa các model không?
- Nếu model không available, API trả `model_unavailable` hay UI tự fallback?
- Response stream có bất kỳ model metadata nào không?

**Không giả định** same history = backend gửi toàn bộ messages. Có thể chỉ gửi reference; phải kiểm chứng.

## API behavior đề xuất

- `GET /v1/models`: fetch/merge menu + capability evidence đã xác minh; cache với TTL và invalidation.
- `POST /v1/chat/completions`: nhận `model=alias`; resolve bằng registry; chuyển model theo contract; giữ conversation state.
- `requested_model`, `selected_ui_label`, `upstream_reported_model` và `resolved_model` là các biến khác nhau.
- Nếu model unknown/unsupported: trả lỗi; không đánh tráo model.
- Nếu upstream có fallback: giữ trung thực thông tin báo về; nếu không có metadata thì hiển thị `unverified` thay vì tuyên bố “đang dùng Opus 5.5”.
- Không vượt Workspace quota: limit/upstream 429 được xử lý bằng wait/backoff có giới hạn; không tự động xoay tài khoản để vượt quota.

## Điều kiện kết luận

- Hoàn thành matrix ≥2 model và một model switch trong cùng conversation.
- Mapping từ UI label tới wire selection đã xác minh, không chỉ dựa trên screenshot.
- Capture cho thấy response framing và status/capabilities hoặc ghi `unknown`.
- Tests có fixture với model A, model B, unavailable, fallback, timeout và concurrent chat.

Xem [worksheet](04_OBSERVATION_WORKSHEET.md) và [research playbook](06_AUTHORIZED_PROTOCOL_RESEARCH.md).
