"""Best-effort display-layer masking for sensitive-looking data in agent output.

This runs only on data already produced for API responses (transcript text, tool
argument values) - never on data used for deterministic evaluation - so it cannot
influence scoring. It is a defensive UX measure, not a PII detector: patterns are
intentionally conservative Turkish-context heuristics (TC kimlik no, mobile phone,
card-like digit runs), not a general PII classifier.
"""

import re

_CARD_LIKE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?<=\d)(?!\d)")
_TC_KIMLIK_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?90[\s.-]?)?0?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"
)


def _mask_middle(digits: str, keep_start: int, keep_end: int) -> str:
    if len(digits) <= keep_start + keep_end:
        return "*" * len(digits)
    hidden = len(digits) - keep_start - keep_end
    return f"{digits[:keep_start]}{'*' * hidden}{digits[-keep_end:]}"


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if not 13 <= len(digits) <= 19:
        return match.group(0)
    return _mask_middle(digits, 4, 4)


def _mask_tc_kimlik(match: re.Match[str]) -> str:
    return _mask_middle(match.group(0), 3, 2)


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    mobile = digits[-10:]
    return _mask_middle(mobile, 3, 4)


def mask_sensitive_text(text: str) -> str:
    """Mask card-like, TC kimlik no, and Turkish mobile phone digit runs in text."""

    masked = _CARD_LIKE_RE.sub(_mask_card, text)
    masked = _TC_KIMLIK_RE.sub(_mask_tc_kimlik, masked)
    masked = _PHONE_RE.sub(_mask_phone, masked)
    return masked
