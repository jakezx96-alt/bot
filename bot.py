import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

BOT_TOKEN = "8936358808:AAE__GPtgV-2UpuXYE-cTm8gv73Dzh5elzA"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

os.makedirs("downloads", exist_ok=True)

def search_tracks(query: str, limit: int = 5) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "default_search": f"ytsearch{limit}",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        return info.get("entries", []) if info else []

def download_track(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = f"downloads/{video_id}.%(ext)s"
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer("Привет! Отправь мне название песни или имя исполнителя, и я найду трек на YouTube.")

@dp.message()
async def handle_search(message: types.Message):
    query = message.text
    waiting_msg = await message.answer("🔍 Ищу трек...")
    
    tracks = search_tracks(query, limit=5)
    
    if not tracks:
        await message.answer("Ничего не найдено. Попробуй другой запрос.")
        await waiting_msg.delete()
        return

    keyboard_buttons = []
    for track in tracks:
        title = track.get("title", "Трек")
        video_id = track.get("id")
        if video_id:
            keyboard_buttons.append([InlineKeyboardButton(text=title, callback_data=f"dl_{video_id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer("Вот что удалось найти:", reply_markup=keyboard)
    await waiting_msg.delete()

@dp.callback_query(F.data.startswith("dl_"))
async def handle_download(callback: types.CallbackQuery):
    video_id = callback.data.split("_")[1]
    await callback.message.answer("📥 Скачиваю музыку...")
    
    try:
        file_path = download_track(video_id)
        audio = types.FSInputFile(file_path)
        await callback.message.answer_audio(audio)
        
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        await callback.message.answer(f"Произошла ошибка при скачивании: {e}")
    
    await callback.answer()

# --- Заглушка веб-сервера для бесплатного Render ---
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
        print(f"⚠️ ВНИМАНИЕ: Файл '{COOKIE_FILE}' не найден! YouTube может выдавать ошибку 'Sign in to confirm...'")
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
