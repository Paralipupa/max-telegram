
from flask import Flask, request
import asyncio, os, requests
from browser import BrowserManager
from max_client import MaxClient

app = Flask(__name__)

async def download_photo(photo):
    file_id = photo[-1]["file_id"]
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    data = requests.get(f"https://api.telegram.org/bot{tg_token}/getFile?file_id={file_id}").json()
    file_path = data["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{tg_token}/{file_path}"
    out_path = f"/data/{file_path.split('/')[-1]}"
    with open(out_path, "wb") as f:
        f.write(requests.get(url).content)
    return out_path

@app.post("/")
def webhook():
    payload = request.json
    asyncio.create_task(process(payload))
    return "ok"

async def process(data):
    b = await BrowserManager.get()
    page = b["page"]
    maxc = MaxClient(page)
    chat_id = "-72609697391229"

    await maxc.open_chat(chat_id)

    msg = data["message"]

    if "photo" in msg:
        file = await download_photo(msg["photo"])
        await maxc.send_photo(file)
    else:
        await maxc.send_text(msg.get("text",""))

