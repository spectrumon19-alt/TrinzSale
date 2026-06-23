"""Reports blueprint package. Split from monolithic routes/reports.py
into one module per report domain. All URL paths unchanged."""
from .sales import reports_sales_bp
from .purchase import reports_purchase_bp
from .inventory import reports_inventory_bp
from .profit_loss import reports_pl_bp

REPORTS_BLUEPRINTS = [
    reports_sales_bp,
    reports_purchase_bp,
    reports_inventory_bp,
    reports_pl_bp,
]
