"""Safe, local-only memory of ClickUp Brain's landing route.

Never persist a conversationId query parameter or existing chat URL. A
workspace route is NOT a credential, but still private workspace metadata.
Store it under Git-ignored .local/, not in the repository's tracked files.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
from urllib.parse import urlsplit

DEFAULT_URL = "https://app.clickup.com/"
DEFAULT_START_FILE = Path(__file__).resolve().parents[1] / ".local" / "brain-start-url.txt"
_BRAIN_PATH = re.compile(r"^/[0-9]+/ai/brain/?$")


def normalize_brain_start_url(url: str) -> str:
    """Exact ClickUp Brain landing URL; strip conversation/query/fragment."""
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Invalid ClickUp Brain URL.")
    try:
        p = urlsplit(url)
        valid = (
            p.scheme == "https"
            and p.hostname == "app.clickup.com"
            and p.username is None
            and p.password is None
            and p.port is None
            and bool(_BRAIN_PATH.fullmatch(p.path))
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError(
            "Expected an HTTPS app.clickup.com/<workspace-id>/ai/brain URL."
        )
    # Canonical workspace route, never query or fragment.
    return f"https://app.clickup.com{p.path.rstrip('/')}"


def load_start_url(path: Path = DEFAULT_START_FILE) -> str | None:
    """Read optional remembered route; malformed file fails safely."""
    try:
        stored = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise ValueError("Unable to read local Brain startup URL.") from exc
    if not stored:
        return None
    return normalize_brain_start_url(stored)


def remember_start_url(url: str, path: Path = DEFAULT_START_FILE) -> str:
    """Persist only the canonical route via a restrictive temporary file."""
    clean = normalize_brain_start_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(clean + "\n")
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        os.replace(tmp, path)
    except OSError as exc:
        raise ValueError("Cannot save local Brain startup URL.") from exc
    return clean


def choose_start_url(
    explicit_url: str | None, path: Path = DEFAULT_START_FILE
) -> str:
    """An explicitly chosen URL wins; otherwise use last verified route."""
    if explicit_url is not None:
        try:
            p = urlsplit(explicit_url)
            if p.scheme != "https" or p.hostname != "app.clickup.com":
                raise ValueError()
            if p.username is not None or p.password is not None or p.port is not None:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise ValueError("Only https://app.clickup.com/ is allowed.") from exc
        # Explicit existing-chat URL is operator-provided. Saving still strips
        # its conversationId, so subsequent auto-start goes to Brain landing.
        return explicit_url
    return load_start_url(path) or DEFAULT_URL
