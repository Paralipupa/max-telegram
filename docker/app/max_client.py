
class MaxClient:
    def __init__(self, page):
        self.page = page

    async def open_chat(self, chat_id):
        await self.page.goto(f"https://web.max.ru/{chat_id}")
        await self.page.wait_for_selector('[contenteditable]', timeout=15000)

    async def send_text(self, text):
        editor = await self.page.wait_for_selector('[contenteditable]')
        await editor.fill(text)
        await editor.press("Enter")

    async def send_photo(self, file_path):
        file_input = await self.page.wait_for_selector('input[type=file]')
        await file_input.set_input_files(file_path)
        await self.page.wait_for_selector('[aria-label="Отправить сообщение"]')
        await self.page.click('[aria-label="Отправить сообщение"]')

    async def read_last_message(self):
        msgs = await self.page.query_selector_all('div[class*="message"] span[class*="text"]')
        if not msgs:
            return None
        msg = msgs[-1]
        txt = await msg.inner_text()
        return txt.strip() if txt else None
