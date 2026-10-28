# ClickUp Brain² — Web-to-API Research

> **Trạng thái (28/10/2026):** Nghiên cứu kiến trúc và tính khả thi; **chưa có adapter ClickUp Brain chạy được**, chưa xác minh giao thức nội bộ và chưa có quyền truy cập được cấp riêng cho private API. Repo này **không** công bố endpoint/cookie/token ClickUp.

## Mục tiêu

Khảo sát các mã nguồn mở chuyển ứng dụng hội thoại web thành giao diện API; tách các thành phần kỹ thuật có thể tái sử dụng (session, transport, event stream, conversation state, API facade) và đánh giá **khả năng tích hợp ClickUp Brain² một cách được phép**.

**Điểm quan trọng:** [Điều khoản ClickUp](https://clickup.com/terms) hiện hạn chế reverse engineering, truy cập private API không được cho phép và thu thập tự động. Việc làm chủ một tài khoản ClickUp **không tự động đồng nghĩa** được quyền tái sử dụng private API. Ưu tiên [ClickUp Public API](https://developer.clickup.com/), [ClickUp MCP](https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server), và xin chấp thuận bằng văn bản cho mọi tích hợp Brain chat không có API công khai.

## Tài liệu

1. [Khảo sát mã nguồn mở](docs/01_OPEN_SOURCE_SURVEY.md) — 5 dự án, đối chiếu cơ chế cụ thể và mã nguồn.
2. [Tính khả thi với Brain²](docs/02_CLICKUP_BRAIN_FEASIBILITY.md) — cái gì biết từ ảnh/tài liệu; cái gì chỉ là giả thuyết; điều kiện pháp lý/kỹ thuật.
3. [Kiến trúc & lộ trình POC](docs/03_ARCHITECTURE_AND_POC_PLAN.md) — kiến trúc phân tầng, API contract, lỗi, kiểm thử và mốc quyết định.
4. [Phiếu khảo sát bảo mật](docs/04_OBSERVATION_WORKSHEET.md) — biểu mẫu kiểm chứng với môi trường được phép, không ghi bí mật.

## Phân biệt 3 hướng

| Hướng | Có thể dùng chính thức? | Có gọi **chính Brain² Max**? | Trạng thái |
|---|---|---|---|
| ClickUp Public API + LLM provider API | Có, trong phạm vi quyền/tính năng được cấp | **Không**, là trợ lý tự xây trên dữ liệu ClickUp | Khả thi để phát triển |
| ClickUp MCP + LLM provider/agent | Có, qua OAuth và tool được hỗ trợ | **Không**, không phải endpoint chat Brain² | Khả thi để phát triển |
| Đưa giao diện web Brain² thành API qua browser/private requests | Cần ClickUp cho phép; rủi ro điều khoản/vận hành | Có thể là ý tưởng, **chưa xác minh** | Chưa được phê duyệt; chưa triển khai |

## Nguyên tắc nghiên cứu

- Không suy đoán hoặc công bố endpoint Brain² chưa quan sát/kiểm chứng.
- Không commit session, cookies, access token, HAR gốc, workspace ID, tài liệu nội bộ.
- Không tìm cách né CAPTCHA, WAF, rate limit, giới hạn gói hay cơ chế thanh toán.
- Không ngầm biến giải pháp **dùng Public API + LLM khác** thành tuyên bố “ClickUp Brain² API”.
- Nếu nhận quyền bằng văn bản: xác minh quyền, scope, chế độ rate limit và hợp đồng xử lý dữ liệu **trước khi** thử tích hợp.
- Đây là báo cáo phân tích source và tài liệu công khai; không phải kết quả chạy thử trên tài khoản ClickUp của người dùng.

## Nguồn chính

- [ClickUp Brain²](https://help.clickup.com/hc/en-us/articles/12578085238039-What-is-ClickUp-Brain-AI)
- [ClickUp Terms](https://clickup.com/terms)
- [ClickUp MCP tools](https://developer.clickup.com/docs/mcp-tools)
- [Playwright Network](https://playwright.dev/docs/network)
- [Playwright Auth](https://playwright.dev/docs/auth)
- [MDN — SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)

> Đề nghị: bắt đầu với hướng **official API/MCP + LLM** để có prototype hợp lệ; giữ kế hoạch kiểm chứng Brain² độc lập, chờ nhà cung cấp cho phép.
