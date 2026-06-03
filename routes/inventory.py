from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required
from psycopg2.extras import RealDictCursor

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/inventory', methods=['GET'])
@token_required
def get_inventory(payload):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT 
                p.product_id,
                p.name,
                p.sku,
                p.pack_size,
                p.selling_rate,
                p.gst_rate,
                i.stock_quantity
            FROM products p
            JOIN inventory i ON p.product_id = i.product_id
            ORDER BY p.name
        """)
        
        inventory = cur.fetchall()
        return jsonify(inventory), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch inventory', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@inventory_bp.route('/inventory/update', methods=['POST'])
@admin_required
def update_inventory(payload):
    data = request.get_json()
    product_id = data.get('product_id')
    quantity_change = data.get('quantity_change')  # Positive to add, negative to subtract
    
    if not product_id or quantity_change is None:
        return jsonify({'message': 'Product ID and quantity change are required'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Update inventory
        cur.execute("""
            UPDATE inventory 
            SET stock_quantity = stock_quantity + %s 
            WHERE product_id = %s
        """, (quantity_change, product_id))
        
        if cur.rowcount == 0:
            return jsonify({'message': 'Product not found in inventory'}), 404
            
        conn.commit()
        return jsonify({'message': 'Inventory updated successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to update inventory', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)