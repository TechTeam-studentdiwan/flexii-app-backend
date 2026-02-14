from fastapi import FastAPI, APIRouter, HTTPException, Body
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
from bson import ObjectId
import random

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# ============== MODELS ==============

class Address(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str  # Home, Work, etc
    fullName: str
    phone: str
    addressLine1: str
    addressLine2: Optional[str] = None
    city: str
    state: str
    postalCode: str
    country: str = "Qatar"
    isDefault: bool = False

class MeasurementProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    profileName: str  # Me, Mother, Sister
    measurements: Dict[str, float]  # bust, waist, hips, shoulder, sleeveLength, dressLength
    notes: Optional[str] = None
    lastUpdated: datetime = Field(default_factory=datetime.utcnow)

class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phone: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    isGuest: bool = False
    addresses: List[Address] = []
    measurementProfiles: List[MeasurementProfile] = []
    wishlist: List[str] = []  # product IDs
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class SizeChart(BaseModel):
    bust_max: float
    waist_max: float
    hips_max: float
    shoulder_max: float

class Product(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    price: float
    discountPrice: Optional[float] = None
    category: str
    subcategory: Optional[str] = None
    images: List[str]  # base64 images
    sizes: List[str]
    fitAdjustmentEnabled: bool
    sizeChart: Optional[Dict[str, SizeChart]] = None
    stock: int
    fabric: str
    occasion: str
    tags: List[str] = []
    whatsIncluded: str = "2pc set"
    careInstructions: str = "Dry clean recommended"
    isActive: bool = True
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class CartItem(BaseModel):
    productId: str
    size: str
    quantity: int = 1
    fitAdjustment: Optional[Dict[str, Any]] = None  # {profileId, profileName, fee, extraDays}

class Cart(BaseModel):
    userId: str
    items: List[CartItem] = []
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

class Coupon(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: str
    type: str  # percentage, flat, freedelivery
    value: float
    minCartValue: float = 0
    maxDiscount: Optional[float] = None
    validFrom: datetime
    validTo: datetime
    usageLimit: int = 1000
    usedCount: int = 0
    eligibleCategories: List[str] = []
    firstOrderOnly: bool = False
    isActive: bool = True

class OrderItem(BaseModel):
    productId: str
    productName: str
    productImage: str
    size: str
    quantity: int
    price: float
    fitAdjustment: Optional[Dict[str, Any]] = None

class Order(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    userId: str
    orderNumber: str = Field(default_factory=lambda: f"ORD{random.randint(100000, 999999)}")
    items: List[OrderItem]
    shippingAddress: Address
    subtotal: float
    discount: float = 0
    fitAdjustmentFee: float = 0
    deliveryFee: float = 0
    total: float
    paymentStatus: str = "pending"  # pending, paid, failed
    orderStatus: str = "confirmed"  # confirmed, processing, fit_adjustment_in_progress, shipped, delivered
    couponCode: Optional[str] = None
    trackingNumber: Optional[str] = None
    estimatedDelivery: datetime
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class Category(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    image: str  # base64
    order: int

# ============== REQUEST/RESPONSE MODELS ==============

class SendOTPRequest(BaseModel):
    phone: str

class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str

class AddToCartRequest(BaseModel):
    userId: str
    productId: str
    size: str
    quantity: int = 1
    fitAdjustment: Optional[Dict[str, Any]] = None

class UpdateCartRequest(BaseModel):
    userId: str
    productId: str
    size: str
    quantity: int

class RemoveFromCartRequest(BaseModel):
    userId: str
    productId: str
    size: str

class ValidateFitAdjustmentRequest(BaseModel):
    productId: str
    selectedSize: str
    profileId: str

class CreateOrderRequest(BaseModel):
    userId: str
    shippingAddressId: str
    couponCode: Optional[str] = None
    paymentMethod: str = "card"

class AddMeasurementProfileRequest(BaseModel):
    userId: str
    profile: MeasurementProfile

class AddAddressRequest(BaseModel):
    userId: str
    address: Address

class ValidateCouponRequest(BaseModel):
    code: str
    cartTotal: float
    userId: str

# ============== AUTH ROUTES ==============

@app.get("/")
async def api_check():
    return {
        "status": "online",
        "message": "E-commerce API is running",
        "timestamp": datetime.utcnow()
    }

@api_router.post("/auth/register")
async def register(email: str = Body(...), password: str = Body(...), name: str = Body(...)):
    # Check if user already exists
    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # In production, hash the password with bcrypt
    # For MVP, storing plain password (NEVER DO THIS IN PRODUCTION)
    new_user = User(email=email, name=name, isGuest=False)
    user_dict = new_user.dict()
    user_dict["password"] = password  # In production: hash_password(password)
    
    await db.users.insert_one(user_dict)
    
    # Remove password from response
    user_dict.pop("password")
    user_dict["_id"] = str(user_dict["_id"])
    
    return {"success": True, "user": user_dict, "message": "Registration successful"}

@api_router.post("/auth/login")
async def login(email: str = Body(...), password: str = Body(...)):
    # Find user by email
    user = await db.users.find_one({"email": email})
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # In production, verify hashed password
    # For MVP, direct comparison (NEVER DO THIS IN PRODUCTION)
    if user.get("password") != password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Remove password from response
    user_dict = dict(user)
    user_dict.pop("password", None)
    user_dict["_id"] = str(user_dict["_id"])
    
    return {"success": True, "user": user_dict, "message": "Login successful"}

@api_router.post("/auth/guest")
async def create_guest():
    guest_user = User(isGuest=True, name=f"Guest{random.randint(1000, 9999)}")
    await db.users.insert_one(guest_user.dict())
    return {"success": True, "user": guest_user.dict()}

# ============== PRODUCT ROUTES ==============

@api_router.get("/products")
async def get_products(
    category: Optional[str] = None,
    search: Optional[str] = None,
    minPrice: Optional[float] = None,
    maxPrice: Optional[float] = None,
    occasion: Optional[str] = None,
    fabric: Optional[str] = None,
    fitAdjustmentOnly: Optional[bool] = None,
    sort: Optional[str] = "popular",
    limit: int = 20,
    skip: int = 0
):
    query = {"isActive": True}
    
    if category:
        query["category"] = category
    if occasion:
        query["occasion"] = occasion
    if fabric:
        query["fabric"] = fabric
    if fitAdjustmentOnly:
        query["fitAdjustmentEnabled"] = True
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}}
        ]
    
    # Price filter
    if minPrice is not None or maxPrice is not None:
        query["$or"] = [
            {"discountPrice": {"$gte": minPrice or 0, "$lte": maxPrice or 999999}},
            {"discountPrice": None, "price": {"$gte": minPrice or 0, "$lte": maxPrice or 999999}}
        ]
    
    # Sorting
    sort_options = {
        "popular": [("createdAt", -1)],
        "new": [("createdAt", -1)],
        "price_low": [("price", 1)],
        "price_high": [("price", -1)]
    }
    
    sort_by = sort_options.get(sort, [("createdAt", -1)])
    products = await db.products.find(query).sort(sort_by).skip(skip).limit(limit).to_list(limit)
    
    for product in products:
        product["_id"] = str(product["_id"])
    
    total = await db.products.count_documents(query)
    
    return {"products": products, "total": total}

@api_router.get("/products/{product_id}")
async def get_product(product_id: str):
    product = await db.products.find_one({"id": product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    product["_id"] = str(product["_id"])
    return product

# ============== CART ROUTES ==============

@api_router.get("/cart/{user_id}")
async def get_cart(user_id: str):
    cart = await db.carts.find_one({"userId": user_id})
    if not cart:
        return {"items": [], "total": 0}
    
    # Populate product details
    cart_items = []
    total = 0
    
    for item in cart.get("items", []):
        product = await db.products.find_one({"id": item["productId"]})
        if product:
            price = product.get("discountPrice") or product.get("price")
            item_total = price * item["quantity"]
            
            if item.get("fitAdjustment"):
                item_total += item["fitAdjustment"].get("fee", 0) * item["quantity"]
            
            cart_items.append({
                "productId": item["productId"],
                "productName": product["name"],
                "productImage": product["images"][0] if product["images"] else "",
                "price": price,
                "size": item["size"],
                "quantity": item["quantity"],
                "fitAdjustment": item.get("fitAdjustment"),
                "itemTotal": item_total
            })
            total += item_total
    
    return {"items": cart_items, "total": total}

@api_router.post("/cart/add")
async def add_to_cart(request: AddToCartRequest):
    cart = await db.carts.find_one({"userId": request.userId})
    
    cart_item = CartItem(
        productId=request.productId,
        size=request.size,
        quantity=request.quantity,
        fitAdjustment=request.fitAdjustment
    )
    
    if cart:
        # Check if item already exists
        existing_item = None
        for i, item in enumerate(cart["items"]):
            if item["productId"] == request.productId and item["size"] == request.size:
                existing_item = i
                break
        
        if existing_item is not None:
            cart["items"][existing_item]["quantity"] += request.quantity
        else:
            cart["items"].append(cart_item.dict())
        
        await db.carts.update_one(
            {"userId": request.userId},
            {"$set": {"items": cart["items"], "updatedAt": datetime.utcnow()}}
        )
    else:
        new_cart = Cart(userId=request.userId, items=[cart_item])
        await db.carts.insert_one(new_cart.dict())
    
    return {"success": True, "message": "Added to cart"}

@api_router.post("/cart/update")
async def update_cart(request: UpdateCartRequest):
    cart = await db.carts.find_one({"userId": request.userId})
    
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    
    for item in cart["items"]:
        if item["productId"] == request.productId and item["size"] == request.size:
            item["quantity"] = request.quantity
            break
    
    await db.carts.update_one(
        {"userId": request.userId},
        {"$set": {"items": cart["items"], "updatedAt": datetime.utcnow()}}
    )
    
    return {"success": True, "message": "Cart updated"}

@api_router.post("/cart/remove")
async def remove_from_cart(request: RemoveFromCartRequest):
    cart = await db.carts.find_one({"userId": request.userId})
    
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    
    cart["items"] = [item for item in cart["items"] if not (item["productId"] == request.productId and item["size"] == request.size)]
    
    await db.carts.update_one(
        {"userId": request.userId},
        {"$set": {"items": cart["items"], "updatedAt": datetime.utcnow()}}
    )
    
    return {"success": True, "message": "Item removed"}

@api_router.delete("/cart/{user_id}")
async def clear_cart(user_id: str):
    await db.carts.delete_one({"userId": user_id})
    return {"success": True, "message": "Cart cleared"}

# ============== MEASUREMENT ROUTES ==============

@api_router.get("/measurements/{user_id}")
async def get_measurement_profiles(user_id: str):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"profiles": user.get("measurementProfiles", [])}

@api_router.post("/measurements/add")
async def add_measurement_profile(request: AddMeasurementProfileRequest):
    user = await db.users.find_one({"id": request.userId})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profiles = user.get("measurementProfiles", [])
    profiles.append(request.profile.dict())
    
    await db.users.update_one(
        {"id": request.userId},
        {"$set": {"measurementProfiles": profiles}}
    )
    
    return {"success": True, "message": "Profile added", "profile": request.profile.dict()}

@api_router.post("/measurements/validate")
async def validate_fit_adjustment(request: ValidateFitAdjustmentRequest):
    # Get product and user measurements
    product = await db.products.find_one({"id": request.productId})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    user = await db.users.find_one({"measurementProfiles.id": request.profileId})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Find the specific profile
    profile = None
    for p in user.get("measurementProfiles", []):
        if p["id"] == request.profileId:
            profile = p
            break
    
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Check eligibility
    if not product.get("fitAdjustmentEnabled") or not product.get("sizeChart"):
        return {
            "eligible": False,
            "message": "Fit adjustment not available for this product"
        }
    
    size_chart = product["sizeChart"].get(request.selectedSize)
    if not size_chart:
        return {
            "eligible": False,
            "message": "Size chart not available"
        }
    
    measurements = profile["measurements"]
    reasons = []
    
    if measurements.get("bust", 0) > size_chart["bust_max"]:
        reasons.append("bust")
    if measurements.get("waist", 0) > size_chart["waist_max"]:
        reasons.append("waist")
    if measurements.get("hips", 0) > size_chart["hips_max"]:
        reasons.append("hips")
    if measurements.get("shoulder", 0) > size_chart["shoulder_max"]:
        reasons.append("shoulder")
    
    if reasons:
        return {
            "eligible": False,
            "reasons": reasons,
            "message": f"These measurements exceed the selected size ({', '.join(reasons)}). Please choose a larger size."
        }
    
    return {
        "eligible": True,
        "fee": 30,  # QAR
        "extraDays": 3,
        "adjustments": ["length", "sleeve", "waist"],
        "profileName": profile["profileName"]
    }

# ============== ORDER ROUTES ==============

@api_router.post("/orders/create")
async def create_order(request: CreateOrderRequest):
    # Get cart
    cart = await db.carts.find_one({"userId": request.userId})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    # Get user
    user = await db.users.find_one({"id": request.userId})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Find shipping address
    shipping_address = None
    for addr in user.get("addresses", []):
        if addr["id"] == request.shippingAddressId:
            shipping_address = addr
            break
    
    if not shipping_address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    # Calculate totals
    order_items = []
    subtotal = 0
    fit_adjustment_fee = 0
    
    for item in cart["items"]:
        product = await db.products.find_one({"id": item["productId"]})
        if product:
            price = product.get("discountPrice") or product.get("price")
            item_total = price * item["quantity"]
            subtotal += item_total
            
            if item.get("fitAdjustment"):
                fit_adjustment_fee += item["fitAdjustment"].get("fee", 0) * item["quantity"]
            
            order_items.append(OrderItem(
                productId=item["productId"],
                productName=product["name"],
                productImage=product["images"][0] if product["images"] else "",
                size=item["size"],
                quantity=item["quantity"],
                price=price,
                fitAdjustment=item.get("fitAdjustment")
            ).dict())
    
    # Apply coupon
    discount = 0
    if request.couponCode:
        coupon = await db.coupons.find_one({"code": request.couponCode, "isActive": True})
        if coupon and coupon["validFrom"] <= datetime.utcnow() <= coupon["validTo"]:
            if coupon["type"] == "percentage":
                discount = (subtotal * coupon["value"]) / 100
                if coupon.get("maxDiscount"):
                    discount = min(discount, coupon["maxDiscount"])
            elif coupon["type"] == "flat":
                discount = coupon["value"]
    
    delivery_fee = 15 if subtotal < 200 else 0  # Free delivery over 200 QAR
    total = subtotal - discount + fit_adjustment_fee + delivery_fee
    
    # Determine estimated delivery
    extra_days = 5  # Base delivery
    has_fit_adjustment = any(item.get("fitAdjustment") for item in cart["items"])
    if has_fit_adjustment:
        extra_days += 3
    
    estimated_delivery = datetime.utcnow() + timedelta(days=extra_days)
    
    # Create order
    order = Order(
        userId=request.userId,
        items=order_items,
        shippingAddress=shipping_address,
        subtotal=subtotal,
        discount=discount,
        fitAdjustmentFee=fit_adjustment_fee,
        deliveryFee=delivery_fee,
        total=total,
        couponCode=request.couponCode,
        estimatedDelivery=estimated_delivery,
        orderStatus="fit_adjustment_in_progress" if has_fit_adjustment else "processing"
    )
    
    await db.orders.insert_one(order.dict())
    
    # Clear cart
    await db.carts.delete_one({"userId": request.userId})
    
    return {"success": True, "order": order.dict()}

@api_router.get("/orders/{user_id}")
async def get_orders(user_id: str):
    orders = await db.orders.find({"userId": user_id}).sort("createdAt", -1).to_list(100)
    for order in orders:
        order["_id"] = str(order["_id"])
    return {"orders": orders}

@api_router.get("/orders/detail/{order_id}")
async def get_order_detail(order_id: str):
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order["_id"] = str(order["_id"])
    return order

# ============== COUPON ROUTES ==============

@api_router.get("/coupons")
async def get_coupons():
    coupons = await db.coupons.find({"isActive": True, "validTo": {"$gte": datetime.utcnow()}}).to_list(100)
    for coupon in coupons:
        coupon["_id"] = str(coupon["_id"])
    return {"coupons": coupons}

@api_router.post("/coupons/validate")
async def validate_coupon(request: ValidateCouponRequest):
    coupon = await db.coupons.find_one({"code": request.code, "isActive": True})
    
    if not coupon:
        raise HTTPException(status_code=404, detail="Invalid coupon code")
    
    now = datetime.utcnow()
    if not (coupon["validFrom"] <= now <= coupon["validTo"]):
        raise HTTPException(status_code=400, detail="Coupon has expired")
    
    if request.cartTotal < coupon["minCartValue"]:
        raise HTTPException(status_code=400, detail=f"Minimum cart value is QAR {coupon['minCartValue']}")
    
    # Calculate discount
    discount = 0
    if coupon["type"] == "percentage":
        discount = (request.cartTotal * coupon["value"]) / 100
        if coupon.get("maxDiscount"):
            discount = min(discount, coupon["maxDiscount"])
    elif coupon["type"] == "flat":
        discount = coupon["value"]
    elif coupon["type"] == "freedelivery":
        discount = 15  # Delivery fee
    
    return {
        "valid": True,
        "discount": discount,
        "message": f"Coupon applied! You saved QAR {discount:.2f}"
    }

# ============== ADDRESS ROUTES ==============

@api_router.post("/addresses/add")
async def add_address(request: AddAddressRequest):
    user = await db.users.find_one({"id": request.userId})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    addresses = user.get("addresses", [])
    
    # If this is set as default, unset others
    if request.address.isDefault:
        for addr in addresses:
            addr["isDefault"] = False
    
    addresses.append(request.address.dict())
    
    await db.users.update_one(
        {"id": request.userId},
        {"$set": {"addresses": addresses}}
    )
    
    return {"success": True, "message": "Address added"}

@api_router.get("/addresses/{user_id}")
async def get_addresses(user_id: str):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"addresses": user.get("addresses", [])}

# ============== WISHLIST ROUTES ==============

@api_router.post("/wishlist/add")
async def add_to_wishlist(userId: str = Body(...), productId: str = Body(...)):
    user = await db.users.find_one({"id": userId})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    wishlist = user.get("wishlist", [])
    if productId not in wishlist:
        wishlist.append(productId)
        await db.users.update_one(
            {"id": userId},
            {"$set": {"wishlist": wishlist}}
        )
    
    return {"success": True, "message": "Added to wishlist"}

@api_router.post("/wishlist/remove")
async def remove_from_wishlist(userId: str = Body(...), productId: str = Body(...)):
    user = await db.users.find_one({"id": userId})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    wishlist = user.get("wishlist", [])
    if productId in wishlist:
        wishlist.remove(productId)
        await db.users.update_one(
            {"id": userId},
            {"$set": {"wishlist": wishlist}}
        )
    
    return {"success": True, "message": "Removed from wishlist"}

@api_router.get("/wishlist/{user_id}")
async def get_wishlist(user_id: str):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    wishlist_ids = user.get("wishlist", [])
    products = await db.products.find({"id": {"$in": wishlist_ids}}).to_list(100)
    
    for product in products:
        product["_id"] = str(product["_id"])
    
    return {"products": products}

# ============== CATEGORIES ROUTES ==============

@api_router.get("/categories")
async def get_categories():
    categories = await db.categories.find().sort("order", 1).to_list(100)
    for cat in categories:
        cat["_id"] = str(cat["_id"])
    return {"categories": categories}

# ============== USER ROUTES ==============

@api_router.get("/users/{user_id}")
async def get_user(user_id: str):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user["_id"] = str(user["_id"])
    return user

@api_router.put("/users/{user_id}")
async def update_user(user_id: str, name: Optional[str] = Body(None), email: Optional[str] = Body(None)):
    update_data = {}
    if name:
        update_data["name"] = name
    if email:
        update_data["email"] = email
    
    if update_data:
        await db.users.update_one(
            {"id": user_id},
            {"$set": update_data}
        )
    
    return {"success": True, "message": "User updated"}

# ============== SEED DATA ROUTE ==============

@api_router.post("/seed")
async def seed_data():
    # Check if already seeded
    existing_products = await db.products.count_documents({})
    if existing_products > 0:
        return {"message": "Database already seeded"}
    
    # Sample categories
    categories = [
        Category(name="Chikankari", image="", order=1),
        Category(name="Pakistani Suits", image="", order=2),
        Category(name="Jaipuri", image="", order=3),
        Category(name="Lehengas", image="", order=4),
        Category(name="Sarees", image="", order=5)
    ]
    
    for cat in categories:
        await db.categories.insert_one(cat.dict())
    
    # Sample products
    sample_products = [
        Product(
            name="Chikankari Kurta Set - Ivory",
            description="Beautiful hand-embroidered Chikankari work on pure cotton fabric. Perfect for Ramadan.",
            price=349,
            discountPrice=249,
            category="Chikankari",
            images=[""],
            sizes=["S", "M", "L", "XL", "XXL"],
            fitAdjustmentEnabled=True,
            sizeChart={
                "S": {"bust_max": 90, "waist_max": 70, "hips_max": 95, "shoulder_max": 38},
                "M": {"bust_max": 95, "waist_max": 75, "hips_max": 100, "shoulder_max": 40},
                "L": {"bust_max": 100, "waist_max": 80, "hips_max": 105, "shoulder_max": 42},
                "XL": {"bust_max": 105, "waist_max": 85, "hips_max": 110, "shoulder_max": 44},
                "XXL": {"bust_max": 110, "waist_max": 90, "hips_max": 115, "shoulder_max": 46}
            },
            stock=25,
            fabric="Cotton",
            occasion="Ramadan",
            tags=["bestseller", "ramadan"],
            whatsIncluded="3pc set - Kurta, Palazzo, Dupatta"
        ),
        Product(
            name="Pakistani Lawn Suit - Pastel Pink",
            description="Elegant Pakistani lawn suit with intricate embroidery. Lightweight and comfortable.",
            price=449,
            discountPrice=329,
            category="Pakistani Suits",
            images=[""],
            sizes=["S", "M", "L", "XL"],
            fitAdjustmentEnabled=True,
            sizeChart={
                "S": {"bust_max": 88, "waist_max": 68, "hips_max": 93, "shoulder_max": 37},
                "M": {"bust_max": 93, "waist_max": 73, "hips_max": 98, "shoulder_max": 39},
                "L": {"bust_max": 98, "waist_max": 78, "hips_max": 103, "shoulder_max": 41},
                "XL": {"bust_max": 103, "waist_max": 83, "hips_max": 108, "shoulder_max": 43}
            },
            stock=18,
            fabric="Lawn",
            occasion="Eid",
            tags=["eid", "newin"]
        ),
        Product(
            name="Jaipuri Block Print Kurta",
            description="Traditional Jaipuri block print on soft cotton. Vibrant colors and patterns.",
            price=299,
            discountPrice=199,
            category="Jaipuri",
            images=[""],
            sizes=["S", "M", "L", "XL"],
            fitAdjustmentEnabled=False,
            stock=30,
            fabric="Cotton",
            occasion="Casual",
            tags=["under199"]
        ),
        Product(
            name="Designer Lehenga - Royal Blue",
            description="Stunning designer lehenga with zari work. Perfect for special occasions.",
            price=1299,
            discountPrice=999,
            category="Lehengas",
            images=[""],
            sizes=["S", "M", "L", "XL"],
            fitAdjustmentEnabled=True,
            sizeChart={
                "S": {"bust_max": 86, "waist_max": 66, "hips_max": 91, "shoulder_max": 36},
                "M": {"bust_max": 91, "waist_max": 71, "hips_max": 96, "shoulder_max": 38},
                "L": {"bust_max": 96, "waist_max": 76, "hips_max": 101, "shoulder_max": 40},
                "XL": {"bust_max": 101, "waist_max": 81, "hips_max": 106, "shoulder_max": 42}
            },
            stock=12,
            fabric="Silk",
            occasion="Wedding",
            tags=["premium"]
        ),
        Product(
            name="Banarasi Silk Saree - Magenta",
            description="Authentic Banarasi silk saree with golden zari border. Timeless elegance.",
            price=899,
            discountPrice=699,
            category="Sarees",
            images=[""],
            sizes=["One Size"],
            fitAdjustmentEnabled=False,
            stock=20,
            fabric="Silk",
            occasion="Festive",
            tags=["traditional"]
        )
    ]
    
    for product in sample_products:
        await db.products.insert_one(product.dict())
    
    # Sample coupons
    now = datetime.utcnow()
    coupons = [
        Coupon(
            code="RAMADAN15",
            type="percentage",
            value=15,
            minCartValue=200,
            maxDiscount=50,
            validFrom=now,
            validTo=now + timedelta(days=30)
        ),
        Coupon(
            code="FIRST50",
            type="flat",
            value=50,
            minCartValue=300,
            validFrom=now,
            validTo=now + timedelta(days=60),
            firstOrderOnly=True
        ),
        Coupon(
            code="FREESHIP",
            type="freedelivery",
            value=0,
            minCartValue=0,
            validFrom=now,
            validTo=now + timedelta(days=90)
        )
    ]
    
    for coupon in coupons:
        await db.coupons.insert_one(coupon.dict())
    
    return {"success": True, "message": "Database seeded successfully"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


if __name__ == "__main__":
    import uvicorn
    # This block only runs if you type: python main.py
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)