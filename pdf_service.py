import base64
from io import BytesIO
from pathlib import Path
import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from weasyprint import HTML
from template_registry import get_template_by_id

TEMPLATES_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

DEFAULT_BRAND = {
    "company_name": "TicketForge Pro",
    "logo_base64": None,
    "primary_color": "#1e3a8a",
    "secondary_color": "#d4af37",
    "contact_email": "support@ticketforge.com",
    "contact_phone": "",
    "website": "",
    "address": "",
    "gst_number": "",
    "social_facebook": "",
    "social_instagram": "",
    "social_twitter": "",
    "social_linkedin": ""
}


def _merge_brand(brand: dict | None) -> dict:
    """Merge user's brand kit over the defaults, keeping non-empty values."""
    merged = dict(DEFAULT_BRAND)
    if not brand:
        return merged
    for key, value in brand.items():
        if value not in (None, ""):
            merged[key] = value
    # Hard fallback for company name if user cleared it
    if not merged.get("company_name"):
        merged["company_name"] = DEFAULT_BRAND["company_name"]
    return merged


def image_to_data_url(img: Image.Image, format: str = "PNG") -> str:
    buffer = BytesIO()
    img.save(buffer, format=format)
    im_bytes = buffer.getvalue()
    im_b64 = base64.b64encode(im_bytes).decode("ascii")
    return f"data:image/{format.lower()};base64,{im_b64}"


def generate_qr_data_url(data: str) -> str:
    """Generate QR code PNG data URL. Falls back to placeholder for empty/invalid input."""
    safe = (data or "").strip() or "N/A"
    try:
        qr_img = qrcode.make(safe)
        if qr_img.mode != "RGB":
            qr_img = qr_img.convert("RGB")
        return image_to_data_url(qr_img, format="PNG")
    except Exception:
        placeholder = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        return image_to_data_url(placeholder, format="PNG")


def generate_barcode_data_url(data: str) -> str:
    """Generate Code128 barcode as a base64 PNG data URL.

    Defensive: pads short/empty input so Code128 won't raise IndexError,
    and falls back to a 1x1 transparent placeholder if generation fails entirely.
    """
    # Code128 needs a non-empty string with reasonable length to optimize.
    # Pad to at least 8 chars with zeros to avoid library edge cases.
    safe = (data or "").strip() or "00000000"
    if len(safe) < 8:
        safe = safe + "0" * (8 - len(safe))
    try:
        barcode = Code128(safe, writer=ImageWriter())
        buffer = BytesIO()
        barcode.write(buffer)
        buffer.seek(0)
        img = Image.open(buffer)
        return image_to_data_url(img, format="PNG")
    except Exception:
        # Last-resort fallback: 1x1 transparent PNG so template <img> still resolves.
        placeholder = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        return image_to_data_url(placeholder, format="PNG")


def render_ticket_pdf(ticket: dict, brand: dict | None = None, template_id: str | None = None) -> bytes:
    tpl_meta = get_template_by_id(template_id or "ticket_premium", "ticket")
    template = env.get_template(tpl_meta["file"])
    qr_url = generate_qr_data_url(ticket.get("booking_reference", "N/A"))
    barcode_url = generate_barcode_data_url(ticket.get("ticket_number", "000000"))
    html = template.render(
        ticket=ticket,
        qr_url=qr_url,
        barcode_url=barcode_url,
        brand=_merge_brand(brand),
    )
    pdf_bytes = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
    return pdf_bytes


def render_voucher_pdf(voucher: dict, brand: dict | None = None, template_id: str | None = None) -> bytes:
    tpl_meta = get_template_by_id(template_id or "voucher_premium", "voucher")
    template = env.get_template(tpl_meta["file"])
    qr_url = generate_qr_data_url(voucher.get("confirmation_number", "N/A"))
    barcode_url = generate_barcode_data_url(voucher.get("voucher_number", "000000"))
    html = template.render(
        voucher=voucher,
        qr_url=qr_url,
        barcode_url=barcode_url,
        brand=_merge_brand(brand),
    )
    pdf_bytes = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
    return pdf_bytes
