import os
import json
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from supabase import create_client, Client
from PIL import Image
from schemas import ParsedFinanceResponse

load_dotenv()

# Inisialisasi Clients
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Gunakan gemini-1.5-flash untuk kuota harian besar (1.500 RPD) pada free tier
DEFAULT_MODEL = "gemini-1.5-flash"

SYSTEM_PROMPT = """
Kamu adalah sistem AI penasihat finansial pribadi bernama "Acasia". Karaktermu adalah seorang profesional berlatar belakang gabungan Akuntansi & Sistem Informasi/Teknologi yang kritis, pragmatis, direct (langsung pada intinya), cerdas, dan tidak suka basa-basi manis.

Gaya Komunikasi & Persona:
1. PENGELUARAN (Expense):
   - JANGAN PERNAH bersikap manis, memaklumi berlebihan, atau memberi penghiburan klise seperti "tidak apa-apa sekali-sekali self reward".
   - Berikan komentar/roasting (1-2 kalimat) yang tajam, logis, berorientasi angka, dan analitis. Soroti beban pengeluaran yang tidak produktif, perbandingan terhadap cash flow, pemborosan terselubung, atau disiplin budget yang bocor.
   - Gunakan gaya bahasa kasual-profesional yang sarkastik, cerdas, dan langsung menyentil realitas keuangan.

2. PEMASUKAN (Income) & TABUNGAN/INVESTASI:
   - Apresiatif secara objektif dan mantap. 
   - Akui pertambahan likuiditas dan disiplin penumpukan aset secara ringkas tanpa berlebihan.

Tugas Ekstraksi & Struktur Data:
1. Analisis teks percakapan transaksi bebas atau gambar struk belanja.
2. Lakukan Smart Itemization: pisahkan setiap item belanja secara presisi beserta nominal dan kategorinya yang rapi (contoh kategori: Kebutuhan Pokok, Makanan & Minuman, Transportasi, Gaya Hidup/Hobi, Operasional, Tabungan & Investasi).
3. Tentukan type: 'income' atau 'expense' secara akurat.
4. Set flag is_savings_or_investment = True hanya jika transaksi bertujuan menambah tabungan, deposito, atau instrumen investasi.
5. Tulis roast_comment sesuai aturan persona di atas ke dalam field JSON yang diminta.
"""

def parse_with_gemini(content: str | Image.Image) -> ParsedFinanceResponse:
    contents = [content] if isinstance(content, Image.Image) else [content]
    
    try:
        response = gemini_client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ParsedFinanceResponse,
                temperature=0.2,
            ),
        )
        return ParsedFinanceResponse.model_validate_json(response.text)
    except APIError as e:
        print(f"[Gemini API Error] {e}")
        # Fallback jika terjadi rate limit / kuota habis, agar bot tidak melempar error mentah
        raise RuntimeError("AI sedang mencapai batas laju pemrosesan. Coba kirim ulang pesan dalam 30 detik.")
    except Exception as e:
        print(f"[Unexpected Parsing Error] {e}")
        raise RuntimeError("Gagal memproses transaksi finansial. Pastikan format teks atau foto terbaca jelas.")

def save_transactions_to_db(parsed_data: ParsedFinanceResponse, raw_source: str) -> None:
    rows = []
    total_new_savings = 0
    savings_keywords = ["tabung", "invest", "deposito", "dana darurat", "simpan"]

    for item in parsed_data.items:
        rows.append({
            "type": item.type,
            "category": item.category,
            "item_name": item.item_name,
            "amount": item.amount,
            "is_savings_or_investment": item.is_savings_or_investment,
            "raw_text": raw_source,
            "notes": parsed_data.roast_comment
        })

        is_saving = getattr(item, 'is_savings_or_investment', False)
        item_text = f"{item.item_name} {item.category}".lower()
        
        if is_saving or any(kw in item_text for kw in savings_keywords):
            total_new_savings += item.amount

    # 1. Simpan transaksi ke tabel mutasi
    if rows:
        supabase.table("transactions").insert(rows).execute()

    # 2. Akumulasi otomatis ke monthly_balances jika ada alokasi tabungan
    if total_new_savings > 0:
        try:
            current_month_str = datetime.now().strftime("%Y-%m-01")
            res = supabase.table("monthly_balances").select("liquid_assets").eq("month_year", current_month_str).execute()
            
            current_liquid = 0
            if res.data and len(res.data) > 0:
                current_liquid = float(res.data[0].get("liquid_assets") or 0)

            new_liquid_balance = current_liquid + total_new_savings

            supabase.table("monthly_balances").upsert({
                "month_year": current_month_str,
                "liquid_assets": new_liquid_balance,
                "notes": f"Diakumulasi otomatis dari tabungan: +Rp{total_new_savings:,.0f}",
                "updated_at": datetime.now().isoformat()
            }, on_conflict="month_year").execute()

            print(f"Saldo likuid otomatis terupdate: +Rp{total_new_savings:,.0f} -> Total: Rp{new_liquid_balance:,.0f}")
        except Exception as err:
            print("Gagal mengupdate saldo kas likuid otomatis:", err)

def query_financial_summary(user_query: str) -> str:
    res = supabase.table("transactions").select("*").order("created_at", desc=True).limit(50).execute()
    history = res.data or []
    
    prompt = f"""
    Pengguna bertanya: "{user_query}"
    Berikut data transaksi terakhir pengguna (JSON):
    {json.dumps(history)}

    Jawablah pertanyaan pengguna dengan ringkas, akurat sesuai data di atas, dan pertahankan nada persona finansialmu.
    """
    try:
        response = gemini_client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"[Gemini Summary Error] {e}")
        return "Sistem analitik sedang sibuk merefresh database. Silakan coba lagi beberapa saat lagi."