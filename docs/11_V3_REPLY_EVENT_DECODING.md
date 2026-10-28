# 11 — V3: Giải mã sự kiện trả lời Brain² (28/10/2026)

> **Nguồn:** bộ log `brain_v3_private_content.jsonl` và `brain_v3_meta.jsonl` do người nghiên cứu gửi trong hội thoại. Bản công khai này **không chứa** prompt, câu trả lời, access token, Workspace ID, conversation ID hoặc ai_result_id. Kết luận được rút từ 8 lượt quan sát với tài khoản nghiên cứu; không suy diễn endpoint hay các tính năng chưa đo được.

## 1. Kết quả định lượng

| Event / phép kiểm chứng | Kết quả |
|---|---:|
| `aiConversationStarted` | 8 |
| `chatCommentCreated` | 16 |
| Tin người dùng trong `chatCommentCreated` | 8 |
| Tin AI trong `chatCommentCreated` | 8 |
| Tin AI khớp `ai_result_id` với sự kiện start | **8/8** |
| Tin AI có `conversation_id` trùng với sự kiện start | **8/8** |
| `chatCommentEdited` | 13, `changes=[]` trong capture |
| Kích thước văn bản phản hồi (ký tự, theo thứ tự quan sát) | 3, 81, 39, 3, 207, 3, 3, 3 |

## 2. Nguồn văn bản phản hồi đã quan sát

```text
WS event.name = aiConversationStarted
  event.payload.ai_result_id             [opaque correlation, không công bố]
  event.payload.conversation_id          [opaque correlation, không công bố]
                 |
                 | match on ai_result_id + verify conversation_id
                 v
WS event.name = chatCommentCreated
  event.version_event_data.changes[]
    field = ai_result_id                 [có với AI reply, không có với user]
    field = conversation_id
    field = comment
      after = '[{"text":"...","attributes":{}}]'
                 |
                 v
  json.loads(after) -> concatenate blocks[].text
```

**Khác biệt quan trọng:** `changes[].after` của field `comment` là **JSON được mã hóa trong một string**, không phải trực tiếp là text response thuần. Trong V3 các block là `{text, attributes}`. Chỉ parse JSON, không execute/render HTML.

`chatCommentCreated` tạo 8 event user và 8 event AI; nhận diện AI bằng field `ai_result_id` xuất hiện trong `version_event_data.changes`. Tracer cho thấy có thể lấy nội dung trả lời từ event **sau khi comment được tạo**, nhưng chưa chứng minh đây luôn là final event hoặc duy nhất một event đối với câu trả lời dài/tool calls.

## 3. Thời gian từ WS AI-start đến WS AI-comment-created

Trong 8 lượt: **2.753, 5.051, 0.033, 2.659, 33.516, 2.897, 2.806, 3.411 giây**.

- Min: 0.033 s; median: 2.852 s; max: 33.516 s.
- Các giá trị là **khoảng thời gian giữa hai sự kiện đã capture**, **không phải** tổng thời gian inference hoặc time-to-first-token.
- Lượt 33.516 s vượt ranh giới marker: `opus_low#5` start nhưng `chatCommentCreated` đến sau khi đã nhập `opus_low#6`. Không cắt bỏ output khi gặp marker tiếp theo; dùng `ai_result_id`.

## 4. Streaming: vẫn chưa xác minh

Không thấy các delta token có thể nhận diện trong các `chatCommentEdited` V3: 13 sự kiện đều có `changes=[]` trong payload đã capture. `chatCommentCreated` đưa rich text hoàn chỉnh ở thời điểm tạo comment trong các case V3. Các tình huống có thể khác nhau:

- UI có thể hiển thị nội dung dần bằng một cơ chế khác không được tracer này capture;
- các kết quả V3 ngắn nên chỉ có một message hoàn chỉnh;
- upstream thực hiện sinh nội bộ, sau đó đồng bộ reply qua comment event.

**Không kết luận** ClickUp không hỗ trợ streaming; cần thêm dữ liệu nếu muốn hỗ trợ stream thực. Nếu gateway dùng `stream=true` trước khi biết transport delta, chỉ được stream ra một event hoàn chỉnh theo contract riêng, không tuyên bố đó là token streaming thực.

## 5. Tool và kiểm thử

File mới: [`tools/brain_event_decoder.py`](../tools/brain_event_decoder.py).

```powershell
git pull
.\.venv\Scripts\python.exe tools\brain_event_decoder.py artifacts\brain_v3_private_content.jsonl
```

Chế độ mặc định chỉ in **count, text lengths, elapsed seconds**. Không in nội dung, ID, Workspace hoặc credential.

Tùy chọn **chỉ dành cho file local private**:

```powershell
.\.venv\Scripts\python.exe tools\brain_event_decoder.py artifacts\brain_v3_private_content.jsonl --export-replies artifacts\brain_v3_local_replies.json
```

`--export-replies` tạo file chứa **nội dung phản hồi AI**, không có opaque IDs; vẫn phải giữ bí mật và không đưa lên GitHub. `artifacts/` nằm trong `.gitignore`. Bộ test offline [`tests/test_brain_event_decoder.py`](../tests/test_brain_event_decoder.py) dùng fixture giả, không cần tài khoản.

## 6. Những gì đã chắc chắn và những gì chưa

| Hạng mục | Kết luận |
|---|---|
| Query chọn `selectedModel` / `selectedReasoningLevel` | Quan sát trong HTTP chat command |
| Phân biệt New Chat / follow-up HTTP routes | Quan sát trong 8 lượt |
| Liên kết `aiConversationStarted` → `chatCommentCreated` theo ID | Xác minh 8/8 trong log |
| Tách plain text từ WS comment | Xác minh được với rich-text JSON của 8 replies |
| Streaming delta / completion marker | **Chưa xác minh** |
| Server-side effective model / thinking effort | **Chưa xác minh** (request thể hiện lựa chọn) |
| Auth/session refresh contract | **Chưa xác minh** |
| Direct Web → API gửi prompt ngoài browser | **Chưa triển khai, chưa kiểm thử** |

## 7. Bước kỹ thuật ưu tiên tiếp theo

Từ decoder offline, trừu tượng hóa `ConversationEventCorrelator`: quản lý nhiều request cùng lúc theo `ai_result_id`, giữ state đến khi có event kết thúc được xác nhận, cho phép timeout/cancel, không trộn phiên. Sau đó phát triển browser-based adapter được ủy quyền hoặc direct protocol adapter nếu xác định được contract/permission thực tế. Không đưa browser profile/cookie/private JSON lên cloud repository.
