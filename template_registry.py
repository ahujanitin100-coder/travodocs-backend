"""Template registry for PDF generation."""

# Template metadata: id, name, category, file, doc_type, thumbnail
TEMPLATE_REGISTRY = [
    # Ticket templates
    {
        "id": "ticket_premium",
        "name": "Premium Airline",
        "category": "Airlines",
        "doc_type": "ticket",
        "file": "ticket.html",
        "description": "Bold gradient header inspired by modern airline boarding passes.",
        "thumbnail": "https://images.unsplash.com/photo-1545132147-d037e6c54cfd?w=400",
        "is_premium": True,
    },
    {
        "id": "ticket_luxury",
        "name": "Luxury Serif",
        "category": "Luxury",
        "doc_type": "ticket",
        "file": "ticket_luxury.html",
        "description": "Editorial serif typography on cream with gold borders and dark footer.",
        "thumbnail": "https://images.unsplash.com/photo-1521295121783-8a321d551ad2?w=400",
        "is_premium": True,
    },
    {
        "id": "ticket_minimal",
        "name": "Corporate Minimal",
        "category": "Corporate",
        "doc_type": "ticket",
        "file": "ticket_minimal.html",
        "description": "Crisp sans-serif layout with single accent line. Great for B2B.",
        "thumbnail": "https://images.unsplash.com/photo-1497366216548-37526070297c?w=400",
        "is_premium": False,
    },

    # Voucher templates
    {
        "id": "voucher_premium",
        "name": "Premium Resort",
        "category": "Hotels",
        "doc_type": "voucher",
        "file": "voucher.html",
        "description": "Gold gradient header reminiscent of luxury hotel branding.",
        "thumbnail": "https://images.unsplash.com/photo-1650965171703-087486b3a1b0?w=400",
        "is_premium": True,
    },
    {
        "id": "voucher_luxury",
        "name": "Luxury Heritage",
        "category": "Luxury",
        "doc_type": "voucher",
        "file": "voucher_luxury.html",
        "description": "Elegant serif voucher with centered hotel block and dark footer.",
        "thumbnail": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=400",
        "is_premium": True,
    },
    {
        "id": "voucher_minimal",
        "name": "Corporate Minimal",
        "category": "Corporate",
        "doc_type": "voucher",
        "file": "voucher_minimal.html",
        "description": "Clean sans-serif voucher for corporate travel desks.",
        "thumbnail": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=400",
        "is_premium": False,
    },
]


def get_template_by_id(template_id: str, doc_type: str) -> dict:
    """Get template by id; fallback to the first template matching doc_type."""
    for tpl in TEMPLATE_REGISTRY:
        if tpl["id"] == template_id and tpl["doc_type"] == doc_type:
            return tpl
    # Fallback to default for doc_type
    for tpl in TEMPLATE_REGISTRY:
        if tpl["doc_type"] == doc_type:
            return tpl
    raise ValueError(f"No template found for doc_type={doc_type}")


def list_templates(doc_type: str | None = None, category: str | None = None) -> list[dict]:
    items = TEMPLATE_REGISTRY
    if doc_type:
        items = [t for t in items if t["doc_type"] == doc_type]
    if category and category.lower() != "all":
        items = [t for t in items if t["category"].lower() == category.lower()]
    # Return public metadata only (exclude file path)
    return [
        {k: v for k, v in t.items() if k != "file"}
        for t in items
    ]
