# 07 — Cập nhật khảo sát web công khai (28/10/2026)

## Truy cập trang đích

Đã thử mở trang `https://app.clickup.com/90182985436/ai/brain` bằng công cụ truy cập web từ phiên nghiên cứu độc lập. **Không truy cập được giao diện Brain đã đăng nhập**, không có quyền truy xuất private client state, live network của Workspace hoặc session người dùng. Screenshot trước đó chỉ cung cấp thông tin UI.

Không nên đồng nhất **client-side JavaScript được tải công khai** với source backend; ngay cả khi tải được frontend bundle thì business logic, session, request-to-model routing và backend prompt processing vẫn không thể khẳng định từ UI.

## Các nguồn đã kiểm tra

1. [ClickUp Developer — Chat](https://developer.clickup.com/docs/chat): **Chat API** dùng để tạo và quản lý **channels, messages, DMs, reactions, replies** trong ClickUp; **không phải** tài liệu API gửi prompt trực tiếp tới Brain².
2. [ClickUp Developer — MCP](https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server): MCP cho phép AI client bên ngoài tương tác với Workspace qua các tools. Điều này không chứng minh `Brain² Max` có REST endpoint public.
3. [ClickUp Help — Select an AI model](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model): có dynamic model selector và mid-chat model switching.
4. [ClickUp Canny — Make ClickUp Brain available via API](https://clickup.canny.io/public-api/p/make-clickup-brain-available-via-api): yêu cầu xuất hiện ngày 04/04/2025. Bình luận của đại diện ClickUp ngày **29/09/2026** cho biết họ **đang phát triển quyền truy cập Brain thông qua MCP Server**. Đây là định hướng sản phẩm, **không chứng minh tính năng đã phát hành** và không tương đương Brain² Web Chat API.

## Phân định trách nhiệm thu thập bằng chứng

**Có thể tự làm không cần người dùng thao tác UI:** nghiên cứu public developer docs, mã nguồn open-source Web → API, static assets truy cập công khai, thiết kế adapter, xây mock test, review GitHub code/CI.

**Cần một phiên trình duyệt được ủy quyền để xác minh:** endpoint chat, HTTP method/request schema, conversation state, streaming framing, model IDs thực tế, session refresh. Có thể chạy công cụ Playwright trong repo trên máy/cổng cloud browser có tài khoản nghiên cứu; **không cần chụp từng nút**. Nếu người dùng không cung cấp quyền truy cập hoặc trace, không thể xác nhận phần protocol.

**Đầu ra ưu tiên người dùng cung cấp:** file `artifacts/network_events.jsonl` tạo bởi `tools/trace_browser.py`, hoặc kết quả `tools/summarize_trace.py artifacts/network_events.jsonl --json`. Kiểm tra nội dung trước khi chia sẻ; tracer lưu metadata/path/schema keys đã mask, không lưu raw credentials/request bodies. **Tránh gửi HAR gốc, cookie, Authorization header, localStorage, profile Chromium.**

## Trạng thái bằng chứng hiện tại

| Hạng mục | Trạng thái |
|---|---|
| Open-source survey | Done |
| Static ClickUp docs | Done |
| Repo architecture, tracer, analyzer, CI | Done |
| Access private Brain page | Blocked — không có phiên browser người dùng |
| Model-to-wire-ID mapping | Not tested |
| JSON/SSE/WS protocol | Not tested |
| Brain² adapter hoạt động | Not implemented |
| Production deployment | Not implemented |

**Next:** lấy một trace metadata của Max first turn + continuation + chuyển sang ít nhất một model khác. Đối chiếu endpoint candidate với DevTools **nội bộ** rồi mới xây protocol adapter theo schema quan sát được.
