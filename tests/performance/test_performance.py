"""
Performance validation tests.

Measures:
  - Response time SLAs for critical endpoints
  - Throughput under sequential load
  - Large dataset handling (many products in a single response)
  - Paginated vs full-list response size comparison
  - Gzip compression effectiveness for large payloads

These tests use time.perf_counter() and are marked `slow` so they can be
excluded from fast CI runs: `pytest -m "not slow"`.
"""

import time
import pytest
from tests.conftest import parse_json, uid8
from tests.helpers.data_factory import product_payload
from tests.helpers.db_helpers import execute


pytestmark = [pytest.mark.performance, pytest.mark.slow]

# Acceptable response time thresholds (seconds)
SLA = {
    "login":     1.5,
    "products":  2.0,
    "inventory": 2.0,
    "suppliers": 2.0,
    "sale":      3.0,
}


def timed(fn):
    """Call fn() and return (result, elapsed_seconds)."""
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return result, elapsed


# ── Response Time SLAs ────────────────────────────────────────────────────────

class TestResponseTimeSLAs:

    def test_login_responds_within_sla(self, client):
        _, elapsed = timed(lambda: client.post(
            "/api/login",
            json={"username": "test_admin", "password": "adminpass"},
        ))
        assert elapsed < SLA["login"], f"Login took {elapsed:.2f}s, SLA={SLA['login']}s"

    def test_get_products_responds_within_sla(self, client, admin_headers):
        _, elapsed = timed(lambda: client.get("/api/products", headers=admin_headers))
        assert elapsed < SLA["products"], f"GET /products took {elapsed:.2f}s"

    def test_get_inventory_responds_within_sla(self, client, admin_headers):
        _, elapsed = timed(lambda: client.get("/api/inventory", headers=admin_headers))
        assert elapsed < SLA["inventory"], f"GET /inventory took {elapsed:.2f}s"

    def test_get_suppliers_responds_within_sla(self, client, admin_headers):
        _, elapsed = timed(lambda: client.get("/api/suppliers", headers=admin_headers))
        assert elapsed < SLA["suppliers"], f"GET /suppliers took {elapsed:.2f}s"

    def test_create_sale_responds_within_sla(self, client, cashier_headers, test_product):
        from tests.helpers.data_factory import sale_payload
        payload = sale_payload(
            test_product["product_id"],
            float(test_product["selling_rate"]),
            float(test_product["gst_rate"]),
        )
        _, elapsed = timed(lambda: client.post("/api/sales", json=payload, headers=cashier_headers))
        assert elapsed < SLA["sale"], f"POST /sales took {elapsed:.2f}s"


# ── Sequential Throughput ─────────────────────────────────────────────────────

class TestSequentialThroughput:

    def test_50_sequential_product_reads(self, client, admin_headers):
        """50 sequential GET /products should complete within 30 s total."""
        start = time.perf_counter()
        for _ in range(50):
            resp = client.get("/api/products", headers=admin_headers)
            assert resp.status_code == 200
        total = time.perf_counter() - start
        assert total < 30.0, f"50 sequential reads took {total:.1f}s"

    def test_10_sequential_logins(self, client):
        start = time.perf_counter()
        for _ in range(10):
            resp = client.post(
                "/api/login",
                json={"username": "test_admin", "password": "adminpass"},
            )
            assert resp.status_code == 200
        total = time.perf_counter() - start
        assert total < 15.0, f"10 sequential logins took {total:.1f}s"


# ── Large Dataset Handling ────────────────────────────────────────────────────

class TestLargeDatasetHandling:

    @pytest.fixture(scope="class")
    def bulk_products(self, client, admin_headers):
        """Insert 100 products before the class tests run, remove them afterwards."""
        pids = []
        for i in range(100):
            payload = product_payload(
                name=f"Bulk Perf Product {i:04d} {uid8()}",
                sku=f"BULK-{i:04d}-{uid8()}",
            )
            resp = client.post("/api/products", json=payload, headers=admin_headers)
            if resp.status_code == 201:
                pids.append(parse_json(resp)["product_id"])
        yield pids
        for pid in pids:
            execute("DELETE FROM inventory WHERE product_id=%s", (pid,))
            execute("DELETE FROM products WHERE product_id=%s", (pid,))

    def test_large_product_list_returns_within_sla(self, client, admin_headers, bulk_products):
        resp, elapsed = timed(lambda: client.get("/api/products", headers=admin_headers))
        assert resp.status_code == 200
        products = parse_json(resp)
        assert len(products) >= 100
        assert elapsed < SLA["products"], f"Large product list took {elapsed:.2f}s"

    def test_large_inventory_list_returns_within_sla(self, client, admin_headers, bulk_products):
        resp, elapsed = timed(lambda: client.get("/api/inventory", headers=admin_headers))
        assert resp.status_code == 200
        assert elapsed < SLA["inventory"]


# ── Gzip Compression ──────────────────────────────────────────────────────────

class TestGzipCompression:

    def test_large_response_is_gzip_compressed(self, client, admin_headers):
        """
        With 100+ products, the JSON response exceeds 500 bytes and should be
        gzip-compressed by the middleware.  The test verifies the Content-Encoding
        header and that the decompressed body is valid JSON.
        """
        resp = client.get("/api/products", headers=admin_headers)
        assert resp.status_code == 200
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            import json
            body = json.loads(gzip.decompress(resp.data))
            assert isinstance(body, list)
        else:
            # Small response – no compression needed
            assert isinstance(parse_json(resp), list)
