from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import bcrypt
import jwt
import stripe
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
STRIPE_API_KEY = os.environ["STRIPE_API_KEY"]
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

stripe.api_key = STRIPE_API_KEY

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="DropSell API")
api_router = APIRouter(prefix="/api")
security = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ===================== Models =====================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Product(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    slug: str
    category: str  # "maquetas" | "fidgets"
    price: float  # EUR
    description: str
    short_description: str = ""
    images: List[str] = []
    specs: Dict[str, str] = {}
    stock: int = 100
    featured: bool = False
    created_at: str = Field(default_factory=now_iso)


class ProductCreate(BaseModel):
    name: str
    slug: str
    category: str
    price: float
    description: str
    short_description: str = ""
    images: List[str] = []
    specs: Dict[str, str] = {}
    stock: int = 100
    featured: bool = False


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    images: Optional[List[str]] = None
    specs: Optional[Dict[str, str]] = None
    stock: Optional[int] = None
    featured: Optional[bool] = None


class CartItem(BaseModel):
    product_id: str
    quantity: int


class ShippingInfo(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    address_line1: str
    address_line2: str = ""
    city: str
    postal_code: str
    country: str = "ES"


class CheckoutRequest(BaseModel):
    items: List[CartItem]
    shipping: ShippingInfo
    origin_url: str


class AdminLoginRequest(BaseModel):
    email: str
    password: str


# ===================== Auth Helpers =====================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_jwt(email: str) -> str:
    payload = {
        "email": email,
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def require_admin(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ===================== Seed data =====================
SAMPLE_PRODUCTS = [
    {
        "name": "Lamborghini Aventador SVJ 1:18",
        "slug": "lamborghini-aventador-svj-118",
        "category": "maquetas",
        "price": 189.00,
        "short_description": "Edición coleccionista. Detalles CNC, puertas abatibles, llantas forjadas.",
        "description": "Reproducción a escala 1:18 del Lamborghini Aventador SVJ. Construido en die-cast de alta densidad con interior textil real, cinturones bordados y motor V12 visible. Caja de madera con certificado numerado. Solo 500 unidades en todo el mundo.",
        "images": [
            "https://images.pexels.com/photos/12361140/pexels-photo-12361140.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
            "https://images.unsplash.com/photo-1696824711583-651876031b30?crop=entropy&cs=srgb&fm=jpg&h=900&w=1200&q=85",
        ],
        "specs": {"Escala": "1:18", "Material": "Die-cast metal", "Edición": "Limitada", "Caja": "Madera"},
        "stock": 24,
        "featured": True,
    },
    {
        "name": "Porsche 911 GT3 RS 1:24",
        "slug": "porsche-911-gt3-rs-124",
        "category": "maquetas",
        "price": 79.00,
        "short_description": "Réplica oficial. Aerodinámica funcional, ruedas direccionales.",
        "description": "Maqueta certificada del Porsche 911 GT3 RS en escala 1:24. Pintura nacarada multicapa y detallado de pinzas de freno cerámicas. Direccion funcional.",
        "images": [
            "https://images.pexels.com/photos/38570/lamborghini-car-speed-prestige-38570.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
        ],
        "specs": {"Escala": "1:24", "Material": "Die-cast + ABS", "Edición": "Estándar"},
        "stock": 60,
        "featured": True,
    },
    {
        "name": "Ferrari F40 Classic 1:18",
        "slug": "ferrari-f40-classic-118",
        "category": "maquetas",
        "price": 149.00,
        "short_description": "Leyenda de los 80. Capó abatible, motor twin-turbo replicado.",
        "description": "Reproducción a escala 1:18 del icónico Ferrari F40. Acabado Rosso Corsa, motor twin-turbo expuesto bajo cristal trasero.",
        "images": [
            "https://images.pexels.com/photos/919073/pexels-photo-919073.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
        ],
        "specs": {"Escala": "1:18", "Material": "Die-cast metal", "Color": "Rosso Corsa"},
        "stock": 18,
        "featured": False,
    },
    {
        "name": "BMW M4 GTS 1:43 Track Pack",
        "slug": "bmw-m4-gts-143",
        "category": "maquetas",
        "price": 39.00,
        "short_description": "Pack compacto. Ideal para vitrina o escritorio.",
        "description": "Detalle profesional del BMW M4 GTS en escala 1:43. Pintura Frozen Dark Grey con detalles naranja flúor.",
        "images": [
            "https://images.unsplash.com/photo-1696824711583-651876031b30?crop=entropy&cs=srgb&fm=jpg&h=900&w=1200&q=85",
        ],
        "specs": {"Escala": "1:43", "Material": "Die-cast"},
        "stock": 120,
        "featured": False,
    },
    {
        "name": "Magnetic Slider — Titanium",
        "slug": "magnetic-slider-titanium",
        "category": "fidgets",
        "price": 89.00,
        "short_description": "Fidget de titanio mecanizado. Sliding lineal con tope magnético.",
        "description": "Fidget premium en titanio grado 5 mecanizado CNC. Sistema de imanes de neodimio N52 para resistencia táctil precisa. Acabado microbalado.",
        "images": [
            "https://images.pexels.com/photos/28752153/pexels-photo-28752153.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
        ],
        "specs": {"Material": "Titanio Grado 5", "Imanes": "Neodimio N52", "Peso": "62g"},
        "stock": 45,
        "featured": True,
    },
    {
        "name": "Orbiter Magnetic Spinner — Steel",
        "slug": "orbiter-magnetic-spinner",
        "category": "fidgets",
        "price": 59.00,
        "short_description": "Spinner magnético orbital. Acero inox 316. Rodamiento cerámico.",
        "description": "El Orbiter combina un rodamiento cerámico de precisión con un sistema orbital de imanes para una rotación de hasta 3 minutos. Acero inoxidable 316L cepillado.",
        "images": [
            "https://images.pexels.com/photos/10406128/pexels-photo-10406128.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
        ],
        "specs": {"Material": "Acero Inox 316L", "Rodamiento": "Cerámico", "Peso": "98g"},
        "stock": 72,
        "featured": True,
    },
    {
        "name": "Click Bar — Brass Edition",
        "slug": "click-bar-brass",
        "category": "fidgets",
        "price": 45.00,
        "short_description": "Barra fidget de latón. Click magnético satisfactorio.",
        "description": "Barra de latón macizo con sistema de click magnético. Tacto cálido, pátina natural con el uso. Hecho a mano.",
        "images": [
            "https://images.pexels.com/photos/28752153/pexels-photo-28752153.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
        ],
        "specs": {"Material": "Latón macizo", "Tipo": "Click magnético", "Peso": "75g"},
        "stock": 80,
        "featured": False,
    },
    {
        "name": "Cube Fidget — Carbon Steel",
        "slug": "cube-fidget-carbon-steel",
        "category": "fidgets",
        "price": 65.00,
        "short_description": "Cubo magnético reconfigurable. Acero al carbono.",
        "description": "Cubo modular con piezas reconfigurables mediante imanes ocultos. Acero al carbono tratado con DLC negro mate.",
        "images": [
            "https://images.pexels.com/photos/10406128/pexels-photo-10406128.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200",
        ],
        "specs": {"Material": "Acero al carbono DLC", "Imanes": "Neodimio", "Peso": "110g"},
        "stock": 35,
        "featured": False,
    },
]


@app.on_event("startup")
async def startup_event():
    # Seed admin
    existing_admin = await db.admins.find_one({"email": ADMIN_EMAIL})
    if not existing_admin:
        await db.admins.insert_one(
            {
                "id": str(uuid.uuid4()),
                "email": ADMIN_EMAIL,
                "password_hash": hash_password(ADMIN_PASSWORD),
                "created_at": now_iso(),
            }
        )
        logger.info(f"Seeded admin: {ADMIN_EMAIL}")
    # Seed products
    count = await db.products.count_documents({})
    if count == 0:
        for p in SAMPLE_PRODUCTS:
            prod = Product(**p)
            await db.products.insert_one(prod.model_dump())
        logger.info(f"Seeded {len(SAMPLE_PRODUCTS)} products")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


# ===================== Public Routes =====================
@api_router.get("/")
async def root():
    return {"message": "DropSell API"}


@api_router.get("/products", response_model=List[Product])
async def list_products(category: Optional[str] = None, featured: Optional[bool] = None):
    query: Dict[str, Any] = {}
    if category:
        query["category"] = category
    if featured is not None:
        query["featured"] = featured
    docs = await db.products.find(query, {"_id": 0}).to_list(500)
    return docs


@api_router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not doc:
        doc = await db.products.find_one({"slug": product_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc


# ===================== Admin Routes =====================
@api_router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    admin = await db.admins.find_one({"email": req.email})
    if not admin or not verify_password(req.password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = create_jwt(req.email)
    return {"token": token, "email": req.email}


@api_router.get("/admin/me")
async def admin_me(payload: dict = Depends(require_admin)):
    return {"email": payload["email"], "role": payload["role"]}


@api_router.post("/admin/products", response_model=Product)
async def create_product(data: ProductCreate, _: dict = Depends(require_admin)):
    prod = Product(**data.model_dump())
    await db.products.insert_one(prod.model_dump())
    return prod


@api_router.put("/admin/products/{product_id}", response_model=Product)
async def update_product(product_id: str, data: ProductUpdate, _: dict = Depends(require_admin)):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await db.products.update_one({"id": product_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    return doc


@api_router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, _: dict = Depends(require_admin)):
    result = await db.products.delete_one({"id": product_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"ok": True}


@api_router.get("/admin/orders")
async def list_orders(_: dict = Depends(require_admin)):
    docs = await db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


# ===================== Checkout (Stripe) =====================
SHIPPING_FLAT_RATE_EUR = 6.90


@api_router.post("/checkout/session")
async def create_checkout(req: CheckoutRequest, request: Request):
    if not req.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    subtotal = 0.0
    line_items_meta = []
    stripe_line_items = []

    for item in req.items:
        if item.quantity <= 0 or item.quantity > 99:
            raise HTTPException(status_code=400, detail="Invalid quantity")
        prod = await db.products.find_one({"id": item.product_id}, {"_id": 0})
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        subtotal += float(prod["price"]) * item.quantity
        line_items_meta.append({
            "product_id": prod["id"],
            "name": prod["name"],
            "price": prod["price"],
            "quantity": item.quantity,
        })
        stripe_line_items.append({
            "price_data": {
                "currency": "eur",
                "unit_amount": int(round(float(prod["price"]) * 100)),
                "product_data": {
                    "name": prod["name"],
                    "images": prod["images"][:1] if prod.get("images") else [],
                },
            },
            "quantity": item.quantity,
        })

    # Add shipping as a line item
    stripe_line_items.append({
        "price_data": {
            "currency": "eur",
            "unit_amount": int(SHIPPING_FLAT_RATE_EUR * 100),
            "product_data": {"name": "Envío estándar"},
        },
        "quantity": 1,
    })

    shipping_cost = SHIPPING_FLAT_RATE_EUR
    total = round(subtotal + shipping_cost, 2)
    origin = req.origin_url.rstrip("/")
    order_id = str(uuid.uuid4())

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=stripe_line_items,
        mode="payment",
        success_url=f"{origin}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/checkout",
        customer_email=req.shipping.email,
        metadata={
            "order_id": order_id,
            "full_name": req.shipping.full_name,
            "subtotal": f"{subtotal:.2f}",
            "shipping_cost": f"{shipping_cost:.2f}",
        },
    )

    await db.payment_transactions.insert_one({
        "id": order_id,
        "session_id": session.id,
        "amount": total,
        "currency": "eur",
        "subtotal": subtotal,
        "shipping_cost": shipping_cost,
        "items": line_items_meta,
        "shipping": req.shipping.model_dump(),
        "payment_status": "initiated",
        "status": "open",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    return {"url": session.url, "session_id": session.id, "order_id": order_id}


@api_router.get("/checkout/status/{session_id}")
async def checkout_status(session_id: str):
    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Session not found")

    if tx.get("payment_status") == "paid":
        return {
            "payment_status": "paid",
            "status": tx.get("status", "complete"),
            "amount_total": int(tx["amount"] * 100),
            "currency": tx["currency"],
            "order_id": tx["id"],
        }

    session = stripe.checkout.Session.retrieve(session_id)
    new_payment_status = session.payment_status
    new_status = session.status

    if tx.get("payment_status") != new_payment_status or tx.get("status") != new_status:
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {
                "payment_status": new_payment_status,
                "status": new_status,
                "updated_at": now_iso(),
            }},
        )

    return {
        "payment_status": new_payment_status,
        "status": new_status,
        "amount_total": session.amount_total,
        "currency": session.currency,
        "order_id": tx["id"],
    }


@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None)):
    body = await request.body()
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(body, stripe_signature, webhook_secret)
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    else:
        import json
        event = json.loads(body)

    if event.get("type") == "checkout.session.completed":
        session_data = event["data"]["object"]
        session_id = session_data.get("id")
        payment_status = session_data.get("payment_status", "unpaid")
        if session_id:
            tx = await db.payment_transactions.find_one({"session_id": session_id})
            if tx and tx.get("payment_status") != "paid":
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {"$set": {
                        "payment_status": payment_status,
                        "status": "complete" if payment_status == "paid" else "open",
                        "updated_at": now_iso(),
                    }},
                )

    return {"received": True}


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
