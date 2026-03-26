
import asyncio
from browser import BrowserManager
from max_client import MaxClient
from telegram import send_telegram

async def run_bridge():
    b = await BrowserManager.get()
    page = b["page"]
    maxc = MaxClient(page)

    last = None
    while True:
        msg = await maxc.read_last_message()
        if msg and msg != last:
            last = msg
            send_telegram("MAX: " + msg)
        await asyncio.sleep(1)
