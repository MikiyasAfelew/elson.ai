"""Application errors.

Every error carries a short code and a message written to be spoken aloud by a screen reader
or by the app itself: plain words, no jargon, and a hint about what to do next.
"""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}
