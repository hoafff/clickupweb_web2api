# 12 — Async ConversationEventCorrelator (28/10/2026)

**Objective:** Từ HTTP/WS research, dựng thành phần nhận phản hồi không nhầm hội thoại, có thể mở rộng cho browser session adapter. Đây là **phần thực thi offline**; chưa gửi prompt tự động hoặc tạo Web → API độc lập.

## Thành phần mới

| File | Mục đích | Trạng thái |
|---|---|---|
| [`tools/conversation_correlator.py`](../tools/conversation_correlator.py) | State machine ghép `aiConversationStarted` ↔ `chatCommentCreated` bằng `ai_result_id` và xác minh `conversation_id` | Implemented |
| [`tools/replay_brain_events.py`](../tools/replay_brain_events.py) | Replay JSONL V3 **offline** và chỉ trả số đếm, không hiển thị nội dung | Implemented |
| [`tests/test_conversation_correlator.py`](../tests/test_conversation_correlator.py) | Parallel conversations, out-of-order, duplicate, mismatch, timeout, cancel, eviction, scope | Mock tests |
| [`tests/test_replay_brain_events.py`](../tests/test_replay_brain_events.py) | Offline interleaving + privacy | Mock tests |

## Vận hành từ máy đã có V3

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\replay_brain_events.py artifacts\brain_v3_private_content.jsonl --expected 8
```

Kỳ vọng: `correlation_counters.matched=8` dựa trên phân tích V3 trước đó. Nếu khác, **điều tra và báo cáo**, không tự điều chỉnh code để ép đạt. Replay không kết nối web hoặc thực hiện đăng nhập, không gửi request tới ClickUp.

## Contract cho adapter tương lai

```python
from tools.conversation_correlator import ConversationEventCorrelator

# Create ONE instance per authenticated account/workspace scope.
c = ConversationEventCorrelator(scope_id="local-authorized-workspace")
# Feed every incoming WS message (do not rely on UI marker boundaries).
classification = c.ingest({
    "kind": "ws_frame_content",
    "direction": "received",
    "timestamp_utc": "2026-10-28T05:00:00+00:00",
    "payload": {"data": {"event": {...}}},
})
# Once a real, observed ai_result_id is known from the authorized session:
reply_created = await c.wait_for_created(
    ai_result_id, conversation_id=conversation_id, timeout=60.0
)
c.close()
```

`wait_for_created` **không đồng nghĩa final generation**. Nó chỉ giải quyết khi cả 2 event đã quan sát được và cùng `ai_result_id`, có kiểm tra `conversation_id` nếu cả hai bên đều đưa ID.

## Bảo vệ luồng đồng thời

- Không giao nhầm phản hồi giữa 2 result IDs hoặc 2 conversations.
- Dùng một instance riêng cho mỗi Workspace/identity; không chia sẻ toàn cục.
- Cho phép reply đến trước started (buffer), đến sau marker tiếp theo hoặc chứa duplicate event.
- Nhiều awaiters trên cùng result ID có timeout/cancellation riêng biệt.
- Conflict, mismatch, cache eviction và TTL phát ra lỗi rõ, không trả nội dung sai.
- Giới hạn bộ nhớ: `max_records=1024` và `ttl_seconds=900` mặc định; TTL được quét lúc ingest/wait/prune, **không có background sweeper**.
- `statistics()` chỉ trả số, không chứa message, ai_result_id hay conversation_id. `CorrelatedComment` trả text riêng tư chỉ cho ứng dụng gọi; không log trực tiếp.

## Findings vs Limitations

**Đã có bằng chứng từ V3:** 8 AI starts, 8 AI reply-created events khớp và không có mismatch. Dữ liệu chat có `comment` JSON rich-text. Mốc UI có thể xuất hiện trước khi event reply của lượt trước kết thúc.

**Chưa xác minh:** websocket auth/refresh, engine completion event (end-of-stream), token deltas, model tatsächlich được chạy, direct HTTP replay, gửi prompt từ một client khác hoặc multi-tenant isolation trong hệ thống thực tế. Correlator chỉ bảo đảm ghép đúng sự kiện khi input đã hợp lệ; không xác thực nguồn WS và không tự cấp quyền.

## Next priority

1. Kết nối correlator với **BrowserUIAdapter** trong một phiên nghiên cứu được phép, dùng thao tác UI hợp lệ để gửi prompt và WS handler để nhận reply.
2. Tạo interface `send / await_reply_created / cancel / close` và mock end-to-end integration test (chưa cần private protocol).
3. Chỉ khi có bằng chứng protocol và scope phù hợp mới cân nhắc direct HTTP/WS adapter + OpenAI-compatible gateway. Không tự claim access token/session có thể tái sử dụng từ nơi khác.
