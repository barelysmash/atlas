"""The error the peer API reports, shared by its route modules."""

from __future__ import annotations

from http import HTTPStatus


class ApiError(Exception):
    """A request the service refuses, with the status and code to report."""

    def __init__(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = dict(headers or {})
