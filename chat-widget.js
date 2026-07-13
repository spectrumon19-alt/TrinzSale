/* TrintzERP AI Chat Widget — self-contained IIFE, no external deps */
(function () {
  'use strict';

  // ── Prevent double-init ───────────────────────────────────────────────────
  if (window._posChatInitialized) return;
  window._posChatInitialized = true;

  // ── RBAC permission gate ──────────────────────────────────────────────────
  // Admin-tier users always have access; Cashier users need explicit ai-chat permission.
  (function () {
    var user = (typeof getCurrentUser === 'function') ? getCurrentUser() : null;
    if (!user) return; // not logged in — widget will be a no-op anyway
    var adminTier = (user.role === 'Admin' || user.role === 'Super Admin' || user.role === 'Manager');
    if (adminTier) return; // always allowed
    try {
      var cached = localStorage.getItem('pos_permissions');
      if (cached) {
        var perms = JSON.parse(cached);
        if (!perms._admin && perms['ai-chat'] !== true) {
          window._posChatInitialized = false; // allow re-init if permissions change
          throw new Error('no-perm');
        }
      }
      // If no cache yet, allow — page auth will handle it; widget will be harmless
    } catch (e) {
      if (e.message === 'no-perm') { return (window._posChatBlocked = true); }
    }
  })();
  if (window._posChatBlocked) return;

  // ── Config ────────────────────────────────────────────────────────────────
  var ENDPOINT_CHAT   = '/api/chat';
  var ENDPOINT_EXPORT = '/api/chat/export';
  var EXAMPLES = [
    "Top 10 selling products this month",
    "Today's total sales and revenue",
    "Sales by payment method this week",
    "Products with low stock (< 10 units)",
    "Top 5 customers by total purchase",
    "GST collected in current financial year",
  ];

  // ── Inject CSS ────────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = [
    '#pos-chat-bubble{position:fixed;bottom:24px;right:24px;z-index:9998;',
    'width:60px;height:60px;border-radius:18px;border:none;cursor:pointer;padding:0;',
    'background:radial-gradient(120% 120% at 30% 20%,#1e2a52 0%,#0b1124 100%);',
    'box-shadow:0 8px 26px rgba(67,56,202,.45),0 0 0 1px rgba(129,140,248,.35) inset;',
    'display:flex;align-items:center;justify-content:center;overflow:visible;',
    'transition:transform .2s,box-shadow .2s;outline:none;}',

    '#pos-chat-bubble:hover{transform:translateY(-2px) scale(1.06);',
    'box-shadow:0 12px 34px rgba(67,56,202,.6),0 0 0 1px rgba(129,140,248,.55) inset;}',
    '#pos-chat-bubble:active{transform:scale(.98);}',
    '#pos-chat-bubble img{width:40px;height:40px;object-fit:contain;border-radius:12px;',
    'filter:drop-shadow(0 1px 4px rgba(99,102,241,.55));pointer-events:none;}',

    /* soft pulsing aura ring */
    '#pos-chat-bubble::before{content:"";position:absolute;inset:-4px;border-radius:22px;',
    'background:conic-gradient(from 0deg,#6366f1,#8b5cf6,#22d3ee,#6366f1);',
    'opacity:.0;z-index:-1;filter:blur(7px);transition:opacity .25s;}',
    '#pos-chat-bubble:hover::before{opacity:.55;}',

    '#pos-chat-badge{position:absolute;top:-5px;right:-5px;',
    'height:18px;min-width:18px;padding:0 5px;border-radius:9px;',
    'background:linear-gradient(135deg,#22d3ee,#6366f1);color:#fff;font-size:9px;',
    'font-weight:800;letter-spacing:.04em;',
    'display:flex;align-items:center;justify-content:center;',
    'box-shadow:0 2px 8px rgba(34,211,238,.5);',
    'animation:pos-bounce .9s infinite alternate;border:2px solid var(--surface,#fff);}',

    '@keyframes pos-bounce{from{transform:translateY(0)}to{transform:translateY(-3px)}}',

    '#pos-chat-panel{position:fixed;bottom:90px;right:24px;z-index:9999;',
    'width:380px;max-width:calc(100vw - 32px);',
    'height:560px;max-height:calc(100vh - 110px);',
    'border-radius:16px;overflow:hidden;',
    'box-shadow:0 20px 60px rgba(0,0,0,.25);',
    'display:flex;flex-direction:column;',
    'background:var(--surface,#fff);',
    'border:1px solid var(--surface-border,rgba(0,0,0,.08));',
    'transform-origin:bottom right;',
    'transition:transform .25s cubic-bezier(.34,1.56,.64,1),opacity .2s;',
    'transform:scale(.85);opacity:0;pointer-events:none;}',

    '#pos-chat-panel.open{transform:scale(1);opacity:1;pointer-events:auto;}',

    '#pos-chat-head{position:relative;display:flex;align-items:center;gap:11px;',
    'padding:13px 14px;',
    'background:radial-gradient(120% 140% at 0% 0%,#4f46e5 0%,#6d28d9 55%,#7c3aed 100%);',
    'flex-shrink:0;overflow:hidden;}',
    '#pos-chat-head::after{content:"";position:absolute;right:-30px;top:-50px;',
    'width:140px;height:140px;border-radius:50%;',
    'background:radial-gradient(circle,rgba(255,255,255,.16),transparent 70%);pointer-events:none;}',

    '#pos-chat-avatar{position:relative;z-index:1;width:38px;height:38px;border-radius:11px;flex-shrink:0;',
    'background:radial-gradient(120% 120% at 30% 20%,#1e2a52,#0b1124);',
    'display:flex;align-items:center;justify-content:center;',
    'box-shadow:0 2px 8px rgba(0,0,0,.3),0 0 0 1px rgba(129,140,248,.4) inset;}',
    '#pos-chat-avatar img{width:26px;height:26px;object-fit:contain;}',
    '#pos-chat-avatar .pos-online{position:absolute;bottom:-2px;right:-2px;width:11px;height:11px;',
    'border-radius:50%;background:#22c55e;border:2px solid #5b3bd6;',
    'box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:pos-pulse 1.8s infinite;}',
    '@keyframes pos-pulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}70%{box-shadow:0 0 0 6px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}',

    '#pos-chat-head-title{position:relative;z-index:1;flex:1;color:#fff;font-weight:800;font-size:.96rem;',
    'font-family:inherit;letter-spacing:-.01em;line-height:1.15;}',

    '#pos-chat-head-sub{color:rgba(255,255,255,.8);font-size:.69rem;font-family:inherit;',
    'display:flex;align-items:center;gap:5px;margin-top:1px;}',

    '#pos-chat-close{background:none;border:none;cursor:pointer;',
    'color:rgba(255,255,255,.85);padding:4px;border-radius:6px;',
    'display:flex;align-items:center;transition:background .15s;}',
    '#pos-chat-close:hover{background:rgba(255,255,255,.2);}',

    '#pos-chat-msgs{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:14px 12px;',
    'display:flex;flex-direction:column;gap:10px;',
    'scroll-behavior:smooth;overscroll-behavior:contain;',
    'scrollbar-width:thin;scrollbar-color:rgba(99,102,241,.32) transparent;}',
    '#pos-chat-msgs::-webkit-scrollbar{width:6px;}',
    '#pos-chat-msgs::-webkit-scrollbar-track{background:transparent;}',
    '#pos-chat-msgs::-webkit-scrollbar-thumb{background:rgba(99,102,241,.28);',
    'border-radius:8px;border:1px solid transparent;background-clip:padding-box;}',
    '#pos-chat-msgs:hover::-webkit-scrollbar-thumb{background:rgba(99,102,241,.5);}',
    '#pos-chat-msgs::-webkit-scrollbar-thumb:hover{background:rgba(99,102,241,.7);}',

    '.pos-msg{display:flex;flex-direction:column;max-width:88%;}',
    '.pos-msg.user{align-self:flex-end;align-items:flex-end;}',
    '.pos-msg.ai{align-self:flex-start;align-items:flex-start;}',

    '.pos-bubble{padding:9px 13px;border-radius:12px;font-size:.82rem;line-height:1.55;',
    'word-break:break-word;font-family:inherit;}',
    '.pos-msg.user .pos-bubble{background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;',
    'box-shadow:0 2px 8px rgba(79,70,229,.3);border-bottom-right-radius:3px;}',
    '.pos-msg.ai .pos-bubble{background:var(--surface-alt,#f8fafc);',
    'color:var(--text-base,#1e293b);border:1px solid var(--surface-border,rgba(0,0,0,.08));',
    'border-bottom-left-radius:3px;}',

    '.pos-typing{display:flex;gap:5px;padding:10px 14px;align-items:center;}',
    '.pos-dot{width:7px;height:7px;border-radius:50%;background:#6366f1;',
    'animation:pos-typing 1.2s infinite;}',
    '.pos-dot:nth-child(2){animation-delay:.2s;}',
    '.pos-dot:nth-child(3){animation-delay:.4s;}',
    '@keyframes pos-typing{0%,80%,100%{opacity:.25;transform:scale(.9)}',
    '40%{opacity:1;transform:scale(1.1)}}',

    '.pos-tbl-wrap{margin-top:8px;max-height:200px;overflow:auto;',
    'border-radius:8px;border:1px solid var(--surface-border,rgba(0,0,0,.1));}',
    '.pos-tbl{width:100%;border-collapse:collapse;font-size:.73rem;}',
    '.pos-tbl th{position:sticky;top:0;background:#6366f1;color:#fff;',
    'font-weight:600;padding:5px 8px;text-align:left;white-space:nowrap;}',
    '.pos-tbl td{padding:4px 8px;border-bottom:1px solid var(--surface-border,rgba(0,0,0,.07));',
    'color:var(--text-base,#1e293b);white-space:nowrap;}',
    '.pos-tbl tr:nth-child(even) td{background:var(--surface-alt,#f8fafc);}',
    '.pos-tbl tr:last-child td{border-bottom:none;}',

    '.pos-msg-actions{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;}',
    '.pos-act-btn{border:1px solid var(--surface-border,rgba(0,0,0,.12));',
    'background:var(--surface,#fff);color:var(--text-muted,#64748b);',
    'border-radius:6px;padding:3px 9px;font-size:.7rem;cursor:pointer;',
    'font-family:inherit;transition:background .15s,color .15s;}',
    '.pos-act-btn:hover{background:#6366f1;color:#fff;border-color:#6366f1;}',

    '.pos-examples{display:flex;flex-direction:column;gap:6px;padding:4px 0 2px;}',
    '.pos-example-chip{padding:7px 11px;border-radius:10px;font-size:.78rem;',
    'background:var(--surface-alt,#f8fafc);border:1px solid var(--surface-border,rgba(0,0,0,.09));',
    'color:var(--text-base,#1e293b);cursor:pointer;text-align:left;font-family:inherit;',
    'transition:background .15s,border-color .15s;line-height:1.4;}',
    '.pos-example-chip:hover{background:rgba(99,102,241,.1);border-color:#6366f1;color:#6366f1;}',

    '.pos-empty{display:flex;flex-direction:column;align-items:center;',
    'padding:14px 8px 8px;gap:9px;}',
    '.pos-empty-icon{width:64px;height:64px;border-radius:18px;',
    'background:radial-gradient(120% 120% at 30% 20%,#1e2a52,#0b1124);',
    'display:flex;align-items:center;justify-content:center;',
    'box-shadow:0 6px 18px rgba(67,56,202,.35),0 0 0 1px rgba(129,140,248,.3) inset;}',
    '.pos-empty-icon img{width:44px;height:44px;object-fit:contain;',
    'filter:drop-shadow(0 1px 5px rgba(99,102,241,.5));}',
    '.pos-empty-title{font-size:.92rem;font-weight:700;color:var(--text-base,#1e293b);}',
    '.pos-empty-sub{font-size:.75rem;color:var(--text-muted,#64748b);text-align:center;max-width:240px;line-height:1.5;}',

    '#pos-chat-foot{padding:10px 12px;border-top:1px solid var(--surface-border,rgba(0,0,0,.08));',
    'display:flex;gap:8px;flex-shrink:0;background:var(--surface,#fff);}',

    '#pos-chat-input{flex:1;border:1px solid var(--surface-border,rgba(0,0,0,.12));',
    'border-radius:10px;padding:9px 12px;font-size:.82rem;',
    'background:var(--surface-alt,#f8fafc);color:var(--text-base,#1e293b);',
    'font-family:inherit;resize:none;outline:none;',
    'transition:border-color .15s;}',
    '#pos-chat-input:focus{border-color:#6366f1;}',
    '#pos-chat-input::placeholder{color:var(--text-muted,#94a3b8);}',

    '#pos-chat-send{width:38px;height:38px;border-radius:11px;border:none;cursor:pointer;',
    'background:linear-gradient(135deg,#4f46e5,#7c3aed);',
    'box-shadow:0 2px 8px rgba(79,70,229,.35);',
    'display:flex;align-items:center;justify-content:center;',
    'flex-shrink:0;align-self:flex-end;',
    'transition:opacity .15s,transform .15s;}',
    '#pos-chat-send:disabled{opacity:.45;cursor:default;}',
    '#pos-chat-send:not(:disabled):hover{transform:scale(1.08);}',
    '#pos-chat-send svg{width:16px;height:16px;fill:none;stroke:#fff;stroke-width:2.2;}',

    '.pos-sql-block{margin-top:6px;background:var(--surface-alt,#f1f5f9);',
    'border:1px solid var(--surface-border,rgba(0,0,0,.09));',
    'border-radius:8px;padding:8px 10px;font-size:.7rem;',
    'font-family:\'Courier New\',monospace;color:var(--text-muted,#475569);',
    'white-space:pre-wrap;word-break:break-word;display:none;}',
  ].join('');
  document.head.appendChild(style);

  // ── Build DOM ─────────────────────────────────────────────────────────────
  var LOGO_SRC = 'assets/Abhi_AI.png';
  // Graceful fallback: if the logo asset can't load, swap in a stylised "A" so
  // the bubble/header never show a broken-image icon.
  window._posChatLogoFallback = function (img) {
    if (!img || img.dataset.fellBack) return;
    img.dataset.fellBack = '1';
    var span = document.createElement('span');
    span.textContent = 'A';
    span.style.cssText = 'font-weight:900;font-size:1.05em;color:#a5b4fc;'
      + 'font-family:inherit;line-height:1;';
    if (img.parentNode) img.parentNode.replaceChild(span, img);
  };
  var LOGO_IMG = function (cls) {
    return '<img src="' + LOGO_SRC + '" alt="Abhi AI"'
      + (cls ? ' class="' + cls + '"' : '')
      + ' onerror="window._posChatLogoFallback(this)" />';
  };

  var bubble = document.createElement('button');
  bubble.id = 'pos-chat-bubble';
  bubble.setAttribute('aria-label', 'Open Abhi AI');
  bubble.title = 'Ask Abhi AI';
  bubble.innerHTML = (
    LOGO_IMG()
    + '<span id="pos-chat-badge">AI</span>'
  );

  var panel = document.createElement('div');
  panel.id = 'pos-chat-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Abhi AI Assistant');
  panel.innerHTML = (
    '<div id="pos-chat-head">'
    + '<div id="pos-chat-avatar">' + LOGO_IMG() + '<span class="pos-online"></span></div>'
    + '<div style="flex:1;min-width:0;">'
    + '<div id="pos-chat-head-title">Abhi AI</div>'
    + '<div id="pos-chat-head-sub"><span style="width:6px;height:6px;border-radius:50%;background:#4ade80;display:inline-block;"></span> Online · Sales &amp; inventory assistant</div>'
    + '</div>'
    + '<button id="pos-chat-close" aria-label="Close" onclick="window._posChatClose()">'
    + '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
    + '</button>'
    + '</div>'
    + '<div id="pos-chat-msgs"></div>'
    + '<div id="pos-chat-foot">'
    + '<textarea id="pos-chat-input" rows="1" placeholder="Ask Abhi AI about sales, inventory, GST…" maxlength="1000"></textarea>'
    + '<button id="pos-chat-send" aria-label="Send">'
    + '<svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>'
    + '</button>'
    + '</div>'
  );

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  // ── State ─────────────────────────────────────────────────────────────────
  var _open    = false;
  var _busy    = false;
  var _history = [];
  var _msgData = {};  // msgId → {columns, rows, question, sql}
  var _msgCnt  = 0;
  var _firstOpen = true;

  var msgsEl = panel.querySelector('#pos-chat-msgs');
  var inputEl = panel.querySelector('#pos-chat-input');
  var sendEl  = panel.querySelector('#pos-chat-send');

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _scroll() {
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  function _token() {
    return localStorage.getItem('pos_token') || '';
  }

  function _setLoading(v) {
    _busy = v;
    sendEl.disabled = v;
    inputEl.disabled = v;
    if (v) inputEl.setAttribute('placeholder', 'Abhi AI is thinking…');
    else    inputEl.setAttribute('placeholder', 'Ask Abhi AI about sales, inventory, GST…');
  }

  // ── Render empty state ────────────────────────────────────────────────────
  function _renderEmpty() {
    msgsEl.innerHTML = (
      '<div class="pos-empty">'
      + '<div class="pos-empty-icon">' + LOGO_IMG() + '</div>'
      + '<div class="pos-empty-title">Hi, I’m Abhi AI</div>'
      + '<div class="pos-empty-sub">Ask me anything about your sales, inventory, customers or GST — in plain English.</div>'
      + '</div>'
      + '<div class="pos-examples"></div>'
    );
    // Build chips via DOM to avoid any HTML-quoting issues with the query text
    var examplesDiv = msgsEl.querySelector('.pos-examples');
    EXAMPLES.forEach(function (e) {
      var btn = document.createElement('button');
      btn.className = 'pos-example-chip';
      btn.textContent = e;
      btn.addEventListener('click', function () { _send(e); });
      examplesDiv.appendChild(btn);
    });
  }

  // ── Render message ────────────────────────────────────────────────────────
  function _addMsg(role, content, extra) {
    // Remove empty state
    var empty = msgsEl.querySelector('.pos-empty');
    if (empty) empty.parentNode.innerHTML = '';
    var examples = msgsEl.querySelector('.pos-examples');
    if (examples) examples.remove();

    var id = 'pm' + (++_msgCnt);
    var div = document.createElement('div');
    div.className = 'pos-msg ' + role;
    div.id = id;

    var bubble2 = document.createElement('div');
    bubble2.className = 'pos-bubble';
    bubble2.textContent = content;
    div.appendChild(bubble2);

    if (role === 'ai' && extra) {
      _msgData[id] = extra;

      // Data table
      if (extra.columns && extra.columns.length && extra.rows && extra.rows.length) {
        var tblWrap = document.createElement('div');
        tblWrap.className = 'pos-tbl-wrap';
        var tbl = '<table class="pos-tbl"><thead><tr>';
        extra.columns.forEach(function (c) {
          tbl += '<th>' + _esc(c.replace(/_/g, ' ').replace(/\b\w/g, function (l) { return l.toUpperCase(); })) + '</th>';
        });
        tbl += '</tr></thead><tbody>';
        extra.rows.slice(0, 100).forEach(function (row) {
          tbl += '<tr>';
          extra.columns.forEach(function (c) {
            tbl += '<td>' + _esc(row[c]) + '</td>';
          });
          tbl += '</tr>';
        });
        tbl += '</tbody></table>';
        tblWrap.innerHTML = tbl;
        div.appendChild(tblWrap);
      }

      // Action buttons
      var actions = document.createElement('div');
      actions.className = 'pos-msg-actions';
      if (extra.columns && extra.columns.length && extra.rows && extra.rows.length) {
        actions.innerHTML += '<button class="pos-act-btn" onclick="window._posChatExport(\'' + id + '\')">⬇ Export Excel</button>';
      }
      if (extra.sql) {
        actions.innerHTML += '<button class="pos-act-btn" onclick="window._posChatToggleSql(\'' + id + '\')">SQL ▾</button>';
        var sqlBlock = document.createElement('div');
        sqlBlock.className = 'pos-sql-block';
        sqlBlock.id = id + '-sql';
        sqlBlock.textContent = extra.sql;
        div.appendChild(sqlBlock);
      }
      if (actions.innerHTML) div.appendChild(actions);
    }

    msgsEl.appendChild(div);
    _scroll();
    return id;
  }

  function _addTyping() {
    var div = document.createElement('div');
    div.className = 'pos-msg ai';
    div.id = 'pos-typing';
    div.innerHTML = '<div class="pos-bubble pos-typing"><div class="pos-dot"></div><div class="pos-dot"></div><div class="pos-dot"></div></div>';
    msgsEl.appendChild(div);
    _scroll();
  }

  function _removeTyping() {
    var t = document.getElementById('pos-typing');
    if (t) t.remove();
  }

  // ── Send message ──────────────────────────────────────────────────────────
  function _send(question) {
    question = (question || '').trim();
    if (!question || _busy) return;

    if (_firstOpen) {
      msgsEl.innerHTML = '';
      _firstOpen = false;
    }

    _addMsg('user', question);
    _addTyping();
    _setLoading(true);
    inputEl.value = '';
    inputEl.style.height = 'auto';

    var token = _token();
    if (!token) {
      _removeTyping();
      _addMsg('ai', 'Please log in to chat with Abhi AI.', null);
      _setLoading(false);
      return;
    }

    fetch(ENDPOINT_CHAT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
      },
      body: JSON.stringify({ question: question, history: _history }),
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      _removeTyping();
      if (d.error) {
        _addMsg('ai', 'Sorry: ' + d.error, null);
      } else {
        _addMsg('ai', d.answer, {
          columns: d.columns,
          rows: d.rows,
          question: question,
          sql: d.sql,
        });
        _history.push({ user: question, sql: d.sql });
        if (_history.length > 8) _history = _history.slice(-8);
      }
    })
    .catch(function (err) {
      _removeTyping();
      _addMsg('ai', 'Network error. Please check your connection.', null);
    })
    .finally(function () {
      _setLoading(false);
    });
  }

  // ── Open / Close ──────────────────────────────────────────────────────────
  function _openPanel() {
    _open = true;
    panel.classList.add('open');
    bubble.setAttribute('aria-expanded', 'true');
    var badge = document.getElementById('pos-chat-badge');
    if (badge) badge.style.display = 'none';
    if (_firstOpen) _renderEmpty();
    setTimeout(function () { inputEl.focus(); }, 280);
  }

  function _closePanel() {
    _open = false;
    panel.classList.remove('open');
    bubble.setAttribute('aria-expanded', 'false');
  }

  // ── Global API ────────────────────────────────────────────────────────────
  window._posChatSend = function (q) { _send(q); };
  window._posChatClose = function () { _closePanel(); };
  window._posChatOpen  = function () { _openPanel(); };

  window._posChatExport = function (msgId) {
    var data = _msgData[msgId];
    if (!data) return;
    var token = _token();
    fetch(ENDPOINT_EXPORT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
      },
      body: JSON.stringify({
        columns: data.columns,
        rows: data.rows,
        question: data.question,
        sql: data.sql,
      }),
    })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || 'Export failed'); });
      return r.blob();
    })
    .then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'ai_report.xlsx';
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
    })
    .catch(function (err) {
      alert('Export failed: ' + err.message);
    });
  };

  window._posChatToggleSql = function (msgId) {
    var el = document.getElementById(msgId + '-sql');
    if (!el) return;
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
  };

  window.POSChat = {
    send: _send,
    open: _openPanel,
    close: _closePanel,
  };

  // ── Event listeners ───────────────────────────────────────────────────────
  bubble.addEventListener('click', function () {
    if (_open) _closePanel(); else _openPanel();
  });

  sendEl.addEventListener('click', function () {
    _send(inputEl.value);
  });

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      _send(inputEl.value);
    }
  });

  inputEl.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 100) + 'px';
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && _open) _closePanel();
  });

}());
