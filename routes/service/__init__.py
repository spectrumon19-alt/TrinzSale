"""Service blueprint package. Split from monolithic routes/service.py.
All URL paths unchanged; shared helpers live in _helpers.py."""
from .status import service_status_bp
from .backup import service_backup_bp
from .logs import service_logs_bp
from .sql import service_sql_bp
from .dbconfig import service_dbconfig_bp

SERVICE_BLUEPRINTS = [
    service_status_bp,
    service_backup_bp,
    service_logs_bp,
    service_sql_bp,
    service_dbconfig_bp,
]
