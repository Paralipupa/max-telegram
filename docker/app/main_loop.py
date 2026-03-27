"""Event loop where Playwright runs (set from runner.py). Used to schedule webhook work."""

from __future__ import annotations

import asyncio
from typing import Optional

_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _loop
