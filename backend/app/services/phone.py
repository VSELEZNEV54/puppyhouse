"""Russian phone numbers: the site mask is «+7 (XXX) XXX-XX-XX», the database keeps E.164 «+7XXXXXXXXXX».

The rules mirror phoneDigits() in assets/js/main.js, so the server accepts exactly what the form accepts."""
from __future__ import annotations

import re

_NON_DIGIT = re.compile(r"\D")


def ten_digits(value: str | None) -> str:
    """The 10 national digits after +7 / 8 / 7, or '' if the value cannot be one Russian number."""
    s = (value or "").strip()
    if s.startswith("+7"):
        digits = _NON_DIGIT.sub("", s[2:])
    else:
        digits = _NON_DIGIT.sub("", s)
        if len(digits) == 11 and digits[0] in "78":
            digits = digits[1:]
    return digits if len(digits) == 10 else ""


def normalize(value: str | None) -> str | None:
    """'+7 (495) 123-45-67' → '+74951234567'; None if it is not a full Russian number."""
    d = ten_digits(value)
    return "+7" + d if d else None


def display(e164: str | None) -> str:
    """'+74951234567' → '+7 (495) 123-45-67' (the same look as the site mask)."""
    if not e164 or len(e164) != 12 or not e164.startswith("+7"):
        return e164 or ""
    d = e164[2:]
    return f"+7 ({d[:3]}) {d[3:6]}-{d[6:8]}-{d[8:]}"
