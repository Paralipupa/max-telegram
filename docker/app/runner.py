import asyncio
import threading
import uvicorn
from bridge import run_bridge
from webhook import app
from browser import BrowserManager
from main_loop import set_main_loop

async def main():
    set_main_loop(asyncio.get_running_loop())
    await BrowserManager.get()

    threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info"),
        daemon=True,
    ).start()
    await run_bridge()

if __name__ == "__main__":
    asyncio.run(main())
