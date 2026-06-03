// sidebar-utils.js - Sidebar pin/unpin functionality
// Note: filterSidebarByPermissions and SIDEBAR_HREF_TO_PERMISSION are defined in auth-utils.js

// Enforce uniform sidebar link styling (matching dashboard.html: py-2 px-3 text-sm)
(function() {
    const style = document.createElement('style');
    style.textContent = `
        #sidebar a[href] {
            display: block;
            padding: 0.5rem 0.75rem;
            font-size: 0.875rem;
            line-height: 1.25rem;
            border-radius: 0.25rem;
            transition: background-color 200ms;
        }
        #sidebar a[href]:hover {
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
    const mainContent = document.querySelector('.flex-1');
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

function initializeSidebarPin() {
    const sidebar = document.getElementById('sidebar');
    const pinToggle = document.getElementById('pin-sidebar-toggle');
    const mainContent = document.querySelector('.flex-1');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');
    const overlay = document.getElementById('overlay');
    
    if (!sidebar) return;
    
    if (overlay) overlay.addEventListener('click', closeMenu);
    
    // Default to pinned (visible on desktop)
    sidebar.classList.remove('md:-translate-x-full');
    sidebar.classList.add('md:translate-x-0');
    if (mainContent) mainContent.classList.add('md:ml-[220px]');
    if (mainContent) mainContent.classList.remove('sidebar-hidden');
    if (pinToggle) pinToggle.checked = true;
    if (floatingToggle) floatingToggle.classList.add('hidden');
    
    if (pinToggle) pinToggle.addEventListener('change', toggleSidebarPin);
    
    const headerPinToggle = document.getElementById('pin-sidebar-toggle-header');
    if (headerPinToggle) {
        headerPinToggle.addEventListener('change', toggleSidebarPin);
        if (pinToggle) headerPinToggle.checked = pinToggle.checked;
    }
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
        window.sidebarInitialized = true;
    }
});
