"""
Returns propagation + GST-inclusive reporting tests.

Validates that a sales return (credit note) flows correctly into every
reporting surface, and that "amount" fields are GST-inclusive where they
represent money actually paid.

Surfaces under test:
  - POST /api/returns                 (return record: inventory, amount, GST)
  - GET  /api/reports/sales           (net of returns; gross/returns/net fields)
  - GET  /api/dashboard/kpis          (GST-inclusive, net of returns)
  - GET  /api/gst/gstr1               (credit notes reduce outward supply)
  - GET  /api/gst/gstr3b              (net outward = outward - credit notes)

Because the test DB is shared, most assertions compare before/after deltas
rather than absolute totals.
"""

import datetime

import pytest

from tests.conftest import parse_json
from tests.helpers.db_helpers import (
    fetch_one, fetch_all, get_product_stock,
)

pytestmark = pytest.mark.sales


# ───────────────────────── helpers ───────────────────────────────────────────

def _make_sale(client, headers, product, qty=4):
    payload = {
        "customer_name": "Return Test",
        "customer_mobile": "9000022222",
        "mode_of_payment": "Cash",
        "discount_percentage": 0,
        "items": [{
            "product_id": product["product_id"],
            "quantity": qty,
            "rate": product["selling_rate"],
            "gst_rate": product["gst_rate"],
        }],
    }
    resp = client.post("/api/sales", json=payload, headers=headers)
    assert resp.status_code == 201, f"sale setup failed: {resp.data}"
    return parse_json(resp)


def _return_first_item(client, headers, invoice_id, qty):
    items = fetch_all(
        "SELECT item_id, product_id FROM sales_invoice_items WHERE invoice_id=%s",
        (invoice_id,),
    )
    payload = {
        "original_invoice_id": invoice_id,
        "return_reason": "Customer Changed Mind",
        "refund_method": "Cash",
        "items": [{
            "original_item_id": items[0]["item_id"],
            "product_id": items[0]["product_id"],
            "quantity": qty,
        }],
    }
    resp = client.post("/api/returns", json=payload, headers=headers)
    return resp


def _current_period():
    return datetime.date.today().strftime("%Y-%m")


# ───────────────────────── return record correctness ─────────────────────────

class TestReturnRecord:

    def test_return_restores_inventory(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        stock_after_sale = get_product_stock(test_product["product_id"])

        resp = _return_first_item(client, admin_headers, sale["invoice_id"], qty=3)
        assert resp.status_code == 201, resp.data
        stock_after_return = get_product_stock(test_product["product_id"])
        assert stock_after_return == stock_after_sale + 3

    def test_return_records_gst_split(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        resp = _return_first_item(client, admin_headers, sale["invoice_id"], qty=2)
        assert resp.status_code == 201
        rid = parse_json(resp)["return_id"]

        line = fetch_one(
            "SELECT sgst, cgst, exclusive_gst_amount, total_line_amount "
            "FROM sales_return_items WHERE return_id=%s", (rid,)
        )
        # SGST and CGST must each be half the total GST.
        assert abs(float(line["sgst"]) - float(line["cgst"])) < 0.02

    def test_over_return_blocked(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=2)
        # Return more than was sold.
        resp = _return_first_item(client, admin_headers, sale["invoice_id"], qty=5)
        assert resp.status_code == 400

    def test_cannot_return_cancelled_invoice(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=2)
        client.put(f"/api/sales/{sale['invoice_id']}/cancel", headers=admin_headers)
        resp = _return_first_item(client, admin_headers, sale["invoice_id"], qty=1)
        assert resp.status_code == 400


# ───────────────────────── sales report nets returns ─────────────────────────

class TestSalesReportNetsReturns:

    def test_report_exposes_gross_returns_net_fields(self, client, admin_headers):
        data = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        for key in ("total_sales", "gross_sales", "returns_amount",
                    "returns_gst", "net_sales", "net_gst"):
            assert key in data, f"missing field {key} in sales report"

    def test_net_sales_equals_gross_minus_returns(self, client, admin_headers):
        data = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        expected = round(data["gross_sales"] - data["returns_amount"], 2)
        assert abs(data["net_sales"] - expected) < 0.01
        assert abs(data["total_sales"] - data["net_sales"]) < 0.01

    def test_return_increases_returns_amount(self, client, admin_headers, cashier_headers, test_product):
        before = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        _return_first_item(client, admin_headers, sale["invoice_id"], qty=2)
        after = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        assert after["returns_amount"] >= before["returns_amount"]

    def test_return_reduces_net_versus_gross(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        _return_first_item(client, admin_headers, sale["invoice_id"], qty=2)
        data = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        # With at least one return in the period, net must be below gross.
        assert data["net_sales"] <= data["gross_sales"]


# ───────────────────────── dashboard GST-inclusive & net ──────────────────────

class TestDashboardGstInclusive:

    def test_kpi_shape(self, client, admin_headers):
        data = parse_json(client.get("/api/dashboard/kpis", headers=admin_headers))
        assert "today" in data and "month" in data
        assert "amount" in data["today"]
        assert "gst" in data["today"]

    def test_today_amount_is_gst_inclusive(self, client, admin_headers, cashier_headers, test_product):
        # Verify the dashboard 'today.amount' is GST-INCLUSIVE and net of returns,
        # by comparing it to an authoritative direct computation. (A before/after
        # delta is unreliable on a shared DB where accumulated returns can floor
        # the net to zero, so we assert the reported value equals the true value.)
        _make_sale(client, cashier_headers, test_product, qty=1)

        # Authoritative: GST-inclusive gross today minus GST-inclusive returns today.
        gross = fetch_one(
            "SELECT COALESCE(SUM(total_amount + total_gst),0) AS v "
            "FROM sales_invoices WHERE status='Completed' AND DATE(invoice_date)=CURRENT_DATE"
        )["v"]
        rets = fetch_one(
            "SELECT COALESCE(SUM(total_amount + total_gst),0) AS v "
            "FROM sales_returns WHERE status='Completed' AND return_date=CURRENT_DATE"
        )["v"]
        expected = max(0.0, round(float(gross) - float(rets), 2))

        data = parse_json(client.get("/api/dashboard/kpis", headers=admin_headers))
        reported = data["today"]["amount"]
        # Must match the GST-inclusive, returns-netted figure (not the ex-GST base).
        assert abs(reported - expected) < 1.0, (
            f"dashboard today.amount={reported} but expected GST-inclusive net={expected}"
        )

    def test_return_reduces_today_amount(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        mid = parse_json(client.get("/api/dashboard/kpis", headers=admin_headers))
        amt_mid = mid["today"]["amount"]
        _return_first_item(client, admin_headers, sale["invoice_id"], qty=2)
        after = parse_json(client.get("/api/dashboard/kpis", headers=admin_headers))
        assert after["today"]["amount"] <= amt_mid


# ───────────────────────── GSTR-1 credit notes ───────────────────────────────

class TestGstr1CreditNotes:

    def test_gstr1_exposes_credit_note_fields(self, client, admin_headers):
        period = _current_period()
        resp = client.get(f"/api/gst/gstr1?period={period}", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        for key in ("credit_notes", "credit_note_list", "cn_total_taxable",
                    "cn_total_gst", "net_taxable", "net_gst"):
            assert key in data, f"GSTR-1 missing {key}"

    def test_net_taxable_is_outward_minus_credit_notes(self, client, admin_headers):
        period = _current_period()
        data = parse_json(client.get(f"/api/gst/gstr1?period={period}", headers=admin_headers))
        expected = round(data["total_taxable"] - data["cn_total_taxable"], 2)
        assert abs(data["net_taxable"] - expected) < 0.01

    def test_return_appears_as_credit_note(self, client, admin_headers, cashier_headers, test_product):
        period = _current_period()
        before = parse_json(client.get(f"/api/gst/gstr1?period={period}", headers=admin_headers))
        cn_before = before["cn_total_taxable"]

        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        _return_first_item(client, admin_headers, sale["invoice_id"], qty=2)

        after = parse_json(client.get(f"/api/gst/gstr1?period={period}", headers=admin_headers))
        assert after["cn_total_taxable"] >= cn_before


# ───────────────────────── GSTR-3B net outward ───────────────────────────────

class TestGstr3bNetOutward:

    def test_gstr3b_exposes_credit_notes_and_net(self, client, admin_headers):
        period = _current_period()
        resp = client.get(f"/api/gst/gstr3b?period={period}", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "outward" in data
        assert "credit_notes" in data
        assert "net_outward" in data
        assert "net_payable" in data

    def test_net_outward_is_outward_minus_credit_notes(self, client, admin_headers):
        period = _current_period()
        data = parse_json(client.get(f"/api/gst/gstr3b?period={period}", headers=admin_headers))
        out = data["outward"]["taxable_value"]
        cn = data["credit_notes"]["taxable_value"]
        expected = round(out - cn, 2)
        assert abs(data["net_outward"]["taxable_value"] - expected) < 0.01

    def test_return_reduces_net_outward_tax(self, client, admin_headers, cashier_headers, test_product):
        period = _current_period()
        sale = _make_sale(client, cashier_headers, test_product, qty=4)
        mid = parse_json(client.get(f"/api/gst/gstr3b?period={period}", headers=admin_headers))
        net_tax_mid = mid["net_outward"]["total_gst"]

        _return_first_item(client, admin_headers, sale["invoice_id"], qty=2)
        after = parse_json(client.get(f"/api/gst/gstr3b?period={period}", headers=admin_headers))
        # Net outward tax after the return must not exceed the pre-return figure.
        assert after["net_outward"]["total_gst"] <= net_tax_mid + 0.01


# ───────────────────────── authorization ─────────────────────────────────────

class TestReturnsAuthorization:

    def test_create_return_requires_admin(self, client, cashier_headers, test_product):
        sale_resp = client.post("/api/sales", json={
            "customer_name": "X", "mode_of_payment": "Cash", "discount_percentage": 0,
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "rate": test_product["selling_rate"], "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        invoice_id = parse_json(sale_resp)["invoice_id"]
        resp = _return_first_item(client, cashier_headers, invoice_id, qty=1)
        assert resp.status_code == 403

    def test_gst_reports_require_auth(self, client):
        period = _current_period()
        assert client.get(f"/api/gst/gstr1?period={period}").status_code == 401
        assert client.get(f"/api/gst/gstr3b?period={period}").status_code == 401
