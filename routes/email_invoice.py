import os
import base64
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders as email_encoders
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor

from auth import cashier_required
from db import get_db_connection, release_db_connection
from routes.irn import _build_qr_payload, generate_qr_bytes

email_invoice_bp = Blueprint('email_invoice', __name__)
logger = logging.getLogger(__name__)

BREVO_REST_URL  = 'https://api.brevo.com/v3/smtp/email'
BREVO_SMTP_HOST = 'smtp-relay.brevo.com'
BREVO_SMTP_PORT = 587


def _send_email(to_email, to_name, subject, html_body, attachments=None):
    """
    attachments: list of {'filename': str, 'data': bytes, 'mime': str} sent as file attachments.
    """
    api_key      = os.environ.get('BREVO_API_KEY', '')
    sender_email = os.environ.get('BREVO_SENDER_EMAIL', '')
    sender_name  = os.environ.get('BREVO_SENDER_NAME', 'TrintzPOS')

    if not api_key or not sender_email:
        logger.warning('Email not configured (BREVO_API_KEY / BREVO_SENDER_EMAIL missing)')
        return False, 'Email service not configured. Set BREVO_API_KEY and BREVO_SENDER_EMAIL in .env'

    if api_key.startswith('xkeysib-'):
        payload_dict = {
            'sender': {'name': sender_name, 'email': sender_email},
            'to': [{'email': to_email, 'name': to_name}],
            'subject': subject,
            'htmlContent': html_body,
        }
        if attachments:
            payload_dict['attachment'] = [
                {
                    'content': base64.b64encode(a['data']).decode('ascii'),
                    'name':    a['filename'],
                }
                for a in attachments
            ]
        payload = json.dumps(payload_dict).encode('utf-8')
        req = Request(
            BREVO_REST_URL,
            data=payload,
            headers={
                'api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        try:
            with urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201, 202):
                    return True, 'sent'
                return False, f'Brevo API returned {resp.status}'
        except HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:300]
            logger.error('Brevo REST %s: %s', e.code, body)
            return False, f'Brevo API error {e.code}: {body}'
        except URLError as e:
            logger.error('Brevo URL error: %s', e.reason)
            return False, 'Email service unreachable'
    else:
        smtp_user = os.environ.get('BREVO_SMTP_USER', sender_email)
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From']    = f'{sender_name} <{sender_email}>'
        msg['To']      = f'{to_name} <{to_email}>'
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        if attachments:
            for a in attachments:
                mime_type = a.get('mime', 'octet-stream')
                is_image = mime_type in ('png', 'jpeg', 'jpg', 'gif', 'webp') or mime_type.startswith('image/')
                if is_image:
                    part = MIMEImage(a['data'], mime_type.split('/')[-1] if '/' in mime_type else mime_type)
                else:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(a['data'])
                    email_encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment', filename=a['filename'])
                msg.attach(part)
        try:
            with smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT, timeout=15) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(smtp_user, api_key)
                srv.sendmail(sender_email, to_email, msg.as_string())
            return True, 'sent'
        except smtplib.SMTPAuthenticationError:
            logger.error('Brevo SMTP auth failed for user %s', smtp_user)
            return False, 'SMTP authentication failed. Check BREVO_SMTP_USER in .env'
        except smtplib.SMTPException as e:
            logger.error('Brevo SMTP error: %s', e)
            return False, str(e)


def _build_html(invoice, items, store):
    """
    Generates email HTML that matches invoice.html's layout exactly:
    centred header, same 9-column items table, same totals block, same declarations.
    All CSS is inlined for email-client compatibility.
    """
    from datetime import datetime as _dt

    store_name    = store.get('store_name', 'Our Store')
    store_address = store.get('store_address', '')
    store_phone   = store.get('store_phone', '')
    store_gst     = store.get('store_gst', '')

    inv_number   = invoice.get('invoice_number', '')
    receipt_num  = invoice.get('receipt_number', '') or ''
    cust_name    = invoice.get('customer_name') or 'Guest Customer'
    cust_mobile  = invoice.get('customer_mobile') or ''
    payment_mode = invoice.get('mode_of_payment') or 'Cash'
    upi_txn      = invoice.get('upi_transaction_id') or ''
    irn          = invoice.get('irn') or ''
    discount     = float(invoice.get('discount_amount') or 0)

    raw_date = str(invoice.get('invoice_date', ''))[:10]
    try:
        inv_date = _dt.strptime(raw_date, '%Y-%m-%d').strftime('%d/%m/%Y')
    except Exception:
        inv_date = raw_date

    # ── Item rows ─────────────────────────────────────────────────────────
    BD  = 'border:1px solid #000;'
    BDR = 'border-right:1px solid #000;'
    BDB = 'border-bottom:1px solid #000;'
    CELL = f'padding:4px 6px;font-size:12px;color:#000;font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif;{BD}'

    total_taxable = 0.0
    total_cgst    = 0.0
    total_sgst    = 0.0
    total_grand   = 0.0
    item_rows     = ''

    for idx, item in enumerate(items, 1):
        qty        = item.get('quantity', '')
        rate       = float(item.get('rate_at_sale') or 0)
        gst_pct    = float(item.get('gst_rate_at_sale') or 0)
        taxable    = float(item.get('exclusive_gst_amount') or 0)
        cgst       = float(item.get('cgst') or 0)
        sgst       = float(item.get('sgst') or 0)
        line_total = float(item.get('total_line_amount') or 0)
        hsn        = item.get('hsn_code') or '—'
        name       = item.get('product_name') or 'Unknown'

        total_taxable += taxable
        total_cgst    += cgst
        total_sgst    += sgst
        total_grand   += line_total

        item_rows += f"""
        <tr>
          <td style="{CELL}text-align:center;">{idx}</td>
          <td style="{CELL}text-align:left;">{name}</td>
          <td style="{CELL}text-align:center;">{hsn}</td>
          <td style="{CELL}text-align:center;">{qty}</td>
          <td style="{CELL}text-align:center;">{gst_pct:.2f}%</td>
          <td style="{CELL}text-align:right;">&#8377;{rate:.2f}</td>
          <td style="{CELL}text-align:right;">&#8377;{cgst:.2f}</td>
          <td style="{CELL}text-align:right;">&#8377;{sgst:.2f}</td>
          <td style="{CELL}text-align:right;">&#8377;{line_total:.2f}</td>
        </tr>"""

    if not item_rows:
        item_rows = f'<tr><td colspan="9" style="{CELL}text-align:center;">No items</td></tr>'

    grand_total = total_grand  # already includes GST

    # ── UPI row ───────────────────────────────────────────────────────────
    upi_row = ''
    if payment_mode.upper() == 'UPI' and upi_txn:
        ref = str(upi_txn)[-5:] if len(str(upi_txn)) >= 5 else str(upi_txn)
        upi_row = f"""
        <tr>
          <td style="font-size:12px;font-weight:bold;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">UPI Txn ID:</td>
          <td style="font-size:12px;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{ref}</td>
        </tr>"""

    mobile_row = ''
    if cust_mobile:
        mobile_row = f"""
        <tr>
          <td style="font-size:12px;font-weight:bold;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Mobile:</td>
          <td style="font-size:12px;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{cust_mobile}</td>
        </tr>"""

    receipt_row = f"""
        <tr>
          <td style="font-size:12px;font-weight:bold;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Receipt:</td>
          <td style="font-size:12px;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{receipt_num or '—'}</td>
        </tr>""" if receipt_num else ''

    discount_row = ''
    if discount > 0:
        discount_row = f"""
              <tr>
                <td style="padding:3px 6px;font-size:13px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">Discount</td>
                <td style="padding:3px 6px;text-align:right;font-size:13px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">(&#8722;) &#8377;{discount:.2f}</td>
              </tr>"""

    irn_row = ''
    if irn:
        irn_row = f"""
        <tr>
          <td colspan="2" style="padding-top:10px;">
            <div style="font-size:10px;font-weight:bold;margin-bottom:3px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Invoice Reference Number (IRN)</div>
            <div style="font-size:8px;font-family:'Courier New',monospace;word-break:break-all;line-height:1.5;border:1px solid #ccc;padding:4px 6px;background:#f9f9f9;">{irn}</div>
            <div style="font-size:9px;color:#555;margin-top:3px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">QR code attached as image &bull; E-Invoice verified &bull; Powered by TrintzPOS</div>
          </td>
        </tr>"""

    # ── Company header lines ──────────────────────────────────────────────
    company_lines = ''
    if store_address:
        company_lines += f'<div style="font-size:12px;margin-bottom:2px;font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,sans-serif;">{store_address}</div>'
    details = []
    if store_gst:
        details.append(f'GST: {store_gst}')
    if store_phone:
        details.append(f'Cell: {store_phone}')
    if details:
        company_lines += f'<div style="font-size:12px;font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,sans-serif;">{" | ".join(details)}</div>'

    TH = f'padding:6px;font-size:12px;font-weight:bold;background-color:#fff;color:#000;text-align:center;font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif;{BD}'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Invoice #{inv_number} &mdash; {store_name}</title>
</head>
<body style="margin:0;padding:20px;background-color:#f5f7fa;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;font-size:14px;line-height:1.4;color:#000;">

<table width="800" cellpadding="0" cellspacing="0" align="center"
       style="max-width:800px;width:100%;background:#fff;border:1px solid #000;">
  <tr>
    <td style="padding:20px;">

      <!-- ══ HEADER ═══════════════════════════════════════════════════════ -->
      <div style="text-align:center;margin-bottom:20px;">
        <div style="font-size:20px;font-weight:bold;margin-bottom:5px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{store_name}</div>
        {company_lines}
      </div>

      <!-- ══ INVOICE META ══════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;font-size:13px;">
        <tr>
          <td style="vertical-align:top;width:50%;">
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-weight:bold;padding:2px 0;width:70px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Invoice:</td>
                <td style="padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{inv_number}</td>
              </tr>
              {receipt_row}
              <tr>
                <td style="font-weight:bold;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Customer:</td>
                <td style="padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{cust_name}</td>
              </tr>
            </table>
          </td>
          <td style="vertical-align:top;width:50%;">
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-weight:bold;padding:2px 0;width:70px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Date:</td>
                <td style="padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{inv_date}</td>
              </tr>
              <tr>
                <td style="font-weight:bold;padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">Payment:</td>
                <td style="padding:2px 0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">{payment_mode}</td>
              </tr>
              {upi_row}
              {mobile_row}
            </table>
          </td>
        </tr>
      </table>

      <!-- ══ ITEMS TABLE ════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;margin-bottom:20px;font-size:12px;table-layout:fixed;">
        <thead>
          <tr>
            <th style="{TH}width:5%;">No.</th>
            <th style="{TH}width:30%;text-align:left;">PARTICULAR</th>
            <th style="{TH}width:10%;">HSN / SAC Code</th>
            <th style="{TH}width:8%;">Qty</th>
            <th style="{TH}width:8%;">GST %</th>
            <th style="{TH}width:10%;">Rate</th>
            <th style="{TH}width:8%;">CGST</th>
            <th style="{TH}width:8%;">SGST</th>
            <th style="{TH}width:13%;">Amount</th>
          </tr>
        </thead>
        <tbody>
          {item_rows}
        </tbody>
      </table>

      <!-- ══ TOTALS ════════════════════════════════════════════════════════ -->
      <table width="45%" cellpadding="0" cellspacing="0" align="right"
             style="margin-left:55%;margin-bottom:20px;font-size:13px;border-collapse:collapse;">
        <tr>
          <td style="padding:3px 6px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">Total Taxable Value</td>
          <td style="padding:3px 6px;text-align:right;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">&#8377; {total_taxable:.2f}</td>
        </tr>
        <tr>
          <td style="padding:3px 6px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">Total SGST</td>
          <td style="padding:3px 6px;text-align:right;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">&#8377; {total_sgst:.2f}</td>
        </tr>
        <tr>
          <td style="padding:3px 6px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">Total CGST</td>
          <td style="padding:3px 6px;text-align:right;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">&#8377; {total_cgst:.2f}</td>
        </tr>
        {discount_row}
        <tr>
          <td style="padding:5px 6px;font-weight:bold;font-size:14px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">GRAND TOTAL</td>
          <td style="padding:5px 6px;text-align:right;font-weight:bold;font-size:14px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;{BD}">&#8377; {grand_total:.2f}</td>
        </tr>
      </table>

      <!-- ══ IRN ════════════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0" style="clear:both;">
        {irn_row}
      </table>

      <!-- ══ DECLARATIONS ══════════════════════════════════════════════════ -->
      <div style="margin-top:16px;font-size:13px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
        <div>Goods once sold will not be taken back or exchanged.</div>
        <div>Use Agriculture Purpose Only.</div>
      </div>

      <!-- ══ SIGNATURE ══════════════════════════════════════════════════════ -->
      <div style="margin-top:30px;font-size:13px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
        <div>For {store_name}</div>
        <div style="margin-top:40px;width:150px;border-top:1px solid #000;padding-top:4px;font-size:12px;">Signature</div>
      </div>

    </td>
  </tr>
</table>

</body>
</html>"""


@email_invoice_bp.route('/sales/<int:invoice_id>/send-email', methods=['POST'])
@cashier_required
def send_invoice_email(payload, invoice_id):
    data = request.get_json() or {}
    customer_email = (data.get('email') or '').strip()
    if not customer_email or '@' not in customer_email:
        return jsonify({'error': 'Valid email address is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('SELECT * FROM sales_invoices WHERE invoice_id = %s', (invoice_id,))
        invoice = cur.fetchone()
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404

        cur.execute("""
            SELECT sii.*, p.name AS product_name, p.hsn_code
            FROM sales_invoice_items sii
            LEFT JOIN products p ON sii.product_id = p.product_id
            WHERE sii.invoice_id = %s
            ORDER BY sii.item_id
        """, (invoice_id,))
        items = cur.fetchall()

        cur.execute('SELECT key, value FROM store_settings')
        store = {r['key']: r['value'] for r in cur.fetchall()}

        inv_dict  = dict(invoice)
        item_list = [dict(i) for i in items]

        # Generate QR bytes from stored data URI, or regenerate on-the-fly from invoice payload.
        qr_bytes = None
        raw_qr = inv_dict.get('qr_data') or ''
        if raw_qr.startswith('data:image/png;base64,'):
            try:
                qr_bytes = base64.b64decode(raw_qr.split(',', 1)[1])
            except Exception:
                qr_bytes = None

        if not qr_bytes and inv_dict.get('irn'):
            try:
                qr_payload = _build_qr_payload(inv_dict, item_list, store, inv_dict['irn'])
                qr_bytes   = generate_qr_bytes(qr_payload)
            except Exception as e:
                logger.warning('QR generation failed for invoice %s: %s', invoice_id, e)

        html = _build_html(inv_dict, item_list, store)

        # Attach QR as a PNG file so every email client can open it
        inv_number  = invoice.get('invoice_number', str(invoice_id))
        attachments = []
        if qr_bytes:
            attachments.append({
                'filename': f'QR_Invoice_{inv_number}.png',
                'data':     qr_bytes,
                'mime':     'png',
            })

        subject = f"Your Invoice #{inv_number} from {store.get('store_name', 'Store')}"
        ok, msg = _send_email(customer_email, invoice.get('customer_name') or 'Customer',
                              subject, html, attachments=attachments or None)

        if ok:
            return jsonify({'success': True, 'message': f'Receipt sent to {customer_email}'})
        return jsonify({'error': msg}), 502

    except Exception as e:
        logger.exception('send_invoice_email failed')
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)
