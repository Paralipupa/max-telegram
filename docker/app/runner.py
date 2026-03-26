
import asyncio
import threading
from bridge import run_bridge
from webhook import app
from browser import BrowserManager

async def main():
    await BrowserManager.get()

    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8081)).start()
    await run_bridge()

if __name__ == "__main__":
    asyncio.run(main())
