from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import admin_required
from psycopg2.extras import RealDictCursor
import os
import shutil
import datetime
import platform
import re

service_logs_bp = Blueprint('service_logs', __name__)

@service_logs_bp.route('/admin/service/logs', methods=['GET'])
@admin_required
def get_logs(payload):
    """Get system logs"""
    try:
        # In a real implementation, this would read from actual log files
        # For now, we'll return simulated log data
        log_level = request.args.get('level', 'all')
        
        # Simulated logs
        logs = [
            {"timestamp": "2023-06-15T10:30:15", "level": "INFO", "message": "System started successfully"},
            {"timestamp": "2023-06-15T10:32:45", "level": "INFO", "message": "User admin logged in"},
            {"timestamp": "2023-06-15T10:45:22", "level": "WARNING", "message": "Low disk space (15% remaining)"},
            {"timestamp": "2023-06-15T11:15:33", "level": "INFO", "message": "Database backup completed"},
            {"timestamp": "2023-06-15T12:05:17", "level": "ERROR", "message": "Failed to connect to external API"},
            {"timestamp": "2023-06-15T12:05:18", "level": "INFO", "message": "Retrying API connection"},
            {"timestamp": "2023-06-15T12:05:20", "level": "INFO", "message": "API connection restored"},
            {"timestamp": "2023-06-15T14:22:05", "level": "INFO", "message": "New sale recorded (Invoice #INV-2023-0015)"},
            {"timestamp": "2023-06-15T15:40:11", "level": "INFO", "message": "Inventory updated for Product ID 123"},
            {"timestamp": "2023-06-15T16:15:27", "level": "WARNING", "message": "High memory usage detected (85%)"},
            {"timestamp": "2023-06-15T17:30:44", "level": "INFO", "message": "Daily report generated"}
        ]
        
        # Filter logs by level if specified
        if log_level != 'all':
            logs = [log for log in logs if log['level'].lower() == log_level.lower()]
        
        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving logs: {str(e)}'
        }), 500
