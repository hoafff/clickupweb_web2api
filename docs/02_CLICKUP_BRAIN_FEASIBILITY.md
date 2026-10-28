# 02 — Đối chiếu ClickUp Brain²: bằng chứng, rủi ro, điều kiện

**Cập nhật:** 28/10/2026. **Mức độ xác minh:** screenshot người dùng + tài liệu ClickUp công khai. Chưa có quan sát network (HAR) hoặc thử nghiệm API trên Workspace của người dùng.

## Những gì đã xác nhận

1. Screenshot cho thấy người dùng ở **app.clickup.com/.../ai/brain**, màn hình Brain²; ô Ask, Agents, Skills, Memory, recent chats; nút chọn model hiện **Max**. Không có endpoint AI chat backend nào hiển thị trong ảnh.
2. Theo [ClickUp — Chat with Brain](https://help.clickup.com/hc/en-us/articles/28401383762455-Chat-with-Brain), model selector cho phép chọn Max hoặc các model cao cấp từ Claude, ChatGPT, Gemini; có context selector, mention và upload tài liệu.
3. Theo [ClickUp — Select an AI model](https://help.clickup.com/hc/en-us/articles/30802296047511-Select-an-AI-model), có thể **chuyển model giữa cùng một cuộc trò chuyện**, giữ history/context. Đây là yêu cầu bắt buộc nếu muốn mô phỏng trải nghiệm người dùng; không thể chỉ có `model=clickup-max`.
4. Theo [ClickUp — AI models, privacy and security FAQ](https://help.clickup.com/hc/en-us/articles/15428419095831-ClickUp-AI-models-privacy-and-security-FAQ), model và phiên bản thay đổi theo thời gian; menu model thể hiện **danh sách có sẵn thực tế trong Workspace**.
5. Theo [ClickUp — Brain availability and limits](https://help.clickup.com/hc/en-us/articles/44297778247063-ClickUp-Brain-availability-and-limits), model standard/premium có hạn mức theo Workspace, giới hạn có thể thay đổi hành vi và mức sử dụng; không tự suy từ gói đăng ký.
6. [ClickUp MCP Server](https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server) hỗ trợ thao tác data/tasks/docs với AI agent bên ngoài. **MCP này không đồng nghĩa một public endpoint cho Brain² chat/Max.**

## Điều khoản cần xét trước mọi POC Web → API

[ClickUp Terms of Service](https://clickup.com/terms) quy định:
- Điều 1.5 hạn chế reverse engineering (trừ trường hợp pháp luật không cho phép áp dụng hạn chế).
- Điều 2.2 hạn chế truy cập **private API** ngoài những cách được cho phép.
- Điều 3.9 hạn chế crawling/scraping/truy cập tự động.
- Điều 4.13(e) hạn chế API client không được cho phép.

[Developer Terms](https://clickup.com/terms/developer-terms) cũng đặt giới hạn với platform/API. **Không khẳng định dự án này là chính thức hay được ClickUp phê duyệt.** Nếu muốn truy cập Brain² qua giao thức nội bộ, cần có chấp thuận có thể kiểm chứng; nếu chưa có thì không triển khai đường đó.

## Bảng chứng cứ / giả thuyết

| Nội dung | Kết luận | Nguồn / cách kiểm chứng |
|---|---|---|
| Có nút Max trong Brain² | **Đã quan sát** | Screenshot |
| Có nhiều model hơn Max | **Xác nhận theo tài liệu ClickUp và phản hồi người dùng** | Help Center model selector |
| Model có thể đổi giữa cuộc chat | **Có, theo tài liệu** | Select an AI model |
| Có public REST API dành cho việc chat trực tiếp với Brain² Max | **Chưa tìm thấy tài liệu hỗ trợ; không thể kết luận là không tồn tại** | ClickUp Developer Docs / cần xác nhận từ ClickUp |
| Một backend request = một lần sinh AI | **Chưa xác minh** | Cần hợp đồng hoặc quan sát được phép |
| Brain² dùng SSE / WebSocket | **Chưa xác minh** | Cần hợp đồng hoặc quan sát được phép |
| Menu model có stable `model_id` gọi được từ bên ngoài | **Chưa xác minh** | Cần nguồn chính thức |
| Brain² hỗ trợ upload, Skills, Memory, context | **Có thành phần UI / theo help**, API equivalence **chưa xác nhận** | Screenshot / help |
| Dùng ClickUp MCP là gọi đúng Brain² Max | **Không** | MCP cung cấp tools cho external AI clients |
| Chọn GPT/Claude/Gemini qua Brain = gọi provider API riêng có cùng hành vi | **Không** | Brain có Workspace context và tích hợp sản phẩm riêng |

## Vì sao không được hứa “Web → API y như Brain²”

- Max có thể là chế độ điều phối động và không phải một provider model tĩnh.
- Chọn model trong UI không có nghĩa có model ID công khai hoặc quyền dùng model đó từ một proxy ngoài sản phẩm.
- Skills, Memory, Mentions, Workspace context, attachments, tool execution có thể sử dụng nhiều thành phần nội bộ. Chỉ forward prompt sang một LLM khác **không tái hiện Brain²**.
- Hạn mức của Workspace và gói có thể ảnh hưởng đến khả dụng/hiển thị của từng model; không đồng nhất với số lượng API tokens.
- Trả model name mong muốn khi upstream thực chất dùng model khác là **sai tương thích và dễ làm người dùng hiểu nhầm**.

## Con đường hợp lệ được khuyến nghị

**MVP A — ClickUp MCP / Public REST API + LLM được người dùng cấp khóa riêng.** Cho phép query task/doc, tổng hợp, tạo tác vụ trong phạm vi OAuth/scopes được cấp; hỗ trợ nhiều model tùy provider, và thông báo rõ đây là **AI sử dụng dữ liệu ClickUp**, không phải “ClickUp Brain² API”.

**Track B — Chờ xác nhận từ ClickUp** về endpoint Brain chat/SDK/partner access hoặc văn bản cho phép tự động hóa; sau đó mới viết provider adapter vào một giao thức **có phạm vi được phép rõ ràng**.

## Câu hỏi cần gửi ClickUp (không cần dữ liệu bí mật)

1. Có API hoặc partner SDK **được hỗ trợ** để gửi prompt đến Brain², bao gồm Max / lựa chọn model ngoài và nhận câu trả lời không?
2. Có API hỗ trợ continuation, model switch mid-chat, memory, Workspace context, Skills, file upload và streaming không?
3. Nếu không, những kiểu automation nào được phép và trên môi trường nào?
4. Quy tắc quota/premium model allowance, rate limit và điều kiện triển khai server-side?
5. Chính sách lưu log, dữ liệu Workspace và yêu cầu cấp quyền OAuth/app?

**Trạng thái:** Chưa trả lời từ ClickUp; không lấy sự im lặng làm sự cho phép.
