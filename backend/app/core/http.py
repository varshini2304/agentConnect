"""Bound request buffering before JSON parsing or authentication."""
from starlette.responses import JSONResponse


class RequestSizeLimit:
    def __init__(self, app, max_bytes=1_048_576):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        length = headers.get(b'content-length', b'0')
        if not length.isdigit() or int(length) > self.max_bytes:
            return await JSONResponse({'detail': 'Request body exceeds the 1 MiB limit'}, status_code=413)(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.max_bytes:
                return await JSONResponse({'detail': 'Request body exceeds the 1 MiB limit'}, status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get('more_body', False):
                break
        iterator = iter(messages)

        async def replay():
            message = next(iterator, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)
