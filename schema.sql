-- PostgreSQL Database Schema for POS System

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR UNIQUE NOT NULL,
    password_hash VARCHAR NOT NULL,
    role VARCHAR NOT NULL CHECK (role IN ('Admin', 'Cashier', 'Super Admin', 'Manager')),
    full_name VARCHAR,
    email VARCHAR,
    mobile VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add columns for existing databases that were created before these fields were added
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mobile VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret  VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE;

-- Products table
CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    pack_size VARCHAR,
    sku VARCHAR UNIQUE,
    gst_rate DECIMAL(5, 2) NOT NULL,
    purchase_rate DECIMAL(10, 2),
    selling_rate DECIMAL(10, 2) NOT NULL,
    status VARCHAR DEFAULT 'Active' CHECK (status IN ('Active', 'Inactive'))
);

-- Inventory table
CREATE TABLE IF NOT EXISTS inventory (
    product_id INTEGER PRIMARY KEY REFERENCES products(product_id),
    stock_quantity INTEGER NOT NULL DEFAULT 0
);

-- Suppliers table (for purchase orders)
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id SERIAL PRIMARY KEY,
    supplier_name VARCHAR NOT NULL,
    supplier_gst_number VARCHAR UNIQUE,
    contact_person VARCHAR,
    email VARCHAR,
    address TEXT,
    mobile VARCHAR,
    bank_name VARCHAR,
    bank_account_number VARCHAR,
    ifsc_code VARCHAR,
    current_balance DECIMAL(10, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Purchase orders table
CREATE TABLE IF NOT EXISTS purchase_orders (
    purchase_order_id SERIAL PRIMARY KEY,
    supplier_id INTEGER REFERENCES suppliers(supplier_id),
    supplier_name VARCHAR, -- For backward compatibility
    supplier_gst_number VARCHAR, -- For backward compatibility
    purchase_order_number VARCHAR UNIQUE NOT NULL,
    purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER REFERENCES users(user_id),
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR DEFAULT 'Completed' CHECK (status IN ('Completed', 'Cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add a comment to clarify the uniqueness constraint
COMMENT ON COLUMN purchase_orders.purchase_order_number IS 'Unique purchase order number - each PO number must be unique across all purchase orders';

-- Purchase order items table
CREATE TABLE IF NOT EXISTS purchase_order_items (
    item_id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER REFERENCES purchase_orders(purchase_order_id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    purchase_rate DECIMAL(10, 2) NOT NULL,
    gst_rate DECIMAL(5, 2) DEFAULT 0.00,
    taxable_value DECIMAL(10, 2) DEFAULT 0.00,
    sgst DECIMAL(10, 2) DEFAULT 0.00,
    cgst DECIMAL(10, 2) DEFAULT 0.00,
    total_amount DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add a comment to clarify the relationship
COMMENT ON TABLE purchase_order_items IS 'Items for purchase orders - each purchase order can have multiple items';

-- Add columns to existing purchase_order_items table if they don't exist
-- This is for upgrading existing databases
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS gst_rate DECIMAL(5, 2) DEFAULT 0.00;
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS taxable_value DECIMAL(10, 2) DEFAULT 0.00;
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS sgst DECIMAL(10, 2) DEFAULT 0.00;
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS cgst DECIMAL(10, 2) DEFAULT 0.00;
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Add current_balance column to suppliers table if it doesn't exist
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS current_balance DECIMAL(10, 2) DEFAULT 0.00;

-- Barcode field for products (used by hardware/camera barcode scanners)
ALTER TABLE products ADD COLUMN IF NOT EXISTS barcode VARCHAR UNIQUE;

-- Add foreign key constraint with cascade delete if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'purchase_order_items_purchase_order_id_fkey'
    ) THEN
        ALTER TABLE purchase_order_items 
        ADD CONSTRAINT purchase_order_items_purchase_order_id_fkey 
        FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(purchase_order_id) ON DELETE CASCADE;
    END IF;
END $$;

-- Sales invoices table
CREATE TABLE IF NOT EXISTS sales_invoices (
    invoice_id SERIAL PRIMARY KEY,
    invoice_number VARCHAR UNIQUE NOT NULL,
    receipt_number VARCHAR UNIQUE,
    invoice_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    customer_name VARCHAR,
    customer_contact VARCHAR,
    user_id INTEGER REFERENCES users(user_id),
    mode_of_payment VARCHAR,
    upi_transaction_id VARCHAR,
    customer_mobile VARCHAR,
    total_amount DECIMAL(10, 2) NOT NULL,
    total_gst DECIMAL(10, 2) NOT NULL,
    discount_percentage DECIMAL(5, 2) DEFAULT 0.00,
    discount_amount DECIMAL(10, 2) DEFAULT 0.00,
    status VARCHAR DEFAULT 'Completed' CHECK (status IN ('Completed', 'Cancelled'))
);

-- Cancellation audit trail (who/when/why) — a cancelled invoice reverses a legal
-- document, so the action must be traceable. Added via ALTER for existing databases.
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_by   INTEGER REFERENCES users(user_id);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_at   TIMESTAMP;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancel_reason  TEXT;

-- Sales invoice items table
CREATE TABLE IF NOT EXISTS sales_invoice_items (
    item_id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES sales_invoices(invoice_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    rate_at_sale DECIMAL(10, 2) NOT NULL,
    gst_rate_at_sale DECIMAL(5, 2) NOT NULL,
    exclusive_gst_amount DECIMAL(10, 2) NOT NULL,
    sgst DECIMAL(10, 2) NOT NULL,
    cgst DECIMAL(10, 2) NOT NULL,
    total_line_amount DECIMAL(10, 2) NOT NULL,
    discount_percentage DECIMAL(5, 2) DEFAULT 0.00
);

-- Sales returns header table
CREATE TABLE IF NOT EXISTS sales_returns (
    return_id            SERIAL PRIMARY KEY,
    return_number        VARCHAR NOT NULL UNIQUE,
    original_invoice_id  INTEGER REFERENCES sales_invoices(invoice_id),
    original_invoice_number VARCHAR NOT NULL,
    return_date          DATE NOT NULL DEFAULT CURRENT_DATE,
    customer_name        VARCHAR,
    customer_mobile      VARCHAR,
    return_reason        VARCHAR NOT NULL,
    refund_method        VARCHAR NOT NULL,
    subtotal             DECIMAL(10, 2) NOT NULL DEFAULT 0,
    total_gst            DECIMAL(10, 2) NOT NULL DEFAULT 0,
    total_amount         DECIMAL(10, 2) NOT NULL DEFAULT 0,
    status               VARCHAR NOT NULL DEFAULT 'Completed',
    user_id              INTEGER REFERENCES users(user_id),
    notes                TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sales return line items table
CREATE TABLE IF NOT EXISTS sales_return_items (
    return_item_id       SERIAL PRIMARY KEY,
    return_id            INTEGER REFERENCES sales_returns(return_id) ON DELETE CASCADE,
    original_item_id     INTEGER REFERENCES sales_invoice_items(item_id),
    product_id           INTEGER REFERENCES products(product_id),
    product_name         VARCHAR NOT NULL,
    sku                  VARCHAR,
    pack_size            VARCHAR,
    quantity             INTEGER NOT NULL,
    rate_at_return       DECIMAL(10, 2) NOT NULL,
    discount_percentage  DECIMAL(5, 2) DEFAULT 0,
    gst_rate             DECIMAL(5, 2) NOT NULL,
    exclusive_gst_amount DECIMAL(10, 2) NOT NULL,
    sgst                 DECIMAL(10, 2) NOT NULL,
    cgst                 DECIMAL(10, 2) NOT NULL,
    total_line_amount    DECIMAL(10, 2) NOT NULL
);

-- Sample data for testing (only insert if tables are empty)
INSERT INTO users (username, password_hash, role) 
SELECT 'admin', '$pbkdf2-sha256$29000$xLj3fs9Zi7E2ZgxhrBUixA$xufNJFzqPmmSAS2pnMraPuQUbE1yWEld2UAYJBmP0aj8', 'Admin'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin');

INSERT INTO users (username, password_hash, role) 
SELECT 'cashier', '$pbkdf2-sha256$29000$rJUyZqyVkpLyHoMwZsy51w$M7F9vPmL0AsyWFgHhXgLWU4P9r6IjHQ1BjoBz6Naz.0', 'Cashier'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'cashier');

INSERT INTO products (name, pack_size, sku, gst_rate, purchase_rate, selling_rate) 
SELECT 'Product A', '1 kg', 'PROD-A-001', 18.00, 80.00, 100.00
WHERE NOT EXISTS (SELECT 1 FROM products WHERE sku = 'PROD-A-001');

INSERT INTO products (name, pack_size, sku, gst_rate, purchase_rate, selling_rate) 
SELECT 'Product B', '500 g', 'PROD-B-002', 12.00, 45.00, 60.00
WHERE NOT EXISTS (SELECT 1 FROM products WHERE sku = 'PROD-B-002');

INSERT INTO products (name, pack_size, sku, gst_rate, purchase_rate, selling_rate) 
SELECT 'Product C', '1 piece', 'PROD-C-003', 5.00, 25.00, 30.00
WHERE NOT EXISTS (SELECT 1 FROM products WHERE sku = 'PROD-C-003');

INSERT INTO inventory (product_id, stock_quantity) 
SELECT 1, 100
WHERE NOT EXISTS (SELECT 1 FROM inventory WHERE product_id = 1);

INSERT INTO inventory (product_id, stock_quantity) 
SELECT 2, 200
WHERE NOT EXISTS (SELECT 1 FROM inventory WHERE product_id = 2);

INSERT INTO inventory (product_id, stock_quantity) 
SELECT 3, 150
WHERE NOT EXISTS (SELECT 1 FROM inventory WHERE product_id = 3);

-- Sample suppliers data
INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, bank_name, bank_account_number, ifsc_code) 
SELECT 'ABC Supplier', '22AAAAA0000A1Z5', '9876543210', 'State Bank of India', '123456789012', 'SBIN0002499'
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_gst_number = '22AAAAA0000A1Z5');

INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, bank_name, bank_account_number, ifsc_code) 
SELECT 'XYZ Distributors', '23BBBBB0000B2Y6', '8765432109', 'ICICI Bank', '234567890123', 'ICIC0001234'
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_gst_number = '23BBBBB0000B2Y6');

INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, bank_name, bank_account_number, ifsc_code) 
SELECT 'PQR Traders', '24CCCCC0000C3X7', '7654321098', 'HDFC Bank', '345678901234', 'HDFC0004567'
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_gst_number = '24CCCCC0000C3X7');

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_purchase_orders_date ON purchase_orders(purchase_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_number ON purchase_orders(purchase_order_number);
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(supplier_name);
CREATE INDEX IF NOT EXISTS idx_purchase_order_items_po_id ON purchase_order_items(purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);

-- Supplier transactions table
CREATE TABLE IF NOT EXISTS supplier_transactions (
    transaction_id SERIAL PRIMARY KEY,
    supplier_id INTEGER REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
    transaction_type VARCHAR NOT NULL CHECK (transaction_type IN ('credit', 'debit')),
    amount DECIMAL(10, 2) NOT NULL,
    previous_balance DECIMAL(10, 2),
    new_balance DECIMAL(10, 2),
    purchase_order_number VARCHAR,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Credit customers table
CREATE TABLE IF NOT EXISTS credit_customers (
    customer_id SERIAL PRIMARY KEY,
    customer_code VARCHAR UNIQUE NOT NULL,
    customer_uuid VARCHAR UNIQUE NOT NULL,
    name VARCHAR NOT NULL,
    mobile VARCHAR NOT NULL,
    email VARCHAR,
    address TEXT,
    invoice_no VARCHAR,
    current_balance DECIMAL(10, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Credit transactions table
CREATE TABLE IF NOT EXISTS credit_transactions (
    transaction_id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES credit_customers(customer_id) ON DELETE CASCADE,
    transaction_type VARCHAR NOT NULL CHECK (transaction_type IN ('credit', 'debit')),
    amount DECIMAL(10, 2) NOT NULL,
    invoice_no VARCHAR,
    note TEXT,
    previous_balance DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add customer_code column if it doesn't exist
ALTER TABLE credit_customers ADD COLUMN IF NOT EXISTS customer_code VARCHAR UNIQUE;

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_credit_customers_mobile ON credit_customers(mobile);
CREATE INDEX IF NOT EXISTS idx_credit_customers_name ON credit_customers(name);
CREATE INDEX IF NOT EXISTS idx_credit_customers_code ON credit_customers(customer_code);
CREATE INDEX IF NOT EXISTS idx_credit_transactions_customer_id ON credit_transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_credit_transactions_date ON credit_transactions(created_at);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at on credit_customers table
DROP TRIGGER IF EXISTS update_credit_customers_updated_at ON credit_customers;
CREATE TRIGGER update_credit_customers_updated_at 
    BEFORE UPDATE ON credit_customers 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Licenses table
CREATE TABLE IF NOT EXISTS licenses (
    id SERIAL PRIMARY KEY,
    license_id VARCHAR UNIQUE NOT NULL,
    license_key TEXT NOT NULL,
    license_type VARCHAR NOT NULL CHECK (license_type IN ('Trial', 'Standard', 'Premium')),
    expiry_date DATE NOT NULL,
    hardware_binding BOOLEAN NOT NULL DEFAULT FALSE,
    activated BOOLEAN NOT NULL DEFAULT FALSE,
    activation_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_licenses_license_id ON licenses(license_id);
CREATE INDEX IF NOT EXISTS idx_licenses_expiry_date ON licenses(expiry_date);
CREATE INDEX IF NOT EXISTS idx_licenses_activated ON licenses(activated);

-- Invoice sequence — atomic counter used by generate_invoice_number() (fixes BUG-011 race condition)
CREATE SEQUENCE IF NOT EXISTS invoice_seq START 1 INCREMENT 1;

-- Login activity table (tracks all login attempts)
CREATE TABLE IF NOT EXISTS login_activity (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    username VARCHAR NOT NULL,
    login_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR,
    user_agent TEXT,
    browser VARCHAR,
    os VARCHAR,
    device_type VARCHAR,
    location_city VARCHAR,
    location_country VARCHAR,
    login_status VARCHAR NOT NULL CHECK (login_status IN ('success', 'failed')),
    failure_reason VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_login_activity_timestamp ON login_activity(login_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_login_activity_username ON login_activity(username);
CREATE INDEX IF NOT EXISTS idx_login_activity_status ON login_activity(login_status);

-- User permissions table (fine-grained page-level access control)
CREATE TABLE IF NOT EXISTS user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    page_id VARCHAR NOT NULL,
    has_access BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, page_id)
);

CREATE INDEX IF NOT EXISTS idx_user_permissions_user_id ON user_permissions(user_id);

-- Registration OTPs — pending user registrations awaiting email verification
CREATE TABLE IF NOT EXISTS registration_otps (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    mobile VARCHAR(20),
    password_hash VARCHAR(512) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reg_otps_email    ON registration_otps(email);
CREATE INDEX IF NOT EXISTS idx_reg_otps_username ON registration_otps(username);

-- Login OTPs — one-time codes for step-up verification on unrecognised devices
CREATE TABLE IF NOT EXISTS login_otps (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    otp_hash   VARCHAR(255) NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    is_used    BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_login_otps_user_id ON login_otps(user_id);

-- Trusted devices — browser/device tokens trusted for 7 days after OTP verification
CREATE TABLE IF NOT EXISTS trusted_devices (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    device_fingerprint VARCHAR(128) NOT NULL,
    browser            VARCHAR(100),
    os                 VARCHAR(100),
    device_type        VARCHAR(50),
    last_ip            VARCHAR(64),
    expires_at         TIMESTAMP NOT NULL,
    last_seen          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, device_fingerprint)
);
-- Migration: add last_ip if upgrading from older schema
ALTER TABLE trusted_devices ADD COLUMN IF NOT EXISTS last_ip VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_trusted_devices_user_fp ON trusted_devices(user_id, device_fingerprint);

-- Password reset OTPs — one-time codes for resetting forgotten passwords
CREATE TABLE IF NOT EXISTS password_reset_otps (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    otp_hash   VARCHAR(255) NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    is_used    BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pw_reset_otps_user_id ON password_reset_otps(user_id);

-- Store settings — key/value config (UPI ID, business info, etc.)
CREATE TABLE IF NOT EXISTS store_settings (
    key        VARCHAR(100) PRIMARY KEY,
    value      TEXT         NOT NULL DEFAULT '',
    updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO store_settings (key, value) VALUES
    ('store_name',        'Nandi Agro'),
    ('store_address',     '#2454, Agasi Main Road, Kolhar - 586210'),
    ('store_phone',       '8660180378'),
    ('store_gst',         '29AASFN9214H1ZP'),
    ('upi_id',            ''),
    ('upi_display_name',  'Nandi Agro')
ON CONFLICT (key) DO NOTHING;

-- Backup logs — history of every backup run
CREATE TABLE IF NOT EXISTS backup_logs (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR NOT NULL,
    file_size_bytes BIGINT  DEFAULT 0,
    backup_type     VARCHAR DEFAULT 'manual',
    destination     VARCHAR DEFAULT 'local',
    status          VARCHAR DEFAULT 'success',
    error_message   TEXT,
    gdrive_file_id  VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── E-Invoice / IRN support ───────────────────────────────────────────────
-- HSN code on products (required for GST e-invoicing)
ALTER TABLE products       ADD COLUMN IF NOT EXISTS hsn_code          VARCHAR(8);

-- IRN fields on sales invoices
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS irn               VARCHAR(64);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS irn_generated_at  TIMESTAMP;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS qr_data           TEXT;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS einvoice_status   VARCHAR(20) DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS idx_sales_invoices_irn ON sales_invoices(irn);

-- Backup settings — single-row config
CREATE TABLE IF NOT EXISTS backup_settings (
    id                  SERIAL PRIMARY KEY,
    enabled             BOOLEAN DEFAULT FALSE,
    schedule_time       VARCHAR DEFAULT '02:00',
    retention_days      INTEGER DEFAULT 30,
    gdrive_enabled      BOOLEAN DEFAULT FALSE,
    gdrive_folder_id    VARCHAR DEFAULT '',
    gdrive_credentials  TEXT    DEFAULT '',
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Knowledge Base (RAG) ──────────────────────────────────────────────────────
-- Requires pgvector extension: https://github.com/pgvector/pgvector
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_documents (
    id          SERIAL        PRIMARY KEY,
    title       VARCHAR(255)  NOT NULL,
    description TEXT          NOT NULL DEFAULT '',
    source_type VARCHAR(20)   NOT NULL DEFAULT 'text',
    file_name   VARCHAR(255),
    char_count  INTEGER       NOT NULL DEFAULT 0,
    chunk_count INTEGER       NOT NULL DEFAULT 0,
    status      VARCHAR(20)   NOT NULL DEFAULT 'ready',
    error_msg   TEXT,
    is_active   BOOLEAN       NOT NULL DEFAULT TRUE,
    created_by  INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id          SERIAL  PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content     TEXT    NOT NULL,
    embedding   vector,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);

-- Add embed_model column to ai_settings (stores the embedding model name, separate from chat model)
ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS embed_model VARCHAR(150) DEFAULT '';
