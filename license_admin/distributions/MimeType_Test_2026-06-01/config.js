// config.js - Application configuration

// API base URL configuration
// Handle both development and production environments
let API_BASE_URL;

// Check if we're in a development environment (localhost)
if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    // Local development - API runs on localhost with PORT or 5001
    const port = window.location.port || '5001';
    API_BASE_URL = window.location.protocol + '//' + window.location.hostname + ':' + port;
} else {
    // Production environment - Check if there's a specific API configuration
    // First check if there's an environment variable for the API URL
    if (typeof window.API_BASE_URL !== 'undefined' && window.API_BASE_URL) {
        API_BASE_URL = window.API_BASE_URL;
    } else {
        // Default to same host - in production, frontend and backend are typically on the same server
        // If your API is on a different port, you'll need to specify it
        const currentPort = window.location.port;
        API_BASE_URL = window.location.protocol + '//' + window.location.hostname + (currentPort ? ':' + currentPort : '');
    }
}

// Export configuration
window.APP_CONFIG = {
    API_BASE_URL: API_BASE_URL
};