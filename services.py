import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client
from PIL import Image
from schemas import ParsedFinanceResponse

load_dotenv()

# Inisialisasi Clients
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """
Kamu adalah asisten pengelola keuangan pribadi yang cerdas, teliti, dan memiliki persona realistis dengan sentuhan humor sarkas/roasting.
Tugasmu:
1. Membaca teks transaksi bebas atau gambar struk belanja.
2. Memecah item belanja secara spesifik (Smart Itemization). Contoh: sabun & deterjen masuk 'Kebutuhan Pokok', ciki & es kopi masuk 'Hiburan/Jajan'.
3. Tandai is_savings_or_investment = True hanya jika transaksi bertujuan untuk menabung atau investasi.
4. Buat roast_comment (1-2 kalimat) yang mengomentari pengeluaran/pemasukan tersebut secara tajam, kocak, atau memberi peringatan dompet tipis.
"""

def parse_with_gemini(content: str | Image.Image) -> ParsedFinanceResponse:
    contents = [content] if isinstance(content, Image.Image) else [content]
    
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ParsedFinanceResponse,
            temperature=0.2,
        ),
    )
    return ParsedFinanceResponse.model_validate_json(response.text)

def save_transactions_to_db(parsed_data: ParsedFinanceResponse, raw_source: str) -> None:
    rows = []
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
    if rows:
        supabase.table("transactions").insert(rows).execute()

def query_financial_summary(user_query: str) -> str:
    # Ambil transaksi 30 hari terakhir
    res = supabase.table("transactions").select("*").order("created_at", desc=True).limit(50).execute()
    history = res.data or []
    
    prompt = f"""
    Pengguna bertanya: "{user_query}"
    Berikut data transaksi terakhir pengguna (JSON):
    {json.dumps(history)}

    Jawablah pertanyaan pengguna dengan ringkas, akurat sesuai data di atas, dan pertahankan nada persona finansialmu.
    """
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text