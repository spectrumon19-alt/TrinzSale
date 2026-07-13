import logging
from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, cashier_required, admin_required
from psycopg2.extras import RealDictCursor
from datetime import datetime

logger = logging.getLogger(__name__)

sales_bp = Blueprint('sales', __name__)

def calculate_invoice_item(quantity, selling_rate, gst_rate, rebate_amount=0):
    """Calculate invoice item details based on quantity, rate, GST and a flat rebate.

    rebate_amount is a flat ₹ amount subtracted from the line total (qty × rate),
    BEFORE GST is split out (GST-inclusive line total is reduced, then taxable and
    GST are recomputed on the reduced figure). It is clamped to [0, line total].
    """
    try:
        # Validate inputs
        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        if selling_rate < 0:
            raise ValueError("Selling rate cannot be negative")
        if gst_rate < 0 or gst_rate > 100:
            raise ValueError("GST rate must be between 0 and 100")
        if rebate_amount < 0:
            raise ValueError("Rebate amount cannot be negative")

        # S.Amount (Total Line Amount) = Quantity * Selling Rate
        total_line_amount = quantity * selling_rate

        # Apply flat rebate if any (clamp so a rebate can't drive the line negative)
        if rebate_amount > 0:
            rebate_amount = min(rebate_amount, total_line_amount)
            total_line_amount = total_line_amount - rebate_amount

        # S.Exclusive GST (Taxable Value) = S.Amount / (1 + (GST Rate / 100))
        exclusive_gst_amount = total_line_amount / (1 + (gst_rate / 100))
        
        # Total GST = S.Amount - S.Exclusive GST
        total_gst = total_line_amount - exclusive_gst_amount
        
        # SGST = Total GST / 2
        sgst = total_gst / 2
        
        # CGST = Total GST / 2
        cgst = total_gst / 2
        
        return {
            'total_line_amount': round(total_line_amount, 2),
            'exclusive_gst_amount': round(exclusive_gst_amount, 2),
            'total_gst': round(total_gst, 2),
            'sgst': round(sgst, 2),
            'cgst': round(cgst, 2)
        }
    except Exception as e:
        raise ValueError(f"Error calculating invoice item: {str(e)}")

def generate_invoice_number(conn, cur):
    """
    Generate invoice number in format D{DD}P{DDD}{YYMMDD}.
    BUG-011 fixed: uses nextval('invoice_seq') — atomic DB sequence,
    no race condition under concurrent requests.
    D counter = ((seq-1) // 100) + 1, P counter = ((seq-1) % 100) + 1
    """
    date_str = datetime.now().strftime('%y%m%d')
    cur.execute("SELECT nextval('invoice_seq')")
    seq = cur.fetchone()['nextval']
    d_val = ((seq - 1) // 100) + 1
    p_val = ((seq - 1) % 100) + 1
    return f"D{d_val:02d}P{p_val:03d}{date_str}"

def generate_receipt_number(conn, cur):
    """Generate receipt number in format RYYYYMMDDseq with daily reset (e.g. R20260617005)"""
    # Get current date
    now = datetime.now()
    full_date_str = now.strftime('%Y%m%d')  # YYYYMMDD format

    # Find all receipt numbers for today. Match both the current format (RYYYYMMDDseq)
    # and the legacy format (R_YYYYMMDD_seq) so the daily sequence stays correct.
    cur.execute(
        "SELECT receipt_number FROM sales_invoices "
        "WHERE receipt_number IS NOT NULL AND (receipt_number LIKE %s OR receipt_number LIKE %s)",
        (f'R{full_date_str}%', f'R_{full_date_str}_%'))
    today_receipts = cur.fetchall()

    # Extract sequence numbers from today's receipts
    max_seq = 0
    for row in today_receipts:
        receipt = row['receipt_number']
        if not receipt:
            continue
        seq_part = None
        if receipt.startswith(f'R_{full_date_str}_'):
            # Legacy format: sequence after the last underscore
            seq_part = receipt.split('_')[-1]
        elif receipt.startswith(f'R{full_date_str}'):
            # Current format: sequence is everything after RYYYYMMDD
            seq_part = receipt[len(f'R{full_date_str}'):]
        if seq_part is None:
            continue
        try:
            seq_num = int(seq_part)
            if seq_num > max_seq:
                max_seq = seq_num
        except (ValueError, IndexError):
            # Skip invalid formats
            continue

    # Increment sequence number
    next_seq = max_seq + 1

    # Format with leading zeros (3 digits)
    seq_str = str(next_seq).zfill(3)

    return f'R{full_date_str}{seq_str}'

@sales_bp.route('/customers/search', methods=['GET'])
@token_required
def search_customers(payload):
    """Search registered credit customers by name or mobile."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([]), 200

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        like = f'%{q}%'
        cur.execute("""
            SELECT
                name    AS customer_name,
                mobile  AS customer_mobile,
                ''      AS customer_contact
            FROM credit_customers
            WHERE (
                (name   IS NOT NULL AND name   <> '' AND name   ILIKE %s)
                OR (mobile IS NOT NULL AND mobile <> '' AND mobile ILIKE %s)
            )
            ORDER BY name
            LIMIT 8
        """, (like, like))
        return jsonify(cur.fetchall()), 200
    except Exception as e:
        logger.exception("Customer search error")
        return jsonify([]), 200
    finally:
        cur.close()
        release_db_connection(conn)


@sales_bp.route('/sales', methods=['POST'])
@cashier_required
def create_sale(payload):
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'message': 'No data provided'}), 400
        
        user_id = payload.get('user_id')
        discount_percentage = data.get('discount_percentage', 0)
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # BUG-011 fixed: generate_invoice_number now uses nextval('invoice_seq')
            invoice_number = generate_invoice_number(conn, cur)
            receipt_number = generate_receipt_number(conn, cur)

            if not data.get('items'):
                return jsonify({'message': 'At least one item is required'}), 400

            invoice_date = data.get('invoice_date') or None

            # COALESCE so an explicit date is honoured, but when none is provided
            # the invoice gets the current timestamp. Inserting a bare NULL would
            # override the column DEFAULT and leave invoice_date NULL, which makes
            # the sale vanish from every date-filtered report and the dashboard.
            cur.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, receipt_number, invoice_date, customer_name, customer_contact,
                    user_id, mode_of_payment, upi_transaction_id, customer_mobile,
                    total_amount, total_gst, discount_percentage, status
                ) VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s, %s, %s, 0, 0, %s, 'Completed')
                RETURNING invoice_id, invoice_number, receipt_number, invoice_date
            """, (
                invoice_number, receipt_number, invoice_date,
                data.get('customer_name') or '',
                data.get('customer_contact') or '',
                user_id,
                data.get('mode_of_payment') or 'Cash',
                data.get('upi_transaction_id') or None,
                data.get('customer_mobile') or None,
                discount_percentage,
            ))

            invoice = cur.fetchone()
            if not invoice:
                raise Exception('Failed to create invoice')
            invoice_id = invoice['invoice_id']
            
            # Process each item
            items = data.get('items', [])
            total_invoice_amount = 0
            total_invoice_gst = 0
            total_discount_amount = 0

            # ── Bill-level discount factor (whole-invoice %) ───────────────────
            # Applied per item BEFORE insert so that the item rows (which GSTR-1,
            # returns, and itemized reports read) always reconcile with the
            # invoice-level totals. Scaling every line's taxable/GST by the same
            # (1 - disc%) factor is GST-correct across mixed rates because each
            # slab's taxable and GST scale together.
            try:
                bill_disc_pct = float(discount_percentage or 0)
            except (TypeError, ValueError):
                bill_disc_pct = 0.0
            bill_disc_pct = max(0.0, min(bill_disc_pct, 100.0))
            bill_keep = 1 - (bill_disc_pct / 100.0)
            total_bill_discount_value = 0.0

            # Check stock availability for all items first
            for i, item in enumerate(items):
                product_id = item.get('product_id')
                quantity = item.get('quantity')

                if not product_id or not quantity:
                    raise Exception(f"Item {i+1} is missing required fields (product_id or quantity)")
                
                # Check current stock - join with products to ensure product exists
                cur.execute("""
                    SELECT COALESCE(i.stock_quantity, 0) as stock_quantity, p.name 
                    FROM products p
                    LEFT JOIN inventory i ON p.product_id = i.product_id
                    WHERE p.product_id = %s
                """, (product_id,))
                
                product_result = cur.fetchone()
                if not product_result:
                    raise Exception(f"Product with ID {product_id} does not exist")
                
                current_stock = product_result['stock_quantity'] or 0
                product_name = product_result['name']
                
                if current_stock < quantity:
                    raise Exception(f"INSUFFICIENT_STOCK: Product '{product_name}' has only {current_stock} units in stock, but {quantity} units were requested. Please reduce the quantity or select a different product.")
            
            # Process each item (now that we know we have enough stock)
            for i, item in enumerate(items):
                product_id = item.get('product_id')
                quantity = item.get('quantity')
                # Per-line flat rebate (₹). Accept legacy 'discount' key as 0-safe fallback.
                item_rebate = float(item.get('rebate', 0) or 0)

                # Get product details
                cur.execute("""
                    SELECT selling_rate, gst_rate FROM products WHERE product_id = %s
                """, (product_id,))

                product = cur.fetchone()
                if not product:
                    raise Exception(f"Product with ID {product_id} not found")

                # Use selling_rate from request if provided (edited rate), otherwise use database value
                selling_rate = float(item.get('selling_rate', product['selling_rate']))
                gst_rate = float(product['gst_rate'])

                # Clamp the rebate so it can't exceed this line's gross total
                item_rebate = max(0.0, min(item_rebate, quantity * selling_rate))

                # Calculate item details with the flat rebate applied
                calc = calculate_invoice_item(quantity, selling_rate, gst_rate, item_rebate)

                # Apply the whole-bill discount to THIS line so stored item rows
                # reconcile with invoice totals (GSTR-1 / returns / reports read
                # these rows). Track the ₹ taken off for discount_amount reporting.
                line_taxable = round(calc['exclusive_gst_amount'] * bill_keep, 2)
                line_gst     = round(calc['total_gst'] * bill_keep, 2)
                line_sgst    = round(line_gst / 2, 2)
                line_cgst    = round(line_gst - line_sgst, 2)
                line_total   = round(line_taxable + line_gst, 2)
                total_bill_discount_value += round(
                    (calc['exclusive_gst_amount'] + calc['total_gst']) * (1 - bill_keep), 2)

                # Insert invoice item
                cur.execute("""
                    INSERT INTO sales_invoice_items (
                        invoice_id, product_id, quantity, rate_at_sale,
                        gst_rate_at_sale, exclusive_gst_amount, sgst, cgst, total_line_amount, rebate_amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    invoice_id, product_id, quantity, selling_rate,
                    gst_rate, line_taxable, line_sgst,
                    line_cgst, line_total, item_rebate
                ))

                # BUG-006 fixed: total_amount stores ex-GST subtotal so that
                # grand_total = total_amount + total_gst is correct (not double-counted).
                total_invoice_amount += line_taxable
                total_invoice_gst += line_gst

                # Track total per-line rebate given (for reporting / discount_amount)
                total_discount_amount += item_rebate

                # Update inventory (decrement stock)
                cur.execute("""
                    UPDATE inventory 
                    SET stock_quantity = stock_quantity - %s 
                    WHERE product_id = %s
                """, (quantity, product_id))
                
                # Check if update was successful
                if cur.rowcount == 0:
                    # If no rows were updated, it means there's no inventory record for this product
                    # Let's check if the product exists
                    cur.execute("SELECT 1 FROM products WHERE product_id = %s", (product_id,))
                    product_exists = cur.fetchone()
                    
                    if not product_exists:
                        raise Exception(f"Product with ID {product_id} does not exist")
                    
                    # If product exists but no inventory record, create one with 0 stock and then update
                    try:
                        cur.execute("""
                            INSERT INTO inventory (product_id, stock_quantity) 
                            VALUES (%s, %s)
                        """, (product_id, 0))  # Start with 0 stock
                        
                        # Now update the inventory
                        cur.execute("""
                            UPDATE inventory 
                            SET stock_quantity = stock_quantity - %s 
                            WHERE product_id = %s
                        """, (quantity, product_id))
                    except Exception as insert_error:
                        # If insert fails due to constraint, try update again
                        cur.execute("""
                            UPDATE inventory 
                            SET stock_quantity = stock_quantity - %s 
                            WHERE product_id = %s
                        """, (quantity, product_id))
                        
                        if cur.rowcount == 0:
                            raise Exception(f"Failed to update inventory for product {product_id}. No inventory record found and unable to create one.")
            
            # The whole-bill discount was already applied per line above, so the
            # accumulated totals are net. Fold the bill-discount ₹ value into
            # discount_amount (which now = line rebates + bill-discount value).
            total_invoice_amount = round(total_invoice_amount, 2)
            total_invoice_gst = round(total_invoice_gst, 2)
            total_discount_amount = round(total_discount_amount + total_bill_discount_value, 2)

            # Update invoice with calculated totals
            cur.execute("""
                UPDATE sales_invoices
                SET total_amount = %s, total_gst = %s, discount_amount = %s
                WHERE invoice_id = %s
            """, (total_invoice_amount, total_invoice_gst, total_discount_amount, invoice_id))

            # Tally-style: a credit sale debits the customer (Debtor) ledger so the
            # receivable goes up automatically. Customer is a debtor → 'debit' entry,
            # which decreases current_balance (negative = receivable per credit module).
            # Non-fatal: if no matching credit customer is found, the sale still saves
            # and we surface a warning instead of blocking the cashier.
            credit_post_warning = None
            if (data.get('mode_of_payment') or '').strip().lower() == 'credit':
                grand_total = round(float(total_invoice_amount) + float(total_invoice_gst), 2)
                cust_mobile = (data.get('customer_mobile') or data.get('customer_contact') or '').strip()
                try:
                    cc = None
                    if cust_mobile:
                        cur.execute("""
                            SELECT customer_id, current_balance
                            FROM credit_customers
                            WHERE mobile = %s
                            ORDER BY customer_id
                            LIMIT 1
                        """, (cust_mobile,))
                        cc = cur.fetchone()
                    if cc and grand_total > 0:
                        prev_balance = float(cc['current_balance'] or 0)
                        new_balance = round(prev_balance - grand_total, 2)  # debit lowers balance
                        cur.execute("""
                            INSERT INTO credit_transactions (
                                customer_id, transaction_type, amount, invoice_no, note, previous_balance
                            ) VALUES (%s, 'debit', %s, %s, %s, %s)
                        """, (cc['customer_id'], grand_total, invoice_number,
                              'Auto-posted from credit sale', prev_balance))
                        cur.execute("""
                            UPDATE credit_customers
                            SET current_balance = %s
                            WHERE customer_id = %s
                        """, (new_balance, cc['customer_id']))
                    else:
                        credit_post_warning = (
                            "Sale marked 'Credit' but no matching credit customer was found"
                            + (f" for mobile {cust_mobile}." if cust_mobile else " (no customer mobile provided).")
                            + " The customer's receivable was NOT updated — add them in Credit Management."
                        )
                except Exception as _credit_err:
                    logger.warning("Credit-ledger auto-post skipped for invoice %s: %s",
                                   invoice_number, _credit_err)
                    credit_post_warning = ("Sale saved, but the credit ledger could not be "
                                           "updated automatically. Adjust the customer's balance manually.")

            # Commit transaction
            conn.commit()

            # Generate IRN + QR (non-fatal — invoice already saved)
            try:
                from routes.irn import attach_irn as _attach_irn
                cur.execute('SELECT key, value FROM store_settings')
                _store = {r['key']: r['value'] for r in cur.fetchall()}
                irn_result = _attach_irn(invoice_id, conn, cur, _store)
                conn.commit()
            except Exception as _irn_err:
                logger.warning('IRN generation skipped: %s', _irn_err)
                irn_result = {}

            # Fetch the complete invoice with items
            cur.execute("""
                SELECT
                    si.invoice_id,
                    si.invoice_number,
                    si.receipt_number,
                    si.invoice_date,
                    si.customer_name,
                    si.customer_contact,
                    si.user_id,
                    si.mode_of_payment,
                    si.upi_transaction_id,
                    si.customer_mobile,
                    si.total_amount,
                    si.total_gst,
                    si.discount_percentage,
                    si.discount_amount,
                    si.status,
                    si.irn,
                    si.qr_data,
                    si.einvoice_status,
                    u.username as created_by,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'item_id', sii.item_id,
                                'invoice_id', sii.invoice_id,
                                'product_id', sii.product_id,
                                'product_name', p.name,
                                'pack_size', p.pack_size,
                                'hsn_code', p.hsn_code,
                                'quantity', sii.quantity,
                                'rate_at_sale', sii.rate_at_sale,
                                'gst_rate_at_sale', sii.gst_rate_at_sale,
                                'exclusive_gst_amount', sii.exclusive_gst_amount,
                                'sgst', sii.sgst,
                                'cgst', sii.cgst,
                                'total_line_amount', sii.total_line_amount,
                                'discount_percentage', sii.discount_percentage,
                                'rebate_amount', sii.rebate_amount
                            )
                        ) FILTER (WHERE sii.item_id IS NOT NULL),
                        '[]'
                    ) as items
                FROM sales_invoices si
                JOIN users u ON si.user_id = u.user_id
                LEFT JOIN sales_invoice_items sii ON si.invoice_id = sii.invoice_id
                LEFT JOIN products p ON sii.product_id = p.product_id
                WHERE si.invoice_id = %s
                GROUP BY si.invoice_id, si.invoice_number, si.receipt_number, si.invoice_date,
                         si.customer_name, si.customer_contact, si.user_id, si.mode_of_payment,
                         si.upi_transaction_id, si.customer_mobile, si.total_amount, si.total_gst,
                         si.discount_percentage, si.discount_amount, si.status,
                         si.irn, si.qr_data, si.einvoice_status, u.username
            """, (invoice_id,))
            
            result = cur.fetchone()
            
            # Add calculated fields for the frontend and ensure they are floats
            if result:
                # Grand total should include GST (total_amount + total_gst)
                result['grand_total'] = (float(result['total_amount']) if result['total_amount'] else 0.0) + (float(result['total_gst']) if result['total_gst'] else 0.0)
                result['discount_amount'] = float(result['discount_amount']) if result['discount_amount'] else 0.0
                result['total_gst'] = float(result['total_gst']) if result['total_gst'] else 0.0
                result['total_amount'] = float(result['total_amount']) if result['total_amount'] else 0.0
                result['discount_percentage'] = float(result['discount_percentage']) if result['discount_percentage'] else 0.0
                # Add receipt number to the result
                result['receipt_number'] = result['receipt_number'] if result.get('receipt_number') else None
                if credit_post_warning:
                    result['warning'] = credit_post_warning

            return jsonify(result), 201
        except Exception as e:
            if conn:
                conn.rollback()
            # BUG-010 fixed: log server-side only, never send traceback to client
            logger.exception("Sales creation error")
            error_message = str(e)
            if "INSUFFICIENT_STOCK" in error_message or "No stock in inventory" in error_message:
                return jsonify({'message': error_message}), 400
            return jsonify({'message': 'Failed to create sale'}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
    except Exception as e:
        logger.exception("Sales route error")
        return jsonify({'message': 'Failed to process sale request'}), 500

@sales_bp.route('/sales/<int:invoice_id>/cancel', methods=['PUT'])
@admin_required
def cancel_sale(payload, invoice_id):
    """
    Cancel a sales invoice professionally and atomically:

      1. Lock the invoice row (FOR UPDATE) so two concurrent cancels cannot
         both pass the status check and restore stock twice.
      2. Refuse to cancel if the invoice has returns recorded against it —
         those returns already restored stock and refunded the customer, so a
         blind cancel would double-restore inventory and double-refund. The
         operator must reverse the returns first (or the return already handles it).
      3. Restore inventory by the full original quantity (safe now that returns
         are excluded).
      4. Stamp the cancellation audit trail (who / when / why).
      5. Set status = 'Cancelled' (rows are kept for history — never deleted).
      6. Warn — but do not fail — if a credit-ledger entry references this
         invoice, since that manual ledger must be adjusted separately.
    """
    user_id = payload.get('user_id')
    data = request.get_json(silent=True) or {}
    cancel_reason = (data.get('reason') or data.get('cancel_reason') or '').strip() or None

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 1. Lock the invoice row for the duration of the transaction
        cur.execute("""
            SELECT invoice_id, invoice_number, status
            FROM sales_invoices
            WHERE invoice_id = %s
            FOR UPDATE
        """, (invoice_id,))
        invoice = cur.fetchone()

        if not invoice:
            return jsonify({'message': 'Invoice not found'}), 404
        if invoice['status'] == 'Cancelled':
            return jsonify({'message': 'Invoice is already cancelled'}), 400

        # 2. Block if any returns exist against this invoice
        cur.execute("""
            SELECT COUNT(*) AS return_count
            FROM sales_returns
            WHERE original_invoice_id = %s AND status = 'Completed'
        """, (invoice_id,))
        return_count = int((cur.fetchone() or {}).get('return_count', 0))
        if return_count > 0:
            return jsonify({
                'message': 'Cannot cancel an invoice that has returns recorded against it. '
                           'Reverse the return(s) first, then cancel.',
                'return_count': return_count
            }), 409

        # 3. Restore inventory for each line (original quantity)
        cur.execute("""
            SELECT product_id, quantity
            FROM sales_invoice_items
            WHERE invoice_id = %s
        """, (invoice_id,))
        items = cur.fetchall()

        for item in items:
            cur.execute("""
                UPDATE inventory
                SET stock_quantity = stock_quantity + %s
                WHERE product_id = %s
            """, (item['quantity'], item['product_id']))

            if cur.rowcount == 0:
                # A sold product must already have an inventory row. If it does not,
                # the product was deleted or data is inconsistent — surface it rather
                # than silently papering over it.
                cur.execute("SELECT 1 FROM products WHERE product_id = %s", (item['product_id'],))
                if not cur.fetchone():
                    raise Exception(f"Product {item['product_id']} no longer exists; "
                                    f"cannot restore inventory. Cancellation aborted.")
                # Product exists but had no inventory row — create it with the restored qty.
                cur.execute("""
                    INSERT INTO inventory (product_id, stock_quantity)
                    VALUES (%s, %s)
                """, (item['product_id'], item['quantity']))

        # 4 + 5. Mark cancelled with audit trail
        cur.execute("""
            UPDATE sales_invoices
            SET status        = 'Cancelled',
                cancelled_by  = %s,
                cancelled_at  = CURRENT_TIMESTAMP,
                cancel_reason = %s
            WHERE invoice_id = %s
        """, (user_id, cancel_reason, invoice_id))

        # 6. Reverse any auto-posted credit-ledger debit for this invoice (Tally:
        #    cancelling a credit sale reverses the debtor charge). We post an
        #    offsetting 'credit' entry per linked 'debit' and restore the balance.
        #    Non-fatal: if the ledger isn't present we just skip with a warning.
        credit_warning = None
        try:
            cur.execute("""
                SELECT transaction_id, customer_id, amount
                FROM credit_transactions
                WHERE invoice_no = %s AND transaction_type = 'debit'
            """, (invoice['invoice_number'],))
            posted = cur.fetchall() or []
            reversed_count = 0
            for txn in posted:
                cur.execute("""
                    SELECT current_balance FROM credit_customers WHERE customer_id = %s
                """, (txn['customer_id'],))
                row = cur.fetchone()
                if not row:
                    continue
                prev_balance = float(row['current_balance'] or 0)
                amt = float(txn['amount'] or 0)
                new_balance = round(prev_balance + amt, 2)  # credit reverses the debit
                cur.execute("""
                    INSERT INTO credit_transactions (
                        customer_id, transaction_type, amount, invoice_no, note, previous_balance
                    ) VALUES (%s, 'credit', %s, %s, %s, %s)
                """, (txn['customer_id'], amt, invoice['invoice_number'],
                      'Reversal of cancelled credit sale', prev_balance))
                cur.execute("""
                    UPDATE credit_customers SET current_balance = %s WHERE customer_id = %s
                """, (new_balance, txn['customer_id']))
                reversed_count += 1
            if reversed_count:
                credit_warning = (f"Reversed {reversed_count} credit-ledger entry(ies); "
                                  f"the customer's receivable was restored automatically.")
        except Exception as _rev_err:
            # credit_transactions may not exist in every deployment — ignore.
            logger.warning("Credit-ledger reversal skipped for invoice %s: %s",
                           invoice['invoice_number'], _rev_err)
            credit_warning = None

        conn.commit()
        logger.info("Invoice %s (id=%s) cancelled by user %s. Reason: %s",
                    invoice['invoice_number'], invoice_id, user_id, cancel_reason or '(none)')

        resp = {
            'message': 'Invoice cancelled successfully',
            'invoice_number': invoice['invoice_number'],
            'items_restored': len(items),
        }
        if credit_warning:
            resp['warning'] = credit_warning
        return jsonify(resp), 200

    except Exception as e:
        if conn:
            conn.rollback()
        logger.exception("Cancel sale error (invoice_id=%s)", invoice_id)
        return jsonify({'message': 'Failed to cancel sale', 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)


@sales_bp.route('/sales/<int:invoice_id>', methods=['GET'])
@token_required
def get_invoice_by_id(payload, invoice_id):
    """Get a specific invoice by ID"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Fetch the complete invoice with items
        cur.execute("""
            SELECT 
                si.invoice_id,
                si.invoice_number,
                si.receipt_number,
                si.invoice_date,
                si.customer_name,
                si.customer_contact,
                si.user_id,
                si.mode_of_payment,
                si.upi_transaction_id,
                si.customer_mobile,
                si.total_amount,
                si.total_gst,
                si.discount_percentage,
                si.discount_amount,
                si.status,
                u.username as created_by,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'item_id', sii.item_id,
                            'invoice_id', sii.invoice_id,
                            'product_id', sii.product_id,
                            'product_name', p.name,
                            'pack_size', p.pack_size,
                            'quantity', sii.quantity,
                            'rate_at_sale', sii.rate_at_sale,
                            'gst_rate_at_sale', sii.gst_rate_at_sale,
                            'exclusive_gst_amount', sii.exclusive_gst_amount,
                            'sgst', sii.sgst,
                            'cgst', sii.cgst,
                            'total_line_amount', sii.total_line_amount,
                            'discount_percentage', sii.discount_percentage,
                            'rebate_amount', sii.rebate_amount
                        )
                    ) FILTER (WHERE sii.item_id IS NOT NULL),
                    '[]'
                ) as items
            FROM sales_invoices si
            JOIN users u ON si.user_id = u.user_id
            LEFT JOIN sales_invoice_items sii ON si.invoice_id = sii.invoice_id
            LEFT JOIN products p ON sii.product_id = p.product_id
            WHERE si.invoice_id = %s
            GROUP BY si.invoice_id, si.invoice_number, si.receipt_number, si.invoice_date, 
                     si.customer_name, si.customer_contact, si.user_id, si.mode_of_payment, 
                     si.upi_transaction_id, si.customer_mobile, si.total_amount, si.total_gst, 
                     si.discount_percentage, si.discount_amount, si.status, u.username
        """, (invoice_id,))
        
        result = cur.fetchone()
        
        if not result:
            return jsonify({'message': 'Invoice not found'}), 404
            
        # Add calculated fields for the frontend and ensure they are floats
        if result:
            # Grand total should include GST (total_amount + total_gst)
            result['grand_total'] = (float(result['total_amount']) if result['total_amount'] else 0.0) + (float(result['total_gst']) if result['total_gst'] else 0.0)
            result['discount_amount'] = float(result['discount_amount']) if result['discount_amount'] else 0.0
            result['total_gst'] = float(result['total_gst']) if result['total_gst'] else 0.0
            result['total_amount'] = float(result['total_amount']) if result['total_amount'] else 0.0
            result['discount_percentage'] = float(result['discount_percentage']) if result['discount_percentage'] else 0.0
        
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Failed to fetch invoice %s", invoice_id)
        return jsonify({'message': 'Failed to fetch invoice'}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)