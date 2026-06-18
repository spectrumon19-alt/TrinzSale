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
                elif mime_type == 'application/pdf':
                    part = MIMEBase('application', 'pdf')
                    part.set_payload(a['data'])
                    email_encoders.encode_base64(part)
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


def _logo_base64() -> str:
    """Return nandiAgro.png as a base64 data URI for inline email embedding."""
    logo_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'nandiAgro.png')
    try:
        with open(os.path.abspath(logo_path), 'rb') as fh:
            return 'data:image/png;base64,' + base64.b64encode(fh.read()).decode('ascii')
    except Exception:
        return ''


# ── Hardcoded Nandi Agro identity (mirrors invoice.html) ─────────────────────
_STORE = {
    'name':     'NANDI AGRO',
    'tagline':  'Trusted Quality • Better Harvest • Prosperous Future',
    'sub':      'Dealers in Fertilisers, Pesticides & Seeds',
    'address':  '#2454, Agasi Main Road, Sangameshwar Circle, Kolhar – 586210, Dist. Vijayapur',
    'gst':      '29AASFN9214H1ZP',
    'phone':    '8660180378 / 9148271333',
    'lic':      'Fertiliser Lic: FE19-20103879 | Pesticide Lic: JDA/VJ/PL/PE19-2099256/2021-2022 | Seed Lic: VJ/SE19-20104382/2021',
    'green':    '#1a5c1a',
}


def _build_html(invoice, items, store):
    """
    Email invoice HTML — layout mirrors invoice.html exactly.
    Logo is embedded as base64 so every email client renders it.
    All CSS is inlined for maximum compatibility.
    """
    from datetime import datetime as _dt

    # Use hardcoded Nandi Agro identity; store_settings values are secondary
    store_name = _STORE['name']

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

    # ── Logo (inline base64 so it renders in Gmail / Outlook) ────────────
    logo_src  = _logo_base64()
    logo_html = (
        f'<img src="{logo_src}" alt="Nandi Agro" width="70" height="70" '
        f'style="width:70px;height:70px;object-fit:contain;display:block;">'
        if logo_src else ''
    )

    # ── Item rows ─────────────────────────────────────────────────────────
    BD   = 'border:1px solid #ccc;'
    CELL = (
        f'padding:5px 7px;font-size:12px;color:#111;'
        f'font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif;{BD}'
    )
    TH = (
        f'padding:7px;font-size:11px;font-weight:700;'
        f'background-color:{_STORE["green"]};color:#fff;text-align:center;'
        f'font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif;{BD}'
    )

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
        bg         = '#f9fdf9' if idx % 2 == 0 else '#fff'

        total_taxable += taxable
        total_cgst    += cgst
        total_sgst    += sgst
        total_grand   += line_total

        item_rows += f"""
        <tr style="background:{bg};">
          <td style="{CELL}text-align:center;">{idx}</td>
          <td style="{CELL}text-align:left;">{name}</td>
          <td style="{CELL}text-align:center;">{hsn}</td>
          <td style="{CELL}text-align:center;">{qty}</td>
          <td style="{CELL}text-align:center;">{gst_pct:.2f}%</td>
          <td style="{CELL}text-align:right;">&#8377;{rate:.2f}</td>
          <td style="{CELL}text-align:right;">&#8377;{cgst:.2f}</td>
          <td style="{CELL}text-align:right;">&#8377;{sgst:.2f}</td>
          <td style="{CELL}text-align:right;font-weight:600;">&#8377;{line_total:.2f}</td>
        </tr>"""

    if not item_rows:
        item_rows = f'<tr><td colspan="9" style="{CELL}text-align:center;">No items</td></tr>'

    grand_total = total_grand  # already GST-inclusive

    # ── Optional rows ─────────────────────────────────────────────────────
    KV = 'font-size:12px;font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif;'
    upi_row = ''
    if payment_mode.upper() == 'UPI' and upi_txn:
        ref = str(upi_txn)[-5:] if len(str(upi_txn)) >= 5 else str(upi_txn)
        upi_row = f'<tr><td style="{KV}font-weight:700;padding:2px 0;width:90px;">UPI Txn ID:</td><td style="{KV}padding:2px 0;">{ref}</td></tr>'

    mobile_row = ''
    if cust_mobile:
        mobile_row = f'<tr><td style="{KV}font-weight:700;padding:2px 0;">Mobile:</td><td style="{KV}padding:2px 0;">{cust_mobile}</td></tr>'

    receipt_row = (
        f'<tr><td style="{KV}font-weight:700;padding:2px 0;width:90px;">Receipt:</td>'
        f'<td style="{KV}padding:2px 0;">{receipt_num}</td></tr>'
    ) if receipt_num else ''

    discount_row = ''
    if discount > 0:
        discount_row = (
            f'<tr><td style="padding:4px 8px;font-size:13px;font-family:\'Segoe UI\',sans-serif;{BD}">Discount</td>'
            f'<td style="padding:4px 8px;text-align:right;font-size:13px;font-family:\'Segoe UI\',sans-serif;{BD}">'
            f'(&minus;) &#8377;{discount:.2f}</td></tr>'
        )

    irn_row = ''
    if irn:
        irn_row = f"""
        <tr>
          <td colspan="2" style="padding-top:12px;">
            <div style="font-size:10px;font-weight:700;margin-bottom:4px;font-family:'Segoe UI',sans-serif;">Invoice Reference Number (IRN)</div>
            <div style="font-size:8px;font-family:'Courier New',monospace;word-break:break-all;line-height:1.5;border:1px solid #ccc;padding:5px 7px;background:#f9f9f9;">{irn}</div>
            <div style="font-size:9px;color:#666;margin-top:3px;font-family:'Segoe UI',sans-serif;">QR code attached &bull; E-Invoice verified &bull; Powered by TrintzPOS</div>
          </td>
        </tr>"""

    TOT_CELL = f'padding:4px 8px;font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif;font-size:13px;{BD}'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Invoice #{inv_number} &mdash; {store_name}</title>
</head>
<body style="margin:0;padding:20px;background-color:#f0f4f0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;font-size:14px;line-height:1.5;color:#111;">

<table width="800" cellpadding="0" cellspacing="0" align="center"
       style="max-width:800px;width:100%;background:#fff;border:1px solid #d1d5db;border-radius:6px;overflow:hidden;">
  <tr>
    <td style="padding:0;">

      <!-- ══ HEADER ═════════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-bottom:3px solid {_STORE['green']};padding:18px 24px;background:#fff;">
        <tr>
          <td style="vertical-align:middle;width:84px;">{logo_html}</td>
          <td style="vertical-align:middle;padding-left:14px;">
            <div style="font-size:22px;font-weight:900;color:{_STORE['green']};letter-spacing:.5px;line-height:1.1;">{store_name}</div>
            <div style="font-size:10px;color:#888;font-style:italic;margin:2px 0;">{_STORE['tagline']}</div>
            <div style="font-size:11px;color:#444;margin-top:2px;">{_STORE['sub']}</div>
            <div style="font-size:11px;color:#555;">{_STORE['address']}</div>
            <div style="font-size:11px;color:#555;">GST: {_STORE['gst']} &nbsp;|&nbsp; Cell: {_STORE['phone']}</div>
            <div style="font-size:10px;color:#777;">{_STORE['lic']}</div>
          </td>
          <td style="vertical-align:top;text-align:right;padding-left:10px;">
            <div style="background:{_STORE['green']};color:#fff;font-size:12px;font-weight:700;
                        padding:5px 14px;border-radius:4px;letter-spacing:1px;display:inline-block;">TAX INVOICE</div>
          </td>
        </tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0" style="padding:16px 24px 0;">
        <tr><td>

      <!-- ══ INVOICE META ════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="margin-bottom:16px;font-size:13px;background:#f9fdf9;border:1px solid #d1fae5;
                    border-radius:6px;padding:10px 14px;">
        <tr>
          <td style="vertical-align:top;width:50%;padding:4px 8px;">
            <table cellpadding="0" cellspacing="0">
              <tr><td style="font-weight:700;padding:2px 0;width:90px;font-family:'Segoe UI',sans-serif;color:#555;">Invoice No.:</td>
                  <td style="padding:2px 0;font-family:'Segoe UI',sans-serif;font-weight:700;color:{_STORE['green']};">{inv_number}</td></tr>
              {receipt_row}
              <tr><td style="font-weight:700;padding:2px 0;font-family:'Segoe UI',sans-serif;color:#555;">Customer:</td>
                  <td style="padding:2px 0;font-family:'Segoe UI',sans-serif;">{cust_name}</td></tr>
              {mobile_row}
            </table>
          </td>
          <td style="vertical-align:top;width:50%;padding:4px 8px;">
            <table cellpadding="0" cellspacing="0">
              <tr><td style="font-weight:700;padding:2px 0;width:90px;font-family:'Segoe UI',sans-serif;color:#555;">Date:</td>
                  <td style="padding:2px 0;font-family:'Segoe UI',sans-serif;">{inv_date}</td></tr>
              <tr><td style="font-weight:700;padding:2px 0;font-family:'Segoe UI',sans-serif;color:#555;">Payment:</td>
                  <td style="padding:2px 0;font-family:'Segoe UI',sans-serif;">{payment_mode}</td></tr>
              {upi_row}
            </table>
          </td>
        </tr>
      </table>

      <!-- ══ ITEMS TABLE ═════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;margin-bottom:16px;font-size:12px;table-layout:fixed;">
        <thead>
          <tr>
            <th style="{TH}width:5%;">No.</th>
            <th style="{TH}width:30%;text-align:left;">PARTICULAR</th>
            <th style="{TH}width:10%;">HSN / SAC</th>
            <th style="{TH}width:7%;">Qty</th>
            <th style="{TH}width:8%;">GST%</th>
            <th style="{TH}width:10%;">Rate</th>
            <th style="{TH}width:8%;">CGST</th>
            <th style="{TH}width:8%;">SGST</th>
            <th style="{TH}width:14%;">Amount</th>
          </tr>
        </thead>
        <tbody>{item_rows}</tbody>
      </table>

      <!-- ══ TOTALS ══════════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;">
        <tr>
          <td width="55%">&nbsp;</td>
          <td width="45%">
            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
              <tr>
                <td style="{TOT_CELL}">Total Taxable Value</td>
                <td style="{TOT_CELL}text-align:right;">&#8377; {total_taxable:.2f}</td>
              </tr>
              <tr>
                <td style="{TOT_CELL}">Total SGST</td>
                <td style="{TOT_CELL}text-align:right;">&#8377; {total_sgst:.2f}</td>
              </tr>
              <tr>
                <td style="{TOT_CELL}">Total CGST</td>
                <td style="{TOT_CELL}text-align:right;">&#8377; {total_cgst:.2f}</td>
              </tr>
              {discount_row}
              <tr style="background:{_STORE['green']};">
                <td style="padding:6px 8px;font-weight:700;font-size:14px;color:#fff;
                           font-family:'Segoe UI',sans-serif;border:1px solid {_STORE['green']};">GRAND TOTAL</td>
                <td style="padding:6px 8px;text-align:right;font-weight:700;font-size:14px;color:#fff;
                           font-family:'Segoe UI',sans-serif;border:1px solid {_STORE['green']};">&#8377; {grand_total:.2f}</td>
              </tr>
            </table>
          </td>
        </tr>
      </table>

      <!-- ══ IRN ════════════════════════════════════════════════════════════ -->
      <table width="100%" cellpadding="0" cellspacing="0" style="clear:both;">
        {irn_row}
      </table>

      <!-- ══ DECLARATIONS ══════════════════════════════════════════════════ -->
      <div style="margin-top:16px;font-size:12px;color:#555;font-family:'Segoe UI',sans-serif;
                  border-top:1px solid #e5e7eb;padding-top:10px;">
        <div>Goods once sold will not be taken back or exchanged.</div>
        <div>Use for Agriculture Purpose Only.</div>
      </div>

      <!-- ══ SIGNATURE ══════════════════════════════════════════════════════ -->
      <div style="margin-top:28px;font-size:13px;font-family:'Segoe UI',sans-serif;">
        <div>For <strong>Nandi Agro</strong></div>
        <div style="margin-top:38px;width:160px;border-top:1px solid #555;padding-top:4px;font-size:12px;color:#555;">Authorised Signatory</div>
      </div>

      <!-- ══ POWERED BY ═════════════════════════════════════════════════════ -->
      <div style="margin-top:18px;padding-top:10px;border-top:1px dashed #e5e7eb;
                  text-align:center;font-size:10px;color:#bbb;font-family:'Segoe UI',sans-serif;">
        Powered by &nbsp;<strong style="color:#999;">TrintzPOS</strong>
        &nbsp;&mdash;&nbsp; Smart Billing for Agri Retail
      </div>

        </td></tr>
      </table>

    </td>
  </tr>
</table>

</body>
</html>"""


def _amount_words(n: float) -> str:
    """Convert a rupee total to words, e.g. 9310.00 → 'Nine Thousand Three Hundred Ten Rupees Only'."""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')).strip()

    def _three(n):
        if n >= 100:
            return ones[n // 100] + ' Hundred' + (' ' + _two(n % 100) if n % 100 else '')
        return _two(n)

    rupees = int(n)
    parts = []
    if rupees >= 10_000_000:
        parts.append(_three(rupees // 10_000_000) + ' Crore'); rupees %= 10_000_000
    if rupees >= 100_000:
        parts.append(_three(rupees // 100_000) + ' Lakh'); rupees %= 100_000
    if rupees >= 1_000:
        parts.append(_three(rupees // 1_000) + ' Thousand'); rupees %= 1_000
    if rupees > 0:
        parts.append(_three(rupees))
    return (' '.join(parts) + ' Rupees Only') if parts else 'Zero Rupees Only'


def _build_pdf_html(invoice: dict, items: list, store: dict, qr_bytes: bytes | None = None) -> str:
    """
    Table-layout invoice HTML for xhtml2pdf.
    xhtml2pdf uses ReportLab which does not support flexbox/grid — all layout
    must be done with <table>. This mirrors _build_html() content exactly but
    uses only table-based CSS.
    """
    from datetime import datetime as _dt

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

    GREEN = _STORE['green']
    FONT  = "font-family: Helvetica, Arial, sans-serif;"

    # Logo as base64
    logo_src  = _logo_base64()
    logo_html = (
        f'<img src="{logo_src}" width="64" height="64" '
        f'style="width:64px;height:64px;">'
        if logo_src else ''
    )

    # Item rows
    total_taxable = total_cgst = total_sgst = total_grand = 0.0
    item_rows = ''
    for idx, item in enumerate(items, 1):
        qty        = item.get('quantity', '')
        rate       = float(item.get('rate_at_sale') or 0)
        gst_pct    = float(item.get('gst_rate_at_sale') or 0)
        taxable    = float(item.get('exclusive_gst_amount') or 0)
        cgst       = float(item.get('cgst') or 0)
        sgst       = float(item.get('sgst') or 0)
        line_total = float(item.get('total_line_amount') or 0)
        hsn        = item.get('hsn_code') or '-'
        name       = item.get('product_name') or 'Unknown'
        bg         = '#f9fdf9' if idx % 2 == 0 else '#ffffff'
        total_taxable += taxable; total_cgst += cgst
        total_sgst    += sgst;    total_grand += line_total
        item_rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:center;">{idx}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;">{name}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:center;">{hsn}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:center;">{qty}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:center;">{gst_pct:.0f}%</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:right;">Rs.{rate:.2f}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:right;">Rs.{cgst:.2f}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:right;">Rs.{sgst:.2f}</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:right;font-weight:bold;">Rs.{line_total:.2f}</td>'
            f'</tr>'
        )
    if not item_rows:
        item_rows = '<tr><td colspan="9" style="padding:6px;text-align:center;border:1px solid #ccc;">No items</td></tr>'

    # Optional meta rows — styles applied after LBL/VAL are defined below,
    # so we use inline literals matching those constants exactly.
    _L  = 'font-size:9.5px;color:#666;padding:3px 6px;white-space:nowrap;width:90px;'
    _V  = 'font-size:9.5px;color:#111;padding:3px 6px;font-weight:600;'
    _VG = f'font-size:9.5px;color:{_STORE["green"]};padding:3px 6px;font-weight:700;'

    upi_row = ''
    if payment_mode.upper() == 'UPI' and upi_txn:
        ref = str(upi_txn)[-5:] if len(str(upi_txn)) >= 5 else str(upi_txn)
        upi_row = f'<tr><td style="{_L}">UPI Txn ID</td><td style="{_V}">{ref}</td></tr>'
    mobile_row = ''
    if cust_mobile:
        mobile_row = f'<tr><td style="{_L}">Mobile</td><td style="{_V}">{cust_mobile}</td></tr>'
    receipt_row = (
        f'<tr><td style="{_L}">Receipt No.</td><td style="{_V}">{receipt_num}</td></tr>'
    ) if receipt_num else ''
    discount_row = ''
    if discount > 0:
        discount_row = (
            f'<tr><td style="padding:4px 5px;border:1px solid #ccc;">Discount</td>'
            f'<td style="padding:4px 5px;border:1px solid #ccc;text-align:right;">(-) Rs.{discount:.2f}</td></tr>'
        )
    irn_block = ''
    if irn:
        irn_block = (
            f'<p style="font-size:9px;font-weight:bold;margin:10px 0 3px;">Invoice Reference Number (IRN)</p>'
            f'<p style="font-size:8px;font-family:Courier,monospace;word-break:break-all;'
            f'border:1px solid #ccc;padding:4px;background:#f9f9f9;margin:0;">{irn}</p>'
            f'<p style="font-size:8px;color:#555;margin:2px 0 0;">E-Invoice verified &bull; Powered by TrintzPOS</p>'
        )

    qr_block = ''
    if qr_bytes:
        qr_b64 = 'data:image/png;base64,' + base64.b64encode(qr_bytes).decode('ascii')
        qr_block = (
            f'<table width="100%" style="margin-top:10px;">'
            f'<tr>'
            f'  <td style="width:50%;vertical-align:top;">'
            f'    <p style="font-size:9px;font-weight:bold;margin:0 0 4px;">QR Code (E-Invoice)</p>'
            f'    <img src="{qr_b64}" width="100" height="100" style="width:100px;height:100px;border:1px solid #ddd;padding:3px;">'
            f'    <p style="font-size:8px;color:#666;margin:3px 0 0;">Scan to verify this invoice</p>'
            f'  </td>'
            f'  <td style="width:50%;">&nbsp;</td>'
            f'</tr>'
            f'</table>'
        )

    # ── xhtml2pdf-safe style constants ───────────────────────────────────────
    S  = f'font-family:Helvetica,Arial,sans-serif;color:#111;'
    G  = f'color:{GREEN};'
    B  = 'border:1px solid #ccc;'
    BG = f'border:1px solid {GREEN};'
    # Label / value cell styles
    LBL  = f'font-size:9.5px;color:#666;padding:3px 6px;white-space:nowrap;width:95px;'
    VAL  = f'font-size:9.5px;color:#111;padding:3px 6px;font-weight:600;'
    VALG = f'font-size:9.5px;color:{GREEN};padding:3px 6px;font-weight:700;'
    # Table header cells
    TH   = f'background:{GREEN};color:#fff;padding:7px 5px;font-size:9.5px;font-weight:700;{BG}text-align:center;'
    THL  = f'background:{GREEN};color:#fff;padding:7px 5px;font-size:9.5px;font-weight:700;{BG}text-align:left;'
    # Item cells
    TC   = f'font-size:10px;padding:5px 5px;{B}text-align:center;vertical-align:middle;'
    TL   = f'font-size:10px;padding:5px 6px;{B}text-align:left;vertical-align:middle;'
    TR   = f'font-size:10px;padding:5px 5px;{B}text-align:right;vertical-align:middle;'
    TRB  = f'font-size:10px;padding:5px 5px;{B}text-align:right;vertical-align:middle;font-weight:700;'
    # Totals
    TOT  = f'font-size:10px;padding:4px 8px;{B}'
    TOTR = f'font-size:10px;padding:4px 8px;{B}text-align:right;'
    GTD  = f'font-size:11px;font-weight:700;padding:6px 8px;color:#fff;background:{GREEN};{BG}'
    GTDR = f'font-size:11px;font-weight:700;padding:6px 8px;color:#fff;background:{GREEN};{BG}text-align:right;'

    discount_td = ''
    if discount > 0:
        discount_td = (
            f'<tr><td style="{TOT}">Discount</td>'
            f'<td style="{TOTR}">(-) Rs.{discount:.2f}</td></tr>'
        )

    amt_words = _amount_words(total_grand)

    # IRN + QR side-by-side
    irn_qr_block = ''
    if irn or qr_bytes:
        qr_td = ''
        if qr_bytes:
            qr_b64 = 'data:image/png;base64,' + base64.b64encode(qr_bytes).decode('ascii')
            qr_td = (
                f'<td style="width:110px;vertical-align:top;padding:8px 0 0 12px;text-align:center;">'
                f'<img src="{qr_b64}" width="90" height="90" style="width:90px;height:90px;'
                f'border:1px solid #ddd;padding:2px;">'
                f'<br><span style="font-size:7.5px;color:#888;">Scan to verify</span>'
                f'</td>'
            )
        irn_td = ''
        if irn:
            irn_td = (
                f'<td style="vertical-align:top;padding:8px 0 0 0;">'
                f'<p style="font-size:8.5px;font-weight:700;margin:0 0 3px;color:#333;">Invoice Reference No. (IRN)</p>'
                f'<p style="font-size:7.5px;font-family:Courier,monospace;word-break:break-all;'
                f'border:1px solid #ddd;padding:4px 5px;background:#f9f9f9;margin:0;color:#444;">{irn}</p>'
                f'<p style="font-size:7.5px;color:#888;margin:3px 0 0;">E-Invoice verified &bull; Powered by TrintzPOS</p>'
                f'</td>'
            )
        elif qr_bytes:
            irn_td = '<td style="vertical-align:top;">&nbsp;</td>'

        irn_qr_block = (
            f'<table width="100%" style="margin-top:8px;margin-bottom:6px;border-top:1px solid #e5e7eb;">'
            f'<tr><td colspan="2" style="height:6px;font-size:1px;">&nbsp;</td></tr>'
            f'<tr>{irn_td}{qr_td}</tr>'
            f'</table>'
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Invoice {inv_number}</title>
<style>
  @page {{ size: A4; margin: 14mm 16mm 14mm 16mm; }}
  body  {{ font-family:Helvetica,Arial,sans-serif; font-size:10px; color:#111; margin:0; padding:0; }}
  table {{ border-collapse:collapse; }}
  .w100 {{ width:100%; }}
</style>
</head>
<body>

<!-- HEADER -->
<table class="w100" style="margin-bottom:0;">
  <tr>
    <td style="width:74px;vertical-align:middle;padding-right:8px;">{logo_html}</td>
    <td style="vertical-align:middle;">
      <p style="font-size:20px;font-weight:900;color:{GREEN};margin:0;line-height:1.1;">{_STORE['name']}</p>
      <p style="font-size:8px;color:#777;font-style:italic;margin:2px 0 1px;">{_STORE['tagline']}</p>
      <p style="font-size:9px;color:#444;margin:1px 0;">{_STORE['sub']}</p>
      <p style="font-size:9px;color:#555;margin:1px 0;">{_STORE['address']}</p>
      <p style="font-size:9px;color:#555;margin:1px 0;">GST: {_STORE['gst']} &nbsp;|&nbsp; Ph: {_STORE['phone']}</p>
      <p style="font-size:7.5px;color:#999;margin:1px 0;">{_STORE['lic']}</p>
    </td>
    <td style="width:85px;vertical-align:top;">
      <table style="border-collapse:collapse;width:85px;">
        <tr>
          <td style="background:{GREEN};color:#fff;font-size:10.5px;font-weight:900;
                     padding:6px 8px;text-align:center;line-height:1.4;
                     width:85px;white-space:nowrap;">
            TAX&nbsp;INVOICE
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>

<!-- Green rule -->
<table class="w100" style="margin:6px 0 8px;">
  <tr><td style="background:{GREEN};height:2.5px;line-height:1px;font-size:1px;">&nbsp;</td></tr>
</table>

<!-- META BOX -->
<table class="w100" style="margin-bottom:9px;border:1px solid #b7ebc8;background:#f7fdf7;">
  <tr>
    <td style="width:49%;vertical-align:top;padding:5px 8px;">
      <table width="100%" style="border-collapse:collapse;">
        <tr>
          <td style="{_L}">Invoice No.</td>
          <td style="{_VG}">{inv_number}</td>
        </tr>
        {receipt_row}
        <tr>
          <td style="{_L}">Customer</td>
          <td style="{_V}">{cust_name}</td>
        </tr>
        {mobile_row}
      </table>
    </td>
    <td style="width:2px;background:#b7ebc8;padding:0;">&nbsp;</td>
    <td style="width:49%;vertical-align:top;padding:5px 8px;">
      <table width="100%" style="border-collapse:collapse;">
        <tr>
          <td style="{_L}">Date</td>
          <td style="{_V}">{inv_date}</td>
        </tr>
        <tr>
          <td style="{_L}">Payment</td>
          <td style="{_V}">{payment_mode}</td>
        </tr>
        {upi_row}
      </table>
    </td>
  </tr>
</table>

<!-- ══ ITEMS TABLE ══════════════════════════════════════════════════════════ -->
<table class="w100" style="margin-bottom:6px;">
  <thead>
    <tr>
      <th style="{TH}width:4%;">#</th>
      <th style="{THL}width:30%;">Item / Particular</th>
      <th style="{TH}width:10%;">HSN/SAC</th>
      <th style="{TH}width:6%;">Qty</th>
      <th style="{TH}width:7%;">GST%</th>
      <th style="{TH}width:12%;">Rate (Rs.)</th>
      <th style="{TH}width:9%;">CGST</th>
      <th style="{TH}width:9%;">SGST</th>
      <th style="{TH}width:13%;">Amount (Rs.)</th>
    </tr>
  </thead>
  <tbody>{item_rows}</tbody>
</table>

<!-- ══ TOTALS + DECLARATIONS ════════════════════════════════════════════════ -->
<table class="w100" style="margin-bottom:10px;">
  <tr>
    <td style="width:54%;vertical-align:middle;padding-right:14px;">
      <p style="font-size:8.5px;color:#888;margin:0 0 2px;font-style:italic;">* Prices are GST-inclusive. Tax breakup shown above.</p>
      <p style="font-size:8.5px;color:#888;margin:0 0 2px;">* Goods once sold will not be taken back or exchanged.</p>
      <p style="font-size:8.5px;color:#888;margin:0;">* For Agriculture Purpose Only.</p>
    </td>
    <td style="width:46%;vertical-align:top;">
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="{TOT}color:#555;">Taxable Value</td>
          <td style="{TOTR}color:#333;">Rs. {total_taxable:.2f}</td>
        </tr>
        <tr>
          <td style="{TOT}color:#555;">CGST</td>
          <td style="{TOTR}color:#333;">Rs. {total_cgst:.2f}</td>
        </tr>
        <tr>
          <td style="{TOT}color:#555;">SGST</td>
          <td style="{TOTR}color:#333;">Rs. {total_sgst:.2f}</td>
        </tr>
        {discount_td}
        <tr>
          <td style="{GTD}">Grand Total</td>
          <td style="{GTDR}">Rs. {total_grand:.2f}</td>
        </tr>
        <tr>
          <td colspan="2" style="font-size:8.5px;color:#555;font-style:italic;
                                  padding:5px 8px;border:1px solid #ccc;background:#f9fdf9;">
            <strong>{amt_words}</strong>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>

<!-- ══ IRN + QR ══════════════════════════════════════════════════════════════ -->
{irn_qr_block}

<!-- TERMS -->
<table width="100%" style="margin-top:8px;border-top:1px solid #e5e7eb;border-collapse:collapse;">
  <tr>
    <td style="padding:5px 0;">
      <p style="font-size:8px;color:#888;margin:0;">
        <strong>T&amp;C:</strong> Goods once sold will not be taken back. For Agriculture use only. Disputes subject to Vijayapur jurisdiction. E. &amp; O. E.
      </p>
    </td>
  </tr>
</table>

<!-- SIGNATURE + POWERED BY -->
<table width="100%" style="margin-top:10px;border-collapse:collapse;">
  <tr>
    <td style="border-top:1px solid #ddd;padding-top:6px;width:50%;vertical-align:top;">
      <p style="font-size:10px;color:#333;margin:0;">For <strong>Nandi Agro</strong></p>
      <p style="font-size:8.5px;color:#666;margin:20px 0 0;padding-top:2px;
                border-top:1px solid #555;width:130px;">Authorised Signatory</p>
    </td>
    <td style="border-top:1px solid #ddd;padding-top:6px;width:50%;vertical-align:top;text-align:right;">
      <p style="font-size:8px;color:#bbb;margin:0;">Powered by <strong style="color:#999;">TrintzPOS</strong></p>
      <p style="font-size:7.5px;color:#ccc;margin:2px 0 0;">Smart Billing for Agri Retail</p>
    </td>
  </tr>
</table>

</body>
</html>"""


def _build_pdf(html: str) -> bytes | None:
    """
    Render invoice HTML → PDF bytes using xhtml2pdf (pure Python, no system libs).
    Returns None on import failure or render error so the caller can fall back
    to sending the invoice as an HTML email body.
    """
    try:
        from io import BytesIO
        from xhtml2pdf import pisa
    except ImportError:
        logger.warning('xhtml2pdf not installed — PDF attachment unavailable.')
        return None
    try:
        buf = BytesIO()
        result = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
        if result.err:
            logger.error('xhtml2pdf render error (err=%s)', result.err)
            return None
        return buf.getvalue()
    except Exception as e:
        logger.error('xhtml2pdf PDF render failed: %s', e)
        return None


def _build_email_body(inv_number: str, cust_name: str, inv_date: str) -> str:
    """Plain professional email body — invoice is the PDF attachment."""
    green = _STORE['green']
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
<table width="600" cellpadding="0" cellspacing="0" align="center"
       style="max-width:600px;width:100%;margin:24px auto;background:#fff;
              border:1px solid #d1d5db;border-radius:8px;overflow:hidden;">
  <!-- Header -->
  <tr>
    <td style="background:{green};padding:20px 28px;">
      <div style="font-size:20px;font-weight:900;color:#fff;letter-spacing:.5px;">NANDI AGRO</div>
      <div style="font-size:11px;color:#bbf7d0;font-style:italic;margin-top:2px;">
        Trusted Quality &bull; Better Harvest &bull; Prosperous Future
      </div>
    </td>
  </tr>
  <!-- Body -->
  <tr>
    <td style="padding:28px 28px 20px;">
      <p style="margin:0 0 14px;font-size:15px;color:#111;">Dear <strong>{cust_name}</strong>,</p>
      <p style="margin:0 0 14px;font-size:14px;color:#444;line-height:1.6;">
        Thank you for your purchase. Please find your tax invoice attached to this email.
      </p>
      <!-- Invoice card -->
      <table cellpadding="0" cellspacing="0" width="100%"
             style="background:#f9fdf9;border:1px solid #d1fae5;border-radius:6px;
                    margin-bottom:20px;font-size:13px;">
        <tr>
          <td style="padding:14px 18px;">
            <div style="color:#555;margin-bottom:4px;">Invoice Number</div>
            <div style="font-size:18px;font-weight:800;color:{green};">#{inv_number}</div>
          </td>
          <td style="padding:14px 18px;border-left:1px solid #d1fae5;">
            <div style="color:#555;margin-bottom:4px;">Date</div>
            <div style="font-size:15px;font-weight:600;color:#111;">{inv_date}</div>
          </td>
          <td style="padding:14px 18px;border-left:1px solid #d1fae5;">
            <div style="color:#555;margin-bottom:4px;">Attachment</div>
            <div style="font-size:13px;font-weight:600;color:#111;">
              &#128196; Invoice_{inv_number}.pdf
            </div>
          </td>
        </tr>
      </table>
      <p style="margin:0 0 14px;font-size:13px;color:#666;line-height:1.6;">
        If you have any questions about your invoice, please contact us at
        <strong>8660180378 / 9148271333</strong>.
      </p>
      <p style="margin:0;font-size:13px;color:#444;">
        Warm regards,<br>
        <strong>Nandi Agro</strong><br>
        <span style="color:#888;font-size:12px;">#2454, Agasi Main Road, Kolhar &ndash; 586210</span>
      </p>
    </td>
  </tr>
  <!-- Footer -->
  <tr>
    <td style="padding:12px 28px;border-top:1px dashed #e5e7eb;text-align:center;
               font-size:10px;color:#bbb;">
      Powered by <strong style="color:#999;">TrintzPOS</strong>
      &nbsp;&mdash;&nbsp; Smart Billing for Agri Retail
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
        inv_number = inv_dict.get('invoice_number', str(invoice_id))
        cust_name  = inv_dict.get('customer_name') or 'Customer'

        raw_date = str(inv_dict.get('invoice_date', ''))[:10]
        try:
            from datetime import datetime as _dt
            inv_date = _dt.strptime(raw_date, '%Y-%m-%d').strftime('%d/%m/%Y')
        except Exception:
            inv_date = raw_date

        # ── Resolve QR bytes (from stored data URI or regenerated) ──────────
        qr_bytes = None
        raw_qr = inv_dict.get('qr_data') or ''
        if raw_qr.startswith('data:image/png;base64,'):
            try:
                qr_bytes = base64.b64decode(raw_qr.split(',', 1)[1])
            except Exception:
                pass
        if not qr_bytes and inv_dict.get('irn'):
            try:
                qr_payload = _build_qr_payload(inv_dict, item_list, store, inv_dict['irn'])
                qr_bytes   = generate_qr_bytes(qr_payload)
            except Exception as e:
                logger.warning('QR generation failed for invoice %s: %s', invoice_id, e)

        # ── Generate HTML versions ────────────────────────────────────────
        invoice_html = _build_html(inv_dict, item_list, store)                    # email body
        pdf_html     = _build_pdf_html(inv_dict, item_list, store, qr_bytes)     # PDF (QR embedded)

        # ── Convert to PDF ────────────────────────────────────────────────
        pdf_bytes = _build_pdf(pdf_html)

        # ── Build attachments — single PDF contains everything ────────────
        attachments = []
        if pdf_bytes:
            attachments.append({
                'filename': f'Invoice_{inv_number}.pdf',
                'data':     pdf_bytes,
                'mime':     'application/pdf',
            })
        else:
            logger.warning('Sending invoice %s as HTML body only (no PDF).', inv_number)

        # ── Email body: clean note when PDF attached, full HTML otherwise ─
        if pdf_bytes:
            email_body = _build_email_body(inv_number, cust_name, inv_date)
        else:
            email_body = invoice_html  # full invoice HTML as body fallback

        # ── Send ──────────────────────────────────────────────────────────
        subject = f'Your Invoice #{inv_number} – Nandi Agro'
        ok, msg = _send_email(customer_email, cust_name, subject, email_body,
                              attachments=attachments or None)

        if ok:
            return jsonify({'success': True, 'message': f'Invoice sent to {customer_email}'})
        return jsonify({'error': msg}), 502

    except Exception as e:
        logger.exception('send_invoice_email failed')
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)
