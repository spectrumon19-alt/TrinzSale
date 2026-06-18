import os, sys
from io import BytesIO
sys.path.insert(0, '.')

invoice = {
    'invoice_number': 'INV-20260618-0042',
    'invoice_date': '2026-06-18',
    'customer_name': 'Ramesh Kumar',
    'customer_mobile': '9876543210',
    'mode_of_payment': 'UPI',
    'upi_transaction_id': 'UPI123456789',
    'receipt_number': 'RCP-0042',
    'discount_amount': 0,
    'irn': 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
    'qr_data': '',
}
items = [
    {'product_name': 'DAP Fertiliser 50kg',  'hsn_code': '31042000', 'quantity': 2,  'rate_at_sale': 1400.0, 'gst_rate_at_sale': 5.0,  'exclusive_gst_amount': 2666.67, 'cgst': 66.67,  'sgst': 66.67,  'total_line_amount': 2800.0},
    {'product_name': 'Urea 45kg Bag',        'hsn_code': '31021000', 'quantity': 5,  'rate_at_sale': 310.0,  'gst_rate_at_sale': 5.0,  'exclusive_gst_amount': 1476.19, 'cgst': 36.91,  'sgst': 36.90,  'total_line_amount': 1550.0},
    {'product_name': 'Chlorpyrifos 20EC',    'hsn_code': '38081020', 'quantity': 10, 'rate_at_sale': 250.0,  'gst_rate_at_sale': 18.0, 'exclusive_gst_amount': 2118.64, 'cgst': 190.68, 'sgst': 190.68, 'total_line_amount': 2500.0},
    {'product_name': 'NPK 19:19:19 Complex', 'hsn_code': '31059090', 'quantity': 3,  'rate_at_sale': 820.0,  'gst_rate_at_sale': 5.0,  'exclusive_gst_amount': 2342.86, 'cgst': 58.57,  'sgst': 58.57,  'total_line_amount': 2460.0},
]

import qrcode
qr_img = qrcode.make("https://einvoice1.gst.gov.in/verify/INV-20260618-0042")
qr_buf = BytesIO()
qr_img.save(qr_buf, format='PNG')
qr_bytes = qr_buf.getvalue()

from routes.email_invoice import _build_pdf_html, _build_pdf
pdf_html = _build_pdf_html(invoice, items, {}, qr_bytes)
pdf_bytes = _build_pdf(pdf_html)

if pdf_bytes:
    with open('test_invoice_output.pdf', 'wb') as f:
        f.write(pdf_bytes)
    print(f"SUCCESS — {len(pdf_bytes):,} bytes")
else:
    print("FAILED")
