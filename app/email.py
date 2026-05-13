# email_2026-05-10_11-00-00.py
"""
Novella email sending — SendGrid.
"""

import os
import httpx
import re

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "hello@novellaldn.co.uk")
FROM_NAME = "Novella"


async def send_email(to: str, subject: str, body_html: str, body_text: str = "") -> bool:
    """Send an email. Returns True on success, False on failure (never raises)."""
    try:
        return await _send_sendgrid(to, subject, body_html, body_text)
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


async def _send_sendgrid(to: str, subject: str, body_html: str, body_text: str) -> bool:
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": body_text or _strip_html(body_html)},
            {"type": "text/html", "value": body_html},
        ],
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"},
        )
    if r.status_code not in (200, 202):
        print(f"SendGrid error {r.status_code}: {r.text}")
        return False
    return True


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


# ── Email templates ────────────────────────────────────────────────────────────

def seller_book_sold_email(book_title: str, book_author: str, seller_net: float) -> tuple[str, str]:
    subject = f"Your book sold — {book_title}"
    html = f"""
    <div style="font-family:Georgia,'Times New Roman',serif;max-width:560px;margin:0 auto;color:#1a1a1a">
      <div style="border-bottom:1px solid #e0d9cf;padding:1rem 0;margin-bottom:2rem">
        <span style="font-size:1.4rem;letter-spacing:0.08em">Novell<span style="color:#c9963a">a</span></span>
      </div>
      <p style="font-size:1.1rem;margin-bottom:1rem">Good news — your book has sold. 🎉</p>
      <div style="background:#f5f0e8;border:1px solid #e0d9cf;padding:1.2rem;margin-bottom:1.5rem">
        <p style="font-size:1rem;margin-bottom:0.2rem"><strong>{book_title}</strong></p>
        <p style="font-size:0.9rem;color:#8a8278">{book_author}</p>
      </div>
      <p style="margin-bottom:0.5rem">
        You'll receive approximately <strong style="color:#27ae60">£{seller_net:.2f}</strong> once the payment clears.
      </p>
      <p style="margin-bottom:1rem;color:#8a8278;font-size:0.9rem">
        Please post the book within 2 working days using Royal Mail 2nd Class.
        Buy a stamp at your local post office or online — the postage estimate on your listing is your guide.
      </p>
      <p style="margin-bottom:1.5rem;color:#8a8278;font-size:0.9rem">
        Once you've posted it, mark it as sent on your listing page so the buyer knows it's on its way.
      </p>
      <p style="color:#8a8278;font-size:0.85rem;border-top:1px solid #e0d9cf;padding-top:1rem;margin-top:2rem">
        Questions? Reply to this email.<br>© 2026 Novella · novellaldn.co.uk
      </p>
    </div>
    """
    return subject, html


def buyer_order_confirmed_email(book_title: str, book_author: str, condition: str) -> tuple[str, str]:
    subject = f"Order confirmed — {book_title}"
    html = f"""
    <div style="font-family:Georgia,'Times New Roman',serif;max-width:560px;margin:0 auto;color:#1a1a1a">
      <div style="border-bottom:1px solid #e0d9cf;padding:1rem 0;margin-bottom:2rem">
        <span style="font-size:1.4rem;letter-spacing:0.08em">Novell<span style="color:#c9963a">a</span></span>
      </div>
      <div style="font-size:2rem;margin-bottom:1rem">✓</div>
      <p style="font-size:1.1rem;margin-bottom:1rem">Your order is confirmed.</p>
      <div style="background:#f5f0e8;border:1px solid #e0d9cf;padding:1.2rem;margin-bottom:1.5rem">
        <p style="font-size:1rem;margin-bottom:0.2rem"><strong>{book_title}</strong></p>
        <p style="font-size:0.9rem;color:#8a8278">{book_author} · Condition: {condition}</p>
      </div>
      <p style="margin-bottom:1rem;color:#8a8278;font-size:0.9rem">
        The seller has been notified and will post your book within 2 working days.
        We'll email you once it's on its way.
      </p>
      <p style="margin-bottom:1.5rem;color:#8a8278;font-size:0.9rem">
        📬 Check your spam folder and add <strong style="color:#1a1a1a">hello@novellaldn.co.uk</strong> to your contacts so you don't miss updates.
      </p>
      <p style="color:#8a8278;font-size:0.85rem;border-top:1px solid #e0d9cf;padding-top:1rem;margin-top:2rem">
        Questions? Reply to this email.<br>© 2026 Novella · novellaldn.co.uk
      </p>
    </div>
    """
    return subject, html


def buyer_book_posted_email(book_title: str, book_author: str, tracking_reference: str) -> tuple[str, str]:
    subject = f"Your book is on its way — {book_title}"
    tracking_html = (
        f"<p style='margin-bottom:1rem;color:#8a8278;font-size:0.9rem'>"
        f"Your tracking reference is <strong style='color:#1a1a1a'>{tracking_reference}</strong>. "
        f"You can track it at <a href='https://www.royalmail.com/track-your-item' style='color:#c9963a'>royalmail.com</a>.</p>"
    ) if tracking_reference else (
        "<p style='margin-bottom:1rem;color:#8a8278;font-size:0.9rem'>"
        "No tracking reference was provided — your book was sent via standard Royal Mail 2nd Class.</p>"
    )
    html = f"""
    <div style="font-family:Georgia,'Times New Roman',serif;max-width:560px;margin:0 auto;color:#1a1a1a">
      <div style="border-bottom:1px solid #e0d9cf;padding:1rem 0;margin-bottom:2rem">
        <span style="font-size:1.4rem;letter-spacing:0.08em">Novell<span style="color:#c9963a">a</span></span>
      </div>
      <div style="font-size:2rem;margin-bottom:1rem">📦</div>
      <p style="font-size:1.1rem;margin-bottom:1rem">Your book is on its way.</p>
      <div style="background:#f5f0e8;border:1px solid #e0d9cf;padding:1.2rem;margin-bottom:1.5rem">
        <p style="font-size:1rem;margin-bottom:0.2rem"><strong>{book_title}</strong></p>
        <p style="font-size:0.9rem;color:#8a8278">{book_author}</p>
      </div>
      {tracking_html}
      <p style="color:#8a8278;font-size:0.85rem;border-top:1px solid #e0d9cf;padding-top:1rem;margin-top:2rem">
        Questions? Reply to this email.<br>© 2026 Novella · novellaldn.co.uk
      </p>
    </div>
    """
    return subject, html


def admin_book_posted_email(book_title: str, book_author: str, seller_email: str, tracking_reference: str, book_id: int) -> tuple[str, str]:
    subject = f"Posted: {book_title} (#{book_id})"
    tracking_line = tracking_reference or "none provided"
    html = f"""
    <div style="font-family:'Helvetica Neue',Arial,sans-serif;max-width:560px;margin:0 auto;color:#1a1a1a;font-size:0.9rem">
      <p style="margin-bottom:1rem"><strong>Book marked as posted.</strong></p>
      <table style="border-collapse:collapse;width:100%">
        <tr><td style="padding:0.4rem 0;color:#8a8278;width:120px">Book</td><td><strong>{book_title}</strong> by {book_author}</td></tr>
        <tr><td style="padding:0.4rem 0;color:#8a8278">Listing ID</td><td>#{book_id}</td></tr>
        <tr><td style="padding:0.4rem 0;color:#8a8278">Seller</td><td>{seller_email}</td></tr>
        <tr><td style="padding:0.4rem 0;color:#8a8278">Tracking</td><td>{tracking_line}</td></tr>
      </table>
      <p style="margin-top:1.5rem">
        <a href="https://novellaldn.co.uk/admin" style="color:#c9963a">View admin panel</a>
      </p>
    </div>
    """
    return subject, html
