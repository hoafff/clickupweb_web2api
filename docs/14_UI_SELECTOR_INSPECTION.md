# 14 — Xác định CSS selector cho auto-send một cách có kiểm chứng

## Mục tiêu

Live E2E **manual** trên phiên ClickUp đã được người thực hiện xác nhận:
- `websocket_connections_observed=1`;
- `json_ws_frames_processed=12`;
- `matching_reply_comments=1`;
- phản hồi `OK` với độ dài 3 ký tự.

Đây là **bằng chứng thật cho receiving path** `Browser UI → WS aiConversationStarted → WS chatCommentCreated → reply text`. Nó **chưa chứng minh** Playwright có thể tự gửi prompt hoặc gateway có thể vận hành không cần browser.

Mục tiêu kế tiếp: chọn input composer và nút Send **từ DOM đang hiển thị**, không đoán selector dựa vào screenshot/HTML chưa có.

## Task / trạng thái

| ID | Workstream | Status | Definition of done |
|---|---|---|---|
| S-01 | Read-only inspector | DONE | `tools/inspect_brain_ui.py` không gửi message, không đọc content/cookies |
| S-02 | Safe candidate classification | DONE | editor, nearby button, coordinates, attrs whitelisted, unique selector |
| S-03 | CLI/test portability | DONE | Windows/Linux CLI `--help` qua subprocess, kiểm tra URL và page lựa chọn |
| S-04 | Live DOM verification | TODO | Người thực hiện xác minh composer/send trong browser đang đăng nhập |
| S-05 | Auto-send one prompt | TODO | `browser_adapter.py --mode auto` tự điền, click 1 lần, nhận reply |
| S-06 | API facade | BLOCKED | Cần xác nhận S-05, auth/session hosting và điều kiện triển khai |

## Cách chạy trên Windows

**Đóng Chromium/tracer/adapter cũ** trước để nhả profile nghiên cứu `.local/browser-profile`:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\inspect_brain_ui.py
```

1. Browser Chromium mở với phiên nghiên cứu đã dùng ở V3.
2. Mở ClickUp Brain² → Ask; để ô nhập và nút Send **hiển thị trên màn hình**.
3. Quay lại PowerShell và nhấn ENTER; inspector in JSON gồm `visible_editors` và `nearby_buttons`.
4. JSON **không chứa tin nhắn đang gõ, nội dung lịch sử chat, cookies, auth headers hoặc raw HTML**. Nó có thể có UI labels/attributes có thông tin workspace; kiểm tra trước khi gửi.
5. Dựa trên tên `aria-label`, `placeholder`, `data-testid` và tọa độ `rect` để nhận diện đúng editor và send. `css` là selector được kiểm tra unique trên DOM tại thời điểm inspect; `stable=true` ưu tiên, `stable=false` có thể thay đổi giữa lần load trang. Không tự suy đoán nút theo thứ tự.

**Sau khi xác minh đúng 2 CSS selectors**:

```powershell
.\.venv\Scripts\python.exe tools\browser_adapter.py --mode auto --confirm-send --composer-selector '<CSS thực tế của editor>' --send-selector '<CSS thực tế của nút Send>' --timeout 120 --show-reply
```

Đây là **một lần tự gửi** có opt-in từ người dùng, không phải bot định kỳ hay server public. Script sẽ hỏi một prompt ngắn trong terminal, sau khi Enter tại bước arm, mới fill và click. Chỉ thử một lượt trước khi thử conversation continuation/multiple models.

## Security / test bounds

- DOM inspector chỉ **đọc** element `tagName`, visible box, các attrs whitelisted, tạo CSS selector và thử `querySelectorAll` cho uniqueness.
- Không dump innerHTML/outerHTML, không đọc `input.value`, không chụp ảnh, không ghi browser profile/cookie/upload HAR.
- Phạm vi browser giới hạn `https://app.clickup.com`; nhiều tab ClickUp mơ hồ bị từ chối nếu không xác định được Brain tab.
- Browser Adapter tự kiểm tra phải match **đúng 1 editor và đúng 1 send button**, cả hai visible; nếu không thì từ chối gửi.
- CI dùng DOM/WS mocks; **chưa phải** live auto-send success.

## Rủi ro cần xử lý trước gateway cloud

Browser session profile chứa credential, không commit/đẩy lên GitHub. Cloud deploy thường cần browser persistent riêng, login recovery, credential encryption, concurrency limits, session expiry, có thể gặp thay đổi DOM. Không thể khẳng định GitHub Actions cron là hosting bền vững hay chính sách ClickUp cho phép bất kỳ hình thức web automation nào mà không đánh giá.
