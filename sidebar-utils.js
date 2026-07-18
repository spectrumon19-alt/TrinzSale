// sidebar-utils.js - Sidebar pin/unpin functionality
// Note: filterSidebarByPermissions and SIDEBAR_HREF_TO_PERMISSION are defined in auth-utils.js

// Enforce uniform styling for any *legacy* sidebar links (static <a> tags that
// some pages may still hardcode). Excludes .snav-link — those are rendered by
// renderSidebarLinks() and fully own their own flex/rail styling.
(function() {
    const style = document.createElement('style');
    style.textContent = `
        #sidebar a[href]:not(.snav-link) {
            display: block;
            padding: 0.5rem 0.75rem;
            font-size: 0.875rem;
            line-height: 1.25rem;
            border-radius: 0.25rem;
            transition: background-color 200ms;
        }
        #sidebar a[href]:not(.snav-link):hover {
            background-color: rgb(55, 65, 81);
        }
    `;
    (document.head || document.documentElement).appendChild(style);
})();

function handleFloatingToggleClick(e) {
    e.preventDefault();
    e.stopPropagation();
    toggleMenu();
}

function toggleMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');
    
    if (!sidebar) return;
    
    if (sidebar.classList.contains('-translate-x-full')) {
        sidebar.classList.remove('-translate-x-full');
        if (overlay) {
            overlay.style.display = 'block';
            setTimeout(() => overlay.style.opacity = 1, 10);
        }
        if (floatingToggle) floatingToggle.classList.add('hidden');
    } else {
        if (overlay) {
            overlay.style.opacity = 0;
            setTimeout(() => overlay.style.display = 'none', 300);
        }
        sidebar.classList.add('-translate-x-full');
        if (floatingToggle) floatingToggle.classList.remove('hidden');
    }
}

function closeMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');
    
    if (!sidebar) return;
    
    const isDesktop = window.innerWidth >= 768;
    const isPinned = localStorage.getItem('sidebarPinned') === 'true';
    
    if (isDesktop && isPinned) return;
    
    if (!sidebar.classList.contains('-translate-x-full')) {
        if (overlay) {
            overlay.style.opacity = 0;
            setTimeout(() => overlay.style.display = 'none', 300);
        }
        sidebar.classList.add('-translate-x-full');
        if (floatingToggle) floatingToggle.classList.remove('hidden');
    }
}

function toggleSidebarPin() {
    const sidebar = document.getElementById('sidebar');
    const pinToggle = document.getElementById('pin-sidebar-toggle');
    const headerPinToggle = document.getElementById('pin-sidebar-toggle-header');
    const mainContent = document.querySelector('.main-col') || document.querySelector('.flex-1');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');
    
    if (!sidebar) return;
    
    if (sidebar.classList.contains('md:translate-x-0') && !sidebar.classList.contains('md:-translate-x-full')) {
        sidebar.classList.remove('md:translate-x-0');
        sidebar.classList.add('md:-translate-x-full');
        if (mainContent) mainContent.classList.remove('md:ml-[220px]');
        if (mainContent) mainContent.classList.add('sidebar-hidden');
        if (pinToggle) pinToggle.checked = false;
        if (headerPinToggle) headerPinToggle.checked = false;
        if (floatingToggle) floatingToggle.classList.remove('hidden');
        localStorage.setItem('sidebarPinned', 'false');
    } else {
        sidebar.classList.remove('md:-translate-x-full');
        sidebar.classList.add('md:translate-x-0');
        if (mainContent) mainContent.classList.add('md:ml-[220px]');
        if (mainContent) mainContent.classList.remove('sidebar-hidden');
        if (pinToggle) pinToggle.checked = true;
        if (headerPinToggle) headerPinToggle.checked = true;
        if (floatingToggle) floatingToggle.classList.add('hidden');
        localStorage.setItem('sidebarPinned', 'true');
    }
}

// ── Rail (icon-only) collapse mode ───────────────────────────────────────────
// Toggles a narrow icon-only sidebar that expands on hover. State persists in
// localStorage('sidebarRail') and is applied via .sidebar-rail-mode on <html>.
function toggleSidebarRail() {
    const railed = document.documentElement.classList.toggle('sidebar-rail-mode');
    try { localStorage.setItem('sidebarRail', railed ? 'true' : 'false'); } catch (e) {}
    _syncRailToggleLabel(railed);

    // When entering rail mode, make sure the sidebar is actually pinned/visible
    // (rail only makes sense on desktop with the sidebar showing).
    if (railed && window.innerWidth >= 768) {
        const sidebar = document.getElementById('sidebar');
        if (sidebar && sidebar.classList.contains('md:-translate-x-full')) {
            sidebar.classList.remove('md:-translate-x-full');
            sidebar.classList.add('md:translate-x-0');
            localStorage.setItem('sidebarPinned', 'true');
        }
    }
}

function _syncRailToggleLabel(railed) {
    const btn = document.getElementById('snav-collapse-btn');
    if (!btn) return;
    const span = btn.querySelector('span');
    if (span) span.textContent = railed ? 'Expand' : 'Collapse';
    btn.setAttribute('aria-label', railed ? 'Expand sidebar' : 'Collapse sidebar to icons');
    btn.title = railed ? 'Expand sidebar' : 'Collapse to icons';
}

function initializeSidebarRail() {
    // The early-paint IIFE in auth-utils.js already added .sidebar-rail-mode if
    // it was previously enabled — just sync the toggle button label to match.
    const railed = document.documentElement.classList.contains('sidebar-rail-mode');
    _syncRailToggleLabel(railed);
}

function initializeSidebarPin() {
    const sidebar = document.getElementById('sidebar');
    const pinToggle = document.getElementById('pin-sidebar-toggle');
    const mainContent = document.querySelector('.main-col') || document.querySelector('.flex-1');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');
    const overlay = document.getElementById('overlay');
    
    if (!sidebar) return;
    
    if (overlay) overlay.addEventListener('click', closeMenu);

    const headerPinToggle = document.getElementById('pin-sidebar-toggle-header');

    // Apply the PERSISTED pin state (default pinned when unset). Previously this
    // always forced pinned, so unpinning never survived a reload.
    const isPinned = localStorage.getItem('sidebarPinned') !== 'false';
    if (isPinned) {
        sidebar.classList.remove('md:-translate-x-full');
        sidebar.classList.add('md:translate-x-0');
        if (mainContent) mainContent.classList.add('md:ml-[220px]');
        if (mainContent) mainContent.classList.remove('sidebar-hidden');
        if (floatingToggle) floatingToggle.classList.add('hidden');
    } else {
        sidebar.classList.remove('md:translate-x-0');
        sidebar.classList.add('md:-translate-x-full');
        if (mainContent) mainContent.classList.remove('md:ml-[220px]');
        if (mainContent) mainContent.classList.add('sidebar-hidden');
        if (floatingToggle) floatingToggle.classList.remove('hidden');
    }
    if (pinToggle) pinToggle.checked = isPinned;
    if (headerPinToggle) headerPinToggle.checked = isPinned;

    if (pinToggle) pinToggle.addEventListener('change', toggleSidebarPin);
    if (headerPinToggle) headerPinToggle.addEventListener('change', toggleSidebarPin);
}

window.addEventListener('resize', function() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');
    
    if (!sidebar) return;
    
    const isDesktop = window.innerWidth >= 768;
    const isPinned = localStorage.getItem('sidebarPinned') !== 'false';
    
    if (isDesktop) {
        if (isPinned) {
            sidebar.classList.remove('md:-translate-x-full');
            sidebar.classList.add('md:translate-x-0');
            if (floatingToggle) floatingToggle.classList.add('hidden');
        } else {
            sidebar.classList.remove('md:translate-x-0');
            sidebar.classList.add('md:-translate-x-full');
            if (floatingToggle) floatingToggle.classList.remove('hidden');
        }
        if (overlay) {
            overlay.style.opacity = 0;
            setTimeout(() => overlay.style.display = 'none', 300);
        }
    } else {
        if (floatingToggle) floatingToggle.classList.add('hidden');
    }
});

document.addEventListener('DOMContentLoaded', function() {
    if (!window.sidebarInitialized) {
        initializeSidebarPin();
        initializeSidebarRail();
        // The collapse toggle is injected asynchronously by renderSidebarLinks();
        // sync its label once it exists.
        let _tries = 0;
        const _syncTimer = setInterval(function () {
            if (document.getElementById('snav-collapse-btn') || _tries++ > 20) {
                clearInterval(_syncTimer);
                initializeSidebarRail();
            }
        }, 100);
        window.sidebarInitialized = true;
    }
});
