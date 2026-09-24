from pydantic import BaseModel, Field
from typing import List, Literal

class TransactionItem(BaseModel):
    item_name: str = Field(description="Nama spesifik barang atau aktivitas transaksi")
    type: Literal["income", "expense"] = Field(description="Jenis transaksi: income atau expense")
    category: str = Field(description="Kategori: Makanan, Transportasi, Kebutuhan Pokok, Hiburan, Tabungan, Gaji, dll.")
    amount: float = Field(description="Nominal rupiah berupa angka tanpa titik atau simbol")
    is_savings_or_investment: bool = Field(description="Set True jika uang disisihkan untuk tabungan/investasi/deposito/reksadana")

class ParsedFinanceResponse(BaseModel):
    items: List[TransactionItem] = Field(description="Daftar item transaksi yang dipecah")
    roast_comment: str = Field(description="Komentar persona finansial yang singkat, pedas/sarkas tapi lucu atau memberi reality-check")