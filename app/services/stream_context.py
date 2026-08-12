from contextvars import ContextVar
from typing import Awaitable, Callable


StreamCallback = Callable[[str], Awaitable[None]]

current_stream_callback: ContextVar[StreamCallback | None] = ContextVar(
    "current_stream_callback",
    default=None,
)
