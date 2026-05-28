from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
import os
import logging
from io import BytesIO
import secrets

from auth_utils import hash_password, verify_password, create_access_token, create_refresh_token, get_current_user
from pdf_service import render_ticket_pdf, render_voucher_pdf
from template_registry import list_templates

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="TicketForge Pro API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Auth Models
class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: Optional[str] = "agent"

class LoginRequest(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str

# Document Models
class FlightTicketCreate(BaseModel):
    passenger_name: str
    booking_reference: str
    ticket_number: str
    flight_number: str
    airline: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    class_type: str = "Economy"
    baggage: str = "1PC 23KG"
    template_id: Optional[str] = "ticket_premium"

class HotelVoucherCreate(BaseModel):
    guest_name: str
    confirmation_number: str
    voucher_number: str
    hotel_name: str
    hotel_address: str
    checkin_date: str
    checkout_date: str
    room_category: str = "Deluxe Room"
    meal_plan: str = "Breakfast Included"
    num_guests: int = 1
    template_id: Optional[str] = "voucher_premium"

class TemplateResponse(BaseModel):
    id: str
    name: str
    category: str
    thumbnail: str

class BrandKit(BaseModel):
    company_name: str
    logo_url: Optional[str] = None
    primary_color: str = "#1e3a8a"
    secondary_color: str = "#d4af37"

# Helper function for auth dependency
async def get_auth_user(request: Request):
    return await get_current_user(request, db)

# Admin seeding
async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@ticketforge.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        hashed = hash_password(admin_password)
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hashed,
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc)
        })
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}}
        )
    
    # Save test credentials
    test_user_email = "agent@ticketforge.com"
    test_user_password = "agent123"
    test_user = await db.users.find_one({"email": test_user_email})
    if not test_user:
        await db.users.insert_one({
            "email": test_user_email,
            "password_hash": hash_password(test_user_password),
            "name": "Test Agent",
            "role": "agent",
            "created_at": datetime.now(timezone.utc)
        })
    
    # Write credentials file
    creds_content = f"""# Test Credentials for TicketForge Pro

## Admin Account
- Email: {admin_email}
- Password: {admin_password}
- Role: admin

## Test Agent Account
- Email: {test_user_email}
- Password: {test_user_password}
- Role: agent

## Auth Endpoints
- POST /api/auth/register
- POST /api/auth/login
- GET /api/auth/me
- POST /api/auth/logout
- POST /api/auth/refresh
"""
    with open("test_credentials.md", "w") as f:
        f.write(creds_content)

# Auth Routes
@api_router.post("/auth/register", response_model=UserResponse)
async def register(request: RegisterRequest, response: Response):
    email_lower = request.email.lower()
    existing = await db.users.find_one({"email": email_lower})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed = hash_password(request.password)
    user_doc = {
        "email": email_lower,
        "password_hash": hashed,
        "name": request.name,
        "role": "agent",  # Force 'agent' role - admins created via seed only
        "created_at": datetime.now(timezone.utc)
    }
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    
    access_token = create_access_token(user_id, email_lower)
    refresh_token = create_refresh_token(user_id)
    
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=900,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=604800,
        path="/"
    )
    
    return UserResponse(
        id=user_id,
        email=email_lower,
        name=request.name,
        role="agent"
    )

@api_router.post("/auth/login", response_model=UserResponse)
async def login(request: LoginRequest, response: Response):
    email_lower = request.email.lower()
    user = await db.users.find_one({"email": email_lower})
    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user_id = str(user["_id"])
    access_token = create_access_token(user_id, email_lower)
    refresh_token = create_refresh_token(user_id)
    
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=900,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=604800,
        path="/"
    )
    
    return UserResponse(
        id=user_id,
        email=email_lower,
        name=user["name"],
        role=user["role"]
    )

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_auth_user)):
    return UserResponse(
        id=user["_id"],
        email=user["email"],
        name=user["name"],
        role=user["role"]
    )

@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return {"message": "Logged out successfully"}

@api_router.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    import jwt as _jwt
    from auth_utils import JWT_ALGORITHM, get_jwt_secret
    
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    
    try:
        payload = _jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        
        user_id = payload["sub"]
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        new_access_token = create_access_token(user_id, user["email"])
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=900,
            path="/"
        )
        return {"message": "Token refreshed"}
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

# Document Routes
@api_router.post("/documents/tickets")
async def create_ticket(ticket: FlightTicketCreate, user: dict = Depends(get_auth_user)):
    ticket_doc = ticket.model_dump()
    ticket_doc["user_id"] = user["_id"]
    ticket_doc["type"] = "ticket"
    ticket_doc["created_at"] = datetime.now(timezone.utc)
    result = await db.documents.insert_one(ticket_doc)
    return {"id": str(result.inserted_id), "message": "Ticket created successfully"}

@api_router.post("/documents/vouchers")
async def create_voucher(voucher: HotelVoucherCreate, user: dict = Depends(get_auth_user)):
    voucher_doc = voucher.model_dump()
    voucher_doc["user_id"] = user["_id"]
    voucher_doc["type"] = "voucher"
    voucher_doc["created_at"] = datetime.now(timezone.utc)
    result = await db.documents.insert_one(voucher_doc)
    return {"id": str(result.inserted_id), "message": "Voucher created successfully"}

@api_router.put("/documents/tickets/{document_id}")
async def update_ticket(document_id: str, ticket: FlightTicketCreate, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(document_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")
    existing = await db.documents.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(existing.get("user_id")) != user["_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    if existing.get("type") != "ticket":
        raise HTTPException(status_code=400, detail="Document is not a ticket")
    update_doc = ticket.model_dump()
    update_doc["updated_at"] = datetime.now(timezone.utc)
    await db.documents.update_one({"_id": oid}, {"$set": update_doc})
    return {"id": document_id, "message": "Ticket updated successfully"}

@api_router.put("/documents/vouchers/{document_id}")
async def update_voucher(document_id: str, voucher: HotelVoucherCreate, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(document_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")
    existing = await db.documents.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(existing.get("user_id")) != user["_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    if existing.get("type") != "voucher":
        raise HTTPException(status_code=400, detail="Document is not a voucher")
    update_doc = voucher.model_dump()
    update_doc["updated_at"] = datetime.now(timezone.utc)
    await db.documents.update_one({"_id": oid}, {"$set": update_doc})
    return {"id": document_id, "message": "Voucher updated successfully"}

@api_router.get("/documents/{document_id}")
async def get_document(document_id: str, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(document_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")
    doc = await db.documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc.get("user_id")) != user["_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    doc["id"] = str(doc.pop("_id"))
    doc.pop("user_id", None)
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    if isinstance(doc.get("updated_at"), datetime):
        doc["updated_at"] = doc["updated_at"].isoformat()
    return doc

@api_router.delete("/documents/{document_id}")
async def delete_document(document_id: str, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(document_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")
    doc = await db.documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc.get("user_id")) != user["_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    await db.documents.delete_one({"_id": oid})
    return {"message": "Document deleted successfully"}

@api_router.get("/documents")
async def get_documents(user: dict = Depends(get_auth_user)):
    documents = await db.documents.find(
        {"user_id": user["_id"]},
        {"_id": 1, "type": 1, "passenger_name": 1, "guest_name": 1, "booking_reference": 1, "confirmation_number": 1, "created_at": 1}
    ).sort("created_at", -1).to_list(100)
    
    result = []
    for doc in documents:
        result.append({
            "id": str(doc["_id"]),
            "type": doc["type"],
            "name": doc.get("passenger_name") or doc.get("guest_name", "N/A"),
            "reference": doc.get("booking_reference") or doc.get("confirmation_number", "N/A"),
            "created_at": doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else doc["created_at"]
        })
    
    return result

@api_router.get("/documents/{document_id}/pdf")
async def get_document_pdf(document_id: str, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(document_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")
    
    doc = await db.documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Verify ownership (or admin role)
    if str(doc.get("user_id")) != user["_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    doc["id"] = document_id
    
    # Fetch user's brand kit to apply branding to PDF
    # Use document owner's brand kit (so admins downloading get the agency's branding)
    brand = await db.brand_kits.find_one({"user_id": str(doc.get("user_id"))})
    if brand:
        brand.pop("_id", None)
        brand.pop("user_id", None)
        brand.pop("updated_at", None)
    
    if doc["type"] == "ticket":
        pdf_bytes = render_ticket_pdf(doc, brand=brand, template_id=doc.get("template_id"))
        filename = f"ticket-{document_id}.pdf"
    else:
        pdf_bytes = render_voucher_pdf(doc, brand=brand, template_id=doc.get("template_id"))
        filename = f"voucher-{document_id}.pdf"
    
    file_like = BytesIO(pdf_bytes)
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"'
    }
    return StreamingResponse(file_like, media_type="application/pdf", headers=headers)

# Template Routes
@api_router.get("/templates")
async def get_templates(doc_type: Optional[str] = None, category: Optional[str] = None):
    """List available PDF templates. Optional filters: doc_type (ticket|voucher), category."""
    return list_templates(doc_type=doc_type, category=category)

# Dashboard Stats
@api_router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_auth_user)):
    total_docs = await db.documents.count_documents({"user_id": user["_id"]})
    today_docs = await db.documents.count_documents({
        "user_id": user["_id"],
        "created_at": {"$gte": datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)}
    })
    
    return {
        "total_documents": total_docs,
        "documents_today": today_docs,
        "total_agents": 1,
        "revenue": 0
    }

import re

# Brand Kit Models
def validate_hex_color(color: str) -> str:
    if not re.match(r"^#[0-9a-fA-F]{3,8}$", color):
        raise ValueError("Color must be a valid hex code (e.g. #1e3a8a)")
    return color

class BrandKitData(BaseModel):
    company_name: str = ""
    logo_base64: Optional[str] = None  # Data URL or base64 string
    primary_color: str = "#1e3a8a"
    secondary_color: str = "#d4af37"
    contact_email: str = ""
    contact_phone: str = ""
    website: str = ""
    address: str = ""
    gst_number: str = ""
    email_signature: str = ""
    social_facebook: str = ""
    social_instagram: str = ""
    social_twitter: str = ""
    social_linkedin: str = ""

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def check_hex(cls, v: str) -> str:
        return validate_hex_color(v)

# Brand Kit Routes
@api_router.get("/brand-kit")
async def get_brand_kit(user: dict = Depends(get_auth_user)):
    brand = await db.brand_kits.find_one({"user_id": user["_id"]})
    if not brand:
        # Return default empty brand kit
        return BrandKitData().model_dump()
    brand.pop("_id", None)
    brand.pop("user_id", None)
    brand.pop("updated_at", None)
    return brand

@api_router.put("/brand-kit")
async def update_brand_kit(brand_data: BrandKitData, user: dict = Depends(get_auth_user)):
    # Validate logo size if present (limit ~1MB base64 = ~750KB binary)
    if brand_data.logo_base64 and len(brand_data.logo_base64) > 1_400_000:
        raise HTTPException(status_code=400, detail="Logo file too large. Maximum size is 1MB.")
    
    update_doc = brand_data.model_dump()
    update_doc["user_id"] = user["_id"]
    update_doc["updated_at"] = datetime.now(timezone.utc)
    
    await db.brand_kits.update_one(
        {"user_id": user["_id"]},
        {"$set": update_doc},
        upsert=True
    )
    return {"message": "Brand kit saved successfully"}

# Client Models
class ClientData(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    address: str = ""
    notes: str = ""

# Client Routes
@api_router.post("/clients")
async def create_client(client_data: ClientData, user: dict = Depends(get_auth_user)):
    if not client_data.name.strip():
        raise HTTPException(status_code=400, detail="Client name is required")
    doc = client_data.model_dump()
    doc["user_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc)
    result = await db.clients.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Client created successfully"}

@api_router.get("/clients")
async def list_clients(search: Optional[str] = None, user: dict = Depends(get_auth_user)):
    query: dict = {"user_id": user["_id"]}
    if search:
        # case-insensitive partial match on name or email
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    clients = await db.clients.find(query).sort("created_at", -1).to_list(500)
    return [
        {
            "id": str(c["_id"]),
            "name": c.get("name", ""),
            "email": c.get("email", ""),
            "phone": c.get("phone", ""),
            "address": c.get("address", ""),
            "notes": c.get("notes", ""),
            "created_at": c["created_at"].isoformat() if isinstance(c.get("created_at"), datetime) else c.get("created_at"),
        }
        for c in clients
    ]

@api_router.get("/clients/{client_id}")
async def get_client(client_id: str, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid client ID")
    c = await db.clients.find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    if str(c.get("user_id")) != user["_id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return {
        "id": str(c["_id"]),
        "name": c.get("name", ""),
        "email": c.get("email", ""),
        "phone": c.get("phone", ""),
        "address": c.get("address", ""),
        "notes": c.get("notes", ""),
    }

@api_router.put("/clients/{client_id}")
async def update_client(client_id: str, client_data: ClientData, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid client ID")
    c = await db.clients.find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    if str(c.get("user_id")) != user["_id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    update_doc = client_data.model_dump()
    update_doc["updated_at"] = datetime.now(timezone.utc)
    await db.clients.update_one({"_id": oid}, {"$set": update_doc})
    return {"message": "Client updated successfully"}

@api_router.delete("/clients/{client_id}")
async def delete_client(client_id: str, user: dict = Depends(get_auth_user)):
    try:
        oid = ObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid client ID")
    c = await db.clients.find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    if str(c.get("user_id")) != user["_id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    await db.clients.delete_one({"_id": oid})
    return {"message": "Client deleted successfully"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', 'http://localhost:3000').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB indexes
@app.on_event("startup")
async def startup_event():
    await db.users.create_index("email", unique=True)
    await seed_admin()
    logging.info("Application started successfully")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
