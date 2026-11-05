"""Response headers that harden a JSON API for browsers and shared caches."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # An API response never needs to load or run anything.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware:
    """Adds hardening headers and keeps API responses (which can carry tokens and
    personal data) out of browser and proxy caches.

    The interactive docs pages (development only) are left cacheable and without a
    restrictive CSP so that they keep working.
    """

    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        self.app = app
        self._api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        is_docs = path in ("/docs", "/redoc") or path.startswith("/docs/")
        is_api = path.startswith(self._api_prefix)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                if not is_docs:
                    for name, value in _STATIC_HEADERS.items():
                        headers.setdefault(name, value)
                if is_api:
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_wrapper)
