import os
import io
import base64
import re
import math  # 端数切り捨て用
import fitz  # PyMuPDF
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Order PDF Processor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STAMP_PATH = os.path.join(os.path.dirname(__file__), "stamp.png")
DEFAULT_PASSWORDS = ["00069958"]

def insert_currency_right_aligned(page, x_right, y_top, amount_val, font_size=9.7, use_serif=True):
    """
    先頭に「¥」を付与し、単一フォントで右揃え印字します。
    和字と英数字の混在がないため、カンマの被りや位置ズレが発生せず、
    コピペ時にも余分なスペースが入らないデータ構造になります。
    """
    num_font = "tiro" if use_serif else "helv"
    
    # 1. 「¥187,500」という1つの文字列を作成
    num_str = f"¥{amount_val:,}"
    
    # 2. 全体の描画幅を一括取得
    total_len = fitz.get_text_length(num_str, fontname=num_font, fontsize=font_size)
    
    # 3. 右端(x_right)から逆算して印字
    start_x = x_right - total_len
    page.insert_text((start_x, y_top), num_str, fontname=num_font, fontsize=font_size)

def extract_metadata(doc):
    p1 = doc[0]
    p1_blocks = p1.get_text("blocks")
    p1_text = p1.get_text("text")

    # 1. 広告主名
    client_name = None
    for b in p1_blocks:
        if 215 < b[1] < 245 and 100 < b[0] < 200:
            val = b[4].strip().replace("\n", "")
            if val and "広告主名" not in val and "(G)" not in val:
                client_name = val
                break
    if not client_name:
        if "花王" in p1_text:
            client_name = "花王"
        elif "長瀬産業" in p1_text:
            client_name = "長瀬産業"
        else:
            client_name = "その他"

    # 2. 金額
    amounts = re.findall(r'(\d{1,3}(?:,\d{3})+)', p1_text)
    amount_int = None
    for a in amounts:
        val = int(a.replace(',', ''))
        if val >= 1000:
            amount_int = val
            break
    if not amount_int:
        raise ValueError("金額を自動抽出できませんでした。")

    # 消費税は端数切り捨て（math.floor）で計算
    tax_int = math.floor(amount_int * 0.10)
    total_int = amount_int + tax_int

    # 3. 納期
    due_parts = ["2026", "08", "31"]
    for b in p1_blocks:
        if 180 < b[1] < 215 and b[0] > 400:
            lines = [l.strip() for l in b[4].split("\n") if l.strip()]
            if len(lines) == 3:
                due_parts = lines
                break

    # 4. 発行日
    issue_parts = ["2026", "08", "21"]
    for b in p1_blocks:
        if "発注書発行日" in b[4]:
            nums = re.findall(r'(\d{4}|\d{2})', b[4])
            if len(nums) >= 3:
                issue_parts = nums[:3]
                break

    year_month = f"{issue_parts[0]}年{int(issue_parts[1]):02d}月"

    return {
        "client_name": client_name,
        "year_month": year_month,
        "amount_int": amount_int,
        "tax_int": tax_int,
        "total_int": total_int,
        "due_parts": due_parts,
        "issue_parts": issue_parts,
        "delivery_place": "御社指定場所"
    }

def process_pdf_bytes(pdf_bytes: bytes, filename: str):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    if doc.is_encrypted:
        auth_success = False
        for pwd in DEFAULT_PASSWORDS:
            if doc.authenticate(pwd):
                auth_success = True
                break
        if not auth_success:
            raise ValueError("パスワード解除に失敗しました。")

    meta = extract_metadata(doc)
    client = meta["client_name"]
    ym = meta["year_month"]
    amount_int = meta["amount_int"]
    tax_int = meta["tax_int"]
    total_int = meta["total_int"]
    due_parts = meta["due_parts"]
    issue_parts = meta["issue_parts"]
    delivery_place = meta["delivery_place"]

    def draw_delivery_date(page):
        page.insert_text((422.0, 235.0), due_parts[0], fontname="helv", fontsize=9.7)
        page.insert_text((469.0, 235.0), due_parts[1], fontname="helv", fontsize=9.7)
        page.insert_text((508.0, 235.0), due_parts[2], fontname="helv", fontsize=9.7)
        
    def draw_amounts(page):
        # 揃えたい右端の基準X座標
        X_RIGHT = 530.0
        
        # 1. 抜計金額（「¥187,500」形式で右揃え印字）
        insert_currency_right_aligned(page, X_RIGHT, 476.0, amount_int, font_size=9.7, use_serif=True)
        
        # 2. 適用税率「10%」の表示（右揃え計算）
        tax_rate_str = "10%"
        tax_rate_len = fitz.get_text_length(tax_rate_str, fontname="helv", fontsize=9.7)
        page.insert_text((X_RIGHT - tax_rate_len, 498.0), tax_rate_str, fontname="helv", fontsize=9.7)
        
        # 3. 消費税額（切り捨て）
        insert_currency_right_aligned(page, X_RIGHT, 523.0, tax_int, font_size=9.7, use_serif=True)
        
        # 4. 請求額（合計）
        insert_currency_right_aligned(page, X_RIGHT, 545.0, total_int, font_size=9.7, use_serif=True)
        
    def draw_tax_circle(page):
        shape = page.new_shape()
        shape.draw_oval(fitz.Rect(398.5, 559.0, 412.5, 574.5))
        shape.finish(color=(0, 0, 0), width=0.8)
        shape.commit()

    if len(doc) >= 2:
        p2 = doc[1]
        draw_delivery_date(p2)
        draw_amounts(p2)
        draw_tax_circle(p2)

    if len(doc) >= 3:
        p3 = doc[2]
        p3.insert_image(fitz.Rect(346.3, 116.3, 545.7, 166.3), filename=STAMP_PATH)
        draw_delivery_date(p3)
        p3.insert_text((441.2, 253.5), delivery_place, fontname="japan", fontsize=9.7)
        draw_amounts(p3)
        draw_tax_circle(p3)

    if len(doc) >= 4:
        p4 = doc[3]
        p4.insert_image(fitz.Rect(346.3, 128.3, 545.7, 178.3), filename=STAMP_PATH)
        draw_delivery_date(p4)
        p4.insert_text((441.2, 253.5), delivery_place, fontname="japan", fontsize=9.7)
        draw_amounts(p4)
        draw_tax_circle(p4)

    out_bytes = doc.write()
    doc.close()
    return out_bytes, client, ym

@app.post("/process-pdf")
async def handle_process_pdf(file: UploadFile = File(...)):
    try:
        content = await file.read()
        out_bytes, client, ym = process_pdf_bytes(content, file.filename)
        out_base64 = base64.b64encode(out_bytes).decode("utf-8")
        
        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "output_filename": f"【完成】{file.filename}",
            "client_name": client,
            "year_month": ym,
            "pdf_base64": out_base64
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

@app.get("/")
def root():
    return {"status": "ok", "service": "Order PDF Processor"}
