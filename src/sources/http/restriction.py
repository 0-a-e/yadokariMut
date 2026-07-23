"""Detect access restriction / bot-block responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sources.http.settings import HttpFetchSettings


def is_restricted(
    *,
    status_code: int,
    body: str | bytes | None,
    settings: "HttpFetchSettings",
) -> tuple[bool, str | None]:
    """Return (restricted, reason)."""
    if status_code in settings.restriction_status_codes:
        return True, f"http_{status_code}"

    if body is None:
        return False, None

    if isinstance(body, bytes):
        body_len = len(body)
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    else:
        text = body
        body_len = len(body.encode("utf-8", errors="replace"))

    # Heuristic: tiny body with block-ish markers only when status looks OK
    # (avoid flagging legitimate empty 404 pages as restriction for 404 itself —
    # 404 is not in restriction_status_codes by default).
    if status_code == 200 and body_len < settings.min_body_bytes:
        lower = text.lower()
        for pat in settings.body_block_patterns:
            if pat.lower() in lower or pat in text:
                return True, f"body_pattern:{pat[:40]}"

    if status_code == 200 and text:
        lower = text.lower()
        for pat in settings.body_block_patterns:
            if pat.lower() in lower or pat in text:
                # Only treat as restricted if pattern is strong / page looks like challenge
                strong = any(
                    k in lower
                    for k in (
                        "cf-browser-verification",
                        "just a moment",
                        "access denied",
                        "captcha",
                    )
                )
                if strong or pat.lower() in (
                    "cf-browser-verification",
                    "just a moment",
                    "access denied",
                ):
                    return True, f"body_pattern:{pat[:40]}"

    return False, None
