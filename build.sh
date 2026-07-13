#!/bin/bash
set -e

echo "============================================================"
echo "TrintzERP — Render build script"
echo "============================================================"

echo "Python version: $(python --version)"
echo "pip version:    $(pip --version)"

# ── Python dependencies ───────────────────────────────────────────────────────
echo ""
echo "Updating pip..."
pip install --upgrade pip

echo ""
echo "Installing Python requirements..."
pip install --prefer-binary --no-cache-dir -r requirements.txt

echo ""
echo "Installed packages:"
pip list

# ── Smoke-test PDF generation ─────────────────────────────────────────────────
echo ""
echo "Smoke-testing xhtml2pdf..."
python - <<'EOF'
try:
    from io import BytesIO
    from xhtml2pdf import pisa
    buf = BytesIO()
    result = pisa.CreatePDF('<p>TrintzERP OK</p>', dest=buf)
    assert not result.err and len(buf.getvalue()) > 100
    print("[PASS] xhtml2pdf rendered a test PDF successfully.")
except Exception as e:
    print(f"[WARN] xhtml2pdf smoke test failed: {e}")
    print("[WARN] PDF email attachments will fall back to HTML body.")
EOF

# ── Gunicorn check ────────────────────────────────────────────────────────────
echo ""
if command -v gunicorn &>/dev/null; then
    echo "gunicorn $(gunicorn --version) — ready."
else
    echo "[FAIL] gunicorn not found."
    exit 1
fi

echo ""
echo "============================================================"
echo "Build complete."
echo "============================================================"
