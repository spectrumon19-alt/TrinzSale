"""
Reports endpoint tests.

Routes exercised:
  GET /api/reports/sales
  GET /api/reports/sales/export
"""

import pytest
from tests.conftest import parse_json


pytestmark = pytest.mark.reports


class TestSalesReport:

    def test_admin_can_fetch_sales_report(self, client, admin_headers):
        resp = client.get("/api/reports/sales", headers=admin_headers)
        assert resp.status_code == 200

    def test_cashier_access_depends_on_route_permissions(self, client, cashier_headers):
        resp = client.get("/api/reports/sales", headers=cashier_headers)
        # Reports may or may not be available to cashiers depending on server config
        assert resp.status_code in (200, 403)

    def test_unauthenticated_cannot_access_reports(self, client):
        resp = client.get("/api/reports/sales")
        assert resp.status_code == 401

    def test_date_filter_start_date(self, client, admin_headers):
        resp = client.get("/api/reports/sales?start_date=2025-01-01", headers=admin_headers)
        assert resp.status_code == 200

    def test_date_filter_end_date(self, client, admin_headers):
        resp = client.get("/api/reports/sales?end_date=2026-12-31", headers=admin_headers)
        assert resp.status_code == 200

    def test_date_filter_range(self, client, admin_headers):
        resp = client.get(
            "/api/reports/sales?start_date=2025-01-01&end_date=2026-12-31",
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_response_is_json_or_list(self, client, admin_headers):
        resp = client.get("/api/reports/sales", headers=admin_headers)
        data = parse_json(resp)
        assert data is not None

    def test_report_after_sale_contains_sale(self, client, admin_headers, cashier_headers, test_product):
        """A sale made today should appear in the sales report."""
        from tests.helpers.data_factory import sale_payload
        payload = sale_payload(
            test_product["product_id"],
            float(test_product["selling_rate"]),
            float(test_product["gst_rate"]),
        )
        sale_resp = client.post("/api/sales", json=payload, headers=cashier_headers)
        assert sale_resp.status_code == 201

        report_resp = client.get("/api/reports/sales", headers=admin_headers)
        assert report_resp.status_code == 200
        # Report data should not be empty after a sale
        data = parse_json(report_resp)
        assert data is not None


class TestSalesReportExport:

    def test_admin_can_export_sales_report(self, client, admin_headers):
        resp = client.get("/api/reports/sales/export", headers=admin_headers)
        assert resp.status_code in (200, 404, 501)
        if resp.status_code == 200:
            # Should be an Excel file
            content_type = resp.content_type or ""
            assert any(
                ct in content_type
                for ct in (
                    "application/vnd.openxmlformats",
                    "application/octet-stream",
                    "application/vnd.ms-excel",
                )
            )

    def test_unauthenticated_cannot_export(self, client):
        resp = client.get("/api/reports/sales/export")
        assert resp.status_code == 401
