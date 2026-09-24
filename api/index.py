import os
import io
import json
from http.server import BaseHTTPRequestHandler
from PIL import Image
from telegram import Update, Bot
from telegram.ext import Application
import asyncio

from services import parse_with_gemini, save_transactions_to_db, query_financial_summary

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def process_telegram_update(data: dict):
    update = Update.de_json(data, bot)
    if not update or not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    # 1. Handle Foto (Struk Belanja)
    if message.photo:
        await bot.send_message(chat_id=chat_id, text="Menganalisis struk belanja...")
        try:
            photo_file = await message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            image = Image.open(io.BytesIO(image_bytes))

            parsed = parse_with_gemini(image)
            save_transactions_to_db(parsed, raw_source="[Foto Struk Belanja]")

            reply_lines = ["🧾 *Struk Berhasil Diurai & Dicatat:*"]
            total = 0
            for item in parsed.items:
                reply_lines.append(f"• {item.item_name} [{item.category}]: Rp{item.amount:,.0f}")
                total += item.amount
            reply_lines.append(f"\n💰 *Total:* Rp{total:,.0f}")
            reply_lines.append(f"💬 *Roast:* {parsed.roast_comment}")

            await bot.send_message(chat_id=chat_id, text="\n".join(reply_lines), parse_mode="Markdown")
        except Exception as e:
            await bot.send_message(chat_id=chat_id, text=f"Gagal membaca struk: {str(e)}")
        return

    # 2. Handle Teks
    if message.text:
        user_text = message.text

        if user_text.startswith("/start"):
            await bot.send_message(
                chat_id=chat_id,
                text="Halo! Kirim catatan pengeluaran/pemasukan lewat chat atau kirim foto struk belanja untuk dicatat."
            )
            return

        query_keywords = ["berapa", "total", "cek", "sisa", "apakah", "rekap"]
        if any(kw in user_text.lower() for kw in query_keywords) and "?" in user_text:
            await bot.send_message(chat_id=chat_id, text="Sedang menganalisis catatanmu...")
            answer = query_financial_summary(user_text)
            await bot.send_message(chat_id=chat_id, text=answer)
            return

        # Pencatatan transaksi teks biasa
        await bot.send_message(chat_id=chat_id, text="Mencatat transaksi...")
        try:
            parsed = parse_with_gemini(user_text)
            save_transactions_to_db(parsed, raw_source=user_text)

            reply_lines = ["✅ *Transaksi Berhasil Dicatat:*"]
            for item in parsed.items:
                reply_lines.append(f"• {item.item_name} ({item.category}): Rp{item.amount:,.0f}")
            reply_lines.append(f"\n💬 *Roast:* {parsed.roast_comment}")

            await bot.send_message(chat_id=chat_id, text="\n".join(reply_lines), parse_mode="Markdown")
        except Exception as e:
            await bot.send_message(chat_id=chat_id, text=f"Terjadi kesalahan: {str(e)}")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data.decode("utf-8"))
            # Jalankan event loop async untuk memproses telegram update
            asyncio.run(process_telegram_update(data))
        except Exception as err:
            print("Error processing update:", err)

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot webhook running!")