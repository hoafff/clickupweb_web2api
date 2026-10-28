# 04 — Worksheet kiểm chứng chức năng (chỉ trong môi trường được phép)

> Không ghi cookies, bearer tokens, session headers, HAR thô, nội dung Workspace hoặc thông tin cá nhân vào issue/repo public. Mẫu dưới đây được dùng để ghi **quan sát UI/tài liệu công khai** và kiểm chứng API **được ClickUp cho phép**; không dùng để thu gom private requests.

## Thông tin phiên khảo sát

- Ngày:
- Reviewer:
- Phiên bản tài liệu ClickUp / URL:
- Workspace role: (chỉ ghi role, không ghi workspace ID)
- Loại bằng chứng: UI-only / official docs / authorized API contract / mock test
- Văn bản chấp thuận và scope (nếu có): tham chiếu ticket nội bộ, **không dán credential**
- Kết quả: Observed / Documented / Hypothesis / Not Tested / Blocked

## Kiểm kê chức năng Brain²

| Thành phần | Có trong UI / docs? | Có official API? | Đã test? | Ghi chú |
|---|---|---|---|---|
| Ask / chat text | Có (UI + docs) | Chưa xác nhận Brain² chat API | Không | Tránh gọi bằng private API |
| Max | Có | Chưa xác nhận external Brain Max API | Không | Có thể là dynamic orchestration |
| ChatGPT-family model picker | Docs có | Chưa xác nhận Brain² API | Không | Version thay đổi |
| Claude-family model picker | Docs có | Chưa xác nhận Brain² API | Không | Version thay đổi |
| Gemini-family model picker | Docs có | Chưa xác nhận Brain² API | Không | Version thay đổi |
| Model switch mid-chat | Docs có | Chưa xác nhận API | Không | Giữ history/context theo UI |
| Skills | Có (UI/docs) | Chưa xác nhận Brain² API | Không | Scope/phân quyền |
| Agents | Có (UI/docs) | API riêng cần kiểm chứng | Không | Không đồng nhất Brain chat |
| Memory | Có (UI) | Chưa xác nhận | Không | Chú ý retention |
| Search context / mentions | Docs có | Một phần thực hiện qua MCP tools | Không | Không đồng nhất Brain internal context |
| File/image uploads | Docs có | Brain² API chưa xác nhận | Không | Kiểm tra dữ liệu nhạy cảm |
| Streaming token-by-token | Chưa xác nhận wire protocol | Chưa xác nhận | Không | Đừng tự nhận SSE |
| Usage / premium allowance | Có theo docs | Chưa xác nhận API chi tiết | Không | Workspace-level |

## Kiểm kê model từ menu

Chụp/ghi **display labels** trong menu model UI; không suy từ bài blog hoặc model đã bị thay thế. Phân loại `Max`, `ChatGPT`, `Claude`, `Gemini`, `Other` nếu UI thực tế có. Chỉ ghi tên **chính xác như hiển thị**, availability và tùy chọn context/feature. Không suy diễn API model ID.

| UI display label | Provider-family | Standard/Premium (nếu UI nói rõ) | Có thể chọn? | Mid-chat? | Ngày kiểm chứng | API alias được xác nhận? |
|---|---|---|---|---|---|---|
| Max | ClickUp orchestrator | Unknown | Trong screenshot đang chọn | Docs nói có thể switch | 28/10/2026 | Không |
| (bổ sung từ model picker UI) | | | | | | |
| (bổ sung từ model picker UI) | | | | | | |

**Nguyên tắc:** `Unknown` khác `No`. Nếu không có đường API được cho phép, field alias phải để trống.

## Test cases không đụng private API

- [ ] ModelRegistry không trả model chưa cấu hình hoặc chưa được cấp phép.
- [ ] Model không tồn tại trả `invalid_model` thay vì fallback ẩn.
- [ ] Test chọn Model A, gửi prompt 1, chuyển Model B, gửi prompt 2, giữ đúng lịch sử do client cho phép.
- [ ] Model alias và display name được lưu riêng; logs chỉ lưu alias, không lưu prompt.
- [ ] Model capability không được đánh đồng giữa các provider (image, file, tools, search, context).
- [ ] Thiếu API key gateway trả 401; thiếu permission trả 403; mock rate limit trả 429.
- [ ] SSE mock kết thúc đúng, xử lý chunk UTF-8, không trộn delta giữa hai conversation.
- [ ] Khi disconnect, hủy tác vụ upstream đang được hỗ trợ; không để job treo.
- [ ] Kiểm tra input injection trong tên tài liệu; LLM không được tự nâng quyền truy xuất dữ liệu.
- [ ] Document ghi rõ Brain² chính thức và bản self-hosted dùng MCP + LLM là **hai sản phẩm khác nhau**.

## Cách lập bằng chứng đáng tin cậy

- Screenshot UI: chỉ giúp biết feature/model hiển thị, **không nói được endpoint**.
- Product docs / API docs: biết contract nhà cung cấp hỗ trợ, phiên bản và giới hạn.
- Unit test mock: chứng minh lớp adapter do mình viết đúng, **không** chứng minh ClickUp thật tương thích.
- Integration test được cấp quyền: mới xác nhận truy cập có hiệu lực trong phạm vi approval.
- Review access/terms: chặn triển khai không được cấp phép kể cả khi “chạy được”.

## Không đưa lên repo

Không commit local storage, browser profile, cookie JSON, URL chứa token, Authorization header, HAR raw, screenshot có thông tin cá nhân, task/doc content, Session ID, passphrase, SSH keys. Nếu sơ ý để lộ: revoke/rotate ngay tại provider, xóa lịch sử git chứa bí mật, không chỉ `git rm` ở HEAD.
