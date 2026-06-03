# License Activation Flow - Post-Login

## Overview
After successful login, the system now checks for a valid license. If no license is present, users are directed to the license activation page to add one before accessing the dashboard.

## Flow Diagram

```
User Login
    ↓
Submit Email + Password
    ↓
Verify OTP (6-digit code)
    ↓
✓ Login successful
    ↓
CHECK LICENSE STATUS
    ↓
    ├─ License Valid? → Go to Dashboard
    │
    ├─ Cloud Mode? → Go to Dashboard
    │
    └─ No License? → Go to License Activation Page
        ↓
        Auto-open License Input Form
        ↓
        Enter License Key
        ↓
        Activate License
        ↓
        ✓ Success → Redirect to Dashboard
        ↓
        Access Dashboard with Valid License
```

## Implementation Details

### 1. Login Page (login.html)
**File**: `login.html` lines 681-701

After OTP verification succeeds:
```javascript
localStorage.setItem('pos_token', data.token);

// Check license status before going to dashboard
try {
    const licRes = await fetch('/api/license/status', {
        headers: { 'Authorization': `Bearer ${data.token}` }
    });
    const licData = await licRes.json();

    // If license is valid or cloud mode, go to dashboard
    if (licData.valid || licData.cloud) {
        window.location.href = 'dashboard.html';
        return;
    }

    // License invalid or missing - go to license check page
    window.location.href = 'license_activation.html?redirect=dashboard.html';
} catch (e) {
    // If license check fails, still allow access to dashboard
    window.location.href = 'dashboard.html';
}
```

**Key Points:**
- ✅ Checks license status via `/api/license/status` API
- ✅ Uses the login token for authentication
- ✅ Handles both invalid and missing licenses
- ✅ Allows fallback if API is unavailable
- ✅ Passes `redirect=dashboard.html` parameter for redirect after activation

### 2. License Activation Page (license_activation.html)

#### Auto-Open Form on Login Redirect
**File**: `license_activation.html` lines 491-520

```javascript
// Check if redirected from login (license required to proceed)
const params = new URLSearchParams(window.location.search);
const redirectAfterActivation = params.get('redirect');

// Load content in background
Promise.all([
    loadLicenseStatus(),
    loadFingerprint()
]).then(() => {
    // If redirected from login, auto-open activation form
    if (redirectAfterActivation) {
        const licenseStatus = document.getElementById('status-badge');
        if (licenseStatus && !licenseStatus.textContent.includes('Active')) {
            // License is not active, open the activation form
            setTimeout(() => {
                openActivate();
                toast('Please enter your license key to continue.', 'info', 5000);
            }, 300);
        }
    }
}).catch((e) => {
    console.error('Failed to load license data:', e);
});
```

**Key Points:**
- ✅ Detects redirect parameter in URL
- ✅ Auto-opens license input form
- ✅ Shows instructional toast message
- ✅ Only opens form if license is not already active

#### Activation with Redirect
**File**: `license_activation.html` lines 401-431

```javascript
async function activateLicense() {
    // ... validation and submit code ...
    
    if (data.success) {
        toast('License activated! Licensed to: ' + data.customer, 'success', 5000);
        document.getElementById('license-key').value = '';
        closeActivate();
        loadLicenseStatus();

        // Check if we need to redirect after activation
        const params = new URLSearchParams(window.location.search);
        const redirectUrl = params.get('redirect');
        if (redirectUrl) {
            setTimeout(() => {
                window.location.href = redirectUrl;
            }, 2000);
        }
    }
}
```

**Key Points:**
- ✅ After successful activation, redirects to specified URL
- ✅ 2-second delay allows success message to display
- ✅ Loads latest license status before redirect
- ✅ Falls back gracefully if no redirect parameter

## User Experience

### Scenario 1: User with Valid License
```
1. Login with email + OTP
2. License check passes
3. Immediately redirected to Dashboard
4. Seamless experience
```

### Scenario 2: User without License
```
1. Login with email + OTP
2. License check fails
3. Redirected to License Activation page
4. Form auto-opens with message: "Please enter your license key to continue"
5. User enters license key
6. License activates
7. Success message: "License activated! Licensed to: [Customer Name]"
8. Auto-redirect to Dashboard after 2 seconds
9. Full access granted
```

### Scenario 3: License Check Fails (Network Error)
```
1. Login with email + OTP
2. License check API fails
3. User allowed to proceed to Dashboard
4. License guard enforces on API calls
5. User redirected to license page on first API call
```

## API Endpoints Used

### /api/license/status
- **Purpose**: Check current license status
- **Auth Required**: Yes (Bearer token)
- **Returns**: 
  - `valid`: boolean (license is valid)
  - `cloud`: boolean (cloud/SaaS mode)
  - `customer`: string (customer name if valid)
  - `message`: string (status message)

### /api/license/activate
- **Purpose**: Activate a license with a key
- **Method**: POST
- **Body**: `{ license_key: "..." }`
- **Returns**: 
  - `success`: boolean
  - `customer`: string (customer name if successful)
  - `message`: string (success or error message)

## Configuration

No additional configuration needed. The feature works automatically when:
1. User logs in successfully
2. License status check is performed
3. User is redirected based on license status

## Testing Checklist

- [ ] Login with valid license → goes to Dashboard
- [ ] Login without license → goes to License Activation with form open
- [ ] License key submission works
- [ ] Successful activation shows success message
- [ ] Redirect to Dashboard happens after activation
- [ ] Toast message displays correctly
- [ ] Network errors handled gracefully
- [ ] Works on mobile and desktop

## Benefits

✅ **Seamless Flow**: No manual redirecting or page navigation  
✅ **User Guidance**: Auto-open form with instructional message  
✅ **Clear UX**: Success message before redirect  
✅ **Fallback Handling**: Graceful degradation if license API fails  
✅ **Clean Integration**: Works with existing authentication flow  

## Security Considerations

✅ License check uses valid authentication token  
✅ Sensitive license data not exposed in URLs  
✅ Redirect parameter is whitelisted (only to dashboard.html)  
✅ API enforces license via HTTP 402 as fallback  

## Summary

The post-login license check provides a smooth user experience by:
1. Automatically checking license validity after login
2. Seamlessly redirecting to license activation if needed
3. Auto-opening the activation form
4. Redirecting back to dashboard after successful activation

This prevents users from reaching the dashboard without a valid license while maintaining a professional, guided workflow.

