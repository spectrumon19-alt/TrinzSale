// component-utils.js - Utility functions for loading reusable components

/**
 * Load a component from the components directory and insert it into an element
 * @param {string} componentPath - Path to the component file (e.g., 'components/footer.html')
 * @param {string} targetElementId - ID of the element to insert the component into
 */
function loadComponent(componentPath, targetElementId) {
    fetch(componentPath)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load component: ${componentPath}`);
            }
            return response.text();
        })
        .then(html => {
            const targetElement = document.getElementById(targetElementId);
            if (targetElement) {
                targetElement.innerHTML = html;
            } else {
                console.error(`Target element with ID '${targetElementId}' not found for component: ${componentPath}`);
            }
        })
        .catch(error => {
            console.error('Error loading component:', error);
        });
}

/**
 * Load the footer component into an element with ID 'footer-container'
 */
function loadFooter() {
    loadComponent('components/footer.html', 'footer-container');
}

// Automatically load footer when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Check if there's a footer container element
    const footerContainer = document.getElementById('footer-container');
    if (footerContainer) {
        loadFooter();
    }
});