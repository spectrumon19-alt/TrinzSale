// sales.js

// Global variables
let currentUser = null;
let invoiceItems = [];
let searchResults = [];
let currentSelectedProduct = null;
let searchTimeout = null;
let activeResultIndex = -1;
let currentSearchQuery = '';
let discountPercentage = 0;
let selectedCreditCustomer = null; // For credit sales
let creditSearchTimeout = null; // For credit customer search debouncing

// ── Product search — called directly via oninput on the HTML element ──────────
function onProductSearch(value) {
    const query = (value || '').trim();
    if (searchTimeout) clearTimeout(searchTimeout);
    const resultsDiv = document.getElementById('search-results');
    if (query.length < 1) {
        if (resultsDiv) resultsDiv.innerHTML = '';
        searchResults = [];
        activeResultIndex = -1;
        return;
    }
    searchTimeout = setTimeout(function() { searchProducts(query); }, 200);
}

function onProductSearchKey(e, input) {
    if (e.key === 'ArrowDown') {
        e.preventDefault(); navigateResults(1);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault(); navigateResults(-1);
    } else if (e.key === 'Escape') {
        e.preventDefault();
        const d = document.getElementById('search-results');
        if (d) d.innerHTML = '';
        activeResultIndex = -1;
    } else if (e.key === 'Enter') {
        e.preventDefault();
        if (activeResultIndex >= 0 && searchResults[activeResultIndex]) {
            selectProduct(searchResults[activeResultIndex]);
        } else {
            const code = input.value.trim();
            if (code) lookupByBarcode(code);
        }
    }
}

// DOM Elements
let productSearchInput, searchResultsDiv, quantityInput, addItemBtn, invoiceItemsBody;
let customerNameInput, customerMobileMainInput, totalAmountSpan, totalGstSpan, grandTotalSpan;
let savePrintBtn, clearBtn, logoutBtn, usernameSpan, discountInput;
let modeOfPaymentSelect, upiDetailsDiv, upiTransactionIdInput, customerMobileInput;
// Credit customer elements
let creditDetailsDiv;
let creditCustomerInfoDiv, creditCustomerName, creditCustomerBalance, creditCustomerId;
// Credit customer modal elements
let creditCustomerSearchModal, closeCreditSearchModalBtn, searchCreditMobileInput, performCreditSearchBtn;
let creditSearchResultsDiv, creditCustomerList, closeCreditWindowBtn;

// Function to initialize UI elements for index.html
function initializeUIElements() {
    // ── Payment pill buttons ──────────────────────────────────────────────────
    const pillContainer = document.getElementById('pay-pills');
    const modeOfPayment = document.getElementById('mode-of-payment');
    if (pillContainer && modeOfPayment) {
        pillContainer.querySelectorAll('.pay-pill').forEach(function(pill) {
            pill.addEventListener('click', function() {
                pillContainer.querySelectorAll('.pay-pill').forEach(p => p.classList.remove('active'));
                this.classList.add('active');
                modeOfPayment.value = this.dataset.value;
                modeOfPayment.dispatchEvent(new Event('change'));
            });
        });
        // Sync pills if select value pre-set
        const activePill = pillContainer.querySelector(`.pay-pill[data-value="${modeOfPayment.value}"]`);
        if (activePill) {
            pillContainer.querySelectorAll('.pay-pill').forEach(p => p.classList.remove('active'));
            activePill.classList.add('active');
        }
    }

    // Mode of payment change handler
    const upiDetails = document.getElementById('upi-details');
    const creditDetails = document.getElementById('credit-details');

    if (modeOfPayment && upiDetails && creditDetails) {
        modeOfPayment.addEventListener('change', function() {
            if (this.value === 'UPI') {
                upiDetails.style.display = 'block';
                creditDetails.style.display = 'none';
                hideCreditCustomerInfo();
                const cur = grandTotalSpan ? parseFloat(grandTotalSpan.textContent.replace(/[₹,]/g, '')) || 0 : 0;
                refreshUpiQr(cur);
            } else if (this.value === 'Credit') {
                upiDetails.style.display = 'none';
                creditDetails.style.display = 'block';
                // Don't hide credit customer info when switching to Credit
                // Open credit customer search modal
                if (creditCustomerSearchModal) {
                    creditCustomerSearchModal.style.display = 'flex';
                }
                refreshUpiQr(0); // hide QR panel
            } else {
                upiDetails.style.display = 'none';
                creditDetails.style.display = 'none';
                hideCreditCustomerInfo();
                refreshUpiQr(0); // hide QR panel
            }
        });
        
        // Initialize payment options visibility on page load
        if (modeOfPayment.value === 'UPI') {
            upiDetails.style.display = 'block';
            creditDetails.style.display = 'none';
        } else if (modeOfPayment.value === 'Credit') {
            upiDetails.style.display = 'none';
            creditDetails.style.display = 'block';
            // Open credit customer search modal
            if (creditCustomerSearchModal) {
                creditCustomerSearchModal.style.display = 'flex';
            }
        } else {
            upiDetails.style.display = 'none';
            creditDetails.style.display = 'none';
        }
    }
}

// Helper function to validate mobile numbers (10 digits)
function validateMobileNumber() {
    // Allow only digits
    this.value = this.value.replace(/[^0-9]/g, '');
    // Limit to 10 digits
    if (this.value.length > 10) {
        this.value = this.value.slice(0, 10);
    }
}

// Helper function to validate UPI transaction ID (5 digits)
function validateUpiTransactionId() {
    // Allow only digits
    this.value = this.value.replace(/[^0-9]/g, '');
    // Limit to 5 digits
    if (this.value.length > 5) {
        this.value = this.value.slice(0, 5);
    }
}

// Helper function to convert API string values to numbers
function convertProductNumbers(product) {
    try {
        return {
            ...product,
            gst_rate: product.gst_rate ? parseFloat(product.gst_rate) : 0,
            selling_rate: product.selling_rate ? parseFloat(product.selling_rate) : 0,
            purchase_rate: product.purchase_rate ? parseFloat(product.purchase_rate) : null
        };
    } catch (error) {
        console.error('Error converting product numbers:', error, product);
        return {
            ...product,
            gst_rate: 0,
            selling_rate: 0,
            purchase_rate: null
        };
    }
}

// Helper function to check stock availability for a product
function checkProductStock(product_id, requested_quantity) {
    return new Promise((resolve, reject) => {
        const token = localStorage.getItem('pos_token');
        if (!token) {
            window.location.href = 'login.html';
            reject(new Error('Not authenticated'));
            return;
        }
        
        // Show loading indicator
        showLoading();
        
        // Call the products API to get current stock information
        fetch(`/api/products/${product_id}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(product => {
            // Hide loading indicator
            hideLoading();
            
            // Check if product has stock information
            if (product && product.stock_quantity !== undefined) {
                const current_stock = parseInt(product.stock_quantity) || 0;
                if (current_stock < requested_quantity) {
                    reject(new Error(`INSUFFICIENT_STOCK: Product '${product.name}' has only ${current_stock} units in stock, but ${requested_quantity} units were requested. Please reduce the quantity or select a different product.`));
                } else {
                    resolve(true);
                }
            } else {
                // If no stock information, assume it's available (backward compatibility)
                resolve(true);
            }
        })
        .catch(error => {
            // Hide loading indicator
            hideLoading();
            
            console.error('Stock check error:', error);
            // If we can't check stock, assume it's available to avoid blocking sales
            resolve(true);
        });
    });
}

// Initialize DOM elements
function initDOMElements() {
    productSearchInput = document.getElementById('product-search-input');
    searchResultsDiv = document.getElementById('search-results');
    quantityInput = document.getElementById('quantity-input');
    addItemBtn = document.getElementById('add-item-btn');
    invoiceItemsBody = document.getElementById('invoice-items-body');
    customerNameInput = document.getElementById('customer-name');
    customerMobileMainInput = document.getElementById('customer-mobile-main');
    totalAmountSpan = document.getElementById('total-amount');
    totalGstSpan = document.getElementById('total-gst');
    grandTotalSpan = document.getElementById('grand-total');
    savePrintBtn = document.getElementById('save-print-btn');
    clearBtn = document.getElementById('clear-btn');
    logoutBtn = document.getElementById('nav-logout-btn');
    usernameSpan = document.getElementById('nav-username');
    discountInput = document.getElementById('discount-input');
    
    // Invoice date - set default to today
    const invoiceDateInput = document.getElementById('invoice-date');
    if (invoiceDateInput) {
        const today = new Date().toISOString().split('T')[0];
        invoiceDateInput.value = today;
    }
    
    // Payment options elements
    modeOfPaymentSelect = document.getElementById('mode-of-payment');
    upiDetailsDiv = document.getElementById('upi-details');
    upiTransactionIdInput = document.getElementById('upi-transaction-id');
    customerMobileInput = document.getElementById('customer-mobile');
    
    // Credit customer elements
    creditDetailsDiv = document.getElementById('credit-details');
    creditCustomerInfoDiv = document.getElementById('credit-customer-info');
    creditCustomerName = document.getElementById('credit-customer-name');
    creditCustomerBalance = document.getElementById('credit-customer-balance');
    creditCustomerId = document.getElementById('credit-customer-id');
    
    // Credit customer modal elements
    creditCustomerSearchModal = document.getElementById('credit-customer-search-modal');
    closeCreditSearchModalBtn = document.getElementById('close-credit-search-modal');
    searchCreditMobileInput = document.getElementById('search-credit-mobile');
    performCreditSearchBtn = document.getElementById('perform-credit-search');
    creditSearchResultsDiv = document.getElementById('credit-search-results');
    creditCustomerList = document.getElementById('credit-customer-list');
    closeCreditWindowBtn = document.getElementById('close-credit-window-btn');

    
    // ── Mobile search (primary) ──────────────────────────────────────────────
    let _mobileSearchTimer = null;
    if (customerMobileMainInput) {
        customerMobileMainInput.addEventListener('input', function() {
            clearTimeout(_mobileSearchTimer);
            const q = this.value.trim();
            if (q.length < 2) { hideMobileDropdown(); return; }
            _mobileSearchTimer = setTimeout(() => searchCustomers(q, 'mobile'), 280);
        });
        customerMobileMainInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') hideMobileDropdown();
        });
    }

    // Close mobile dropdown on outside click
    document.addEventListener('click', function(e) {
        const mDrop = document.getElementById('mobile-search-results');
        if (mDrop && !mDrop.contains(e.target) && e.target !== customerMobileMainInput) {
            hideMobileDropdown();
        }
    });

    // Add input validation for mobile number and UPI transaction ID
    if (customerMobileInput) {
        customerMobileInput.addEventListener('input', validateMobileNumber);
    }
    
    if (upiTransactionIdInput) {
        upiTransactionIdInput.addEventListener('input', validateUpiTransactionId);
    }
    
    // Add Enter key support for credit customer search
    if (searchCreditMobileInput) {
        searchCreditMobileInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                // Trigger the search button click
                if (performCreditSearchBtn) {
                    performCreditSearchBtn.click();
                }
            }
        });
        
        // Add debounced predictive search as user types
        let creditSearchTimeout = null;
        searchCreditMobileInput.addEventListener('input', function() {
            const query = this.value.trim();
            
            // Clear any existing timeout
            if (creditSearchTimeout) {
                clearTimeout(creditSearchTimeout);
            }
            
            // If query is empty, hide results
            if (query.length < 1) {
                if (creditSearchResultsDiv) {
                    creditSearchResultsDiv.style.display = 'none';
                }
                return;
            }
            
            // Debounce search requests - wait 300ms after user stops typing
            // Only search if we have at least 3 characters for better performance
            if (query.length >= 3) {
                creditSearchTimeout = setTimeout(() => {
                    console.log('Performing predictive search for:', query);
                    searchCreditCustomers(query, true); // Pass true for predictive search
                }, 300);
            }
        });
    }
    
    return true;
}

// Attach event listeners
function attachEventListeners() {
    try {
        // Product search is handled via oninput/onkeydown HTML attributes (onProductSearch / onProductSearchKey)
        
        // Discount input change listener
        if (discountInput) {
            discountInput.addEventListener('change', function() {
                discountPercentage = parseFloat(this.value) || 0;
                if (discountPercentage < 0) discountPercentage = 0;
                if (discountPercentage > 100) discountPercentage = 100;
                this.value = discountPercentage;
                renderInvoiceItems(); // Re-render to apply discount
            });
        }
        
        // Add item to invoice
        if (addItemBtn) {
            addItemBtn.addEventListener('click', function() {
                if (!currentSelectedProduct) {
                    alert('Please select a product first');
                    return;
                }
                
                const quantity = parseInt(quantityInput.value) || 1;
                
                // Check stock availability before adding item
                checkProductStock(currentSelectedProduct.product_id, quantity)
                    .then(() => {
                        // Ensure currentSelectedProduct has proper numeric values
                        const productToAdd = convertProductNumbers(currentSelectedProduct);
                        
                        // Check if product is already in invoice
                        const existingItemIndex = invoiceItems.findIndex(item => item.product_id === productToAdd.product_id);
                        
                        if (existingItemIndex >= 0) {
                            // Update quantity if product already exists
                            invoiceItems[existingItemIndex].quantity += quantity;
                        } else {
                            // Add new item
                            const item = {
                                product_id: productToAdd.product_id,
                                name: productToAdd.name,
                                pack_size: productToAdd.pack_size,
                                gst_rate: productToAdd.gst_rate,
                                selling_rate: productToAdd.selling_rate,
                                quantity: quantity,
                                discount: 0
                            };
                            invoiceItems.push(item);
                        }
                        
                        renderInvoiceItems();
                        clearProductSelection();
                    })
                    .catch(error => {
                        // Show stock error alert
                        alert('❌ STOCK ERROR ❌\n\n' + error.message + '\n\nThe item was not added to the cart.');
                    });
            });
        }
        
        // Close credit customer modal
        if (closeCreditSearchModalBtn) {
            closeCreditSearchModalBtn.addEventListener('click', function() {
                if (creditCustomerSearchModal) {
                    creditCustomerSearchModal.style.display = 'none';
                }
            });
        }
        
        // Close window button - hide the modal instead of closing the window
        if (closeCreditWindowBtn) {
            closeCreditWindowBtn.addEventListener('click', function() {
                if (creditCustomerSearchModal) {
                    creditCustomerSearchModal.style.display = 'none';
                }
            });
        }
        
        // Close modal when clicking outside of it
        if (creditCustomerSearchModal) {
            creditCustomerSearchModal.addEventListener('click', function(event) {
                // Check if the click was directly on the modal background (not on its content)
                if (event.target === creditCustomerSearchModal) {
                    creditCustomerSearchModal.style.display = 'none';
                }
            });
            
            // Close modal when pressing Escape key
            document.addEventListener('keydown', function(event) {
                if (event.key === 'Escape' && creditCustomerSearchModal.style.display === 'flex') {
                    creditCustomerSearchModal.style.display = 'none';
                }
            });
        }
        
        // Perform customer search in modal
        if (performCreditSearchBtn) {
            performCreditSearchBtn.addEventListener('click', function() {
                // Don't trim mobile numbers as they might have leading zeros that are significant
                const mobile = searchCreditMobileInput.value;
                if (!mobile) {
                    alert('Please enter a mobile number to search for.');
                    return;
                }
                if (mobile.length !== 10) {
                    alert('Please enter a valid 10-digit mobile number.');
                    return;
                }
                searchCreditCustomers(mobile, false); // Pass false for exact search
            });
        }
        
        // Save and print functionality
        if (savePrintBtn) {
            savePrintBtn.addEventListener('click', function() {
                if (invoiceItems.length === 0) {
                    alert('Please add at least one item to the invoice');
                    return;
                }
                
                const token = localStorage.getItem('pos_token');
                
                // Validate payment method
                if (modeOfPaymentSelect && modeOfPaymentSelect.value === 'UPI') {
                    // Check if mobile number is provided
                    if (customerMobileInput && !customerMobileInput.value.trim()) {
                        alert('Customer mobile number is required for UPI payments');
                        customerMobileInput.focus();
                        return;
                    }
                    
                    // Validate mobile number format (10 digits)
                    if (customerMobileInput && customerMobileInput.value.trim()) {
                        const mobileValue = customerMobileInput.value.trim();
                        const mobileRegex = /^[0-9]{10}$/;
                        if (!mobileRegex.test(mobileValue)) {
                            alert('Please enter a valid 10-digit mobile number');
                            customerMobileInput.focus();
                            return;
                        }
                    }
                    
                    // Check if UPI transaction ID is provided
                    if (upiTransactionIdInput && !upiTransactionIdInput.value.trim()) {
                        alert('Last 5 digits of UPI transaction ID are required for UPI payments');
                        upiTransactionIdInput.focus();
                        return;
                    }
                    
                    // Validate UPI transaction ID format (5 digits)
                    if (upiTransactionIdInput && upiTransactionIdInput.value.trim()) {
                        const upiValue = upiTransactionIdInput.value.trim();
                        const upiRegex = /^[0-9]{5}$/;
                        if (!upiRegex.test(upiValue)) {
                            alert('Please enter exactly 5 digits for the UPI transaction ID');
                            upiTransactionIdInput.focus();
                            return;
                        }
                    }
                } else if (modeOfPaymentSelect && modeOfPaymentSelect.value === 'Credit') {
                    // For credit sales, a customer must be selected
                    if (!selectedCreditCustomer) {
                        alert('Please select a credit customer before proceeding.');
                        return;
                    }
                }
                
                // Show loading indicator
                showLoading();
                
                // Prepare invoice data
                const invoiceDateInput = document.getElementById('invoice-date');
                const invoiceDate = invoiceDateInput && invoiceDateInput.value ? invoiceDateInput.value : null;
                
                const invoiceData = {
                    customer_name: customerNameInput.value,
                    customer_contact: '',
                    invoice_date: invoiceDate,
                    mode_of_payment: modeOfPaymentSelect ? modeOfPaymentSelect.value : 'Cash',
                    upi_transaction_id: (modeOfPaymentSelect && modeOfPaymentSelect.value === 'UPI') ? upiTransactionIdInput.value : null,
                    customer_mobile: customerMobileMainInput && customerMobileMainInput.value.trim()
                        ? customerMobileMainInput.value.trim()
                        : ((modeOfPaymentSelect && modeOfPaymentSelect.value === 'UPI') ? (customerMobileInput ? customerMobileInput.value : null) : null),
                    discount_percentage: discountPercentage,
                    items: invoiceItems.map(item => ({
                        product_id: item.product_id,
                        quantity: item.quantity,
                        selling_rate: item.selling_rate,
                        discount: item.discount || 0
                    }))
                };
                
                fetch('/api/sales', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify(invoiceData)
                })
                .then(response => {
                    if (response.ok) {
                        return response.json();
                    } else {
                        return response.json().then(errorData => {
                            // Check if it's a stock error
                            if (errorData.message && (errorData.message.includes('No stock in inventory') || errorData.message.includes('INSUFFICIENT_STOCK'))) {
                                throw new Error(`Stock Error: ${errorData.message}`);
                            }
                            throw new Error(`HTTP ${response.status}: ${errorData.message || 'Unknown error'}`);
                        });
                    }
                })
                .then(invoice => {
                    hideLoading();

                    // ── Offline path: SW returned synthetic 202 ──────────────
                    if (invoice && invoice.offline === true) {
                        if (window.pwaRefreshQueueBadge) window.pwaRefreshQueueBadge();
                        if (window.showPwaToast) {
                            window.showPwaToast('📶 Offline — sale queued locally. Will sync when connected.', 'warn');
                        } else {
                            alert('You are offline.\n\nSale saved locally and will sync automatically when internet is restored.');
                        }
                        clearInvoice();
                        return;
                    }

                    // ── Online path ──────────────────────────────────────────
                    // For credit sales, update the customer's balance
                    if (modeOfPaymentSelect && modeOfPaymentSelect.value === 'Credit' && selectedCreditCustomer) {
                        updateCreditCustomerBalance(invoice);
                    }

                    // Show email modal (handles print + clear inside)
                    showEmailReceiptModal(invoice);
                })
                .catch(error => {
                    // Hide loading indicator
                    hideLoading();

                    console.error('Save error:', error);
                    const errorMessage = error && error.message ? error.message : 'Unknown error occurred';

                    // Check if it's a stock error
                    if (errorMessage.includes('Stock Error:')) {
                        alert('❌ STOCK ERROR ❌\n\n' + errorMessage.replace('Stock Error: ', '') + '\n\nThe sale has been cancelled to prevent negative inventory.');
                    } else {
                        alert('Failed to save invoice. Please try again. Error: ' + errorMessage);
                    }
                });
            });
        }
        
        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', clearInvoice);
        }
        
        // View Invoices button
        const viewInvoicesBtn = document.getElementById('view-invoices-btn');
        if (viewInvoicesBtn) {
            viewInvoicesBtn.addEventListener('click', function() {
                const modal = document.getElementById('view-invoices-modal');
                if (modal) {
                    modal.classList.remove('hidden');
                    // Default to today
                    const today = new Date().toISOString().split('T')[0];
                    const fromDate = document.getElementById('invoice-from-date');
                    const toDate = document.getElementById('invoice-to-date');
                    if (fromDate && !fromDate.value) fromDate.value = today;
                    if (toDate && !toDate.value) toDate.value = today;
                    loadRecentInvoices();
                }
            });
        }
        
        const closeInvoicesModal = document.getElementById('close-invoices-modal');
        if (closeInvoicesModal) {
            closeInvoicesModal.addEventListener('click', function() {
                const modal = document.getElementById('view-invoices-modal');
                if (modal) modal.classList.add('hidden');
            });
        }
        
        const loadInvoicesBtn = document.getElementById('load-invoices-btn');
        if (loadInvoicesBtn) {
            loadInvoicesBtn.addEventListener('click', loadRecentInvoices);
        }
        
        const todayInvoicesBtn = document.getElementById('today-invoices-btn');
        if (todayInvoicesBtn) {
            todayInvoicesBtn.addEventListener('click', function() {
                const today = new Date().toISOString().split('T')[0];
                const fromDate = document.getElementById('invoice-from-date');
                const toDate = document.getElementById('invoice-to-date');
                if (fromDate) fromDate.value = today;
                if (toDate) toDate.value = today;
                loadRecentInvoices();
            });
        }
        
        const showCancelledChk = document.getElementById('show-cancelled-chk');
        if (showCancelledChk) {
            showCancelledChk.addEventListener('change', loadRecentInvoices);
        }
        const showCompletedChk = document.getElementById('show-completed-chk');
        if (showCompletedChk) {
            showCompletedChk.addEventListener('change', loadRecentInvoices);
        }
        
        // Close modal when clicking outside
        const invoicesModal = document.getElementById('view-invoices-modal');
        if (invoicesModal) {
            invoicesModal.addEventListener('click', function(e) {
                if (e.target === invoicesModal) {
                    invoicesModal.classList.add('hidden');
                }
            });
        }
        
        // Payment method change listener
        if (modeOfPaymentSelect) {
            modeOfPaymentSelect.addEventListener('change', function() {
                if (this.value === 'UPI') {
                    if (upiDetailsDiv) upiDetailsDiv.style.display = 'block';
                    if (creditDetailsDiv) creditDetailsDiv.style.display = 'none';
                    // Only hide credit customer info if we're switching away from Credit
                    if (selectedCreditCustomer) {
                        hideCreditCustomerInfo();
                    }
                } else if (this.value === 'Credit') {
                    if (upiDetailsDiv) upiDetailsDiv.style.display = 'none';
                    if (creditDetailsDiv) creditDetailsDiv.style.display = 'block';
                    // Don't hide credit customer info when switching to Credit
                    // Open credit customer search modal
                    if (creditCustomerSearchModal) {
                        creditCustomerSearchModal.style.display = 'flex';
                    }
                } else {
                    if (upiDetailsDiv) upiDetailsDiv.style.display = 'none';
                    if (creditDetailsDiv) creditDetailsDiv.style.display = 'none';
                    // Only hide credit customer info if we're switching away from Credit
                    if (selectedCreditCustomer) {
                        hideCreditCustomerInfo();
                    }
                }
            });
            
            // Initialize the UPI details visibility based on the default selection
            setTimeout(function() {
                if (modeOfPaymentSelect.value === 'UPI') {
                    if (upiDetailsDiv) upiDetailsDiv.style.display = 'block';
                    if (creditDetailsDiv) creditDetailsDiv.style.display = 'none';
                } else if (modeOfPaymentSelect.value === 'Credit') {
                    if (upiDetailsDiv) upiDetailsDiv.style.display = 'none';
                    if (creditDetailsDiv) creditDetailsDiv.style.display = 'block';
                    // Open credit customer search modal
                    if (creditCustomerSearchModal) {
                        creditCustomerSearchModal.style.display = 'flex';
                    }
                } else {
                    if (upiDetailsDiv) upiDetailsDiv.style.display = 'none';
                    if (creditDetailsDiv) creditDetailsDiv.style.display = 'none';
                }
            }, 100);
        }
        
        // Close search results when clicking elsewhere
        document.addEventListener('click', function(event) {
            if (searchResultsDiv && !productSearchInput.contains(event.target) && !searchResultsDiv.contains(event.target)) {
                searchResultsDiv.innerHTML = '';
            }
        });
        
        console.log('Event listeners attached');
    } catch (error) {
        console.error('Error attaching event listeners:', error);
    }
}

function searchProducts(query) {
    const token = localStorage.getItem('pos_token');
    if (!token) { window.location.href = 'login.html'; return; }

    currentSearchQuery = query;
    activeResultIndex = -1;

    const d = document.getElementById('search-results');
    if (d) d.innerHTML = '<div class="search-result-item" style="color:var(--text-muted,#888);font-style:italic;pointer-events:none;">Searching…</div>';

    fetch(`/api/products?q=${encodeURIComponent(query)}`, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(function(response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
    })
    .then(function(products) {
        searchResults = products.map(function(p) { return convertProductNumbers(p); });
        displaySearchResults();
    })
    .catch(function(error) {
        console.error('Search error:', error);
        const d2 = document.getElementById('search-results');
        if (d2) d2.innerHTML = '<div class="search-result-item" style="color:#ef4444;pointer-events:none;">Search failed</div>';
    });
}

function displaySearchResults() {
    const d = document.getElementById('search-results');
    if (!d) return;

    if (searchResults.length === 0) {
        d.innerHTML = '<div class="search-result-item" style="color:var(--text-muted,#888);pointer-events:none;">No products found</div>';
        return;
    }

    d.innerHTML = '';
    searchResults.forEach(function(product, index) {
        const item = document.createElement('div');
        item.className = 'search-result-item';
        item.dataset.index = index;

        const rate = parseFloat(product.selling_rate) || 0;
        const sku  = product.sku || '';
        const name = product.name || 'Unknown';

        item.innerHTML =
            '<div class="search-result-name" title="' + name + '">' + highlightMatch(name, currentSearchQuery) + '</div>' +
            '<div class="search-result-details">' +
              '<span class="search-result-sku">' + highlightMatch(sku, currentSearchQuery) + '</span>' +
              '<span class="search-result-price">₹' + rate.toFixed(2) + '</span>' +
            '</div>';

        item.addEventListener('mouseenter', function() { setActiveResult(index); });
        item.addEventListener('click', function() { selectProduct(product); });
        d.appendChild(item);
    });
}

function highlightMatch(text, query) {
    if (!query || !text) return text || '';
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return text.replace(new RegExp(`(${escaped})`, 'gi'), '<strong style="color:var(--brand-accent,#6366f1);">$1</strong>');
}

function setActiveResult(index) {
    activeResultIndex = index;
    const d = document.getElementById('search-results');
    if (!d) return;
    d.querySelectorAll('.search-result-item').forEach(function(el, i) {
        el.classList.toggle('search-result-active', i === index);
    });
}

function navigateResults(direction) {
    if (!searchResults.length) return;
    const next = activeResultIndex + direction;
    setActiveResult(next < 0 ? searchResults.length - 1 : next >= searchResults.length ? 0 : next);
    const d = document.getElementById('search-results');
    if (d) { const a = d.querySelector('.search-result-active'); if (a) a.scrollIntoView({ block: 'nearest' }); }
}

function selectProduct(product) {
    try {
        currentSelectedProduct = convertProductNumbers(product);
        activeResultIndex = -1;
        const inp = document.getElementById('product-search-input');
        if (inp) inp.value = product.name || '';
        const d = document.getElementById('search-results');
        if (d) d.innerHTML = '';
        
        // Ensure the Add Item button is enabled
        if (addItemBtn) {
            addItemBtn.disabled = false;
        }
    } catch (error) {
        console.error('Error selecting product:', error, product);
    }
}

function clearProductSelection() {
    if (productSearchInput) {
        productSearchInput.value = '';
    }
    if (quantityInput) {
        quantityInput.value = '1';
    }
    currentSelectedProduct = null;
    if (searchResultsDiv) {
        searchResultsDiv.innerHTML = '';
    }
}

function renderInvoiceItems() {
    if (!invoiceItemsBody) {
        return;
    }
    
    invoiceItemsBody.innerHTML = '';
    
    let totalTaxableAmount = 0;
    let totalGst = 0;
    let totalDiscount = 0;
    
    invoiceItems.forEach((item, index) => {
        // Ensure all numeric values are numbers
        const quantity = typeof item.quantity === 'string' ? parseInt(item.quantity) : item.quantity;
        const sellingRate = typeof item.selling_rate === 'string' ? parseFloat(item.selling_rate) : item.selling_rate;
        const gstRate = typeof item.gst_rate === 'string' ? parseFloat(item.gst_rate) : item.gst_rate;
        const discount = typeof item.discount === 'string' ? parseFloat(item.discount) : item.discount || 0;
        
        // Calculate item amounts
        const lineAmount = quantity * sellingRate;
        const discountedAmount = lineAmount * (1 - discount / 100);
        const taxableValue = discountedAmount / (1 + (gstRate / 100));
        const itemGst = discountedAmount - taxableValue;
        const sgst = itemGst / 2;
        const cgst = itemGst / 2;
        
        // Update totals
        totalTaxableAmount += taxableValue;
        totalGst += itemGst;
        totalDiscount += (lineAmount - discountedAmount);
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="align-center">${index + 1}</td>
            <td class="align-text">${item.name}</td>
            <td class="align-text">${item.pack_size || '-'}</td>
            <td class="align-center">${gstRate}%</td>
            <td class="align-center">${quantity}</td>
            <td class="align-right"><input type="number" class="item-rate" data-index="${index}" value="${sellingRate.toFixed(2)}" min="0" step="0.01" style="width: 80px;"></td>
            <td class="align-right">₹${taxableValue.toFixed(2)}</td>
            <td class="align-right">₹${sgst.toFixed(2)}</td>
            <td class="align-right">₹${cgst.toFixed(2)}</td>
            <td class="align-right">₹${discountedAmount.toFixed(2)}</td>
            <td class="align-center">
                <input type="number" class="item-discount" data-index="${index}" value="${discount}" min="0" max="100" step="0.1" style="width: 60px; margin-right: 5px;">
                <button class="btn-warning edit-item-btn" data-index="${index}" title="Edit Item">
                    <svg fill="currentColor" viewBox="0 0 16 16">
                        <path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168l10-10zM11.207 2.5 13.5 4.793 14.793 3.5 12.5 1.207 11.207 2.5zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293l6.5-6.5zm-9.761 5.175-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.325z"/>
                    </svg>
                </button>
                <button class="btn-danger remove-item-btn" data-index="${index}" title="Remove Item">
                    <svg fill="currentColor" viewBox="0 0 16 16">
                        <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/>
                        <path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
                    </svg>
                </button>
            </td>
        `;
        invoiceItemsBody.appendChild(row);
    });
    
    // Update totals
    const discountAmount = totalTaxableAmount * (discountPercentage / 100);
    const finalTotal = (totalTaxableAmount - discountAmount) + totalGst;

    // Cart item count badge
    const countEl = document.getElementById('cart-item-count');
    if (countEl) {
        const total = invoiceItems.reduce((s, i) => s + (i.quantity || 1), 0);
        countEl.textContent = total + (total === 1 ? ' item' : ' items');
    }

    // Display the totals
    if (totalAmountSpan) totalAmountSpan.textContent = `₹${totalTaxableAmount.toFixed(2)}`;
    if (totalGstSpan) totalGstSpan.textContent = `₹${totalGst.toFixed(2)}`;
    if (grandTotalSpan) grandTotalSpan.textContent = `₹${finalTotal.toFixed(2)}`;
    refreshUpiQr(finalTotal);
    
    // Add event listeners to remove buttons
    document.querySelectorAll('.remove-item-btn').forEach(button => {
        button.addEventListener('click', function() {
            const index = parseInt(this.getAttribute('data-index'));
            removeInvoiceItem(index);
        });
    });
    
    // Add event listeners to edit buttons
    document.querySelectorAll('.edit-item-btn').forEach(button => {
        button.addEventListener('click', function() {
            const index = parseInt(this.getAttribute('data-index'));
            editInvoiceItem(index);
        });
    });
    
    // Add event listeners to discount inputs
    document.querySelectorAll('.item-discount').forEach(input => {
        input.addEventListener('change', function() {
            const index = parseInt(this.getAttribute('data-index'));
            const discount = parseFloat(this.value) || 0;
            if (discount < 0) discount = 0;
            if (discount > 100) discount = 100;
            this.value = discount;
            updateItemDiscount(index, discount);
        });
    });
    
    // Add event listeners to rate inputs
    document.querySelectorAll('.item-rate').forEach(input => {
        input.addEventListener('change', function() {
            const index = parseInt(this.getAttribute('data-index'));
            const newRate = parseFloat(this.value) || 0;
            if (newRate < 0) newRate = 0;
            this.value = newRate.toFixed(2);
            updateItemRate(index, newRate);
        });
    });
}

function removeInvoiceItem(index) {
    invoiceItems.splice(index, 1);
    renderInvoiceItems();
}

function editInvoiceItem(index) {
    const item = invoiceItems[index];
    if (!item) return;
    
    // Create a modal for editing multiple fields
    const modalHtml = `
        <div id="edit-modal" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; justify-content: center; align-items: center;">
            <div style="background: white; padding: 20px; border-radius: 5px; width: 300px;">
                <h3>Edit Item</h3>
                <div>
                    <label>Product: ${item.name}</label>
                </div>
                <div>
                    <label for="edit-quantity">Quantity:</label>
                    <input type="number" id="edit-quantity" value="${item.quantity}" min="1" style="width: 100%; padding: 5px; margin: 5px 0;">
                </div>
                <div>
                    <label for="edit-rate">Rate:</label>
                    <input type="number" id="edit-rate" value="${item.selling_rate.toFixed(2)}" min="0" step="0.01" style="width: 100%; padding: 5px; margin: 5px 0;">
                </div>
                <div>
                    <label for="edit-discount">Discount (%):</label>
                    <input type="number" id="edit-discount" value="${item.discount || 0}" min="0" max="100" step="0.1" style="width: 100%; padding: 5px; margin: 5px 0;">
                </div>
                <div style="margin-top: 10px; display: flex; gap: 10px;">
                    <button id="save-edit" class="btn-success" style="flex: 1; display: flex; align-items: center; justify-content: center; padding: 8px;">
                        <svg width="16" height="16" fill="currentColor" viewBox="0 0 16 16" style="margin-right: 5px;">
                            <path d="M14 1a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h12zM2 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2H2z"/>
                            <path d="M10.97 4.97a.75.75 0 0 1 1.071 1.05l-3.992 4.99a.75.75 0 0 1-1.08.02L4.324 8.384a.75.75 0 1 1 1.06-1.06l2.094 2.093 3.473-4.425a.235.235 0 0 1 .02-.022z"/>
                        </svg>
                        Save
                    </button>
                    <button id="cancel-edit" class="btn-secondary" style="flex: 1; display: flex; align-items: center; justify-content: center; padding: 8px;">
                        <svg width="16" height="16" fill="currentColor" viewBox="0 0 16 16" style="margin-right: 5px;">
                            <path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/>
                            <path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/>
                        </svg>
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    `;
    
    // Add modal to document
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Add event listeners for modal buttons
    document.getElementById('save-edit').addEventListener('click', function() {
        const newQuantity = parseInt(document.getElementById('edit-quantity').value);
        const newRate = parseFloat(document.getElementById('edit-rate').value) || 0;
        const newDiscount = parseFloat(document.getElementById('edit-discount').value) || 0;
        
        if (!isNaN(newQuantity) && newQuantity > 0) {
            item.quantity = newQuantity;
        }
        
        if (!isNaN(newRate) && newRate >= 0) {
            item.selling_rate = newRate;
        }
        
        if (!isNaN(newDiscount) && newDiscount >= 0 && newDiscount <= 100) {
            item.discount = newDiscount;
        }
        
        // Remove modal and refresh invoice
        document.getElementById('edit-modal').remove();
        renderInvoiceItems();
    });
    
    document.getElementById('cancel-edit').addEventListener('click', function() {
        // Remove modal without saving
        document.getElementById('edit-modal').remove();
    });
    
    // Close modal when clicking outside
    document.getElementById('edit-modal').addEventListener('click', function(e) {
        if (e.target.id === 'edit-modal') {
            document.getElementById('edit-modal').remove();
        }
    });
}

function updateItemDiscount(index, discount) {
    if (invoiceItems[index]) {
        invoiceItems[index].discount = discount;
        renderInvoiceItems();
    }
}

function updateItemRate(index, newRate) {
    if (invoiceItems[index]) {
        invoiceItems[index].selling_rate = newRate;
        renderInvoiceItems();
    }
}

// ── Customer search (mobile + contact) ────────────────────────────────────────
function _showDropMsg(dropTarget, msg) {
    const dropId = dropTarget === 'mobile' ? 'mobile-search-results' : 'customer-search-results';
    const drop = document.getElementById(dropId);
    if (!drop) return;
    drop.innerHTML = '';
    const item = document.createElement('div');
    item.className = 'search-result-item';
    item.style.cssText = 'color:var(--text-muted);font-size:0.8125rem;pointer-events:none;';
    item.textContent = msg;
    drop.appendChild(item);
    drop.style.display = 'block';
}

function searchCustomers(q, dropTarget) {
    const token = localStorage.getItem('pos_token');
    if (!token) return;
    _showDropMsg(dropTarget, 'Searching…');
    // /api/search is the proven credit-customer endpoint (used by the credit modal)
    fetch(`/api/search?mobile=${encodeURIComponent(q)}`, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    })
    .then(data => {
        // Normalise: endpoint returns {customers: [{name, mobile, ...}]}
        const raw = (data && Array.isArray(data.customers)) ? data.customers : [];
        const customers = raw.map(c => ({
            customer_name:    c.name   || '',
            customer_mobile:  c.mobile || ''
        }));
        renderCustomerResults(customers, dropTarget, q);
    })
    .catch(() => _showDropMsg(dropTarget, 'Search unavailable'));
}

function renderCustomerResults(customers, dropTarget, q) {
    const dropId = dropTarget === 'mobile' ? 'mobile-search-results' : 'customer-search-results';
    const drop = document.getElementById(dropId);
    if (!drop) return;

    if (!Array.isArray(customers) || customers.length === 0) {
        _showDropMsg(dropTarget, `No customers found for "${q}"`);
        return;
    }

    drop.innerHTML = '';
    customers.forEach(c => {
        const item = document.createElement('div');
        item.className = 'search-result-item';
        const nameHtml = c.customer_name
            ? `<strong>${c.customer_name}</strong>`
            : '<em style="color:var(--text-muted)">No name</em>';
        const sub = c.customer_mobile || '';
        item.innerHTML = `
            <div class="search-result-name">${nameHtml}</div>
            <div class="search-result-details">
                <span class="search-result-sku">${sub}</span>
            </div>
        `;
        item.addEventListener('click', () => selectCustomer(
            c.customer_name    || '',
            c.customer_contact || '',
            c.customer_mobile  || ''
        ));
        drop.appendChild(item);
    });
    drop.style.display = 'block';
}

function selectCustomer(name, contact, mobile) {
    if (customerNameInput)       customerNameInput.value       = name;
    if (customerMobileMainInput) customerMobileMainInput.value = mobile;
    // Also sync the UPI mobile field so UPI validation still works
    if (customerMobileInput && mobile) customerMobileInput.value = mobile;
    hideMobileDropdown();
}

function hideMobileDropdown() {
    const drop = document.getElementById('mobile-search-results');
    if (drop) drop.style.display = 'none';
}

// ──────────────────────────────────────────────────────────────────────────────

function clearInvoice() {
    invoiceItems = [];
    discountPercentage = 0;
    if (discountInput) discountInput.value = '0';
    renderInvoiceItems();
    clearProductSelection();
    if (customerNameInput)       customerNameInput.value       = '';
    if (customerMobileMainInput) customerMobileMainInput.value = '';
    hideMobileDropdown();
    
    // Reset invoice date to today
    const invoiceDateInput = document.getElementById('invoice-date');
    if (invoiceDateInput) {
        const today = new Date().toISOString().split('T')[0];
        invoiceDateInput.value = today;
    }
    
    hideCreditCustomerInfo();
    selectedCreditCustomer = null;
}

function generateReceipt(invoice) {
    try {
        localStorage.setItem('invoiceData', JSON.stringify(invoice));

        const printMode = localStorage.getItem('printMode') || 'a4';
        const invoiceUrl = printMode === 'thermal' ? 'invoice.html?mode=thermal' : 'invoice.html';
        const winSpec = printMode === 'thermal'
            ? 'width=360,height=620,scrollbars=yes,resizable=yes'
            : 'width=800,height=500,scrollbars=yes,resizable=yes';

        // Try to open the invoice in a new window/tab
        let printWindow;
        try {
            printWindow = window.open(invoiceUrl, '_blank', winSpec);
        } catch (openError) {
            console.error('Error opening print window:', openError);
            handlePrintError(invoice);
            return;
        }
        
        // Check if window.open was successful
        if (!printWindow) {
            console.error('Failed to open print window. Popup blocker may be enabled.');
            handlePrintError(invoice);
            return;
        }
        
        // Focus the new window
        try {
            printWindow.focus();
        } catch (focusError) {
            console.error('Error focusing print window:', focusError);
        }
        
    } catch (error) {
        console.error('Error storing invoice data:', error);
        alert('Failed to generate receipt. Please try again. Error: ' + error.message);
        try {
            localStorage.removeItem('invoiceData');
        } catch (cleanupError) {
            console.error('Error cleaning up localStorage:', cleanupError);
        }
    }
}

function handlePrintError(invoice) {
    const errorMessage = `
Printing Issue Detected:

The print window could not be opened automatically. This is commonly due to:
- Browser popup blocker
- Security restrictions on deployed applications
- Browser settings

Options:
1. Click "Print Manually" below to open the invoice in this window
2. Manually navigate to the invoice page
3. Check your browser's popup blocker settings and try again

Would you like to open the invoice manually?
    `;
    
    if (confirm(errorMessage)) {
        window.location.href = 'invoice.html';
    } else {
        alert('To print manually:\n1. Click the "Print Invoice" button on the invoice page\n2. Or use your browser\'s print function (Ctrl+P or Cmd+P)');
    }
}

// Credit customer functions

function searchCreditCustomers(mobile, isPredictive = false) {
    // Validate search parameters
    if (!validateSearchParameters(mobile, isPredictive)) {
        return;
    }
    
    // Show loading indicator in the search results area
    if (creditCustomerList) {
        creditCustomerList.innerHTML = '<div class="p-4 text-center text-gray-500">Searching...</div>';
        creditSearchResultsDiv.style.display = 'block';
    }
    
    // Check if token exists
    const token = localStorage.getItem('pos_token');
    if (!token) {
        if (creditCustomerList) {
            creditCustomerList.innerHTML = '<div class="p-4 text-center text-red-500">Authentication required. Please log in again.</div>';
        }
        return;
    }
    
    // Call API to search credit customers
    const url = `/api/search?mobile=${encodeURIComponent(mobile)}&timestamp=${new Date().getTime()}`;
    console.log('Searching credit customers (modal) with URL:', url); // Debug log
    fetch(url, {
        method: 'GET',
        headers: {
            'Authorization': `Bearer ${localStorage.getItem('pos_token')}`,
            'Content-Type': 'application/json',
            'Cache-Control': 'no-cache'
        }
    })
    .then(response => {
        console.log('Credit customer search (modal) response status:', response.status); // Debug log
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        console.log('Credit customer search (modal) response data:', data); // Debug log
        // Check if data is valid
        if (data && Array.isArray(data.customers)) {
            displayCreditCustomerResults(data.customers);
        } else if (data && data.customers) {
            // Handle case where customers might not be an array
            const customersArray = Array.isArray(data.customers) ? data.customers : [data.customers];
            displayCreditCustomerResults(customersArray);
        } else {
            displayCreditCustomerResults([]);
        }
    })
    .catch(error => {
        console.error('Error searching credit customers:', error);
        if (creditCustomerList) {
            creditCustomerList.innerHTML = '<div class="p-4 text-center text-red-500">Error searching credit customers: ' + error.message + '</div>';
        }
        // Don't hide the results div so the error message is visible
    });
}

function displayCreditCustomerResults(customers, isPredictive = false) {
    // For modal search, we'll use the existing modal results area
    // Regular modal search - use existing logic
    if (!creditCustomerList) return;
    
    if (customers.length === 0) {
        creditCustomerList.innerHTML = '<div class="p-4 text-center text-gray-500">No customers found</div>';
        creditSearchResultsDiv.style.display = 'block';
        return;
    }
    
    creditCustomerList.innerHTML = '';
    
    // Limit results to 10 for better UX in modal
    const displayCustomers = customers.slice(0, 10);
    
    displayCustomers.forEach(customer => {
        const customerDiv = document.createElement('div');
        customerDiv.className = 'p-3 border-b border-gray-200 hover:bg-gray-50 cursor-pointer transition-colors duration-150';
        
        // Determine balance class and text
        let balanceText = '₹0.00';
        let balanceClass = '';
        // Use current_balance instead of balance as returned by the API
        let balance = customer.current_balance !== undefined ? customer.current_balance : customer.balance;
        // Ensure balance is a number
        balance = typeof balance === 'string' ? parseFloat(balance) : (typeof balance === 'number' ? balance : 0);
        // Default to 0 if balance is not a valid number
        if (isNaN(balance) || !isFinite(balance)) balance = 0;
        
        if (balance > 0) {
            balanceText = `₹${balance.toFixed(2)} (Debt)`;
            balanceClass = 'text-red-600';
        } else if (balance < 0) {
            balanceText = `₹${Math.abs(balance).toFixed(2)} (Credit)`;
            balanceClass = 'text-green-600';
        } else {
            balanceText = `₹${balance.toFixed(2)}`;
        }
        
        // Use customer_id instead of customer.id as returned by the API
        const customerId = customer.customer_id || customer.id;
        
        customerDiv.innerHTML = `
            <div class="flex justify-between items-center">
                <div class="flex-1 min-w-0">
                    <div class="font-medium truncate">${customer.name || 'Unknown Customer'}</div>
                    <div class="text-sm text-gray-600 truncate">ID: ${customerId || 'N/A'} | ${customer.mobile || 'No Mobile'}</div>
                </div>
                <div class="text-right ml-2">
                    <div class="font-medium ${balanceClass} truncate customer-balance">${balanceText}</div>
                </div>
            </div>
        `;
        
        customerDiv.addEventListener('click', () => {
            selectCreditCustomer(customer);
        });
        
        creditCustomerList.appendChild(customerDiv);
    });
    
    creditSearchResultsDiv.style.display = 'block';
}

// Common function to handle credit customer search input
function handleCreditCustomerSearchInput(searchFunction, isPredictive = true) {
    // This function is no longer used since we removed the credit customer mobile input field
}

// Enhanced version with better validation and UX for modal search
function handleCreditCustomerSearchModal() {
    // This function is no longer used since we removed the credit customer mobile input field
}

function searchCreditCustomerByMobile(mobile) {
    console.log('searchCreditCustomerByMobile called with mobile:', mobile); // Debug log
    // This function is no longer used since we removed the credit customer mobile input field
}

function validateSearchParameters(mobile, isPredictive = false) {
    // Validate mobile number format
    // Don't trim mobile numbers as they might have leading zeros that are significant
    console.log('Validating mobile number:', mobile, 'Length:', mobile.length, 'IsPredictive:', isPredictive); // Debug log
    // Allow mobile numbers with leading zeros by not trimming them
    
    // For predictive search, allow partial matches (at least 3 digits)
    // For exact search, require full 10 digits
    if (isPredictive) {
        if (!/^\d{3,10}$/.test(mobile)) {
            console.log('Mobile number validation failed for predictive search'); // Debug log
            // Hide results for invalid input
            if (creditSearchResultsDiv) {
                creditSearchResultsDiv.style.display = 'none';
            }
            return false;
        }
    } else {
        // For exact search, still require 10 digits
        if (!/^\d{10}$/.test(mobile)) {
            console.log('Mobile number validation failed for exact search'); // Debug log
            // Hide results for invalid input
            if (creditSearchResultsDiv) {
                creditSearchResultsDiv.style.display = 'none';
            }
            return false;
        }
    }
    console.log('Mobile number validation passed'); // Debug log
    return true;
}

function selectCreditCustomer(customer) {
    selectedCreditCustomer = customer;
    
    // Update UI with customer info
    if (creditCustomerName) creditCustomerName.textContent = customer.name || 'Unknown Customer';
    // Use customer_id instead of customer.id as returned by the API
    if (creditCustomerId) creditCustomerId.textContent = customer.customer_id || customer.id || 'N/A';
    
    // Display balance with appropriate color
    if (creditCustomerBalance) {
        let balanceText = '₹0.00';
        let balanceClass = 'font-medium text-gray-500';
        // Use current_balance instead of balance as returned by the API
        let balance = customer.current_balance !== undefined ? customer.current_balance : customer.balance;
        // Ensure balance is a number
        balance = typeof balance === 'string' ? parseFloat(balance) : (typeof balance === 'number' ? balance : 0);
        // Default to 0 if balance is not a valid number
        if (isNaN(balance) || !isFinite(balance)) balance = 0;
        
        if (balance > 0) {
            balanceText = `₹${balance.toFixed(2)} (Debt)`;
            balanceClass = 'font-medium text-red-600';
        } else if (balance < 0) {
            balanceText = `₹${Math.abs(balance).toFixed(2)} (Credit)`;
            balanceClass = 'font-medium text-green-600';
        } else {
            balanceText = `₹${balance.toFixed(2)}`;
        }
        creditCustomerBalance.textContent = balanceText;
        creditCustomerBalance.className = balanceClass;
    }
    
    // Show customer info
    showCreditCustomerInfo();
    
    // Close modal if it's open
    if (creditCustomerSearchModal) {
        creditCustomerSearchModal.style.display = 'none';
    }
    
    // Also store the customer's mobile number in the selectedCreditCustomer object for consistency
    if (selectedCreditCustomer) {
        selectedCreditCustomer.mobile = customer.mobile || '';
        // Ensure customer_id is properly set
        if (customer.customer_id) {
            selectedCreditCustomer.customer_id = customer.customer_id;
        }
    }
    
    // Hide predictive search results if they exist

    // Focus on the mode of payment select to allow quick continuation
    if (modeOfPaymentSelect) {
        modeOfPaymentSelect.focus();
    }
}

function showCreditCustomerInfo() {
    if (creditCustomerInfoDiv) {
        creditCustomerInfoDiv.style.display = 'block';
    }
}

function hideCreditCustomerInfo() {
    console.log('Hiding credit customer info');
    if (creditCustomerInfoDiv) {
        creditCustomerInfoDiv.style.display = 'none';
    }
    // Only clear selectedCreditCustomer if it exists
    if (selectedCreditCustomer) {
        console.log('Clearing selectedCreditCustomer');
        selectedCreditCustomer = null;
    }
    
    // Reset the balance display to 0.00 when hiding credit customer info
    if (creditCustomerBalance) {
        creditCustomerBalance.textContent = '₹0.00';
        creditCustomerBalance.className = 'font-medium text-gray-500';
    }
}

function updateCreditCustomerBalance(invoice) {
    // Validate inputs
    if (!selectedCreditCustomer || !invoice) {
        console.warn('Cannot update credit customer balance: selectedCreditCustomer or invoice is null');
        return;
    }
    
    // Validate that we have the required customer properties
    if (!selectedCreditCustomer.customer_id) {
        console.error('Cannot update credit customer balance: customer_id is missing');
        alert('Error updating credit customer balance: Customer information is incomplete');
        return;
    }
    
    // Show loading indicator
    showLoading();
    
    // Create transaction data
    const transactionData = {
        transaction_type: 'debit', // Debit because we're adding to the amount owed
        amount: parseFloat(invoice.grand_total) || 0,
        invoice_no: invoice.invoice_number,
        note: 'Sale transaction'
    };
    
    // Call API to add transaction
    fetch(`/api/customers/${selectedCreditCustomer.customer_id}/transactions`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${localStorage.getItem('pos_token')}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(transactionData)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errorData => {
                throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.message === 'Transaction added successfully') {
            // Double-check that selectedCreditCustomer is still valid
            if (!selectedCreditCustomer) {
                console.warn('selectedCreditCustomer became null during transaction');
                return;
            }
            
            // Update the selected customer reference with new balance
            selectedCreditCustomer.current_balance = data.new_balance;
            
            // Update UI
            if (creditCustomerBalance) {
                let balanceText = '₹0.00';
                let balanceClass = 'font-medium text-gray-500';
                // Ensure current_balance is a number
                let currentBalance = typeof selectedCreditCustomer.current_balance === 'string' ? parseFloat(selectedCreditCustomer.current_balance) : (typeof selectedCreditCustomer.current_balance === 'number' ? selectedCreditCustomer.current_balance : 0);
                // Default to 0 if currentBalance is not a valid number
                if (isNaN(currentBalance)) currentBalance = 0;
                
                if (currentBalance > 0) {
                    balanceText = `₹${currentBalance.toFixed(2)} (Debt)`;
                    balanceClass = 'font-medium text-red-600';
                } else if (currentBalance < 0) {
                    balanceText = `₹${Math.abs(currentBalance).toFixed(2)} (Credit)`;
                    balanceClass = 'font-medium text-green-600';
                } else {
                    balanceText = `₹${currentBalance.toFixed(2)}`;
                }
                creditCustomerBalance.textContent = balanceText;
                creditCustomerBalance.className = balanceClass;
            }
            
            console.log('Credit customer balance updated successfully');
        } else {
            throw new Error(data.message || 'Failed to update credit customer balance');
        }
    })
    .catch(error => {
        console.error('Error updating credit customer balance:', error);
        alert('Error updating credit customer balance: ' + error.message);
    })
    .finally(() => {
        // Hide loading indicator
        hideLoading();
    });
}

// View Invoices functions
function loadRecentInvoices() {
    const token = localStorage.getItem('pos_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }
    
    const fromDate = document.getElementById('invoice-from-date');
    const toDate = document.getElementById('invoice-to-date');
    const startDate = fromDate ? fromDate.value : '';
    const endDate = toDate ? toDate.value : '';
    
    if (!startDate || !endDate) {
        alert('Please select both From and To dates');
        return;
    }
    
    const showCancelledChk = document.getElementById('show-cancelled-chk');
    const showCompletedChk = document.getElementById('show-completed-chk');
    const includeCancelled = showCancelledChk && showCancelledChk.checked;
    const includeCompleted = !showCompletedChk || showCompletedChk.checked;

    const tbody = document.getElementById('view-invoices-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-gray-500">Loading invoices...</td></tr>';
    
    fetch(`/api/reports/sales?start_date=${startDate}&end_date=${endDate}&include_cancelled=true`, {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        tbody.innerHTML = '';
        let invoices = data.detailed_invoices || [];
        
        // Filter by status checkboxes
        invoices = invoices.filter(inv => {
            const isCancelled = inv.status === 'Cancelled';
            if (isCancelled) return includeCancelled;
            return includeCompleted;
        });
        
        if (invoices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-gray-500">No invoices found for the selected period</td></tr>';
            return;
        }
        
        invoices.forEach((inv, index) => {
            const row = document.createElement('tr');
            const isCancelled = inv.status === 'Cancelled';
            row.className = isCancelled ? 'border-b bg-red-50' : 'border-b hover:bg-gray-50';
            const dateStr = inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString() : '-';
            const customer = inv.customer_name || '-';
            const amount = inv.total_amount ? parseFloat(inv.total_amount).toFixed(2) : '0.00';
            const payment = inv.mode_of_payment || '-';
            const statusBadge = isCancelled 
                ? '<span class="bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded-full font-medium">Cancelled</span>' 
                : '<span class="bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded-full font-medium">Completed</span>';
            
            row.innerHTML = `
                <td class="py-2 px-3${isCancelled ? ' text-gray-400' : ''}">${index + 1}</td>
                <td class="py-2 px-3 font-medium${isCancelled ? ' text-gray-400 line-through' : ''}">${inv.invoice_number || '-'}</td>
                <td class="py-2 px-3${isCancelled ? ' text-gray-400' : ''}">${dateStr}</td>
                <td class="py-2 px-3${isCancelled ? ' text-gray-400' : ''}">${customer}</td>
                <td class="py-2 px-3 text-right${isCancelled ? ' text-gray-400' : ''}">₹${amount}</td>
                <td class="py-2 px-3 text-center${isCancelled ? ' text-gray-400' : ''}">${payment}</td>
                <td class="py-2 px-3 text-center">${statusBadge}</td>
                <td class="py-2 px-3 text-center">
                    <div class="flex gap-1 justify-center">
                        <button class="bg-blue-500 hover:bg-blue-600 text-white text-xs px-2 py-1 rounded" onclick="viewInvoiceById(${inv.invoice_id})">View</button>
                        ${!isCancelled ? `<a href="returns.html?invoice_id=${inv.invoice_id}" class="bg-orange-500 hover:bg-orange-600 text-white text-xs px-2 py-1 rounded">Return</a>` : ''}
                    </div>
                </td>
            `;
            tbody.appendChild(row);
        });
    })
    .catch(error => {
        console.error('Error loading invoices:', error);
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-red-500">Error loading invoices: ${error.message}</td></tr>`;
    });
}

function viewInvoiceById(invoiceId) {
    const token = localStorage.getItem('pos_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }
    
    fetch(`/api/sales/${invoiceId}`, {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(invoice => {
        generateReceipt(invoice);
    })
    .catch(error => {
        console.error('Error fetching invoice:', error);
        alert('Failed to load invoice: ' + error.message);
    });
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM Content Loaded, initializing sales system...');
    // Initialize sidebar pin functionality
    initializeSidebarPin();
    window.sidebarInitialized = true;
    
    // Use a small delay to ensure auth-utils.js has finished initializing
    setTimeout(function() {
        console.log('Initializing sales system...');
        // Initialize DOM elements
        if (!initDOMElements()) {
            console.error('Failed to initialize DOM elements');
            return;
        }
        
        // Attach event listeners
        attachEventListeners();
        
        // Auth check is now handled by auth-utils.js
        // Just get the current user
        currentUser = getCurrentUser();
        if (currentUser) {
            if (usernameSpan) usernameSpan.textContent = currentUser.username;
        }
        
        // Initialize payment options visibility
        if (modeOfPaymentSelect && upiDetailsDiv && creditDetailsDiv) {
            if (modeOfPaymentSelect.value === 'UPI') {
                upiDetailsDiv.style.display = 'block';
                creditDetailsDiv.style.display = 'none';
            } else if (modeOfPaymentSelect.value === 'Credit') {
                upiDetailsDiv.style.display = 'none';
                creditDetailsDiv.style.display = 'block';
            } else {
                upiDetailsDiv.style.display = 'none';
                creditDetailsDiv.style.display = 'none';
            }
        }
        
        // Call the UI initialization function for index.html
        initializeUIElements();
        
        console.log('Sales system initialized');
    }, 100);
});


// ════════════════════════════════════════════════════════════════════════════
// BARCODE / QR SCANNER SUPPORT
// ════════════════════════════════════════════════════════════════════════════

// ── Scan feedback toast ──────────────────────────────────────────────────────
function showScanFeedback(type, msg) {
    const toast = document.getElementById('scan-toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.className = 'scan-toast ' + type;  // success | error | info
    toast.style.display = 'block';
    // Force reflow so transition fires
    toast.getBoundingClientRect();
    toast.style.opacity = '1';
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => { toast.style.display = 'none'; }, 300);
    }, 2200);
}

// ── Barcode lookup (barcode column OR SKU exact match) ───────────────────────
async function lookupByBarcode(code) {
    if (!code) return;
    const token = localStorage.getItem('pos_token');
    if (!token) return;

    try {
        const res = await fetch(`/api/products/barcode/${encodeURIComponent(code)}`, {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (res.status === 404) {
            showScanFeedback('error', 'No product found for: ' + code);
            return;
        }
        if (!res.ok) {
            showScanFeedback('error', 'Lookup error (' + res.status + ')');
            return;
        }
        const product = await res.json();
        addScannedProductToCart(convertProductNumbers(product));
    } catch (err) {
        showScanFeedback('error', 'Network error: ' + err.message);
    }
}

// ── Add a scanned product directly to the cart (qty 1) ──────────────────────
function addScannedProductToCart(product) {
    if (!product) return;

    const existing = invoiceItems.findIndex(i => i.product_id === product.product_id);
    if (existing >= 0) {
        invoiceItems[existing].quantity += 1;
        showScanFeedback('success', '+ ' + product.name + ' (qty ' + invoiceItems[existing].quantity + ')');
    } else {
        invoiceItems.push({
            product_id:   product.product_id,
            name:         product.name,
            pack_size:    product.pack_size,
            gst_rate:     product.gst_rate,
            selling_rate: product.selling_rate,
            quantity:     1,
            discount:     0
        });
        showScanFeedback('success', 'Added: ' + product.name);
    }

    renderInvoiceItems();
    clearProductSelection();
    if (productSearchInput) productSearchInput.focus();
}

// ── Camera scanner (html5-qrcode) ───────────────────────────────────────────
let _camScanner = null;

async function _stopCamScanner() {
    if (!_camScanner) return;
    const s = _camScanner;
    _camScanner = null;
    try { await s.stop(); } catch (_) {}
    try { s.clear(); }      catch (_) {}
    // Force-release any video tracks the library may not have stopped
    try {
        document.querySelectorAll('#cam-viewfinder video').forEach(v => {
            if (v.srcObject) {
                v.srcObject.getTracks().forEach(t => t.stop());
                v.srcObject = null;
            }
        });
    } catch (_) {}
}

async function openCameraScanner() {
    const modal  = document.getElementById('camera-scanner-modal');
    const status = document.getElementById('cam-status');
    if (!modal) return;

    modal.classList.remove('hidden');
    modal.style.display = 'flex';

    if (typeof Html5Qrcode === 'undefined') {
        if (status) status.textContent = 'Camera library not loaded — check your internet connection.';
        return;
    }

    // Non-secure origins (plain HTTP on non-localhost) are always blocked by browsers.
    const secure = location.protocol === 'https:'
        || location.hostname === 'localhost'
        || location.hostname === '127.0.0.1';
    if (!secure) {
        if (status) status.innerHTML =
            '⚠ Camera blocked: page served over <b>HTTP</b>.<br>' +
            'Open on <b>localhost</b> or use <b>HTTPS</b> to enable camera scanning.';
        return;
    }

    // Stop any lingering instance and give the OS time to release the hardware
    await _stopCamScanner();
    await new Promise(r => setTimeout(r, 300));

    const viewfinder = document.getElementById('cam-viewfinder');
    if (viewfinder) viewfinder.innerHTML = '';

    if (status) status.textContent = 'Detecting camera…';

    // Build format list — include all common barcode types, not just QR
    const fmts = Html5QrcodeSupportedFormats
        ? [
            Html5QrcodeSupportedFormats.QR_CODE,
            Html5QrcodeSupportedFormats.EAN_13,
            Html5QrcodeSupportedFormats.EAN_8,
            Html5QrcodeSupportedFormats.CODE_128,
            Html5QrcodeSupportedFormats.CODE_39,
            Html5QrcodeSupportedFormats.CODE_93,
            Html5QrcodeSupportedFormats.UPC_A,
            Html5QrcodeSupportedFormats.UPC_E,
            Html5QrcodeSupportedFormats.ITF,
            Html5QrcodeSupportedFormats.CODABAR,
          ]
        : undefined;

    const scanConfig = {
        fps: 10,
        qrbox: function(w, h) {
            const bw = Math.min(Math.round(w * 0.9), 400);
            const bh = Math.min(Math.round(h * 0.65), 220);
            return { width: bw, height: bh };
        },
        formatsToSupport: fmts,
    };

    const onSuccess  = (code) => { closeCameraScanner(); lookupByBarcode(code); };
    const onFrameErr = () => {};

    try {
        // Enumerate real cameras instead of relying on facingMode constraints.
        // This is the only reliable strategy for laptops (single front camera).
        let cameras = [];
        try { cameras = await Html5Qrcode.getCameras(); } catch (_) {}

        let cameraId = null;
        if (cameras.length > 0) {
            // Prefer a labelled rear camera; fall back to first available
            const rear = cameras.find(c =>
                /back|rear|environment/i.test(c.label)
            );
            cameraId = (rear || cameras[0]).id;
        }

        if (status) status.textContent = 'Requesting camera access…';
        _camScanner = new Html5Qrcode('cam-viewfinder');

        if (cameraId) {
            await _camScanner.start(cameraId, scanConfig, onSuccess, onFrameErr);
        } else {
            // Fallback: let the browser pick (works on most desktops)
            await _camScanner.start({ facingMode: 'user' }, scanConfig, onSuccess, onFrameErr);
        }

        if (status) status.innerHTML =
            'Hold barcode/QR steady inside the box &nbsp;·&nbsp; ' +
            '<span style="color:var(--accent)">good lighting helps</span>';

    } catch (err) {
        await _stopCamScanner();
        const name = err.name || '';
        const msg  = (err.message || String(err)).toLowerCase();

        if (name === 'NotAllowedError' || msg.includes('permission') || msg.includes('notallowed')) {
            if (status) status.innerHTML =
                '⚠ <b>Camera permission denied.</b><br>' +
                'Click the 🔒 / 📷 icon in the address bar → <b>Allow Camera</b>, then press Try Again.';

        } else if (name === 'NotReadableError' || msg.includes('notreadable') || msg.includes('could not start video')) {
            if (status) status.innerHTML =
                '⚠ <b>Camera could not be started.</b><br>' +
                'Try: close other apps using the camera (Teams, Zoom), refresh the page, or restart the browser.';

        } else if (name === 'NotFoundError' || msg.includes('notfound') || msg.includes('no camera')) {
            if (status) status.textContent = '⚠ No camera detected on this device.';

        } else if (name === 'OverconstrainedError') {
            if (status) status.textContent = '⚠ Camera constraints not supported — press Try Again.';

        } else {
            if (status) status.textContent = '⚠ ' + (err.message || String(err));
        }
    }
}

async function closeCameraScanner() {
    const modal = document.getElementById('camera-scanner-modal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.add('hidden');
    }
    await _stopCamScanner();
}

// ── Global hardware scanner listener ────────────────────────────────────────
// USB/Bluetooth scanners inject chars very fast (all in < 100ms) then send Enter.
// This listener captures scans when no input field is focused so the cashier
// doesn't need to click the search box first.
(function initHardwareScanner() {
    let buffer = '';
    let flushTimer = null;

    document.addEventListener('keydown', function(e) {
        const active = document.activeElement;
        const inInput = active && (
            active.tagName === 'INPUT' ||
            active.tagName === 'TEXTAREA' ||
            active.tagName === 'SELECT'
        );
        // Only intercept when no input is focused
        // (when product-search-input is focused, the Enter listener above handles it)
        if (inInput) return;

        if (e.key === 'Enter') {
            if (buffer.length >= 3) {
                const code = buffer.trim();
                buffer = '';
                clearTimeout(flushTimer);
                flushTimer = null;
                e.preventDefault();
                lookupByBarcode(code);
            }
            return;
        }

        if (e.key.length === 1) {
            buffer += e.key;
            clearTimeout(flushTimer);
            // If no Enter arrives within 200ms, assume manual keystroke — discard
            flushTimer = setTimeout(() => { buffer = ''; flushTimer = null; }, 200);
        }
    });
})(); // end initHardwareScanner

// ── UPI QR helpers ────────────────────────────────────────────────────────────

let _upiSettings = null; // { upi_id, upi_display_name } – cached after first load

async function loadUpiSettings() {
    if (_upiSettings) return _upiSettings;
    // Try localStorage cache (5-min TTL)
    const cached = localStorage.getItem('_upi_settings_cache');
    if (cached) {
        try {
            const { ts, data } = JSON.parse(cached);
            if (Date.now() - ts < 5 * 60 * 1000) { _upiSettings = data; return data; }
        } catch (_) {}
    }
    try {
        const token = localStorage.getItem('pos_token') || sessionStorage.getItem('pos_token');
        const res = await fetch('/api/store-settings', { headers: { 'Authorization': `Bearer ${token}` } });
        if (!res.ok) return null;
        const data = await res.json();
        _upiSettings = { upi_id: data.upi_id || '', upi_display_name: data.upi_display_name || 'Store' };
        localStorage.setItem('_upi_settings_cache', JSON.stringify({ ts: Date.now(), data: _upiSettings }));
        return _upiSettings;
    } catch (_) { return null; }
}

function refreshUpiQr(amount) {
    const modeEl = document.getElementById('mode-of-payment');
    const panel  = document.getElementById('upi-qr-panel');
    const noId   = document.getElementById('upi-qr-no-id');
    const qrWrap = document.getElementById('checkout-qrcode');
    const amtEl  = document.getElementById('upi-qr-amount');
    const idEl   = document.getElementById('upi-qr-id');
    if (!panel || !noId || !qrWrap) return;

    const isUpi = modeEl && modeEl.value === 'UPI';
    if (!isUpi) { panel.style.display = 'none'; noId.style.display = 'none'; return; }

    loadUpiSettings().then(settings => {
        if (!settings || !settings.upi_id) {
            panel.style.display = 'none';
            noId.style.display  = 'block';
            return;
        }
        noId.style.display = 'none';
        const upiStr = `upi://pay?pa=${encodeURIComponent(settings.upi_id)}&pn=${encodeURIComponent(settings.upi_display_name)}&am=${(amount || 0).toFixed(2)}&cu=INR&tn=Sale`;
        // Clear previous QR
        qrWrap.innerHTML = '';
        if (typeof QRCode !== 'undefined') {
            new QRCode(qrWrap, { text: upiStr, width: 120, height: 120, correctLevel: QRCode.CorrectLevel.M });
        }
        if (amtEl) amtEl.textContent = (amount || 0).toFixed(2);
        if (idEl)  idEl.textContent  = settings.upi_id;
        panel.style.display = 'block';
    });
}

// ── Email Receipt Modal ───────────────────────────────────────────────────────

let _emailModalInvoice = null;

function showEmailReceiptModal(invoice) {
    _emailModalInvoice = invoice;

    // Populate info strip
    const invNum = document.getElementById('email-modal-inv-num');
    const custEl = document.getElementById('email-modal-customer');
    const totEl  = document.getElementById('email-modal-total');
    if (invNum) invNum.textContent = '#' + (invoice.invoice_number || '—');
    if (custEl) custEl.textContent = invoice.customer_name || 'Walk-in Customer';
    if (totEl)  totEl.textContent  = '₹' + parseFloat(invoice.grand_total || 0).toFixed(2);

    // Pre-fill email: credit customer email takes priority
    const emailInput = document.getElementById('email-modal-input');
    if (emailInput) {
        const knownEmail = (selectedCreditCustomer && selectedCreditCustomer.email) ? selectedCreditCustomer.email : '';
        emailInput.value = knownEmail;
        if (!knownEmail && invoice.customer_mobile) {
            // Try to look up email by mobile for non-credit customers
            const token = localStorage.getItem('pos_token');
            fetch(`/api/customers/lookup-email?mobile=${encodeURIComponent(invoice.customer_mobile)}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            })
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data && data.email) emailInput.value = data.email; })
            .catch(() => {});
        }
        emailInput.focus();
    }

    // Clear status
    const statusEl = document.getElementById('email-modal-status');
    if (statusEl) statusEl.innerHTML = '';

    const modal = document.getElementById('email-receipt-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.style.display = 'flex';
    }
}

function emailModalClose() {
    const modal = document.getElementById('email-receipt-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.style.display = '';
    }
    clearInvoice();
    _emailModalInvoice = null;
}

function emailModalPrint() {
    if (_emailModalInvoice) generateReceipt(_emailModalInvoice);
    emailModalClose();
}

function emailModalSend() {
    if (!_emailModalInvoice) return;
    const emailInput = document.getElementById('email-modal-input');
    const statusEl   = document.getElementById('email-modal-status');
    const sendBtn    = document.getElementById('email-modal-send-btn');
    const email = (emailInput ? emailInput.value : '').trim();

    if (!email || !email.includes('@')) {
        if (statusEl) statusEl.innerHTML = '<span style="color:#dc2626;">&#9888; Please enter a valid email address.</span>';
        if (emailInput) emailInput.focus();
        return;
    }

    if (sendBtn) { sendBtn.disabled = true; sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin" style="margin-right:6px;font-size:12px;"></i>Sending…'; }
    if (statusEl) statusEl.innerHTML = '';

    const token = localStorage.getItem('pos_token');
    fetch(`/api/sales/${_emailModalInvoice.invoice_id}/send-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ email })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            if (statusEl) statusEl.innerHTML = `<span style="color:#16a34a;">&#10003; Receipt sent to <strong>${email}</strong></span>`;
            if (sendBtn) { sendBtn.disabled = false; sendBtn.innerHTML = '<i class="fas fa-check" style="margin-right:6px;font-size:12px;"></i>Sent!'; }
        } else {
            const errMsg = data.error || 'Failed to send email';
            if (statusEl) statusEl.innerHTML = `<span style="color:#dc2626;">&#9888; ${errMsg}</span>`;
            if (sendBtn) { sendBtn.disabled = false; sendBtn.innerHTML = '<i class="fas fa-paper-plane" style="margin-right:6px;font-size:12px;"></i>Retry'; }
        }
    })
    .catch(() => {
        if (statusEl) statusEl.innerHTML = '<span style="color:#dc2626;">&#9888; Network error. Email not sent.</span>';
        if (sendBtn) { sendBtn.disabled = false; sendBtn.innerHTML = '<i class="fas fa-paper-plane" style="margin-right:6px;font-size:12px;"></i>Retry'; }
    });
}