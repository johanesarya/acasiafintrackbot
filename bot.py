import os
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from services import parse_with_gemini, save_transactions_to_db, query_financial_summary

load_dotenv()

# --- DUMMY WEB SERVER UNTUK RENDER HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Telegram Aktif dan Berjalan!")

    # Mencegah log request HTTP memenuhi terminal
    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo! Kirimkan pengeluaran/pemasukan lewat teks (misal: 'makan siang bebek 35rb') "
        "atau langsung kirim foto struk belanja untuk dicatat."
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # Deteksi jika pengguna sedang bertanya (Interactive Query)
    query_keywords = ["berapa", "total", "cek", "sisa", "apakah", "rekap"]
    if any(kw in user_text.lower() for kw in query_keywords) and "?" in user_text:
        await update.message.reply_text("Sedang menganalisis catatanmu...")
        answer = query_financial_summary(user_text)
        await update.message.reply_text(answer)
        return

    # Proses pencatatan transaksi biasa
    await update.message.reply_text("Mencatat transaksi...")
    try:
        parsed = parse_with_gemini(user_text)
        save_transactions_to_db(parsed, raw_source=user_text)
        
        reply_lines = ["✅ **Transaksi Berhasil Dicatat:**"]
        for item in parsed.items:
            reply_lines.append(f"• {item.item_name} ({item.category}): Rp{item.amount:,.0f}")
        reply_lines.append(f"\n💬 *Roast:* {parsed.roast_comment}")
        
        await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan saat memproses data: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Menganalisis struk belanja...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        image = Image.open(io.BytesIO(image_bytes))

        parsed = parse_with_gemini(image)
        save_transactions_to_db(parsed, raw_source="[Foto Struk Belanja]")
        
        reply_lines = ["🧾 **Struk Berhasil Diurai & Dicatat:**"]
        total = 0
        for item in parsed.items:
            reply_lines.append(f"• {item.item_name} [{item.category}]: Rp{item.amount:,.0f}")
            total += item.amount
        reply_lines.append(f"\n💰 *Total:* Rp{total:,.0f}")
        reply_lines.append(f"💬 *Roast:* {parsed.roast_comment}")
        
        await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Gagal membaca struk: {str(e)}")

def main():
    # Menjalankan server HTTP kecil di thread terpisah agar Render mendeteksi port aktif
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Bot Telegram berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()