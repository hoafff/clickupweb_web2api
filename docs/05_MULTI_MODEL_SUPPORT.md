# 05 — Multi-model trong ClickUp Brain²: tách hành vi UI khỏi API

**Ngày kiểm chứng:** 28/10/2026. **Phạm vi:** model selector ở Brain, không phải model API tự host. Hiện mới có screenshot hiển thị **Max**, chưa nhận được danh sách mở rộng tất cả model/phiên bản trong Workspace. Không điền tên phiên bản chưa nhìn thấy.

## Điều được ClickUp xác nhận

- [Select an AI model](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model): có thể chọn Max và mô hình bên ngoài; **đổi model giữa cùng conversation** mà không mất toàn bộ conversation history và Workspace context.
- [Chat with Brain](https://help.clickup.com/hc/en-us/articles/28401383762455-Chat-with-Brain): nhóm model ngoài gồm Claude, ChatGPT và Gemini; UI có context selector / mentions / uploads.
- [AI models FAQ](https://help.clickup.com/hc/en-us/articles/15428419095831-ClickUp-AI-models-privacy-and-security-FAQ): **phiên bản model thay đổi**; selector trong Workspace mới là nguồn xác định danh sách hiện tại.
- [Brain usage](https://help.clickup.com/hc/en-us/articles/44297778247063-ClickUp-Brain-availability-and-limits): standard/premium, allowance, auto fallback khi hết premium usage và chính sách fairness có thể ảnh hưởng hành vi; không dùng để suy ra API quota.
- [Brain definition](https://help.clickup.com/hc/en-us/articles/12578085238039-What-is-ClickUp-Brain-AI): Max là lựa chọn mặc định, Brain có thể tương tác với dữ liệu Workspace trong phạm vi quyền.

**Lưu ý:** 'Max' là label của lựa chọn AI trong Brain, khác với 'Max Plan' trong bảng giá ClickUp. Không gộp hai khái niệm.

## Khả năng cần kiểm chứng riêng cho mỗi model

| Tiêu chí | Max | ChatGPT family | Claude family | Gemini family |
|---|---|---|---|---|
| Có trong tài liệu Brain | Có | Có | Có | Có |
| Tên phiên bản cụ thể của Workspace này | Chưa nhận được danh sách | Chưa nhận được danh sách | Chưa nhận được danh sách | Chưa nhận được danh sách |
| Model switch mid-chat | Docs xác nhận tính năng | Docs xác nhận tính năng | Docs xác nhận tính năng | Docs xác nhận tính năng |
| Brain2 external callable model ID | **Unknown** | **Unknown** | **Unknown** | **Unknown** |
| File/image/tool/Skills ở mỗi lựa chọn | Cần kiểm chứng | Cần kiểm chứng | Cần kiểm chứng | Cần kiểm chứng |
| Exact context window, max tokens, thinking config | Unknown | Unknown | Unknown | Unknown |
| Streaming wire format | Unknown | Unknown | Unknown | Unknown |
| Model có xuất hiện trong public API ClickUp? | Chưa thấy tài liệu Brain chat API | Chưa thấy tài liệu Brain chat API | Chưa thấy tài liệu Brain chat API | Chưa thấy tài liệu Brain chat API |

Đây **không phải kết luận** tất cả model đều có cùng tính năng. Tính năng Brain Workspace có thể được ClickUp điều phối và phụ thuộc vào việc chọn model.

## Thiết kế ModelRegistry

### Ba loại tên không được nhầm

1. `display_label`: tên UI người dùng thấy (ví dụ: `Max`).
2. `public_alias`: tên client gửi vào gateway do **mình** quản lý (ví dụ: `clickup-data-assistant` cho MVP dùng official MCP+LLM).
3. `provider_model_id`: tên model thật trong **API được provider cấp quyền**, nếu có. **Chưa biết bất kỳ provider_model_id của ClickUp Brain²**.

Pseudo JSON minh họa registry (giá trị giả, không phải ClickUp endpoint):

    {
      "public_alias": "demo-model-a",
      "display_label": "Example Provider Model",
      "provider": "authorized_external_llm",
      "provider_model_id": null,
      "available": false,
      "verification": "not_configured",
      "capabilities": {
        "stream": "unknown",
        "file_input": "unknown",
        "tool_calling": "unknown"
      }
    }

**Không trả record này trong `GET /v1/models` khi `available=false`.** Một cấu hình chưa có upstream hợp lệ không phải model có thể sử dụng.

### Luồng chọn model

    UI / SDK sends public_alias
                |
         validate caller ACL
                |
        query active registry
           /         \
     not found       found + allowed
        |                |
      400/403       resolve adapter
                         |
                  pass messages/context
                         |
               verify actual model used
                         |
                   return response

Nếu adapter hỗ trợ `auto` hoặc fallback: phải nói rõ với người gọi resolved model (nếu provider có thông tin). Nếu bên ngoài chỉ báo `Auto` thì không suy diễn một model ẩn cụ thể.

## Chuyển model trong một hội thoại

Vì ClickUp ghi nhận history/context vẫn giữ khi chuyển model trong UI, một API adapter tương đương (nếu có) cần xử lý:
- Turn #1 yêu cầu Max → nhận reply và lưu conversation reference.
- Turn #2 yêu cầu Claude/GPT/Gemini từ menu **được xác thực** → giữ history và chỉ chuyển model nếu contract hỗ trợ.
- Khi mock self-hosting: history có thể do service điều phối; nếu gửi qua nhà cung cấp khác phải xét dữ liệu/scope trước.
- Khi thiếu khả năng chuyển model: trả `unsupported_model_switch` thay vì giả lập cùng context.
- Khi quota premium hết, không giả rằng hệ thống vẫn đang chạy premium; dùng thông tin upstream được phép/trả về hoặc giải thích không xác minh được.

## Danh sách cần điền sau khi người dùng mở dropdown

- Tên hiển thị **chính xác** cho từng model.
- Có chia Standard/Premium, Recommended/More models hay không.
- Model nào đã từng thử và có thể trả lời.
- Khi chọn model A → B giữa cùng chat, UI có giữ context không.
- Có giới hạn tính năng khi chọn từng model không.
- Quan sát giới hạn quota/usage chỉ ở mức giao diện, **không sao chép mã xác thực**.

## Mục tiêu research

**Mục tiêu A:** Có wrapper/gateway dùng ClickUp Public API/MCP với LLM API riêng, nhiều model được cấu hình thật; có tài liệu rõ khác biệt với Brain².

**Mục tiêu B:** Nếu ClickUp chấp thuận chương trình API/partner Brain, bổ sung adapter dùng các model mà **contract đó thực sự hỗ trợ**. Không cho rằng menu model trong trình duyệt là danh sách API model hợp pháp.
