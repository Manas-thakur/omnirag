"""ASGI middleware: optional API-key auth, upload size guard and security headers."""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

API_KEY_HEADER = "X-API-Key"


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


async def _json_error(send: Send, status: int, detail: str, extra: Iterable = ()) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *extra,
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def supplied_key(scope: Scope) -> str:
    key = _header(scope, b"x-api-key")
    if key:
        return key
    auth = _header(scope, b"authorization")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


class APIKeyMiddleware:
    """Require ``X-API-Key: <key>`` (or ``Authorization: Bearer <key>``) on ``/api/*``.

    ``/api/health`` and the OpenAPI docs stay public so clients can discover
    that a key is needed. CORS preflight (``OPTIONS``) requests pass through.
    """

    def __init__(self, app: ASGIApp, api_key: str, public: Iterable[str] = ()) -> None:
        self.app = app
        self.api_key = api_key.encode()
        self.public = set(public)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if (
                path.startswith("/api/")
                and path not in self.public
                and scope.get("method") != "OPTIONS"
                and not hmac.compare_digest(supplied_key(scope).encode(), self.api_key)
            ):
                await _json_error(
                    send,
                    401,
                    "missing or invalid API key",
                    [(b"www-authenticate", b'Bearer realm="omnirag"')],
                )
                return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Reject requests to the given path suffixes whose body exceeds ``max_bytes``.

    Checks ``Content-Length`` up front and also counts streamed bytes, so an
    oversized upload is refused before it is spooled to disk.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, suffixes: Iterable[str]) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.suffixes = tuple(suffixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").endswith(self.suffixes):
            await self.app(scope, receive, send)
            return
        length = _header(scope, b"content-length")
        if length.isdigit() and int(length) > self.max_bytes:
            await _json_error(send, 413, self._message())
            return
        received = 0
        too_large = False
        replaced = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            # If the body overflowed, whatever error the app produced while
            # parsing it is replaced by a clean 413.
            nonlocal replaced
            if too_large:
                if message["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await _json_error(send, 413, self._message())
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            if not replaced:
                await _json_error(send, 413, self._message())
        except Exception:
            if not too_large:
                raise
            if not replaced:
                await _json_error(send, 413, self._message())

    def _message(self) -> str:
        return f"upload exceeds the {self.max_bytes / (1024 * 1024):.0f} MB limit"


class _TooLarge(Exception):
    pass


class SecurityHeadersMiddleware:
    """Conservative default headers on every response."""

    HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"x-frame-options", b"DENY"),
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.HEADERS if k not in existing]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, with_headers)
