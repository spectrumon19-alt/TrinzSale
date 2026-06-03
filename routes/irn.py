import hashlib
import json
import base64
import io
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _financial_year(dt: datetime) -> str:
    """Return GST financial year string, e.g. '2025-26'."""
    if dt.month >= 4:
        return f"{dt.year}-{str(dt.year + 1)[2:]}"
    return f"{dt.year - 1}-{str(dt.year)[2:]}"


def compute_irn(gstin: str, invoice_number: str, invoice_date) -> str:
    """
    SHA-256(GSTIN|FY|DocType|DocNo) as per GST IRN specification.
    Returns 64-character lowercase hex string.
    """
    if not isinstance(invoice_date, datetime):
        try:
            invoice_date = datetime.strptime(str(invoice_date)[:10], '%Y-%m-%d')
        except Exception:
            invoice_date = datetime.now()
    fy  = _financial_year(invoice_date)
    raw = f"{gstin}|{fy}|INV|{invoice_number}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _build_qr_payload(invoice: dict, items: list, store: dict, irn: str) -> str:
    """Compact GST e-invoice QR payload (JSON string)."""
    invoice_date = invoice.get('invoice_date', '')
    try:
        dt       = datetime.strptime(str(invoice_date)[:10], '%Y-%m-%d')
        date_str = dt.strftime('%d/%m/%Y')
    except Exception:
        date_str = str(invoice_date)[:10]

    total_amount = float(invoice.get('total_amount') or 0)
    total_gst    = float(invoice.get('total_gst')    or 0)
    grand_total  = total_amount + total_gst
    main_hsn     = (items[0].get('hsn_code') or '') if items else ''

    return json.dumps({
        'SellerGSTIN': store.get('store_gst', ''),
        'DocNo':       invoice.get('invoice_number', ''),
        'DocType':     'INV',
        'DocDt':       date_str,
        'TotInvVal':   f'{grand_total:.2f}',
        'ItemCnt':     len(items),
        'MainHsn':     main_hsn,
        'IRN':         irn,
        'IssDt':       datetime.now().strftime('%d/%m/%Y %H:%M'),
    }, separators=(',', ':'))


def generate_qr_bytes(text: str):
    """Generate QR code PNG and return raw bytes, or None on failure."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=2,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error('QR generation failed: %s', e)
        return None


def generate_qr_base64(text: str) -> str:
    """Generate QR code PNG and return as inline base64 data URI."""
    raw = generate_qr_bytes(text)
    if raw:
        return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
    return ''


def attach_irn(invoice_id: int, conn, cur, store: dict) -> dict:
    """
    Compute IRN + QR for an invoice and persist both to sales_invoices.
    Must be called after the invoice transaction is committed.
    Returns {'irn': str, 'qr_data': str} or {} on failure.
    """
    try:
        cur.execute("""
            SELECT invoice_id, invoice_number, invoice_date, total_amount, total_gst
            FROM   sales_invoices
            WHERE  invoice_id = %s
        """, (invoice_id,))
        invoice = cur.fetchone()
        if not invoice:
            return {}

        cur.execute("""
            SELECT sii.*, p.hsn_code
            FROM   sales_invoice_items sii
            JOIN   products p ON sii.product_id = p.product_id
            WHERE  sii.invoice_id = %s
        """, (invoice_id,))
        items = cur.fetchall()

        gstin   = store.get('store_gst', '')
        irn     = compute_irn(gstin, invoice['invoice_number'], invoice['invoice_date'])
        payload = _build_qr_payload(dict(invoice), [dict(i) for i in items], store, irn)
        qr_data = generate_qr_base64(payload)

        cur.execute("""
            UPDATE sales_invoices
            SET    irn              = %s,
                   qr_data         = %s,
                   irn_generated_at = NOW(),
                   einvoice_status = 'generated'
            WHERE  invoice_id = %s
        """, (irn, qr_data, invoice_id))

        return {'irn': irn, 'qr_data': qr_data}
    except Exception as e:
        logger.error('attach_irn failed for invoice %s: %s', invoice_id, e)
        return {}
