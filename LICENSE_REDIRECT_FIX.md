# License Redirect Loop Fix

## Problem
On Render deployment, users experienced flashing between `login.html` and `license_activation.html` due to a redirect loop:

```
login.html → GET /api/license/status (402) → redirects to license_activation.html
license_activation.html → GET /api/license/status (402) → redirects to login.html
Loop!
```

## Root Cause
The license guard in `auth-utils.js` was intercepting ALL 402 responses from ANY fetch call and redirecting to `license_activation.html`. This included:
1. Component loading requests (footer.html, etc.)
2. API calls without authentication tokens
3. Calls from pages that should NOT redirect (login.html, license_activation.html)

## Solution

### 1. Updated License Guard (auth-utils.js)
- Added whitelist of pages that should NOT trigger redirects
- Pages excluded from redirect: `login.html`, `license_activation.html`, `reset_password.html`
- Only pages requiring authentication (dashboard, sales, purchase, etc.) trigger the redirect
- This prevents redirect loops on unauthenticated pages

```javascript
const skipRedirectPages = ['login.html', 'license_activation.html', 'reset_password.html'];
const shouldRedirect = !skipRedirectPages.includes(page);
```

### 2. License Page API Call Optimization (license_activation.html)
- Skip API call if no authentication token present
- Token is only present if redirected from an authenticated page (dashboard)
- Without token, shows "No License" state without calling API
- This prevents unnecessary 402 responses and redirect triggers

```javascript
const token = localStorage.getItem('pos_token');
if (!token) {
    renderStatus(null);
    return;
}
```

### 3. Removed Dashboard License Check (dashboard.html)
- Removed early license check on dashboard page load
- Let the license guard handle it via API calls
- Cleaner separation of concerns

## New Clean Flow

```
1. User visits login.html
   ↓ (No redirects - login.html is in skiplist)
   ↓ User enters credentials + OTP
   ↓
2. Dashboard loads
   ↓ (Makes API call for KPIs)
   ↓
3. If license invalid, API returns 402
   ↓ License guard intercepts 402
   ↓ Redirects to license_activation.html?redirect=dashboard.html
   ↓
4. License page loads
   ↓ (Token present from being redirected from authenticated page)
   ↓ Calls API to get license status
   ↓
5. User enters license key
   ↓
6. Activation succeeds
   ↓ Redirects to dashboard.html (via redirect parameter)
```

## Benefits
✅ No redirect loops  
✅ Clean separation: auth pages (login, license) don't trigger redirects  
✅ Protected pages (dashboard, sales, etc.) enforce license via API  
✅ Splash overlay prevents white flashing on page load  
✅ User can visit login.html or license_activation.html without loops  

## Files Modified
- `auth-utils.js` (license guard)
- `license_activation.html` (API call optimization)
- `dashboard.html` (removed early license check)
- `login.html` (removed license check, kept simple)

## Testing
1. Visit https://app/login.html → Should show login form (no flashing/redirects)
2. Enter credentials → Go to dashboard
3. If license invalid → Redirected to license_activation.html
4. Enter license key → Success → Redirect back to dashboard
5. All API calls work with valid license
