-- ============================================================
-- TrintzPOS — COMPLETE DATABASE INITIALISATION SCRIPT
-- ============================================================
-- Idempotent: safe to run on a fresh database or re-run on an
-- existing one (uses CREATE TABLE IF NOT EXISTS everywhere).
--
-- Run via psql, pgAdmin, Aiven console, or the in-app
-- Admin → Service → Execute Schema panel.
--
-- IMPORTANT BEFORE GOING LIVE:
--   1. Change the default admin password via User Management.
--   2. Set strong values for SECRET_KEY, DB_PASSWORD in .env / Render env vars.
-- ============================================================


-- ============================================================
-- CORE TABLES (order matters: referenced tables first)
-- ============================================================

-- Users
CREATE TABLE IF NOT EXISTS users (
    user_id       SERIAL PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    role          VARCHAR(20)  NOT NULL CHECK (role IN ('Admin', 'Cashier', 'Super Admin', 'Manager')),
    full_name     VARCHAR(100),
    email         VARCHAR(100),
    mobile        VARCHAR(20),
    totp_secret   VARCHAR,
    totp_enabled  BOOLEAN DEFAULT FALSE,
    totp_required BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Products
CREATE TABLE IF NOT EXISTS products (
    product_id    SERIAL PRIMARY KEY,
    name          VARCHAR NOT NULL,
    pack_size     VARCHAR,
    sku           VARCHAR UNIQUE,
    gst_rate      DECIMAL(5,2)  NOT NULL,
    purchase_rate DECIMAL(10,2),
    selling_rate  DECIMAL(10,2) NOT NULL,
    status        VARCHAR(10) DEFAULT 'Active' CHECK (status IN ('Active', 'Inactive'))
);

-- Inventory
CREATE TABLE IF NOT EXISTS inventory (
    product_id     INTEGER PRIMARY KEY REFERENCES products(product_id),
    stock_quantity INTEGER NOT NULL DEFAULT 0
);

-- Suppliers
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id         SERIAL PRIMARY KEY,
    supplier_name       VARCHAR NOT NULL,
    supplier_gst_number VARCHAR UNIQUE,
    contact_person      VARCHAR,
    email               VARCHAR,
    address             TEXT,
    mobile              VARCHAR,
    bank_name           VARCHAR,
    bank_account_number VARCHAR,
    ifsc_code           VARCHAR,
    current_balance     DECIMAL(10,2) DEFAULT 0.00,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Purchase orders
CREATE TABLE IF NOT EXISTS purchase_orders (
    purchase_order_id     SERIAL PRIMARY KEY,
    supplier_id           INTEGER REFERENCES suppliers(supplier_id),
    supplier_name         VARCHAR,
    supplier_gst_number   VARCHAR,
    purchase_order_number VARCHAR UNIQUE NOT NULL,
    purchase_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id               INTEGER REFERENCES users(user_id),
    total_amount          DECIMAL(10,2) NOT NULL,
    status                VARCHAR(20) DEFAULT 'Completed' CHECK (status IN ('Completed', 'Cancelled')),
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON COLUMN purchase_orders.purchase_order_number IS 'Unique PO number across all purchase orders';

-- Purchase order items (CASCADE so deleting a PO removes its lines)
CREATE TABLE IF NOT EXISTS purchase_order_items (
    item_id           SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(purchase_order_id) ON DELETE CASCADE,
    product_id        INTEGER REFERENCES products(product_id),
    quantity          INTEGER NOT NULL,
    purchase_rate     DECIMAL(10,2) NOT NULL,
    gst_rate          DECIMAL(5,2)  DEFAULT 0.00,
    taxable_value     DECIMAL(10,2) DEFAULT 0.00,
    sgst              DECIMAL(10,2) DEFAULT 0.00,
    cgst              DECIMAL(10,2) DEFAULT 0.00,
    total_amount      DECIMAL(10,2) NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Supplier payment transactions
CREATE TABLE IF NOT EXISTS supplier_transactions (
    transaction_id        SERIAL PRIMARY KEY,
    supplier_id           INTEGER REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
    transaction_type      VARCHAR(10) NOT NULL CHECK (transaction_type IN ('credit', 'debit')),
    amount                DECIMAL(10,2) NOT NULL,
    previous_balance      DECIMAL(10,2),
    new_balance           DECIMAL(10,2),
    purchase_order_number VARCHAR,
    note                  TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sales invoices
CREATE TABLE IF NOT EXISTS sales_invoices (
    invoice_id          SERIAL PRIMARY KEY,
    invoice_number      VARCHAR UNIQUE NOT NULL,
    receipt_number      VARCHAR UNIQUE,
    invoice_date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    customer_name       VARCHAR,
    customer_contact    VARCHAR,
    user_id             INTEGER REFERENCES users(user_id),
    mode_of_payment     VARCHAR,
    upi_transaction_id  VARCHAR,
    customer_mobile     VARCHAR,
    total_amount        DECIMAL(10,2) NOT NULL,
    total_gst           DECIMAL(10,2) NOT NULL,
    discount_percentage DECIMAL(5,2)  DEFAULT 0.00,
    discount_amount     DECIMAL(10,2) DEFAULT 0.00,
    status              VARCHAR(20) DEFAULT 'Completed' CHECK (status IN ('Completed', 'Cancelled'))
);

-- Invoice line items
CREATE TABLE IF NOT EXISTS sales_invoice_items (
    item_id              SERIAL PRIMARY KEY,
    invoice_id           INTEGER REFERENCES sales_invoices(invoice_id),
    product_id           INTEGER REFERENCES products(product_id),
    quantity             INTEGER NOT NULL,
    rate_at_sale         DECIMAL(10,2) NOT NULL,
    gst_rate_at_sale     DECIMAL(5,2)  NOT NULL,
    exclusive_gst_amount DECIMAL(10,2) NOT NULL,
    sgst                 DECIMAL(10,2) NOT NULL,
    cgst                 DECIMAL(10,2) NOT NULL,
    total_line_amount    DECIMAL(10,2) NOT NULL,
    discount_percentage  DECIMAL(5,2)  DEFAULT 0.00
);

-- Atomic invoice number sequence (prevents race-condition duplicates)
CREATE SEQUENCE IF NOT EXISTS invoice_seq START 1 INCREMENT 1;

-- Credit customers
CREATE TABLE IF NOT EXISTS credit_customers (
    customer_id     SERIAL PRIMARY KEY,
    customer_code   VARCHAR UNIQUE NOT NULL,
    customer_uuid   VARCHAR UNIQUE NOT NULL,
    name            VARCHAR NOT NULL,
    mobile          VARCHAR NOT NULL,
    email           VARCHAR,
    address         TEXT,
    invoice_no      VARCHAR,
    current_balance DECIMAL(10,2) DEFAULT 0.00,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Credit transactions
CREATE TABLE IF NOT EXISTS credit_transactions (
    transaction_id   SERIAL PRIMARY KEY,
    customer_id      INTEGER NOT NULL REFERENCES credit_customers(customer_id) ON DELETE CASCADE,
    transaction_type VARCHAR(10) NOT NULL CHECK (transaction_type IN ('credit', 'debit')),
    amount           DECIMAL(10,2) NOT NULL,
    invoice_no       VARCHAR,
    note             TEXT,
    previous_balance DECIMAL(10,2) NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Software licenses
CREATE TABLE IF NOT EXISTS licenses (
    id               SERIAL PRIMARY KEY,
    license_id       VARCHAR UNIQUE NOT NULL,
    license_key      TEXT NOT NULL,
    license_type     VARCHAR(20) NOT NULL CHECK (license_type IN ('Trial', 'Standard', 'Premium')),
    expiry_date      DATE NOT NULL,
    hardware_binding BOOLEAN NOT NULL DEFAULT FALSE,
    activated        BOOLEAN NOT NULL DEFAULT FALSE,
    activation_date  TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Fine-grained page-level access control
CREATE TABLE IF NOT EXISTS user_permissions (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    page_id    VARCHAR(50) NOT NULL,
    has_access BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, page_id)
);

-- Sales returns header (credit notes)
CREATE TABLE IF NOT EXISTS sales_returns (
    return_id               SERIAL PRIMARY KEY,
    return_number           VARCHAR NOT NULL UNIQUE,
    original_invoice_id     INTEGER REFERENCES sales_invoices(invoice_id),
    original_invoice_number VARCHAR NOT NULL,
    return_date             DATE NOT NULL DEFAULT CURRENT_DATE,
    customer_name           VARCHAR,
    customer_mobile         VARCHAR,
    return_reason           VARCHAR NOT NULL,
    refund_method           VARCHAR NOT NULL,
    subtotal                DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_gst               DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_amount            DECIMAL(10,2) NOT NULL DEFAULT 0,
    status                  VARCHAR NOT NULL DEFAULT 'Completed',
    user_id                 INTEGER REFERENCES users(user_id),
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sales return line items
CREATE TABLE IF NOT EXISTS sales_return_items (
    return_item_id       SERIAL PRIMARY KEY,
    return_id            INTEGER NOT NULL REFERENCES sales_returns(return_id) ON DELETE CASCADE,
    original_item_id     INTEGER REFERENCES sales_invoice_items(item_id),
    product_id           INTEGER REFERENCES products(product_id),
    product_name         VARCHAR NOT NULL,
    sku                  VARCHAR,
    pack_size            VARCHAR,
    quantity             INTEGER NOT NULL,
    rate_at_return       DECIMAL(10,2) NOT NULL,
    discount_percentage  DECIMAL(5,2)  DEFAULT 0,
    gst_rate             DECIMAL(5,2)  NOT NULL,
    exclusive_gst_amount DECIMAL(10,2) NOT NULL,
    sgst                 DECIMAL(10,2) NOT NULL,
    cgst                 DECIMAL(10,2) NOT NULL,
    total_line_amount    DECIMAL(10,2) NOT NULL
);

-- Login activity log (SET NULL so logs survive user deletion)
CREATE TABLE IF NOT EXISTS login_activity (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    username         VARCHAR NOT NULL,
    login_timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address       VARCHAR(45),
    user_agent       TEXT,
    browser          VARCHAR(100),
    os               VARCHAR(100),
    device_type      VARCHAR(50),
    location_city    VARCHAR(100),
    location_country VARCHAR(100),
    login_status     VARCHAR(10) NOT NULL CHECK (login_status IN ('success', 'failed')),
    failure_reason   VARCHAR
);


-- ============================================================
-- AUTHENTICATION OTP TABLES
-- ============================================================

-- Pending registrations awaiting email OTP verification
CREATE TABLE IF NOT EXISTS registration_otps (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) NOT NULL,
    username      VARCHAR(255) NOT NULL,
    full_name     VARCHAR(255),
    mobile        VARCHAR(20),
    password_hash VARCHAR(512) NOT NULL,
    otp_hash      VARCHAR(255) NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    is_used       BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at    TIMESTAMP NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Step-up login OTPs for unrecognised devices
CREATE TABLE IF NOT EXISTS login_otps (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    otp_hash   VARCHAR(255) NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    is_used    BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Devices trusted for 7 days after successful OTP verification
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
    UNIQUE (user_id, device_fingerprint)
);

-- Password reset OTPs
CREATE TABLE IF NOT EXISTS password_reset_otps (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    otp_hash   VARCHAR(255) NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    is_used    BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- INDEXES
-- ============================================================

-- Purchase
CREATE INDEX IF NOT EXISTS idx_purchase_orders_date      ON purchase_orders(purchase_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_number    ON purchase_orders(purchase_order_number);
CREATE INDEX IF NOT EXISTS idx_purchase_order_items_po   ON purchase_order_items(purchase_order_id);

-- Products / inventory
CREATE INDEX IF NOT EXISTS idx_products_name             ON products(name);

-- Suppliers
CREATE INDEX IF NOT EXISTS idx_suppliers_name            ON suppliers(supplier_name);

-- Sales
CREATE INDEX IF NOT EXISTS idx_sales_invoices_date       ON sales_invoices(invoice_date DESC);
CREATE INDEX IF NOT EXISTS idx_sales_invoices_user       ON sales_invoices(user_id);

-- Returns
CREATE INDEX IF NOT EXISTS idx_sales_returns_date        ON sales_returns(return_date DESC);
CREATE INDEX IF NOT EXISTS idx_sales_returns_invoice     ON sales_returns(original_invoice_id);
CREATE INDEX IF NOT EXISTS idx_sales_returns_number      ON sales_returns(return_number);
CREATE INDEX IF NOT EXISTS idx_sales_return_items_return ON sales_return_items(return_id);
CREATE INDEX IF NOT EXISTS idx_sales_return_items_orig   ON sales_return_items(original_item_id);

-- Credit
CREATE INDEX IF NOT EXISTS idx_credit_customers_mobile   ON credit_customers(mobile);
CREATE INDEX IF NOT EXISTS idx_credit_customers_name     ON credit_customers(name);
CREATE INDEX IF NOT EXISTS idx_credit_customers_code     ON credit_customers(customer_code);
CREATE INDEX IF NOT EXISTS idx_credit_txn_customer       ON credit_transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_credit_txn_date           ON credit_transactions(created_at);

-- Licenses
CREATE INDEX IF NOT EXISTS idx_licenses_id               ON licenses(license_id);
CREATE INDEX IF NOT EXISTS idx_licenses_expiry           ON licenses(expiry_date);
CREATE INDEX IF NOT EXISTS idx_licenses_activated        ON licenses(activated);

-- Permissions
CREATE INDEX IF NOT EXISTS idx_user_permissions_user     ON user_permissions(user_id);

-- Login activity
CREATE INDEX IF NOT EXISTS idx_login_activity_ts         ON login_activity(login_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_login_activity_username   ON login_activity(username);
CREATE INDEX IF NOT EXISTS idx_login_activity_status     ON login_activity(login_status);

-- OTP tables
CREATE INDEX IF NOT EXISTS idx_reg_otps_email            ON registration_otps(email);
CREATE INDEX IF NOT EXISTS idx_reg_otps_username         ON registration_otps(username);
CREATE INDEX IF NOT EXISTS idx_login_otps_user           ON login_otps(user_id);
CREATE INDEX IF NOT EXISTS idx_trusted_devices_user_fp   ON trusted_devices(user_id, device_fingerprint);
CREATE INDEX IF NOT EXISTS idx_pw_reset_otps_user        ON password_reset_otps(user_id);


-- ============================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_credit_customers_updated_at ON credit_customers;
CREATE TRIGGER update_credit_customers_updated_at
    BEFORE UPDATE ON credit_customers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- DEFAULT SEED DATA
-- ============================================================
-- DEFAULT LOGIN  (created on a fresh database)
--   Username : admin    / Password : admin123   (Super Admin)
--   Username : cashier  / Password : cashier123 (Cashier)
-- ⚠️  CHANGE THESE PASSWORDS immediately after first login.
-- ============================================================

INSERT INTO users (username, password_hash, role, full_name, email, mobile)
SELECT 'admin',
       '$pbkdf2-sha256$29000$GmOsde6dEwLgfI9R6r03xg$KKvsCErFShayM8D3gtNfNDQeSrMeFKpl1qvbQg0Zf5o',
       'Super Admin', 'System Administrator', '', '9876543210'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin');

UPDATE users SET role = 'Super Admin' WHERE username = 'admin' AND role <> 'Super Admin';

INSERT INTO users (username, password_hash, role, full_name, email, mobile)
SELECT 'cashier',
       '$pbkdf2-sha256$29000$8d5bS2lt7R3j3BvDWOt9rw$XLfECjzY7JkOzcRF4oZaQMTHelxsfP8AuN8fWN9AtbE',
       'Cashier', 'Default Cashier', '', '8765432109'
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
SELECT p.product_id, 100 FROM products p
WHERE p.sku = 'PROD-A-001'
  AND NOT EXISTS (SELECT 1 FROM inventory i WHERE i.product_id = p.product_id);

INSERT INTO inventory (product_id, stock_quantity)
SELECT p.product_id, 200 FROM products p
WHERE p.sku = 'PROD-B-002'
  AND NOT EXISTS (SELECT 1 FROM inventory i WHERE i.product_id = p.product_id);

INSERT INTO inventory (product_id, stock_quantity)
SELECT p.product_id, 150 FROM products p
WHERE p.sku = 'PROD-C-003'
  AND NOT EXISTS (SELECT 1 FROM inventory i WHERE i.product_id = p.product_id);

INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, bank_name, bank_account_number, ifsc_code)
SELECT 'ABC Supplier', '22AAAAA0000A1Z5', '9876543210', 'State Bank of India', '123456789012', 'SBIN0002499'
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_gst_number = '22AAAAA0000A1Z5');

INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, bank_name, bank_account_number, ifsc_code)
SELECT 'XYZ Distributors', '23BBBBB0000B2Y6', '8765432109', 'ICICI Bank', '234567890123', 'ICIC0001234'
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_gst_number = '23BBBBB0000B2Y6');

INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, bank_name, bank_account_number, ifsc_code)
SELECT 'PQR Traders', '24CCCCC0000C3X7', '7654321098', 'HDFC Bank', '345678901234', 'HDFC0004567'
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_gst_number = '24CCCCC0000C3X7');

-- Store settings seed (UPI ID, business info)
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


-- ============================================================
-- SAFE MIGRATIONS (for existing databases — all idempotent)
-- ============================================================

-- TOTP columns (older installs may not have them)
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret   VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled  BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_required BOOLEAN DEFAULT FALSE;

-- Returns status column
ALTER TABLE sales_returns ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'Completed';

-- Invoice cancellation audit trail
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_by  INTEGER REFERENCES users(user_id);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_at  TIMESTAMP;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancel_reason TEXT;

-- Barcode on products
ALTER TABLE products ADD COLUMN IF NOT EXISTS barcode VARCHAR UNIQUE;

-- HSN code + e-invoice fields
ALTER TABLE products       ADD COLUMN IF NOT EXISTS hsn_code         VARCHAR(8);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS irn              VARCHAR(64);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS irn_generated_at TIMESTAMP;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS qr_data          TEXT;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS einvoice_status  VARCHAR(20) DEFAULT 'pending';
CREATE INDEX IF NOT EXISTS idx_sales_invoices_irn ON sales_invoices(irn);

-- last_ip on trusted_devices
ALTER TABLE trusted_devices ADD COLUMN IF NOT EXISTS last_ip VARCHAR(64);

-- EULA acceptance tracking
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at  TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_ip  VARCHAR(45);
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version      VARCHAR(10) DEFAULT '1.0';


-- ============================================================
-- SETTINGS / BACKUP / AI TABLES
-- ============================================================

-- Backup logs
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

-- Backup settings
CREATE TABLE IF NOT EXISTS backup_settings (
    id                 SERIAL PRIMARY KEY,
    enabled            BOOLEAN DEFAULT FALSE,
    schedule_time      VARCHAR DEFAULT '02:00',
    retention_days     INTEGER DEFAULT 30,
    gdrive_enabled     BOOLEAN DEFAULT FALSE,
    gdrive_folder_id   VARCHAR DEFAULT '',
    gdrive_credentials TEXT    DEFAULT '',
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE backup_settings ADD COLUMN IF NOT EXISTS oauth_enabled    BOOLEAN DEFAULT FALSE;
ALTER TABLE backup_settings ADD COLUMN IF NOT EXISTS oauth_tokens     TEXT;
ALTER TABLE backup_settings ADD COLUMN IF NOT EXISTS oauth_user_email VARCHAR(255);

-- AI settings
CREATE TABLE IF NOT EXISTS ai_settings (
    id           SERIAL PRIMARY KEY,
    provider     VARCHAR(32)  NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    api_key      TEXT DEFAULT '',
    api_base_url VARCHAR(500) DEFAULT '',
    model        VARCHAR(150) NOT NULL,
    is_active    BOOLEAN DEFAULT FALSE,
    extra_config JSONB DEFAULT '{}',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS embed_model VARCHAR(150) DEFAULT '';


-- ============================================================
-- KNOWLEDGE BASE (RAG / pgvector) — optional
-- ============================================================
DO $kb$
BEGIN
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
        content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
        embedding   vector,
        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);
    CREATE INDEX IF NOT EXISTS idx_kb_chunks_fts      ON kb_chunks USING gin(content_tsv);

    ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS content_tsv
        tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Knowledge-base (pgvector) setup skipped: %', SQLERRM;
END
$kb$;

-- ============================================================
-- AI TOKEN USAGE TRACKING
-- ============================================================
CREATE TABLE IF NOT EXISTS ai_token_usage (
    id              SERIAL       PRIMARY KEY,
    called_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id         INTEGER      REFERENCES users(user_id) ON DELETE SET NULL,
    username        VARCHAR(100),
    provider        VARCHAR(50)  NOT NULL DEFAULT '',
    model           VARCHAR(150) NOT NULL DEFAULT '',
    feature         VARCHAR(100) NOT NULL DEFAULT 'chat',
    prompt_tokens   INTEGER      NOT NULL DEFAULT 0,
    output_tokens   INTEGER      NOT NULL DEFAULT 0,
    total_tokens    INTEGER      NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ai_token_usage_called_at ON ai_token_usage(called_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_token_usage_user      ON ai_token_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_token_usage_provider  ON ai_token_usage(provider);

-- ============================================================
-- SQL QUERY AUDIT (Query-to-DB tool — who ran what, when, outcome)
-- ============================================================
CREATE TABLE IF NOT EXISTS sql_query_audit (
    id          SERIAL       PRIMARY KEY,
    run_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id     INTEGER,
    username    VARCHAR(100),
    query_text  TEXT         NOT NULL,
    is_select   BOOLEAN      NOT NULL DEFAULT TRUE,
    success     BOOLEAN      NOT NULL DEFAULT FALSE,
    row_count   INTEGER,
    error_msg   TEXT,
    ip_address  VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_sql_audit_run_at ON sql_query_audit(run_at DESC);
