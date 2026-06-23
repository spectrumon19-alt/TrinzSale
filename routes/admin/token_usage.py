from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

admin_tokens_bp = Blueprint('admin_tokens', __name__)

# ============================================================
# AI TOKEN USAGE ENDPOINTS
# ============================================================

def _ensure_token_usage_table(conn):
    with conn.cursor() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_token_usage (
                id              SERIAL       PRIMARY KEY,
                called_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id         INTEGER      REFERENCES users(user_id) ON DELETE SET NULL,
                username        VARCHAR(100),
                provider        VARCHAR(50)  NOT NULL DEFAULT '',
                model           VARCHAR(150) NOT NULL DEFAULT '',
                feature         VARCHAR(100) NOT NULL DEFAULT 'chat',
                prompt_tokens   INTEGER      NOT NULL DEFAULT 0,
                output_tokens   INTEGER      NOT NULL DEFAULT 0,
                total_tokens    INTEGER      NOT NULL DEFAULT 0
            )
        """)
    conn.commit()


@admin_tokens_bp.route('/admin/token-usage/summary', methods=['GET'])
@admin_required
def token_usage_summary(payload):
    """KPI summary + daily chart + by-user + by-model/provider breakdown."""
    days = request.args.get('days', 30, type=int)
    conn = cur = None
    try:
        conn = get_db_connection()
        _ensure_token_usage_table(conn)
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        # ── KPIs ──────────────────────────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(SUM(total_tokens), 0)  AS total_tokens,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COUNT(*)                         AS ai_calls,
                COUNT(DISTINCT user_id)          AS active_users
            FROM ai_token_usage
            WHERE called_at >= NOW() - INTERVAL '%s days'
        """, (days,))
        kpis = dict(cur.fetchone())

        # ── Daily consumption ─────────────────────────────────────────────────
        cur.execute("""
            SELECT
                DATE(called_at AT TIME ZONE 'UTC')      AS day,
                COALESCE(SUM(prompt_tokens), 0)         AS prompt_tokens,
                COALESCE(SUM(output_tokens), 0)         AS output_tokens,
                COALESCE(SUM(total_tokens), 0)          AS total_tokens,
                COUNT(*)                                 AS calls
            FROM ai_token_usage
            WHERE called_at >= NOW() - INTERVAL '%s days'
            GROUP BY day
            ORDER BY day
        """, (days,))
        daily = [dict(r) for r in cur.fetchall()]

        # ── By user ───────────────────────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(u.username, tu.username, 'Unknown') AS username,
                COALESCE(u.full_name, '')                    AS full_name,
                COUNT(*)                                      AS calls,
                COALESCE(SUM(tu.prompt_tokens), 0)           AS prompt_tokens,
                COALESCE(SUM(tu.output_tokens), 0)           AS output_tokens,
                COALESCE(SUM(tu.total_tokens), 0)            AS total_tokens
            FROM ai_token_usage tu
            LEFT JOIN users u ON tu.user_id = u.user_id
            WHERE tu.called_at >= NOW() - INTERVAL '%s days'
            GROUP BY u.username, tu.username, u.full_name
            ORDER BY total_tokens DESC
        """, (days,))
        by_user = [dict(r) for r in cur.fetchall()]

        # ── By provider + model ───────────────────────────────────────────────
        cur.execute("""
            SELECT
                provider,
                model,
                COUNT(*)                         AS calls,
                COALESCE(SUM(total_tokens), 0)   AS total_tokens
            FROM ai_token_usage
            WHERE called_at >= NOW() - INTERVAL '%s days'
            GROUP BY provider, model
            ORDER BY total_tokens DESC
        """, (days,))
        by_model = [dict(r) for r in cur.fetchall()]

        # ── By feature ────────────────────────────────────────────────────────
        cur.execute("""
            SELECT
                feature,
                COUNT(*)                         AS calls,
                COALESCE(SUM(total_tokens), 0)   AS total_tokens
            FROM ai_token_usage
            WHERE called_at >= NOW() - INTERVAL '%s days'
            GROUP BY feature
            ORDER BY total_tokens DESC
        """, (days,))
        by_feature = [dict(r) for r in cur.fetchall()]

        # ── Recent activity ───────────────────────────────────────────────────
        cur.execute("""
            SELECT
                tu.called_at,
                COALESCE(u.username, tu.username, 'Unknown') AS username,
                tu.provider,
                tu.model,
                tu.feature,
                tu.prompt_tokens,
                tu.output_tokens,
                tu.total_tokens
            FROM ai_token_usage tu
            LEFT JOIN users u ON tu.user_id = u.user_id
            WHERE tu.called_at >= NOW() - INTERVAL '%s days'
            ORDER BY tu.called_at DESC
            LIMIT 100
        """, (days,))
        recent = [dict(r) for r in cur.fetchall()]

        return jsonify({
            'kpis':       kpis,
            'daily':      daily,
            'by_user':    by_user,
            'by_model':   by_model,
            'by_feature': by_feature,
            'recent':     recent,
        }), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: release_db_connection(conn)


@admin_tokens_bp.route('/admin/token-usage/purge', methods=['DELETE'])
@admin_required
def purge_token_usage(payload):
    days = request.args.get('days', 90, type=int)
    if days < 1:
        return jsonify({'error': 'days must be >= 1'}), 400
    conn = cur = None
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "DELETE FROM ai_token_usage WHERE called_at < NOW() - INTERVAL '%s days'",
            (days,)
        )
        deleted = cur.rowcount
        conn.commit()
        return jsonify({'success': True, 'deleted': deleted}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: release_db_connection(conn)
