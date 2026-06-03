"""
Factory functions that return valid request payloads for each API endpoint.
Use `uid8()` suffixes when the field must be globally unique across test runs.
"""

import uuid


def uid8() -> str:
    return uuid.uuid4().hex[:8]


# ── Products ─────────────────────────────────────────────────────────────────

def product_payload(**overrides) -> dict:
    suffix = uid8()
    base = {
        "name": f"Test Product {suffix}",
        "sku": f"TST-{suffix}",
        "gst_rate": 18.0,
        "purchase_rate": 80.0,
        "selling_rate": 100.0,
        "pack_size": "1 kg",
        "initial_stock": 10,
    }
    return {**base, **overrides}


def product_update_payload(**overrides) -> dict:
    suffix = uid8()
    base = {
        "name": f"Updated Product {suffix}",
        "sku": f"UPD-{suffix}",
        "gst_rate": 12.0,
        "purchase_rate": 70.0,
        "selling_rate": 90.0,
        "pack_size": "500 g",
    }
    return {**base, **overrides}


# ── Suppliers ────────────────────────────────────────────────────────────────

def gst_number() -> str:
    """Generate a structurally valid (but fictional) 15-char GST number."""
    h = uuid.uuid4().hex[:4].upper()
    # Format: 2 digits + 5 uppercase letters + 4 digits + 1 upper + 1 alphanum + Z + 1 digit
    return f"29ABCDE{h}A1Z5"


def supplier_payload(**overrides) -> dict:
    suffix = uid8()
    base = {
        "supplier_name": f"Supplier {suffix}",
        "supplier_gst_number": gst_number(),
        "mobile": "9876543210",
        "contact_person": f"Contact {suffix}",
        "email": f"sup{suffix}@example.com",
        "address": "123 Test Street, City",
        "bank_name": "Test Bank",
        "bank_account_number": "987654321012",
        "ifsc_code": "SBIN0001234",
    }
    return {**base, **overrides}


# ── Users ────────────────────────────────────────────────────────────────────

def user_payload(role: str = "Cashier", **overrides) -> dict:
    suffix = uid8()
    base = {
        "username": f"user_{suffix}",
        "password": "Password@123",
        "role": role,
        "full_name": f"User {suffix}",
        "email": f"user{suffix}@test.com",
        "mobile": "9000000000",
    }
    return {**base, **overrides}


# ── Sales ────────────────────────────────────────────────────────────────────

def sale_payload(product_id: int, selling_rate: float, gst_rate: float, **overrides) -> dict:
    base = {
        "customer_name": "Test Customer",
        "mode_of_payment": "Cash",
        "discount_percentage": 0,
        "items": [
            {
                "product_id": product_id,
                "quantity": 1,
                "rate": selling_rate,
                "gst_rate": gst_rate,
            }
        ],
    }
    return {**base, **overrides}


# ── Purchase Orders ──────────────────────────────────────────────────────────

def purchase_payload(supplier_id: int, product_id: int, **overrides) -> dict:
    suffix = uid8()
    base = {
        "supplier_id": supplier_id,
        "purchase_order_number": f"PO-{suffix}",
        "purchase_date": "2026-01-15T10:00:00",
        "items": [
            {
                "product_id": product_id,
                "quantity": 5,
                "purchase_rate": 80.0,
                "gst_rate": 18.0,
            }
        ],
    }
    return {**base, **overrides}


# ── Credit Customers ─────────────────────────────────────────────────────────

def credit_customer_payload(**overrides) -> dict:
    suffix = uid8()
    base = {
        "name": f"Credit Customer {suffix}",
        "mobile": "9123456789",
        "email": f"credit{suffix}@test.com",
        "address": "456 Credit Lane",
        "current_balance": 0.0,
    }
    return {**base, **overrides}
