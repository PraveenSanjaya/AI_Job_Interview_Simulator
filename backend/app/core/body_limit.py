"""Reject oversized request bodies before they are buffered.

Multipart parsing buffers the whole upload (to memory/disk) before a route runs, so
a size check inside the route cannot protect the server from a huge body. This
middleware enforces a cap early: by ``Content-Length`` when it is declared, and by
counting streamed bytes otherwise. Once the cap is exceeded the application sees a
client disconnect (so it stops reading) and the client receives a clean ``413``.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import PayloadTooLargeError


class MaxBodySizeMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        path_prefix: str,
        exclude_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self._max_bytes = max_bytes
        self._prefix = path_prefix
        self._excluded = exclude_prefixes

    def _applies(self, path: str) -> bool:
        return path.startswith(self._prefix) and not path.startswith(self._excluded)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._applies(scope["path"]):
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0
        exceeded = False
        rejected = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal rejected
            if not exceeded:
                await send(message)
            elif not rejected:
                # Replace whatever the app tried to say (e.g. a parse error) with 413.
                rejected = True
                await self._reject(scope, receive, send)

        await self.app(scope, counting_receive, guarded_send)
        if exceeded and not rejected:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {
                "error": {
                    "code": PayloadTooLargeError.code,
                    "message": "The request body is too large",
                    "request_id": scope.get("request_id"),
                }
            },
            status_code=PayloadTooLargeError.status_code,
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)
