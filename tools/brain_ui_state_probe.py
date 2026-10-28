"""Read-only ClickUp Brain UI state probe for controlled completion research.

NEVER reads innerText, textContent, value, prompt, messages, cookies, localStorage,
network headers, account/workspace/conversation IDs or page URL text.
Only emits a strict allowlist of booleans / bounded integers.

Candidate Stop/Generating controls are NOT proof of inference completion.
This is instrumentation, not a part of the user-facing completion algorithm.
"""
from __future__ import annotations

from typing import Any

# No interactions, network requests, DOM mutation, timers or messages.
BRAIN_UI_STATE_JS = r"""
() => {
  const visible = (n) => {
    if (!n || !n.isConnected) return false;
    const r = n.getBoundingClientRect();
    const s = window.getComputedStyle(n);
    return r.width > 6 && r.height > 6
      && s.visibility !== 'hidden' && s.display !== 'none'
      && r.bottom > 0 && r.top < window.innerHeight
      && r.right > 0 && r.left < window.innerWidth;
  };
  const editor = document.querySelector('div[contenteditable="true"]');
  const send = document.querySelector(
    'button[data-test="refinement-prompt-submit-button"]'
  );
  const disabled = n => !!n && (
    n.disabled === true ||
    n.getAttribute('aria-disabled') === 'true'
  );
  const candidates = [...document.querySelectorAll(
    'button, [role="button"], [role="progressbar"], [aria-busy="true"]'
  )].slice(0, 500);
  let visibleButtons = 0, stopLike = 0, busyLike = 0;
  let progressbars = 0, ariaBusy = 0, stopNearEditor = 0;
  const root = editor && editor.getBoundingClientRect();
  for (const n of candidates) {
    if (!visible(n)) continue;
    const tag = (n.tagName || '').toLowerCase();
    const role = n.getAttribute('role');
    const isButton = tag === 'button' || role === 'button';
    if (isButton) visibleButtons++;
    if (role === 'progressbar') progressbars++;
    if (n.getAttribute('aria-busy') === 'true') ariaBusy++;
    // Read attributes only as short temporary local strings for boolean
    // classification. NO attribute value or label is ever returned.
    const attributeNames = ['aria-label', 'title', 'data-test', 'data-testid'];
    let attrs = '';
    for (const name of attributeNames) {
      const s = n.getAttribute(name);
      if (typeof s === 'string' && s.length <= 160) attrs += ' ' + s;
    }
    const stop = isButton && /\b(stop|cancel|interrupt|dừng|hủy)\b/i.test(attrs);
    const busy = isButton && /\b(generating|thinking|processing|streaming|đang tạo|đang xử lý)\b/i.test(attrs);
    if (stop) {
      stopLike++;
      if (root) {
        const r = n.getBoundingClientRect();
        const cx = (r.left + r.right) / 2;
        const cy = (r.top + r.bottom) / 2;
        const x = Math.max(root.left, Math.min(cx, root.right));
        const y = Math.max(root.top, Math.min(cy, root.bottom));
        if (Math.hypot(cx - x, cy - y) < 220) stopNearEditor++;
      }
    }
    if (busy) busyLike++;
  }
  return {
    page_is_brain: location.hostname === 'app.clickup.com'
      && location.pathname.includes('/ai/brain'),
    document_visible: document.visibilityState === 'visible',
    composer_visible: visible(editor),
    composer_disabled: disabled(editor),
    send_visible: visible(send),
    send_disabled: disabled(send),
    visible_button_count: visibleButtons,
    stop_candidate_count: stopLike,
    stop_near_composer_count: stopNearEditor,
    generating_candidate_count: busyLike,
    visible_progressbar_count: progressbars,
    visible_aria_busy_count: ariaBusy
  };
}
"""

BOOLEAN_FIELDS = (
    "page_is_brain",
    "document_visible",
    "composer_visible",
    "composer_disabled",
    "send_visible",
    "send_disabled",
)
COUNT_FIELDS = (
    "visible_button_count",
    "stop_candidate_count",
    "stop_near_composer_count",
    "generating_candidate_count",
    "visible_progressbar_count",
    "visible_aria_busy_count",
)


def sanitize_ui_snapshot(raw: Any) -> dict[str, int | bool]:
    """No arbitrary Playwright/JS return fields may reach an HTTP client."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid UI metadata type.")
    clean: dict[str, int | bool] = {}
    for name in BOOLEAN_FIELDS:
        value = raw.get(name)
        if type(value) is not bool:
            raise ValueError("Invalid UI metadata boolean.")
        clean[name] = value
    for name in COUNT_FIELDS:
        value = raw.get(name)
        if type(value) is not int or not 0 <= value <= 500:
            raise ValueError("Invalid UI metadata count.")
        clean[name] = value
    return clean
