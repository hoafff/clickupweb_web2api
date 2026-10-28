#!/usr/bin/env python3
"""Inspect visible ClickUp Brain UI controls without sending a message.

After the authorized researcher signs in and opens Brain, output ONLY
visible input/button attributes, screen coordinates, and locally verified
CSS selectors. Never read input values, message text, cookies or headers.

This tool does not modify the page, execute ClickUp requests, or capture HTML.
All candidate selectors must be visually confirmed before using --mode auto.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError, async_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / ".local" / "browser-profile"

# Read-only JavaScript. The UI's text content and input values are not read.
PROBE_JS = r"""
() => {
  const opts = { maxEntries: 25, attrLimit: 100 };
  const editorNodes = [...document.querySelectorAll(
    'textarea, [contenteditable="true"], [role="textbox"], input:not([type="hidden"]):not([type="password"])'
  )];
  const buttonNodes = [...document.querySelectorAll(
    'button, [role="button"], input[type="submit"]'
  )];
  const visible = (node) => {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 8 && rect.height > 8
      && style.visibility !== 'hidden' && style.display !== 'none'
      && rect.bottom > 0 && rect.top < window.innerHeight
      && rect.right > 0 && rect.left < window.innerWidth;
  };
  const coords = (node) => {
    const r = node.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height)};
  };
  const attrs = (node) => {
    const allowed = ['aria-label', 'placeholder', 'title', 'data-testid',
                     'data-test', 'data-qa', 'role', 'type'];
    const out = {};
    for (const name of allowed) {
      const value = node.getAttribute(name);
      if (typeof value === 'string' && value.length && value.length <= opts.attrLimit) {
        out[name] = value;
      }
    }
    return out;
  };
  const isUnique = (selector) => {
    try {
      return document.querySelectorAll(selector).length === 1;
    } catch {
      return false;
    }
  };
  const selectorFor = (node) => {
    const tag = node.tagName.toLowerCase();
    const priority = ['data-testid', 'data-test', 'data-qa',
                      'aria-label', 'placeholder', 'title'];
    for (const attr of priority) {
      const val = node.getAttribute(attr);
      if (!val || val.length > opts.attrLimit) continue;
      const selector = tag + '[' + attr + '="' + CSS.escape(val) + '"]';
      if (isUnique(selector)) return {css: selector, stable: true};
    }
    if (node.isContentEditable) {
      const sel = tag + '[contenteditable="true"]';
      if (isUnique(sel)) return {css: sel, stable: false};
    }
    if (isUnique(tag)) return {css: tag, stable: false};
    // Last resort: a DOM path from the currently observed page. Fragile!
    const parts = [];
    let cur = node;
    while (cur && cur.nodeType === 1 && parts.length < 30) {
      const name = cur.tagName.toLowerCase();
      if (name === 'html') {
        parts.unshift('html');
        break;
      }
      let index = 1;
      let prev = cur.previousElementSibling;
      while (prev) {
        if (prev.tagName === cur.tagName) index++;
        prev = prev.previousElementSibling;
      }
      parts.unshift(name + ':nth-of-type(' + index + ')');
      const selector = parts.join(' > ');
      if (isUnique(selector)) {
        return {css: selector, stable: false};
      }
      cur = cur.parentElement;
    }
    return {css: null, stable: false};
  };
  const editors = editorNodes.filter(visible).slice(0, opts.maxEntries);
  const editorsInfo = editors.map(node => ({
    kind: 'editor', tag: node.tagName.toLowerCase(),
    attrs: attrs(node), rect: coords(node), ...selectorFor(node)
  }));
  // Only inspect buttons within 320px of an editor center, or in the
  // bottom 35% of the viewport if no visible editor was found.
  const relevantButton = (node) => {
    const r = node.getBoundingClientRect();
    const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
    if (!editors.length) return cy >= window.innerHeight * .65;
    return editors.some(ed => {
      const e = ed.getBoundingClientRect();
      const x = Math.max(e.left, Math.min(cx, e.right));
      const y = Math.max(e.top, Math.min(cy, e.bottom));
      return Math.hypot(cx - x, cy - y) <= 320;
    });
  };
  const buttons = buttonNodes.filter(n => visible(n) && relevantButton(n))
      .slice(0, opts.maxEntries);
  return {
    viewport: {width: window.innerWidth, height: window.innerHeight},
    document_host: location.hostname,
    visible_editors: editorsInfo,
    nearby_buttons: buttons.map(node => ({
      kind: 'button', tag: node.tagName.toLowerCase(),
      attrs: attrs(node), rect: coords(node), ...selectorFor(node)
    })),
    note: 'Never assume a button is Send based on order/coordinates alone. Verify in live DOM.'
  };
}
"""


def valid_clickup_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme == "https" and parts.hostname == "app.clickup.com"
    except (ValueError, TypeError):
        return False


def select_brain_page(pages: list) -> object:
    """Choose the foreground/research page; never browse arbitrary websites."""
    available = [p for p in pages if not p.is_closed() and valid_clickup_url(p.url)]
    if not available:
        raise ValueError("No ClickUp tab found; open app.clickup.com in the browser.")
    for page in reversed(available):
        url = page.url.lower()
        if "/ai/" in url or "/brain" in url:
            return page
    if len(available) > 1:
        raise ValueError("Multiple ClickUp tabs found; close extras or navigate to Brain URL.")
    return available[0]


async def run(args: argparse.Namespace) -> int:
    if not valid_clickup_url(args.url):
        print("This inspector accepts only HTTPS app.clickup.com URLs.", file=sys.stderr)
        return 2
    profile = args.profile_dir.expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=False, accept_downloads=False,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(args.url, wait_until="domcontentloaded", timeout=45_000)
            except PlaywrightError:
                print("Initial navigation incomplete; continue manually.")
            print("Open Brain² chat and ensure composer + send button are visible.")
            print("No message will be sent and no message contents will be read.")
            await asyncio.to_thread(input, "Press ENTER to inspect visible controls: ")
            selected = select_brain_page(context.pages)
            result = await selected.evaluate(PROBE_JS)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        finally:
            await context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://app.clickup.com/")
    parser.add_argument("--profile-dir", type=Path, default=PROFILE)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (ValueError, PlaywrightError) as exc:
        print(f"UI inspection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
