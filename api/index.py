import os
import io
import traceback
import requests
from fastapi import FastAPI, Request
from PIL import Image
from telegram import Update, Bot

from services import parse_with_gemini, save_transactions_to_db, query_financial_summary

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def send_telegram_msg(chat_id, text, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Gagal kirim pesan telegram:", e)

@app.get("/")
@app.get("/api/index")
async def health_check():
    return {"status": "ok", "message": "Bot webhook is running"}

@app.post("/")
@app.post("/api/index")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"ok": True}

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    update = Update.de_json(data, bot)

    if not update or not update.message:
        return {"ok": True}

    message = update.message
    chat_id = message.chat_id

    # 1. Handle Foto Struk Belanja
    if message.photo:
        send_telegram_msg(chat_id, "Menganalisis struk belanja...")
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

            send_telegram_msg(chat_id, "\n".join(reply_lines), parse_mode="Markdown")
        except Exception as e:
            print("Error parsing photo:", traceback.format_exc())
            send_telegram_msg(chat_id, f"Gagal membaca struk: {str(e)}")
        return {"ok": True}

    # 2. Handle Pesan Teks
    if message.text:
        user_text = message.text

        if user_text.startswith("/start"):
            send_telegram_msg(
                chat_id, 
                "Halo! Kirim catatan pengeluaran/pemasukan lewat chat atau kirim foto struk belanja untuk dicatat."
            )
            return {"ok": True}

        query_keywords = ["berapa", "total", "cek", "sisa", "apakah", "rekap"]
        if any(kw in user_text.lower() for kw in query_keywords) and "?" in user_text:
            send_telegram_msg(chat_id, "Sedang menganalisis catatanmu...")
            try:
                answer = query_financial_summary(user_text)
                send_telegram_msg(chat_id, answer)
            except Exception as e:
                print("Error query summary:", traceback.format_exc())
                send_telegram_msg(chat_id, f"Gagal mengambil ringkasan: {str(e)}")
            return {"ok": True}

        # Transaksi Biasa
        send_telegram_msg(chat_id, "Mencatat transaksi...")
        try:
            parsed = parse_with_gemini(user_text)
            save_transactions_to_db(parsed, raw_source=user_text)

            reply_lines = ["✅ *Transaksi Berhasil Dicatat:*"]
            for item in parsed.items:
                reply_lines.append(f"• {item.item_name} ({item.category}): Rp{item.amount:,.0f}")
            reply_lines.append(f"\n💬 *Roast:* {parsed.roast_comment}")

            send_telegram_msg(chat_id, "\n".join(reply_lines), parse_mode="Markdown")
        except Exception as e:
            print("Error parsing text:", traceback.format_exc())
            send_telegram_msg(chat_id, f"Terjadi kesalahan: {str(e)}")

    return {"ok": True}