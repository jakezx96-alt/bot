import asyncio
import os
import yt_dlp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# === НАСТРОЙКИ ===
TOKEN = "8936358808:AAE__GPtgV-2UpuXYE-cTm8gv73Dzh5elzA"
COOKIE_FILE = "cookies.txt"  # Файл куки должен лежать рядом со скриптом

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Общие настройки для yt-dlp (с поддержкой cookies.txt)
ydl_base_opts = {
    'quiet': True,
    'noplaylist': True,
}
if os.path.exists(COOKIE_FILE):
    ydl_base_opts['cookiefile'] = COOKIE_FILE

# Настройки для быстрого поиска 10 треков
YDL_SEARCH_OPTS = {
    **ydl_base_opts,
    'format': 'bestaudio/best',
    'extract_flat': True,
}

# Настройки для скачивания выбранного трека
YDL_DOWNLOAD_OPTS = {
    **ydl_base_opts,
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "🎵 Привет! Отправь мне название трека или имя исполнителя, "
        "и я найду 10 вариантов."
    )


@dp.message(F.text)
async def search_music(message: types.Message):
    query = message.text
    wait_msg = await message.answer("🔍 Ищу 10 вариантов музыки...")

    def _search():
        with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
            try:
                # Ищем 10 результатов на YouTube
                info = ydl.extract_info(f"ytsearch10:{query}", download=False)
                return info.get('entries', [])
            except Exception as e:
                print(f"Ошибка поиска: {e}")
                return []

    entries = await asyncio.to_thread(_search)

    if not entries:
        await wait_msg.edit_text("Ничего не найдено или произошла ошибка 😔 (проверь cookies.txt)")
        return

    keyboard = []
    for entry in entries:
        title = entry.get('title', 'Без названия')[:45]  # Обрезаем длинные названия
        duration = entry.get('duration')
        
        if duration:
            mins, secs = divmod(int(duration), 60)
            dur_str = f"{mins}:{secs:02d}"
        else:
            dur_str = "?:??"

        video_id = entry.get('id')
        if not video_id:
            continue

        btn_text = f"🎶 {title} ({dur_str})"
        # В callback_data передаем ID трека
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl_{video_id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await wait_msg.edit_text("Вот что удалось найти, выбери нужный трек:", reply_markup=markup)


@dp.callback_query(F.data.startswith("dl_"))
async def download_music(callback: types.CallbackQuery):
    video_id = callback.data.split("_", 1)[1]
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    await callback.answer("Скачиваю трек...")
    status_msg = await callback.message.answer("⏳ Скачиваю и конвертирую в MP3, подожди немного...")

    os.makedirs("downloads", exist_ok=True)

    def _download():
        with yt_dlp.YoutubeDL(YDL_DOWNLOAD_OPTS) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = f"downloads/{video_id}.mp3"
            title = info.get('title', 'Track')
            return file_path, title

    try:
        file_path, title = await asyncio.to_thread(_download)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError("Файл MP3 не был создан.")

        audio_file = types.FSInputFile(file_path, filename=f"{title}.mp3")
        await callback.message.answer_audio(audio=audio_file, title=title)
        await status_msg.delete()
        
        # Удаляем файл с диска после успешной отправки
        if os.path.exists(file_path):
            os.remove(file_path)
            
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при скачивании: {e}")


async def main():
    if not os.path.exists(COOKIE_FILE):
        print(f"⚠️ ВНИМАНИЕ: Файл '{COOKIE_FILE}' не найден! YouTube может выдавать ошибку 'Sign in to confirm...'")
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
