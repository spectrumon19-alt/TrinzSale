-- Migration: Add constraint to prevent negative inventory
-- Purpose: Ensure stock_quantity can never go below 0 at the database level
-- This provides ultimate protection against negative inventory from any source

-- Add CHECK constraint to inventory table
ALTER TABLE inventory
ADD CONSTRAINT chk_inventory_non_negative
CHECK (stock_quantity >= 0);

-- This constraint ensures:
-- 1. No sales endpoint can create negative inventory
-- 2. No manual admin updates can create negative inventory
-- 3. No bulk imports can create negative inventory
-- 4. Even if application code is bypassed, database prevents it

-- Verify constraint was added:
-- SELECT constraint_name FROM information_schema.table_constraints
-- WHERE table_name='inventory' AND constraint_type='CHECK';

-- Expected result:
-- chk_inventory_non_negative

-- To test:
-- UPDATE inventory SET stock_quantity = -1 WHERE product_id = 1;
-- Result: ERROR: new row for relation "inventory" violates check constraint "chk_inventory_non_negative"
