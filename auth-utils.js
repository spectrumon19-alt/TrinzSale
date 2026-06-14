// auth-utils.js - Authentication and authorization utilities

// ── Dark mode: apply saved theme BEFORE first paint (no flash) ───────────────
(function () {
    try {
        const theme = localStorage.getItem('pos_theme') || 'dark';
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            document.documentElement.classList.add('dark');
        }
    } catch (e) { /* localStorage unavailable */ }
})();

// ── Enforce uniform sidebar link styling (matching dashboard.html: py-2 px-3 text-sm)
// This runs synchronously during script parse, before DOM renders
(function() {
    const style = document.createElement('style');
    style.id = 'sidebar-uniform-style';
    style.textContent = `
        #sidebar a[href] {
            padding: 0.5rem 0.75rem !important;
            font-size: 0.875rem !important;
            line-height: 1.25rem !important;
            border-radius: 0.25rem !important;
        }
    `;
    (document.head || document.documentElement).appendChild(style);
})();

// License guard disabled - license checking removed per user request


// Prevent sidebar link flash: hide all sidebar links immediately (before DOM renders)
// Only applies to non-admin users. Admin users get instant reveal.
(function() {
    try {
        const token = localStorage.getItem('pos_token');
        if (!token) return; // No token, login page
        const payload = JSON.parse(atob(token.split('.')[1]));
        if (payload.role === 'Super Admin') return; // Super Admin always has full access, no flash issue
        // Non-admin: inject CSS to hide sidebar links until permissions are resolved
        const style = document.createElement('style');
        style.id = 'sidebar-perm-hide';
        style.textContent = '#sidebar a[href] { visibility: hidden !important; }';
        document.head ? document.head.appendChild(style) : document.documentElement.appendChild(style);
    } catch (e) { /* ignore */ }
})();

// Check if user is authenticated
function isAuthenticated() {
    const token = localStorage.getItem('pos_token');
    if (!token) return false;
    
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        // Check if token is expired
        const currentTime = Math.floor(Date.now() / 1000);
        if (payload.exp < currentTime) {
            // Token expired, remove it
            localStorage.removeItem('pos_token');
            return false;
        }
        return true;
    } catch (e) {
        console.error('Error parsing token:', e);
        // Invalid token, remove it
        localStorage.removeItem('pos_token');
        return false;
    }
}

// Get current user from token
function getCurrentUser() {
    const token = localStorage.getItem('pos_token');
    if (!token) return null;
    
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        // Check if token is expired
        const currentTime = Math.floor(Date.now() / 1000);
        if (payload.exp < currentTime) {
            // Token expired, remove it
            localStorage.removeItem('pos_token');
            return null;
        }
        return {
            user_id: payload.user_id,
            username: payload.username,
            role: payload.role
        };
    } catch (e) {
        console.error('Error parsing token:', e);
        // Invalid token, remove it
        localStorage.removeItem('pos_token');
        return null;
    }
}

// Check if user has admin-tier role (Admin, Super Admin, or Manager)
function isAdmin() {
    const user = getCurrentUser();
    return user && (user.role === 'Admin' || user.role === 'Super Admin' || user.role === 'Manager');
}

// Check if user has cashier role
function isCashier() {
    const user = getCurrentUser();
    return user && user.role === 'Cashier';
}

// ============================================================
// PERMISSION SYSTEM
// ============================================================

// Master sidebar nav definition — single source of truth for all navigable pages.
// Order determines display order in the sidebar.
// Sidebar nav — grouped for clarity. Admin-only tools live inside admin.html, not here.
const SIDEBAR_NAV_LINKS = [
    { group: 'Operations' },
    { href: 'dashboard.html', icon: '🏠', label: 'Dashboard', permission: 'dashboard' },
    { href: 'index.html',     icon: '🛒', label: 'Sales',     permission: 'sales'     },
    { href: 'returns.html',   icon: '🔄', label: 'Returns',   permission: 'returns'   },
    { href: 'purchase.html',  icon: '📥', label: 'Purchase',  permission: 'purchase'  },
    { href: 'inventory.html', icon: '📦', label: 'Inventory', permission: 'inventory' },

    { group: 'Customers' },
    { href: 'creditDashboard.html',    icon: '📒', label: 'Credit Dashboard', permission: 'credit' },
    { href: 'creditManagement.html',   icon: '💳', label: 'Credit',    permission: 'credit' },
    { href: 'customerManagement.html', icon: '👤', label: 'Customers', permission: 'credit' },

    { group: 'Reports' },
    { href: 'reports.html',     icon: '📊', label: 'Reports',     permission: 'reports'     },
    { href: 'gst-reports.html', icon: '🧾', label: 'GST Reports', permission: 'gst-reports' },

    { group: 'Tools' },
    { href: 'ocrExcel.html',     icon: '📄', label: 'OCR → Excel',  permission: 'ocr-excel' },

    { group: 'Admin' },
    { href: 'admin.html',        icon: '⚙️', label: 'Admin Panel',  permission: 'admin'      },
    { href: 'service.html',      icon: '🔧', label: 'Service',      permission: 'service'    },
    { href: 'tally-export.html', icon: '📤', label: 'Tally Export', permission: 'tally-export' },
    { href: 'backup.html',       icon: '🛡️', label: 'Auto Backup',  permission: 'backup'       },
    { href: 'ai-settings.html',    icon: '🤖', label: 'AI Settings',    permission: 'ai-settings'  },
    { href: 'knowledge-base.html', icon: '🧠', label: 'Knowledge Base', permission: 'ai-settings'  },
    { href: 'license_activation.html', icon: '🔑', label: 'License',    permission: 'admin'        },
];

// Inject sidebar nav styles once (CSS-variable-aware, dark-mode safe)
(function injectSidebarStyles() {
    if (document.getElementById('_sidebar_nav_styles')) return;
    const s = document.createElement('style');
    s.id = '_sidebar_nav_styles';
    s.textContent = `
        .snav-group {
            font-size: 0.58rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.09em; color: var(--text-subtle, #475569);
            padding: 0.7rem 0.875rem 0.2rem; margin-top: 0.1rem;
            pointer-events: none; user-select: none;
        }
        .snav-link {
            display: flex; align-items: center; gap: 0.55rem;
            padding: 0.42rem 0.875rem; border-radius: 8px; margin: 0 0.35rem;
            font-size: 0.8rem; font-weight: 500;
            color: var(--text-muted, #94a3b8);
            text-decoration: none; transition: background 0.13s, color 0.13s;
            white-space: nowrap; overflow: hidden;
        }
        .snav-link:hover { background: rgba(99,102,241,0.09); color: var(--text-base, #e2e8f0); }
        .snav-link.snav-active {
            background: rgba(99,102,241,0.18); color: #818cf8;
            font-weight: 600; cursor: default;
            border-left: 3px solid #6366f1; padding-left: calc(0.875rem - 3px);
        }
        .snav-link.snav-active:hover { background: rgba(99,102,241,0.18); color: #818cf8; }
        .snav-link.snav-active .snav-icon { opacity: 1; }
        .snav-icon { width: 1.1rem; text-align: center; font-size: 0.82rem; flex-shrink: 0; opacity: 0.75; }
        .snav-label { overflow: hidden; text-overflow: ellipsis; }
    `;
    document.head.appendChild(s);
})();

// Render sidebar links dynamically based on the user's permissions.
function renderSidebarLinks() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const currentPage = (window.location.pathname.split('/').pop() || 'dashboard.html');
    const user        = getCurrentUser();
    const isAdminTier = user && user.role === 'Super Admin';

    let perms = null;
    if (!isAdminTier) {
        try {
            const s = localStorage.getItem('pos_permissions');
            if (s) perms = JSON.parse(s);
        } catch (e) {}
    }

    // Use a dedicated container so clearing is unambiguous — no selector fragility.
    let navContainer = document.getElementById('sidebar-nav-links');
    if (!navContainer) {
        navContainer = document.createElement('div');
        navContainer.id = 'sidebar-nav-links';
        const pinDiv = sidebar.querySelector('.px-4.mt-auto');
        if (pinDiv) sidebar.insertBefore(navContainer, pinDiv);
        else        sidebar.appendChild(navContainer);
    }
    navContainer.innerHTML = '';

    let pendingGroup = null;

    SIDEBAR_NAV_LINKS.forEach(function (item) {
        if (item.group) {
            pendingGroup = item.group;
            return;
        }

        // Admin/Manager with no permissions configured → full access by role default
        const isRoleDefault = user && (user.role === 'Admin' || user.role === 'Manager') &&
            (!perms || Object.keys(perms).length === 0);
        const hasAccess = isAdminTier || isRoleDefault ||
            (perms && (perms._admin === true || perms[item.permission] === true));
        if (!hasAccess) return;

        // First visible item in group → flush the group header
        if (pendingGroup) {
            const div = document.createElement('div');
            div.className = 'snav-group';
            div.textContent = pendingGroup;
            navContainer.appendChild(div);
            pendingGroup = null;
        }

        const isActive = currentPage === item.href;
        const a = document.createElement('a');
        a.href      = isActive ? 'javascript:void(0)' : item.href;
        a.className = 'snav-link' + (isActive ? ' snav-active' : '');
        a.innerHTML = `<span class="snav-icon">${item.icon}</span><span class="snav-label">${item.label}</span>`;
        navContainer.appendChild(a);
    });

    const hideStyle = document.getElementById('sidebar-perm-hide');
    if (hideStyle) hideStyle.remove();
}

// Map page filenames to permission screen IDs
const PAGE_TO_PERMISSION = {
    'dashboard.html': 'dashboard',
    'index.html': 'sales',
    'returns.html': 'returns',
    'purchase.html': 'purchase',
    'inventory.html': 'inventory',
    'reports.html': 'reports',
    'admin.html': 'admin',
    'service.html': 'service',
    'creditDashboard.html': 'credit',
    'creditManagement.html': 'credit',
    'Data Upload.html': 'data-upload',
    'ocrExcel.html': 'ocr-excel',
    'ai-settings.html': 'ai-settings',
    'knowledge-base.html': 'ai-settings',
    'qry2db.html': 'qry2db',
    'Supplier Management.html': 'supplier-management',
    'Product Management.html': 'product-management',
    'User Management.html': 'user-management',
    'Invoice Viewer.html': 'invoice-viewer',
    'SupplierCreditManagement.html': 'credit',
    'storeSettings.html': 'admin',
    'gst-reports.html': 'gst-reports',
    'customerManagement.html': 'credit',
    'tally-export.html': 'tally-export',
    'backup.html': 'backup',
    'login-activity.html': 'login-activity',
    'storeSettings.html': 'store-settings',
    'license_activation.html': 'admin'
};

// Get API base URL (works even without config.js loaded)
function getApiBaseUrl() {
    if (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) {
        return window.APP_CONFIG.API_BASE_URL;
    }
    // Same-origin: use relative URLs (works on both local and Render)
    return '';
}

// Cache permissions for current user into localStorage (called at login)
// Returns a Promise so the caller can wait if needed
function cacheUserPermissions() {
    const user = getCurrentUser();
    if (!user) {
        localStorage.removeItem('pos_permissions');
        return Promise.resolve(null);
    }
    // Super Admin always has full access - no need to fetch
    if (user.role === 'Super Admin') {
        localStorage.setItem('pos_permissions', JSON.stringify({ _admin: true }));
        return Promise.resolve({ _admin: true });
    }
    
    const token = localStorage.getItem('pos_token');
    const apiBase = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || '';
    const apiUrl = `${apiBase}/api/admin/permissions/${user.user_id}`;

    return fetch(apiUrl, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(r => {
        if (!r.ok) {
            console.error('[Permissions] API returned status:', r.status, 'for URL:', apiUrl);
            throw new Error('Failed to fetch permissions: ' + r.status);
        }
        return r.json();
    })
    .then(data => {
        const perms = data.permissions || {};
        localStorage.setItem('pos_permissions', JSON.stringify(perms));
        return perms;
    })
    .catch(err => {
        console.error('[Permissions] Error caching permissions:', err);
        // Don't overwrite existing cache with empty on failure
        // This prevents a failed API call from showing all links
        return null;
    });
}

// Check permission using ONLY localStorage cache (instant, no network)
// Returns true if access allowed, false if denied
function checkPagePermission() {
    const user = getCurrentUser();
    if (!user) return true;
    if (user.role === 'Super Admin') return true;

    const currentPage = window.location.pathname.split('/').pop();
    const screenId = PAGE_TO_PERMISSION[currentPage];
    
    if (!screenId) return true;
    
    const alwaysAccessible = ['login.html', 'logout.html', 'noAccess.html'];
    if (alwaysAccessible.includes(currentPage)) return true;
    
    try {
        const permsStr = localStorage.getItem('pos_permissions');
        if (!permsStr) return true; // No cache yet - allow by default, will refresh in background
        
        const perms = JSON.parse(permsStr);
        if (perms._admin) return true;
        // Admin/Manager with no permissions configured → full access by role default
        if (Object.keys(perms).length === 0 && user && (user.role === 'Admin' || user.role === 'Manager')) return true;

        if (screenId in perms) {
            return perms[screenId] === true;
        }
        // Screen not in perms object - deny by default (secure default)
        return false;
    } catch (e) {
        console.error('[Permissions] Error checking:', e);
        return true;
    }
}

// Filter sidebar links based on current user's permissions
// Map sidebar link hrefs to permission screen IDs
// Only contains pages that actually appear in the sidebar
const SIDEBAR_HREF_TO_PERMISSION = {
    'dashboard.html':          'dashboard',
    'index.html':              'sales',
    'returns.html':            'returns',
    'purchase.html':           'purchase',
    'inventory.html':          'inventory',
    'creditDashboard.html':    'credit',
    'creditManagement.html':   'credit',
    'customerManagement.html': 'credit',
    'reports.html':            'reports',
    'gst-reports.html':        'gst-reports',
    'admin.html':              'admin',
    'tally-export.html':       'tally-export',
    'backup.html':             'backup',
    'service.html':            'service',
    'ai-settings.html':          'ai-settings',
    'knowledge-base.html':       'ai-settings',
    'license_activation.html':   'admin',
    'ocrExcel.html':             'ocr-excel',
    'login-activity.html':     'login-activity',
    'storeSettings.html':      'store-settings',
};

function filterSidebarByPermissions() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    
    const user = getCurrentUser();
    // Super Admin always sees all links
    if (!user || user.role === 'Super Admin') {
        return;
    }
    
    // Get permissions from localStorage
    let perms = null;
    try {
        const permsStr = localStorage.getItem('pos_permissions');
        if (permsStr) {
            perms = JSON.parse(permsStr);
        }
    } catch (e) {
        console.error('[Sidebar] Error reading permissions:', e);
    }
    
    // If no permissions cached, fetch them now and re-run filtering
    if (!perms) {
        console.warn('[Sidebar] No permissions cached, fetching...');
        cacheUserPermissions().then(() => {
            filterSidebarByPermissions();
        });
        return;
    }
    
    if (perms._admin) return;
    // Admin/Manager with no permissions configured → full access by role default
    if (Object.keys(perms).length === 0 && user && (user.role === 'Admin' || user.role === 'Manager')) return;

    // Filter each sidebar link
    const links = sidebar.querySelectorAll('a[href]');
    let hiddenCount = 0;
    links.forEach(link => {
        const href = link.getAttribute('href');
        const screenId = SIDEBAR_HREF_TO_PERMISSION[href];
        
        // If no mapping exists, always show (e.g., TrintzPOS logo link)
        if (!screenId) return;
        
        // Check permission - if in perms object, use value; if NOT in perms, deny by default
        const hasAccess = screenId in perms ? perms[screenId] === true : false;
        
        if (!hasAccess) {
            link.style.setProperty('display', 'none', 'important');
            hiddenCount++;
        } else {
            link.style.removeProperty('display');
        }
    });
    console.log('[Sidebar] Filtered: ' + hiddenCount + ' links hidden for user ' + user.username);
    
    // Reveal allowed sidebar links (remove the anti-flash CSS)
    const hideStyle = document.getElementById('sidebar-perm-hide');
    if (hideStyle) hideStyle.remove();
}

// Redirect to login if not authenticated
function requireAuth() {
    if (!isAuthenticated()) {
        document.body.style.display = 'none'; // hide stale cached content instantly
        window.location.replace('login.html');
        return false;
    }
    return true;
}

// Redirect to appropriate page based on role
function redirectToRolePage() {
    const user = getCurrentUser();
    if (!user) {
        window.location.href = 'login.html';
        return true;
    }
    
    // Super Admin can access all pages
    if (user.role === 'Super Admin') {
        return false;
    }
    
    // Check granular permissions for non-admin users
    if (!checkPagePermission()) {
        window.location.href = 'noAccess.html';
        return true;
    }
    
    return false; // No redirect happened
}

// Update username display on page
function updateUsernameDisplay() {
    const user = getCurrentUser();
    if (user) {
        document.querySelectorAll('#username, #nav-username').forEach(el => {
            if (el) el.textContent = user.username;
        });
    }
}

// Update the #live-datetime element in the shared header
function _updateHeaderClock() {
    const el = document.getElementById('live-datetime');
    if (!el) return;
    const now = new Date();
    const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const hh = now.getHours().toString().padStart(2,'0');
    const mm = now.getMinutes().toString().padStart(2,'0');
    el.textContent = `${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()} · ${hh}:${mm}`;
}

// Logout function — clears all storage and replaces history so back button
// cannot return to any protected page
function logout() {
    var _theme = localStorage.getItem('pos_theme');
    var _salt  = localStorage.getItem('pos_device_salt');
    localStorage.clear();
    sessionStorage.clear();
    if (_theme) localStorage.setItem('pos_theme', _theme);
    if (_salt)  localStorage.setItem('pos_device_salt', _salt);
    // pos_eula_accepted is intentionally NOT preserved — next login must re-verify
    window.location.replace('login.html');
}

// ========== Auto-Logout on Inactivity (10 minutes) ==========
const INACTIVITY_TIMEOUT = 10 * 60 * 1000; // 10 minutes
const WARNING_BEFORE = 60 * 1000;           // Show warning 1 minute before
let _inactivityTimer = null;
let _warningTimer = null;
let _warningOverlay = null;

function resetInactivityTimer() {
    localStorage.setItem('pos_last_activity', Date.now().toString());
    
    // Clear existing timers
    if (_inactivityTimer) clearTimeout(_inactivityTimer);
    if (_warningTimer) clearTimeout(_warningTimer);
    
    // Remove warning if visible
    if (_warningOverlay) {
        _warningOverlay.remove();
        _warningOverlay = null;
    }
    
    // Set warning timer (9 minutes)
    _warningTimer = setTimeout(showInactivityWarning, INACTIVITY_TIMEOUT - WARNING_BEFORE);
    
    // Set logout timer (10 minutes)
    _inactivityTimer = setTimeout(inactivityLogout, INACTIVITY_TIMEOUT);
}

function showInactivityWarning() {
    if (_warningOverlay) return; // Already showing
    
    let remaining = 60; // seconds
    _warningOverlay = document.createElement('div');
    _warningOverlay.id = 'inactivity-warning';
    _warningOverlay.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;background:#1f2937;color:#fff;padding:16px 24px;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.3);font-family:system-ui,-apple-system,sans-serif;max-width:360px;';
    _warningOverlay.innerHTML = `
        <div style="font-weight:600;font-size:14px;margin-bottom:8px;">Session Expiring</div>
        <div style="font-size:13px;color:#d1d5db;margin-bottom:12px;">You will be logged out in <span id="inactivity-countdown" style="color:#f87171;font-weight:700;">${remaining}</span> seconds due to inactivity.</div>
        <button id="inactivity-stay-btn" style="background:#3b82f6;color:#fff;border:none;padding:8px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">Stay Logged In</button>
    `;
    document.body.appendChild(_warningOverlay);
    
    document.getElementById('inactivity-stay-btn').addEventListener('click', function() {
        resetInactivityTimer();
    });
    
    // Countdown
    const countdownEl = document.getElementById('inactivity-countdown');
    const countdownInterval = setInterval(() => {
        remaining--;
        if (countdownEl) countdownEl.textContent = remaining;
        if (remaining <= 0 || !_warningOverlay) {
            clearInterval(countdownInterval);
        }
    }, 1000);
}

function inactivityLogout() {
    var _theme = localStorage.getItem('pos_theme');
    var _salt  = localStorage.getItem('pos_device_salt');
    localStorage.clear();
    sessionStorage.clear();
    if (_theme) localStorage.setItem('pos_theme', _theme);
    if (_salt)  localStorage.setItem('pos_device_salt', _salt);
    // pos_eula_accepted cleared with localStorage.clear() above — next login re-verifies
    window.location.replace('login.html?timeout=1');
}

// Start inactivity tracking on every page (except login)
(function() {
    const page = window.location.pathname.split('/').pop();
    if (page === 'login.html') return;
    
    const events = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];
    let _debounceTimer = null;
    
    events.forEach(evt => {
        document.addEventListener(evt, function() {
            // Debounce: don't reset too aggressively on continuous events
            if (_debounceTimer) clearTimeout(_debounceTimer);
            _debounceTimer = setTimeout(resetInactivityTimer, 1000);
        }, { passive: true });
    });
    
    // Initialize timer on page load
    resetInactivityTimer();
})();

// Loading overlay functions
function showLoading() {
    // Try to find loading overlay in the current document
    let loadingOverlay = document.getElementById('loading-overlay');
    
    // If not found, try to find it in the navigation component
    if (!loadingOverlay) {
        const navComponent = document.querySelector('nav');
        if (navComponent) {
            loadingOverlay = navComponent.nextElementSibling;
            if (loadingOverlay && loadingOverlay.id === 'loading-overlay') {
                // Found it
            } else {
                loadingOverlay = null;
            }
        }
    }
    
    // If still not found, create it dynamically
    if (!loadingOverlay) {
        loadingOverlay = document.createElement('div');
        loadingOverlay.id = 'loading-overlay';
        loadingOverlay.className = 'fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center';
        loadingOverlay.innerHTML = `
            <div class="bg-white rounded-lg p-6 flex flex-col items-center">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mb-4"></div>
                <p class="text-gray-700 font-medium">Loading...</p>
            </div>
        `;
        document.body.appendChild(loadingOverlay);
    }
    
    // Show the loading overlay
    loadingOverlay.classList.remove('hidden');
}

function hideLoading() {
    const loadingOverlay = document.getElementById('loading-overlay');
    if (loadingOverlay) {
        loadingOverlay.classList.add('hidden');
    }
}

// ── Page guard: auth → EULA → page ───────────────────────────────────────────
// Runs on every page load and bfcache restore.
window.addEventListener('pageshow', async function () {
    const page = window.location.pathname.split('/').pop() || '';

    // ── Public pages (no auth needed) ────────────────────────────────────
    const publicPages = ['login.html', 'register.html', 'eula.html', ''];
    if (publicPages.includes(page)) {
        if (page === 'login.html' && isAuthenticated()) {
            window.location.replace('dashboard.html');
        }
        return;
    }

    // ── Auth check ────────────────────────────────────────────────────────
    if (!isAuthenticated()) {
        window.location.replace('login.html');
        return;
    }

    // ── EULA check (skip for pages that don't need it) ────────────────────
    const eulaExempt = ['noAccess.html', 'logout.html', 'license_activation.html'];
    if (!eulaExempt.includes(page)) {
        // Fast path: cache flag set after acceptance
        if (localStorage.getItem('pos_eula_accepted') !== '1') {
            try {
                const token = localStorage.getItem('pos_token');
                const res = await fetch('/api/auth/terms-status', {
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                if (res.ok) {
                    const d = await res.json();
                    if (d.accepted) {
                        localStorage.setItem('pos_eula_accepted', '1');
                    } else {
                        window.location.replace('eula.html');
                        return;
                    }
                }
            } catch (_) { /* network error — fail-open */ }
        }
    }
});

// Re-check auth and refresh permissions whenever the tab regains focus
document.addEventListener('visibilitychange', function () {
    const page = window.location.pathname.split('/').pop();
    const publicPages = ['login.html', 'register.html', 'license_activation.html', ''];
    if (publicPages.includes(page) || document.visibilityState !== 'visible') return;

    if (!isAuthenticated()) {
        document.body.style.display = 'none';
        window.location.replace('login.html');
        return;
    }

    // Re-fetch permissions and re-render sidebar so revoked links disappear immediately
    const _u = getCurrentUser();
    if (_u && _u.role !== 'Super Admin') {
        cacheUserPermissions().then(function () {
            renderSidebarLinks();
        });
    }
});

// ── Dark mode toggle ──────────────────────────────────────────────────────────

function toggleTheme() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var next = isDark ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    if (next === 'dark') {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
    try { localStorage.setItem('pos_theme', next); } catch (e) {}
    _syncThemeBtn();
    // propagate to any iframes on the page
    document.querySelectorAll('iframe').forEach(function (f) {
        try {
            var d = (f.contentDocument || f.contentWindow.document).documentElement;
            d.setAttribute('data-theme', next);
            if (next === 'dark') { d.classList.add('dark'); } else { d.classList.remove('dark'); }
        } catch (e) {}
    });
}

var _SUN_SVG  = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
var _MOON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

function _syncThemeBtn() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    ['dark-mode-toggle-btn', 'theme-toggle-btn'].forEach(function (id) {
        var b = document.getElementById(id);
        if (!b) return;
        b.innerHTML = isDark ? _SUN_SVG : _MOON_SVG;
        b.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
        b.setAttribute('aria-label', b.title);
    });
}

function _injectThemeToggle() {
    var sidebar = document.getElementById('sidebar');
    if (sidebar && !document.getElementById('dark-mode-toggle-btn')) {
        // Inject sun/moon icon button inside the sidebar header (next to TrintzPOS logo)
        var logoLink = sidebar.querySelector('a');
        if (logoLink) {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            var btn = document.createElement('button');
            btn.id = 'dark-mode-toggle-btn';
            btn.type = 'button';
            btn.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
            btn.setAttribute('aria-label', btn.title);
            btn.innerHTML = isDark ? _SUN_SVG : _MOON_SVG;
            btn.style.cssText = [
                'margin-left:auto',
                'flex-shrink:0',
                'width:30px',
                'height:30px',
                'border-radius:7px',
                'border:none',
                'cursor:pointer',
                'display:flex',
                'align-items:center',
                'justify-content:center',
                'background:rgba(255,255,255,0.08)',
                'color:#94a3b8',
                'transition:background 0.15s,color 0.15s,transform 0.15s',
                'outline:none',
                'padding:0'
            ].join(';');
            btn.addEventListener('mouseenter', function () {
                btn.style.background = 'rgba(255,255,255,0.18)';
                btn.style.color = '#f1f5f9';
                btn.style.transform = 'rotate(18deg)';
            });
            btn.addEventListener('mouseleave', function () {
                btn.style.background = 'rgba(255,255,255,0.08)';
                btn.style.color = '#94a3b8';
                btn.style.transform = 'rotate(0deg)';
            });
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                toggleTheme();
            });
            // Ensure the logo row is a flex container so ml-auto pushes button right
            logoLink.style.display = 'flex';
            logoLink.style.alignItems = 'center';
            logoLink.style.width = '100%';
            logoLink.appendChild(btn);
        }
        return;
    }

    // Fallback: floating circle button (login page / no sidebar)
    if (document.getElementById('theme-toggle-btn')) return;
    var btn2 = document.createElement('button');
    btn2.id = 'theme-toggle-btn';
    btn2.type = 'button';
    var _d2 = document.documentElement.getAttribute('data-theme') === 'dark';
    btn2.title = _d2 ? 'Switch to light mode' : 'Switch to dark mode';
    btn2.innerHTML = _d2 ? _SUN_SVG : _MOON_SVG;
    btn2.style.cssText = [
        'position:fixed',
        'bottom:24px',
        'right:24px',
        'z-index:99999',
        'width:44px',
        'height:44px',
        'border-radius:50%',
        'border:none',
        'cursor:pointer',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'box-shadow:0 4px 16px rgba(0,0,0,0.28)',
        'transition:transform 0.15s,box-shadow 0.15s,color 0.15s',
        'outline:none',
        'padding:0',
        'background:#1e293b',
        'color:#94a3b8'
    ].join(';');
    btn2.addEventListener('mouseenter', function () {
        btn2.style.transform = 'scale(1.1)';
        btn2.style.boxShadow = '0 6px 20px rgba(0,0,0,0.38)';
        btn2.style.color = '#f1f5f9';
    });
    btn2.addEventListener('mouseleave', function () {
        btn2.style.transform = 'scale(1)';
        btn2.style.boxShadow = '0 4px 16px rgba(0,0,0,0.28)';
        btn2.style.color = '#94a3b8';
    });
    btn2.addEventListener('click', function () { toggleTheme(); });
    document.body.appendChild(btn2);
}

// ── Initialize authentication on page load ────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    // Don't run auth checks on the login page itself
    const currentPage = window.location.pathname.split('/').pop();
    if (currentPage === 'login.html') {
        _injectThemeToggle();
        // Authenticated users who navigate back to login → check EULA then go to dashboard
        if (isAuthenticated()) {
            (async function() {
                try {
                    const token = localStorage.getItem('pos_token');
                    const res = await fetch('/api/auth/terms-status', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    if (res.ok) {
                        const d = await res.json();
                        window.location.replace(d.accepted ? 'dashboard.html' : 'eula.html');
                        return;
                    }
                } catch (_) {}
                window.location.replace('dashboard.html');
            })();
        }
        return;
    }
    
    // Check authentication
    if (!requireAuth()) {
        return;
    }
    
    // Permission check for all roles except Super Admin
    const user = getCurrentUser();

    // Always keep Super Admin's permission cache set to full access
    if (user && user.role === 'Super Admin') {
        localStorage.setItem('pos_permissions', JSON.stringify({ _admin: true }));
    }

    if (user && user.role !== 'Super Admin') {
        // Check if permissions are cached
        const hasCachedPerms = localStorage.getItem('pos_permissions') !== null;
        
        if (hasCachedPerms) {
            // Use cached permissions (instant, no network)
            if (!checkPagePermission()) {
                window.location.href = 'noAccess.html';
                return;
            }
            // Refresh cache, then re-render sidebar so revoked links disappear
            cacheUserPermissions().then(() => {
                renderSidebarLinks();
            });
        } else {
            // No cache yet (first page after login) - fetch then enforce
            // Hide page content until permissions are resolved
            document.body.style.visibility = 'hidden';
            cacheUserPermissions().then(() => {
                if (!checkPagePermission()) {
                    window.location.href = 'noAccess.html';
                    return;
                }
                document.body.style.visibility = 'visible';
                renderSidebarLinks();
                updateUsernameDisplay();
                _injectThemeToggle();
            });
            return; // Don't render page yet
        }
    }

    // Inject dark mode toggle button
    _injectThemeToggle();

    // Build sidebar from permissions (replaces hardcoded per-page links)
    renderSidebarLinks();

    // Update username display
    updateUsernameDisplay();
    
    // Set up logout buttons (both old #logout-btn and new header #nav-logout-btn)
    document.querySelectorAll('#logout-btn, #nav-logout-btn').forEach(button => {
        if (button) button.addEventListener('click', logout);
    });

    // Start the shared header clock
    _updateHeaderClock();
    setInterval(_updateHeaderClock, 60000);
    
    // Update auth status display in admin panel
    const authStatusElement = document.getElementById('authStatus');
    if (authStatusElement) {
        const user2 = getCurrentUser();
        if (user2) {
            authStatusElement.textContent = 'Authenticated';
            authStatusElement.classList.remove('text-yellow-500');
            authStatusElement.classList.add('text-green-500');
        }
    }
});