// loading-utils.js - Utility functions for showing/hiding loading indicators

/**
 * Show loading overlay
 * This function will look for an existing loading overlay or create one if it doesn't exist
 */
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

/**
 * Hide loading overlay
 */
function hideLoading() {
    const loadingOverlay = document.getElementById('loading-overlay');
    if (loadingOverlay) {
        loadingOverlay.classList.add('hidden');
    }
}

/**
 * Show loading with a custom message
 * @param {string} message - Custom message to display
 */
function showLoadingWithMessage(message) {
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
    
    // Update the message
    const messageElement = loadingOverlay.querySelector('p');
    if (messageElement) {
        messageElement.textContent = message;
    }
    
    // Show the loading overlay
    loadingOverlay.classList.remove('hidden');
}

// Export functions for use in modules (if needed)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showLoading,
        hideLoading,
        showLoadingWithMessage
    };
}