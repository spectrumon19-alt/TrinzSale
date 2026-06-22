import json
import logging
import time

import requests
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_db_connection, release_db_connection
from auth import token_required, admin_required

logger = logging.getLogger(__name__)
ai_settings_bp = Blueprint('ai_settings', __name__)

# ── Provider catalogue ────────────────────────────────────────────────────────
PROVIDERS = {
    'anthropic': {
        'name': 'Anthropic Claude',
        'icon': '🟣',
        'models': [
            'claude-opus-4-8',
            'claude-opus-4-7',
            'claude-sonnet-4-6',
            'claude-haiku-4-5',
            'claude-haiku-4-5-20251001',
        ],
        'needs_key': True,
        'needs_url': False,
        'url_label': None,
        'key_label': 'API Key',
        'key_placeholder': 'sk-ant-api03-…',
    },
    'openai': {
        'name': 'OpenAI',
        'icon': '🟢',
        'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo', 'o1-mini'],
        'needs_key': True,
        'needs_url': True,
        'url_label': 'Base URL (optional – leave blank for default)',
        'url_placeholder': 'https://api.openai.com/v1',
        'key_label': 'API Key',
        'key_placeholder': 'sk-…',
    },
    'ollama': {
        'name': 'Ollama',
        'icon': '🦙',
        'models': [],
        'needs_key': True,
        'needs_url': True,
        'url_label': 'Ollama Server URL',
        'url_placeholder': 'http://localhost:11434',
        'key_label': 'API Key (optional – cloud / authenticated Ollama only)',
        'key_placeholder': 'Leave blank for local Ollama',
        'ollama_fetch_models': True,
        'presets': {
            'Local':        ('http://localhost:11434', ''),
            'Ollama Cloud': ('https://ollama.com',    ''),
        },
        'setup_note': (
            'Click "Fetch Models" after entering the server URL to load available models. '
            'For cloud Ollama (ollama.com) set your OLLAMA_API_KEY. '
            'Local Ollama needs no key.'
        ),
    },
    'groq': {
        'name': 'Groq',
        'icon': '⚡',
        'models': [
            'llama-3.3-70b-versatile',
            'llama-3.1-8b-instant',
            'mixtral-8x7b-32768',
            'gemma2-9b-it',
        ],
        'needs_key': True,
        'needs_url': False,
        'url_label': None,
        'key_label': 'API Key',
        'key_placeholder': 'gsk_…',
    },
    'gemini': {
        'name': 'Google Gemini',
        'icon': '💎',
        'models': [
            'gemini-2.0-flash',
            'gemini-1.5-pro',
            'gemini-1.5-flash',
            'gemini-2.0-flash-lite',
        ],
        'needs_key': True,
        'needs_url': False,
        'url_label': None,
        'key_label': 'API Key',
        'key_placeholder': 'AIza…',
    },
    'minimax': {
        'name': 'MiniMax (MoMo)',
        'icon': '🈲',
        'models': ['MiniMax-Text-01', 'abab6.5s-chat', 'abab6.5g-chat'],
        'needs_key': True,
        'needs_url': False,
        'url_label': None,
        'key_label': 'API Key',
        'key_placeholder': 'eyJ…',
        'extra_fields': [{'key': 'group_id', 'label': 'Group ID', 'placeholder': '123456789'}],
    },
    'together': {
        'name': 'Together AI',
        'icon': '🤝',
        'models': [
            'meta-llama/Llama-3.3-70B-Instruct-Turbo',
            'mistralai/Mixtral-8x7B-Instruct-v0.1',
            'google/gemma-2-9b-it',
            'Qwen/Qwen2.5-72B-Instruct-Turbo',
        ],
        'needs_key': True,
        'needs_url': False,
        'url_label': None,
        'key_label': 'API Key',
        'key_placeholder': '…',
    },
    'mistral': {
        'name': 'Mistral AI',
        'icon': '🌬️',
        'models': ['mistral-large-latest', 'mistral-small-latest', 'open-mistral-7b'],
        'needs_key': True,
        'needs_url': False,
        'url_label': None,
        'key_label': 'API Key',
        'key_placeholder': '…',
    },
    'mimo': {
        'name': 'Xiaomi MiMo',
        'icon': '🤖',
        'models': [
            'mimo-v2.5',
            'mimo-v2-omni',
            'xiaomi/mimo-v2.5',
            'xiaomi/mimo-v2-omni',
        ],
        'needs_key': True,
        'needs_url': True,
        'url_label': 'API Base URL',
        'url_placeholder': 'https://api.xiaomimimo.com/v1',
        'key_label': 'Platform API Key',
        'key_placeholder': 'Get key from platform.xiaomimimo.com',
        'presets': {
            'Xiaomi Official': ('https://api.xiaomimimo.com/v1',   'mimo-v2.5'),
            'OpenRouter':      ('https://openrouter.ai/api/v1',    'xiaomi/mimo-v2.5'),
            'WaveSpeed':       ('https://llm.wavespeed.ai/v1',     'xiaomi/mimo-v2.5'),
        },
        'setup_note': (
            'Use vision-capable models only (mimo-v2.5, mimo-v2-omni). '
            'Skip mimo-v2-flash / mimo-v2-pro — text-only, no tool support. '
            'Get your API key at platform.xiaomimimo.com.'
        ),
    },
}

# ── Ensure table exists ───────────────────────────────────────────────────────
_TABLE_CREATED = False


def _ensure_table(conn, cur):
    global _TABLE_CREATED
    if _TABLE_CREATED:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_settings (
            id           SERIAL PRIMARY KEY,
            provider     VARCHAR(32) NOT NULL,
            display_name VARCHAR(100) NOT NULL,
            api_key      TEXT DEFAULT '',
            api_base_url VARCHAR(500) DEFAULT '',
            model        VARCHAR(150) NOT NULL,
            is_active    BOOLEAN DEFAULT FALSE,
            extra_config JSONB DEFAULT '{}',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    _TABLE_CREATED = True


# ── Helper: mask key ──────────────────────────────────────────────────────────
def _mask(key: str) -> str:
    if not key or len(key) < 8:
        return '••••••••'
    return key[:4] + '••••••••' + key[-4:]


# ── Helper: reject obviously-invalid keys before they reach the DB ────────────
def _validate_key(provider: str, key: str):
    """Return an error string if the key is clearly not a valid key, else None.
    Guards against pasting error text / partial keys into the key field."""
    key = key or ''
    if any(ch.isspace() for ch in key):
        return 'API key contains spaces or line breaks — paste the key only, with no surrounding text.'
    if any(ord(c) > 127 for c in key):
        return 'API key contains hidden non-ASCII characters — re-copy it directly from the provider console.'
    if provider == 'anthropic':
        if not key.startswith('sk-ant-'):
            return 'Anthropic keys start with "sk-ant-". The value you pasted does not look like an API key.'
        if len(key) < 40:
            return 'Anthropic key looks truncated — copy the full key from console.anthropic.com.'
    return None


# ── Helper: call any provider ─────────────────────────────────────────────────
def _log_token_usage(provider: str, model: str, feature: str,
                      prompt_tokens: int, output_tokens: int,
                      user_id=None, username: str = '') -> None:
    """Fire-and-forget insert into ai_token_usage. Errors are suppressed."""
    try:
        from db import get_db_connection, release_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ai_token_usage
                        (user_id, username, provider, model, feature,
                         prompt_tokens, output_tokens, total_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, username or '', provider, model, feature,
                      prompt_tokens, output_tokens, prompt_tokens + output_tokens))
            conn.commit()
        finally:
            release_db_connection(conn)
    except Exception:
        pass  # never break the caller over analytics


def call_provider(config: dict, system: str, user_msg: str, max_tokens: int = 1024,
                  feature: str = 'chat', user_id=None, username: str = '') -> str:
    """Call the configured LLM provider and log token usage to ai_token_usage."""
    provider = config.get('provider', '')
    api_key  = config.get('api_key', '')
    model    = config.get('model', '')
    base_url = (config.get('api_base_url') or '').rstrip('/')
    extra    = config.get('extra_config') or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    if provider == 'anthropic':
        import anthropic
        key = (api_key or '').strip()
        if not key:
            raise RuntimeError('Anthropic API key is missing. Paste your sk-ant-… key and save.')
        if not model:
            raise RuntimeError('No Claude model selected. Pick a model (e.g. claude-sonnet-4-6).')
        client = anthropic.Anthropic(api_key=key)
        try:
            msg = client.messages.create(
                model=model, max_tokens=max_tokens,
                system=system,
                messages=[{'role': 'user', 'content': user_msg}],
            )
        except anthropic.AuthenticationError:
            raise RuntimeError('Invalid Anthropic API key (401). Check the key is correct and active.')
        except anthropic.PermissionDeniedError:
            raise RuntimeError(f'API key lacks access to "{model}" (403). Enable the model for your org or pick another.')
        except anthropic.NotFoundError:
            raise RuntimeError(f'Model "{model}" not found (404). It may be retired — pick a current model like claude-sonnet-4-6.')
        except anthropic.RateLimitError:
            raise RuntimeError('Anthropic rate limit hit (429). Wait a moment and try again.')
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f'Could not reach Anthropic (network/SSL/proxy). {e}')
        pt = getattr(msg.usage, 'input_tokens', 0)
        ot = getattr(msg.usage, 'output_tokens', 0)
        _log_token_usage(provider, model, feature, pt, ot, user_id, username)
        return msg.content[0].text.strip()

    elif provider == 'mimo':
        base = base_url or 'http://localhost:8000/v1'
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        r = requests.post(
            f'{base}/chat/completions',
            headers=headers,
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user_msg},
                ],
                'max_tokens': max_tokens,
                'temperature': 0.1,
            },
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log_token_usage(provider, model, feature,
                         usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                         user_id, username)
        return data['choices'][0]['message']['content'].strip()

    elif provider in ('openai', 'together', 'mistral'):
        base = {
            'openai':   'https://api.openai.com/v1',
            'together': 'https://api.together.xyz/v1',
            'mistral':  'https://api.mistral.ai/v1',
        }[provider]
        if provider == 'openai' and base_url:
            base = base_url
        r = requests.post(
            f'{base}/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user_msg},
                ],
                'max_tokens': max_tokens,
                'temperature': 0.1,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log_token_usage(provider, model, feature,
                         usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                         user_id, username)
        return data['choices'][0]['message']['content'].strip()

    elif provider == 'groq':
        r = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user_msg},
                ],
                'max_tokens': max_tokens,
                'temperature': 0.1,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log_token_usage(provider, model, feature,
                         usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                         user_id, username)
        return data['choices'][0]['message']['content'].strip()

    elif provider == 'ollama':
        base = base_url or 'http://localhost:11434'
        hdrs = {'Content-Type': 'application/json'}
        if api_key:
            hdrs['Authorization'] = f'Bearer {api_key}'
        r = requests.post(
            f'{base}/api/chat',
            headers=hdrs,
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user_msg},
                ],
                'stream': False,
                'options': {'num_predict': max_tokens},
            },
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        pt = data.get('prompt_eval_count', 0)
        ot = data.get('eval_count', 0)
        _log_token_usage(provider, model, feature, pt, ot, user_id, username)
        return data['message']['content'].strip()

    elif provider == 'gemini':
        r = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
            json={
                'contents': [{'parts': [{'text': f'{system}\n\n{user_msg}'}]}],
                'generationConfig': {'maxOutputTokens': max_tokens, 'temperature': 0.1},
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        meta = data.get('usageMetadata', {})
        _log_token_usage(provider, model, feature,
                         meta.get('promptTokenCount', 0), meta.get('candidatesTokenCount', 0),
                         user_id, username)
        return data['candidates'][0]['content']['parts'][0]['text'].strip()

    elif provider == 'minimax':
        r = requests.post(
            'https://api.minimax.chat/v1/text/chatcompletion_v2',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user_msg},
                ],
                'max_tokens': max_tokens,
                'temperature': 0.1,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log_token_usage(provider, model, feature,
                         usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                         user_id, username)
        return data['choices'][0]['message']['content'].strip()

    else:
        raise RuntimeError(f'Unknown AI provider: {provider}')


# ── GET /api/ai/settings ──────────────────────────────────────────────────────
@ai_settings_bp.route('/ai/settings', methods=['GET'])
@admin_required
def list_settings(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_table(conn, cur)
            cur.execute('SELECT * FROM ai_settings ORDER BY is_active DESC, id')
            rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['api_key_masked'] = _mask(d.get('api_key', ''))
            d['api_key'] = ''  # never send key to frontend
            result.append(d)
        return jsonify({'configs': result, 'providers': PROVIDERS})
    finally:
        release_db_connection(conn)


# ── POST /api/ai/settings ─────────────────────────────────────────────────────
@ai_settings_bp.route('/ai/settings', methods=['POST'])
@admin_required
def create_setting(current_user):
    body = request.get_json(force=True, silent=True) or {}
    provider     = (body.get('provider') or '').strip()
    display_name = (body.get('display_name') or '').strip()
    model        = (body.get('model') or '').strip()
    api_key      = (body.get('api_key') or '').strip()
    api_base_url = (body.get('api_base_url') or '').strip()
    extra_config = body.get('extra_config') or {}

    if not provider or provider not in PROVIDERS:
        return jsonify({'error': 'Invalid provider'}), 400
    if not display_name:
        return jsonify({'error': 'Display name is required'}), 400
    if not model:
        return jsonify({'error': 'Model is required'}), 400
    if api_key:
        key_err = _validate_key(provider, api_key)
        if key_err:
            return jsonify({'error': key_err}), 400

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_table(conn, cur)
            cur.execute("""
                INSERT INTO ai_settings (provider, display_name, api_key, api_base_url, model, extra_config)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """, (provider, display_name, api_key, api_base_url, model,
                  json.dumps(extra_config)))
            new_id = cur.fetchone()['id']
            conn.commit()
        return jsonify({'id': new_id, 'message': 'AI configuration saved.'})
    finally:
        release_db_connection(conn)


# ── PUT /api/ai/settings/<id> ─────────────────────────────────────────────────
@ai_settings_bp.route('/ai/settings/<int:cfg_id>', methods=['PUT'])
@admin_required
def update_setting(current_user, cfg_id):
    body = request.get_json(force=True, silent=True) or {}
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_table(conn, cur)
            cur.execute('SELECT * FROM ai_settings WHERE id=%s', (cfg_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Not found'}), 404

            display_name = (body.get('display_name') or row['display_name']).strip()
            model        = (body.get('model') or row['model']).strip()
            api_base_url = (body.get('api_base_url') or row['api_base_url'] or '').strip()
            extra_config = body.get('extra_config', row.get('extra_config') or {})
            # Only update key if provided (non-empty)
            new_key = (body.get('api_key') or '').strip()
            if new_key:
                key_err = _validate_key(row['provider'], new_key)
                if key_err:
                    return jsonify({'error': key_err}), 400
            api_key = new_key if new_key else row['api_key']

            cur.execute("""
                UPDATE ai_settings
                SET display_name=%s, model=%s, api_key=%s, api_base_url=%s,
                    extra_config=%s, updated_at=NOW()
                WHERE id=%s
            """, (display_name, model, api_key, api_base_url,
                  json.dumps(extra_config), cfg_id))
            conn.commit()
        return jsonify({'message': 'Updated successfully.'})
    finally:
        release_db_connection(conn)


# ── DELETE /api/ai/settings/<id> ──────────────────────────────────────────────
@ai_settings_bp.route('/ai/settings/<int:cfg_id>', methods=['DELETE'])
@admin_required
def delete_setting(current_user, cfg_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            _ensure_table(conn, cur)
            cur.execute('DELETE FROM ai_settings WHERE id=%s', (cfg_id,))
            conn.commit()
        return jsonify({'message': 'Deleted.'})
    finally:
        release_db_connection(conn)


# ── POST /api/ai/settings/<id>/activate ───────────────────────────────────────
@ai_settings_bp.route('/ai/settings/<int:cfg_id>/activate', methods=['POST'])
@admin_required
def activate_setting(current_user, cfg_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            _ensure_table(conn, cur)
            cur.execute('UPDATE ai_settings SET is_active=FALSE')
            cur.execute('UPDATE ai_settings SET is_active=TRUE, updated_at=NOW() WHERE id=%s', (cfg_id,))
            conn.commit()
        return jsonify({'message': 'Activated successfully.'})
    finally:
        release_db_connection(conn)


# ── POST /api/ai/settings/test ────────────────────────────────────────────────
@ai_settings_bp.route('/ai/settings/test', methods=['POST'])
@admin_required
def test_connection(current_user):
    body = request.get_json(force=True, silent=True) or {}
    cfg_id = body.get('id')

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_table(conn, cur)
            if cfg_id:
                cur.execute('SELECT * FROM ai_settings WHERE id=%s', (cfg_id,))
                row = cur.fetchone()
                if not row:
                    return jsonify({'ok': False, 'error': 'Configuration not found'}), 404
                config = dict(row)
                # Allow overriding key from body (for unsaved configs)
                if body.get('api_key'):
                    config['api_key'] = body['api_key']
            else:
                # Inline test (for new/unsaved config)
                config = {
                    'provider':     body.get('provider', ''),
                    'api_key':      body.get('api_key', ''),
                    'api_base_url': body.get('api_base_url', ''),
                    'model':        body.get('model', ''),
                    'extra_config': body.get('extra_config', {}),
                }
    finally:
        release_db_connection(conn)

    if not config.get('provider'):
        return jsonify({'ok': False, 'error': 'Provider is required'}), 400

    # ── Non-secret key diagnostic: pinpoints corrupted/partial keys without
    #    ever exposing the key itself. Reports length, visible prefix/suffix,
    #    and flags any hidden/non-ASCII characters or interior whitespace.
    raw_key = config.get('api_key') or ''
    stripped = raw_key.strip()
    has_interior_ws = any(ch.isspace() for ch in stripped)
    non_ascii = [hex(ord(c)) for c in stripped if ord(c) > 127][:5]
    key_diag = {
        'length':            len(raw_key),
        'length_stripped':   len(stripped),
        'prefix':            stripped[:7],
        'suffix':            stripped[-4:] if len(stripped) >= 4 else '',
        'had_outer_ws':      raw_key != stripped,
        'has_interior_ws':   has_interior_ws,
        'non_ascii_codes':   non_ascii,
        'starts_with_skant': stripped.startswith('sk-ant-'),
    }

    start = time.time()
    try:
        response = call_provider(
            config,
            'You are a helpful assistant. Reply very briefly.',
            'Respond with exactly two words: "Connection OK"',
            max_tokens=20,
        )
        latency_ms = round((time.time() - start) * 1000)
        return jsonify({'ok': True, 'response': response, 'latency_ms': latency_ms})
    except Exception as e:
        logger.warning('AI test failed: %s', e)
        return jsonify({
            'ok': False,
            'error': str(e),
            'latency_ms': round((time.time() - start) * 1000),
            'key_diag': key_diag,
        })


# ── GET /api/ai/active ────────────────────────────────────────────────────────
@ai_settings_bp.route('/ai/active', methods=['GET'])
@token_required
def get_active(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_table(conn, cur)
            cur.execute("""
                SELECT id, provider, display_name, model, is_active
                FROM ai_settings WHERE is_active=TRUE LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                prov = PROVIDERS.get(row['provider'], {})
                return jsonify({
                    'configured': True,
                    'id': row['id'],
                    'provider': row['provider'],
                    'provider_name': prov.get('name', row['provider']),
                    'display_name': row['display_name'],
                    'model': row['model'],
                })
            return jsonify({'configured': False})
    finally:
        release_db_connection(conn)


# ── GET /api/ai/ollama/models ─────────────────────────────────────────────────
@ai_settings_bp.route('/ai/ollama/models', methods=['GET'])
@admin_required
def ollama_list_models(current_user):
    """Proxy to Ollama /api/tags — returns list of locally available model names."""
    url     = (request.args.get('url') or 'http://localhost:11434').rstrip('/')
    api_key = (request.args.get('api_key') or '').strip()

    hdrs = {}
    if api_key:
        hdrs['Authorization'] = f'Bearer {api_key}'

    try:
        r = requests.get(f'{url}/api/tags', headers=hdrs, timeout=10)
        r.raise_for_status()
        data   = r.json()
        models = sorted(m['name'] for m in data.get('models', []))
        return jsonify({'models': models, 'count': len(models)})
    except requests.exceptions.ConnectionError:
        return jsonify({'error': f'Cannot connect to Ollama at {url}. Is Ollama running?'}), 502
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timed out. Ollama server may be slow or unreachable.'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
