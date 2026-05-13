# main_2026-05-10_11-00-00.py
from dotenv import load_dotenv
load_dotenv()

import os
import json
import stripe
import base64
import httpx
import anthropic
from datetime import datetime
from pathlib import Path
from PIL import Image
import io
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, Response, Cookie
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from .database import engine, get_db
from . import models
from .email import (
    send_email,
    seller_book_sold_email,
    buyer_order_confirmed_email,
    buyer_book_posted_email,
    admin_book_posted_email,
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "novella")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "hello@novellaldn.co.uk")

models.Base.metadata.create_all(bind=engine)

UPLOAD_DIR = Path("app/static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Novella")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def compress_image(file_bytes: bytes, max_width: int = 1200, quality: int = 82) -> bytes:
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WebP", quality=quality, method=6)
    return out.getvalue()


def estimate_postage(page_count: int, is_hardback: bool = False) -> dict:
    if is_hardback:
        book_weight_g = (page_count * 1.8) + 150
    else:
        book_weight_g = (page_count * 0.9) + 50

    if is_hardback:
        total_weight_g = book_weight_g + 150
    else:
        total_weight_g = book_weight_g + 40

    can_be_large_letter = not is_hardback and page_count < 400

    if can_be_large_letter and total_weight_g <= 750:
        if total_weight_g <= 100:
            service = "Large Letter 2nd Class"
            price = 1.55
        elif total_weight_g <= 250:
            service = "Large Letter 2nd Class"
            price = 2.10
        elif total_weight_g <= 500:
            service = "Large Letter 2nd Class"
            price = 2.80
        else:
            service = "Large Letter 2nd Class"
            price = 3.10
    else:
        if total_weight_g <= 1000:
            service = "Small Parcel 2nd Class"
            price = 3.99
        else:
            service = "Small Parcel 2nd Class"
            price = 5.49

    return {"weight_g": round(total_weight_g), "service": service, "price": price}


# ── Public routes ──────────────────────────────────────────────────────────────

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/sell")
async def sell(request: Request):
    return templates.TemplateResponse(request=request, name="list_book.html")


@app.get("/browse")
async def browse(request: Request, db: Session = Depends(get_db)):
    books = db.query(models.Book).filter(
        models.Book.status == "available"
    ).order_by(models.Book.created_at.desc()).all()
    return templates.TemplateResponse(request=request, name="browse.html", context={"books": books})


@app.get("/listing/{book_id}")
async def view_listing(request: Request, book_id: int, db: Session = Depends(get_db)):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        return HTMLResponse("Listing not found", status_code=404)
    return templates.TemplateResponse(request=request, name="listing.html", context={"book": book})


# ── Seller flow ────────────────────────────────────────────────────────────────

@app.post("/sell")
async def submit_listing(
    request: Request,
    title: str = Form(...),
    author: str = Form(...),
    isbn: str = Form(""),
    seller_note: str = Form(""),
    seller_email: str = Form(""),
    price: float = Form(0.0),
    seller_net: float = Form(0.0),
    buyer_price: float = Form(0.0),
    condition: str = Form("Good"),
    condition_notes: str = Form(""),
    seller_condition: str = Form("Good"),
    cover_url: str = Form(""),
    estimated_postage: float = Form(0.0),
    is_bundle: str = Form("false"),
    bundle_titles: str = Form(""),
    photos: list[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    cover_image = None
    if photos:
        for photo in photos:
            if photo.filename:
                raw = await photo.read()
                compressed = compress_image(raw)
                filename = f"{isbn or 'book'}_{photo.filename.split('.')[0]}.webp"
                dest = UPLOAD_DIR / filename
                dest.write_bytes(compressed)
                cover_image = filename
                break

    final_price = buyer_price if buyer_price > 0 else price

    book = models.Book(
        title=title,
        author=author,
        isbn=isbn,
        condition=condition,
        condition_notes=condition_notes,
        seller_note=seller_note,
        seller_email=seller_email,
        price=final_price,
        seller_net=seller_net,
        cover_image=cover_image,
        estimated_postage=estimated_postage,
        is_bundle=is_bundle,
        bundle_titles=bundle_titles,
        status="available"
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return RedirectResponse(url=f"/listing/{book.id}", status_code=303)


# ── Posting flow ───────────────────────────────────────────────────────────────

@app.post("/mark-posted/{book_id}")
async def mark_posted(
    book_id: int,
    request: Request,
    tracking_reference: str = Form(""),
    db: Session = Depends(get_db)
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or book.status != "sold":
        return HTMLResponse("Not found or not in sold state", status_code=400)

    book.status = "posted"
    book.tracking_reference = tracking_reference.strip()
    book.posted_at = datetime.utcnow()
    db.commit()

    if book.buyer_email:
        subject, html = buyer_book_posted_email(book.title, book.author, book.tracking_reference)
        await send_email(book.buyer_email, subject, html)

    subject, html = admin_book_posted_email(
        book.title, book.author, book.seller_email, book.tracking_reference, book.id
    )
    await send_email(ADMIN_EMAIL, subject, html)

    return RedirectResponse(url=f"/listing/{book.id}", status_code=303)


# ── Checkout & payment ─────────────────────────────────────────────────────────

@app.post("/create-checkout/{book_id}")
async def create_checkout(book_id: int, request: Request, db: Session = Depends(get_db)):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        return HTMLResponse("Book not found", status_code=404)

    book_price_pence = int(book.price * 100)
    postage_pence = int((book.estimated_postage or 0) * 100)

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "gbp",
                    "product_data": {
                        "name": book.title,
                        "description": f"by {book.author} · Condition: {book.condition}",
                    },
                    "unit_amount": book_price_pence,
                },
                "quantity": 1,
            },
            {
                "price_data": {
                    "currency": "gbp",
                    "product_data": {
                        "name": "Postage & handling",
                        "description": "Royal Mail 2nd Class",
                    },
                    "unit_amount": postage_pence,
                },
                "quantity": 1,
            },
        ],
        mode="payment",
        success_url=f"{request.base_url}order-success/{book_id}",
        cancel_url=f"{request.base_url}listing/{book_id}",
        metadata={"book_id": str(book_id)},
    )
    return RedirectResponse(url=session.url, status_code=303)


async def handle_sale(book_id: int, buyer_email: str, db: Session):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or book.status == "sold":
        return
    book.status = "sold"
    book.buyer_email = buyer_email
    db.commit()
    if book.seller_email:
        subject, html = seller_book_sold_email(book.title, book.author, book.seller_net)
        await send_email(book.seller_email, subject, html)
    if buyer_email:
        subject, html = buyer_order_confirmed_email(book.title, book.author, book.condition)
        await send_email(buyer_email, subject, html)


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        print(f"Webhook error: {e}")
        return HTMLResponse("Webhook error", status_code=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        book_id = int(session["metadata"]["book_id"]) if session["metadata"] else 0
        customer_details = session["customer_details"] if session["customer_details"] else {}
        buyer_email = customer_details["email"] if customer_details else ""
        if book_id:
            await handle_sale(book_id, buyer_email, db)

    return {"status": "ok"}


@app.get("/order-success/{book_id}")
async def order_success(request: Request, book_id: int, db: Session = Depends(get_db)):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    return templates.TemplateResponse(request=request, name="checkout_success.html", context={"book": book})


# ── HTMX helpers ───────────────────────────────────────────────────────────────

@app.get("/lookup-isbn", response_class=HTMLResponse)
async def lookup_isbn(isbn: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(
                f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={os.getenv('GOOGLE_BOOKS_API_KEY', '')}"
            )
        data = r.json()
        if not data.get("items"):
            return "<p style='color:#c0392b'>No book found for that ISBN. Try typing the title manually.</p>"

        info = data["items"][0]["volumeInfo"]
        title = info.get("title", "")
        authors = ", ".join(info.get("authors", []))
        year = info.get("publishedDate", "")[:4]
        pages = info.get("pageCount", 200)
        is_hardback = "hardcover" in str(info).lower()

        cover = ""
        if info.get("imageLinks"):
            cover = info["imageLinks"].get("thumbnail", "")

        postage = estimate_postage(pages or 200, is_hardback)

        cover_html = ""
        if cover:
            cover_html = "<img src='" + cover + "' style='height:100px;margin-bottom:0.8rem;display:block;box-shadow:0 2px 8px rgba(0,0,0,0.15)'>"

        title_safe = title.replace('"', '').replace("'", "\\'")
        authors_safe = authors.replace('"', '').replace("'", "\\'")

        html = """
        <div style='background:#f5f0e8;border:1px solid #e0d9cf;padding:1.2rem;margin-bottom:1.5rem'>
        """ + cover_html + """
            <p style='font-size:1rem;margin-bottom:0.2rem'><strong>""" + title + """</strong></p>
            <p style='font-size:0.9rem;color:#8a8278;margin-bottom:1rem'>""" + authors + " · " + year + " · " + str(pages) + """ pages</p>
            <div style='background:#fff;border:1px solid #e0d9cf;padding:0.8rem;font-family:Helvetica Neue,Arial,sans-serif;font-size:0.85rem'>
                <span style='text-transform:uppercase;letter-spacing:0.04em;color:#8a8278;font-size:0.75rem'>Estimated postage</span><br>
                <span style='font-size:1rem;color:#1a1a1a'>£""" + f"{postage['price']:.2f}" + """</span>
                <span style='color:#8a8278'> · """ + postage['service'] + " · ~" + str(postage['weight_g']) + """g</span><br>
                <span style='color:#8a8278;font-size:0.8rem'>Weigh your package to confirm</span>
            </div>
        </div>
        <input type='hidden' name='estimated_postage' id='estimated-postage' value='""" + str(postage['price']) + """'>
        <script>
            document.getElementById('title').value = \"""" + title_safe + """\";
            document.getElementById('author').value = \"""" + authors_safe + """\";
            document.getElementById('cover-url').value = \"""" + cover + """\";
        </script>
        """
        return html

    except Exception as e:
        return f"<p style='color:#c0392b'>Lookup failed: {str(e)}</p>"


@app.get("/recalculate-postage", response_class=HTMLResponse)
async def recalculate_postage(weight_g: int, is_hardback: bool = False):
    weight_g = max(80, min(weight_g, 2000))
    can_be_large_letter = not is_hardback and weight_g <= 750

    if can_be_large_letter:
        if weight_g <= 100:
            service = "Large Letter 2nd Class"
            price = 1.55
        elif weight_g <= 250:
            service = "Large Letter 2nd Class"
            price = 2.10
        elif weight_g <= 500:
            service = "Large Letter 2nd Class"
            price = 2.80
        else:
            service = "Large Letter 2nd Class"
            price = 3.10
    else:
        if weight_g <= 1000:
            service = "Small Parcel 2nd Class"
            price = 3.99
        else:
            service = "Small Parcel 2nd Class"
            price = 5.49

    return (
        "<input type='hidden' name='estimated_postage' id='estimated-postage' value='" + str(price) + "'>"
        "<div style='background:#fff;border:1px solid #e0d9cf;padding:0.8rem;"
        "font-family:Helvetica Neue,Arial,sans-serif;font-size:0.85rem;margin-top:0.5rem'>"
        "<span style='text-transform:uppercase;letter-spacing:0.04em;color:#8a8278;font-size:0.75rem'>"
        "Confirmed postage</span><br>"
        "<span style='font-size:1rem;color:#1a1a1a'>£" + f"{price:.2f}" + "</span>"
        "<span style='color:#8a8278'> · " + service + " · " + str(weight_g) + "g</span>"
        "</div>"
    )


@app.get("/calculate-price", response_class=HTMLResponse)
async def calculate_price(seller_net: float = 0.0):
    seller_net = max(0.50, min(seller_net, 500.0))
    buyer_price = (seller_net / 0.886) + 0.20
    buyer_price = round(buyer_price * 20) / 20

    novella_fee = round(buyer_price * 0.10, 2)
    stripe_fee = round(buyer_price * 0.014 + 0.20, 2)
    seller_receives = round(buyer_price - novella_fee - stripe_fee, 2)

    return (
        "<div style='background:#f5f0e8;border:1px solid #e0d9cf;padding:1rem;"
        "font-family:Helvetica Neue,Arial,sans-serif;font-size:0.9rem;margin-top:0.5rem'>"
        "<div style='display:flex;justify-content:space-between;margin-bottom:0.4rem'>"
        "<span style='color:#8a8278'>Buyer pays</span>"
        "<strong style='font-size:1.1rem'>£" + f"{buyer_price:.2f}" + "</strong>"
        "</div>"
        "<div style='display:flex;justify-content:space-between'>"
        "<span style='color:#8a8278'>You receive (approx.)</span>"
        "<strong style='color:#27ae60'>£" + f"{seller_receives:.2f}" + "</strong>"
        "</div>"
        "</div>"
        "<input type='hidden' name='buyer_price' id='buyer-price' value='" + str(buyer_price) + "'>"
        "<input type='hidden' name='price' id='price-hidden' value='" + str(buyer_price) + "'>"
    )


@app.post("/grade-condition", response_class=HTMLResponse)
async def grade_condition(photos: list[UploadFile] = File(...)):
    try:
        image_contents = []
        for photo in photos[:3]:
            data = await photo.read()
            b64 = base64.standard_b64encode(data).decode("utf-8")
            media_type = photo.content_type or "image/jpeg"
            image_contents.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64}
            })

        check_contents = [image_contents[0], {
            "type": "text",
            "text": "Is this image a photograph of a physical book? Answer only YES or NO."
        }]
        check = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": check_contents}]
        )
        if "NO" in check.content[0].text.upper():
            return (
                "<div style='background:#fdf0f0;border:1px solid #e8c0c0;padding:1.2rem;"
                "margin-bottom:1.5rem;font-family:Helvetica Neue,Arial,sans-serif'>"
                "<p style='color:#c0392b;margin-bottom:0.3rem'>That does not look like a book.</p>"
                "<p style='font-size:0.85rem;color:#8a8278'>Please upload a clear photo of the book "
                "you are listing — cover and spine work best.</p>"
                "</div>"
            )

        image_contents.append({
            "type": "text",
            "text": (
                "You are grading a second-hand book for a marketplace listing.\n"
                "Look at the photos and respond in this exact format:\n"
                "GRADE: [Excellent / Good / Fair / Poor]\n"
                "NOTES: [One sentence describing condition honestly — "
                "mention any visible wear, marks, or highlights]"
            )
        })

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": image_contents}]
        )

        text = response.content[0].text
        grade = "Good"
        notes = ""
        for line in text.split("\n"):
            if line.startswith("GRADE:"):
                grade = line.replace("GRADE:", "").strip()
            if line.startswith("NOTES:"):
                notes = line.replace("NOTES:", "").strip()

        colours = {"Excellent": "#27ae60", "Good": "#2980b9", "Fair": "#e67e22", "Poor": "#c0392b"}
        colour = colours.get(grade, "#2c2c2c")

        return (
            "<input type='hidden' name='condition' value='" + grade + "'>"
            "<input type='hidden' name='condition_notes' value='" + notes.replace("'", "") + "'>"
            "<div style='background:#f5f0e8;border:1px solid #e0d9cf;padding:1.2rem;margin-bottom:1.5rem'>"
            "<p style='font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;color:#8a8278;"
            "font-family:Helvetica Neue,Arial,sans-serif;margin-bottom:0.8rem'>Novella's assessment</p>"
            "<div style='font-size:1.2rem;font-weight:bold;color:" + colour + ";margin-bottom:0.3rem'>" + grade + "</div>"
            "<div style='font-size:0.9rem;color:#555;margin-bottom:1.2rem'>" + notes + "</div>"
            "<p style='font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;color:#8a8278;"
            "font-family:Helvetica Neue,Arial,sans-serif;margin-bottom:0.6rem'>Your assessment</p>"
            "<div style='display:flex;gap:2rem;flex-wrap:wrap;justify-content:center'>"
            "<label style='display:flex;align-items:center;gap:0.4rem;font-size:0.9rem;cursor:pointer;text-transform:none;letter-spacing:0'>"
            "<input type='radio' name='seller_condition' value='Excellent'> Excellent</label>"
            "<label style='display:flex;align-items:center;gap:0.4rem;font-size:0.9rem;cursor:pointer;text-transform:none;letter-spacing:0'>"
            "<input type='radio' name='seller_condition' value='Good' checked> Good</label>"
            "<label style='display:flex;align-items:center;gap:0.4rem;font-size:0.9rem;cursor:pointer;text-transform:none;letter-spacing:0'>"
            "<input type='radio' name='seller_condition' value='Fair'> Fair</label>"
            "<label style='display:flex;align-items:center;gap:0.4rem;font-size:0.9rem;cursor:pointer;text-transform:none;letter-spacing:0'>"
            "<input type='radio' name='seller_condition' value='Poor'> Poor</label>"
            "</div>"
            "</div>"
        )

    except Exception as e:
        return f"<p style='color:#c0392b'>Grading failed: {str(e)}</p>"


# ── Admin ──────────────────────────────────────────────────────────────────────

@app.get("/admin")
async def admin_panel(request: Request, db: Session = Depends(get_db), admin_session: str = Cookie(default="")):
    if admin_session != ADMIN_PASSWORD:
        return templates.TemplateResponse(request=request, name="admin_login.html", context={"error": False})

    books = db.query(models.Book).order_by(models.Book.created_at.desc()).all()
    total_revenue = sum(b.price for b in books if b.status in ("sold", "posted"))
    total_seller_net = sum(b.seller_net for b in books if b.status in ("sold", "posted"))
    stats = {
        "total": len(books),
        "available": sum(1 for b in books if b.status == "available"),
        "sold": sum(1 for b in books if b.status == "sold"),
        "posted": sum(1 for b in books if b.status == "posted"),
        "revenue": total_revenue,
        "seller_net": total_seller_net,
        "novella_net": round(total_revenue - total_seller_net, 2),
    }
    return templates.TemplateResponse(request=request, name="admin.html", context={"books": books, "stats": stats})


@app.post("/admin/login")
async def admin_login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie("admin_session", password, httponly=True, max_age=86400 * 7)
        return response
    return HTMLResponse("""
        <!DOCTYPE html><html><body style='font-family:sans-serif;padding:2rem'>
        <p style='color:#c0392b'>Wrong password. <a href='/admin'>Try again.</a></p>
        </body></html>
    """, status_code=401)


@app.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie("admin_session")
    return response


@app.post("/admin/mark-sold/{book_id}")
async def admin_mark_sold(book_id: int, db: Session = Depends(get_db), admin_session: str = Cookie(default="")):
    if admin_session != ADMIN_PASSWORD:
        return HTMLResponse("Unauthorised", status_code=401)
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if book:
        book.status = "sold"
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/mark-available/{book_id}")
async def admin_mark_available(book_id: int, db: Session = Depends(get_db), admin_session: str = Cookie(default="")):
    if admin_session != ADMIN_PASSWORD:
        return HTMLResponse("Unauthorised", status_code=401)
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if book:
        book.status = "available"
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/delete/{book_id}")
async def admin_delete(book_id: int, db: Session = Depends(get_db), admin_session: str = Cookie(default="")):
    if admin_session != ADMIN_PASSWORD:
        return HTMLResponse("Unauthorised", status_code=401)
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if book:
        db.delete(book)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)
