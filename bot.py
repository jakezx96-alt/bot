import asyncio
import glob
import logging
import os
import re
import shutil
import tempfile

import yt_dlp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.environ["8936358808:AAE__GPtgV-2UpuXYE-cTm8gv73Dzh5elzA"]  # задаётся в переменных окружения, не в коде
COOKIES_FILE = os.environ.get("COOKIES_FILE")  # необязательно: cookies.txt для YouTube
DOWNLOAD_DIR = "downloads"
MAX_DURATION = 15 * 60  # секунд
MAX_FILESIZE = 49 * 1024 * 1024  # лимит Telegram для ботов ~50 МБ

URL_RE = re.compile(r"https?://[^\s]+")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("musicbot")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
download_sem = asyncio.Semaphore(2)


def base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


# --- СИНХРОННЫЕ ФУНКЦИИ yt-dlp (запускаются в потоке) ---

def _search(query: str) -> list:
    """Поиск с запасным вариантом: быстрый -> полный."""
    last_error = None
    for prefix, flat in (("ytsearch10", True), ("ytsearch5", False)):
        try:
            opts = {**base_opts(), "extract_flat": flat}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"{prefix}:{query}", download=False)
            entries = [e for e in ((info or {}).get("entries") or []) if e and e.get("id")]
            if entries:
                return entries
        except Exception as e:
            last_error = e
            log.warning("search via %s failed: %s", prefix, e)
    if last_error:
        raise last_error
    return []


def _download(url: str):
    """Скачивает по ссылке и конвертирует в mp3. Возвращает (tmpdir, mp3_path, info)."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="dl_", dir=DOWNLOAD_DIR)
    opts = {
        **base_opts(),
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
        "match_filter": yt_dlp.utils.match_filter_func(f"duration <= {MAX_DURATION}"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info is None:  # отфильтровано по длительности
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, None, None
        if info.get("entries"):
            info = info["entries"][0]
        files = glob.glob(os.path.join(tmpdir, "*.mp3"))
        if not files:
            raise RuntimeError("mp3 не создан (проверьте, что установлен ffmpeg)")
        return tmpdir, files[0], info
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def friendly_error(e: Exception) -> str:
    text = str(e)
    if "Sign in to confirm" in text or "not a bot" in text:
        return "YouTube заблокировал сервер бота (нужны cookies). Попробуйте позже."
    if "Video unavailable" in text or "Private video" in text:
        return "Видео недоступно (удалено, приватное или закрыто по региону)."
    if "ffmpeg" in text.lower():
        return "На сервере не установлен ffmpeg."
    return "Не удалось скачать трек. Попробуйте другой вариант."


# --- ОБЩАЯ ФУНКЦИЯ: скачать по ссылке и отправить ---

async def send_track(message: types.Message, url: str):
    status = await message.answer("📥 Скачиваю и конвертирую...")
    tmpdir = None
    try:
        async with download_sem:
            tmpdir, mp3_file, info = await asyncio.to_thread(_download, url)

        if mp3_file is None:
            await status.edit_text(f"⚠️ Трек длиннее {MAX_DURATION // 60} минут, пропускаю.")
            return
        if os.path.getsize(mp3_file) > MAX_FILESIZE:
            await status.edit_text("⚠️ Файл больше 50 МБ — Telegram не позволит его отправить.")
            return

        await message.answer_audio(
            audio=types.FSInputFile(mp3_file),
            title=info.get("track") or info.get("title"),
            performer=info.get("artist") or info.get("uploader"),
            duration=int(info.get("duration") or 0) or None,
        )
        await status.delete()
    except Exception as e:
        log.exception("download failed")
        await status.edit_text(f"⚠️ {friendly_error(e)}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Отправь название песни / имя исполнителя "
        "или просто ссылку на YouTube — я пришлю mp3."
    )


@dp.message(F.text)
async def on_text(message: types.Message):
    text = message.text.strip()

    # 1. Если в сообщении есть ссылка — качаем сразу, без поиска
    m = URL_RE.search(text)
    if m:
        await send_track(message, m.group(0))
        return

    # 2. Иначе — поиск по названию
    wait_msg = await message.answer("🔍 Ищу треки...")
    try:
        entries = await asyncio.to_thread(_search, text)
    except Exception as e:
        log.exception("search failed")
        await wait_msg.edit_text(f"⚠️ Ошибка поиска. {friendly_error(e)}")
        return

    if not entries:
        await wait_msg.edit_text("❌ Ничего не найдено. Попробуйте изменить запрос или пришлите ссылку.")
        return

    rows = []
    for i, entry in enumerate(entries[:10], 1):
        title = entry.get("title") or "Без названия"
        if len(title) > 45:
            title = title[:45] + "…"
        dur = fmt_duration(entry.get("duration"))
        label = f"{i}. {title}" + (f" [{dur}]" if dur else "")
        rows.append([types.InlineKeyboardButton(text=label, callback_data=f"dl_{entry['id']}")])

    await wait_msg.edit_text(
        "🎵 Выберите трек для скачивания:",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith("dl_"))
async def on_choose(callback: types.CallbackQuery):
    await callback.answer()
    video_id = callback.data.removeprefix("dl_")
    await send_track(callback.message, f"https://www.youtube.com/watch?v={video_id}")


# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---

async def handle(request):
    return web.Response(text="I am alive!")


async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()


async def main():
    await web_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
