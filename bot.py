import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

BOT_TOKEN = "8936358808:AAE__GPtgV-2UpuXYE-cTm8gv73Dzh5elzA"
COOKIE_FILE = "cookies.txt"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

os.makedirs("downloads", exist_ok=True)

def get_ydl_opts(extra_opts=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
    }
    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE
    if extra_opts:
        opts.update(extra_opts)
    return opts

def search_tracks(query: str, limit: int = 5) -> list[dict]:
    query = query.strip()
    
    # Если скинули прямую ссылку на YouTube
    if query.startswith(("http://", "https://")):
        try:
            with yt_dlp.YoutubeDL(get_ydl_opts({"extract_flat": True})) as ydl:
                info = ydl.extract_info(query, download=False)
                if info:
                    if "entries" in info:
                        return [{"title": e.get("title", "Трек"), "id": e.get("id")} for e in info["entries"] if e][:limit]
                    return [{"title": info.get("title", "Трек"), "id": info.get("id") or query}]
        except Exception as e:
            print(f"Ошибка ссылки: {e}")
        return []

    # Ищем через поисковик DuckDuckGo, чтобы Render не ловил капчу и блокировки от YouTube
    ydl_opts = get_ydl_opts({
        "extract_flat": True,
        "default_search": f"ddgsearch{limit}",
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"site:youtube.com {query}", download=False)
            entries = info.get("entries", []) if info else []
            
            results = []
            for e in entries:
                if e and "url" in e:
                    url = e["url"]
                    if "v=" in url:
                        v_id = url.split("v=")[1].split("&")[0]
                    else:
                        v_id = url.split("/")[-1]
                    results.append({"title": e.get("title", "Трек"), "id": v_id})
            return results[:limit]
    except Exception as e:
        print(f"Ошибка поиска через ddg: {e}")
        return []

def download_track(video_id: str) -> str:
    if video_id.startswith(("http://", "https://")):
        url = video_id
        safe_name = abs(hash(url))
    else:
        url = f"https://www.youtube.com/watch?v={video_id}"
        safe_name = video_id

    output_template = f"downloads/{safe_name}.%(ext)s"
    ydl_opts = get_ydl_opts({
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": output_template,
    })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer("🎵 Привет! Отправь мне название песни или ссылку на YouTube, и я найду и скачаю трек.")

@dp.message()
async def handle_search(message: types.Message):
    query = message.text
    waiting_msg = await message.answer("🔍 Ищу трек...")
    
    tracks = search_tracks(query, limit=5)
    
    if not tracks:
        await message.answer("Ничего не найдено. Попробуй написать название точнее или скинуть ссылку.")
        await waiting_msg.delete()
        return

    keyboard_buttons = []
    for track in tracks:
        title = track.get("title", "Трек")
        v_id = track.get("id")
        if v_id:
            btn_text = title[:50] + "..." if len(title) > 50 else title
            keyboard_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl_{v_id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer("Вот что удалось найти:", reply_markup=keyboard)
    await waiting_msg.delete()

@dp.callback_query(F.data.startswith("dl_"))
async def handle_download(callback: types.CallbackQuery):
    video_id = callback.data[3:]
    await callback.message.answer("📥 Скачиваю аудио...")
    
    try:
        file_path = download_track(video_id)
        audio = types.FSInputFile(file_path)
        await callback.message.answer_audio(audio)
        
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        await callback.message.answer(f"Произошла ошибка при скачивании: {e}")
    
    await callback.answer()

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
