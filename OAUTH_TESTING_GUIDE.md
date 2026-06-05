# OAuth Testing Guide - Complete

## 🧪 How to Test OAuth Implementation

This guide walks you through testing every part of the OAuth backup system.

---

## 📋 Prerequisites

Before testing, you need:

1. ✅ OAuth credentials created (see OAUTH_SETUP_GUIDE.md)
2. ✅ Environment variables configured (.env)
3. ✅ Database migration applied
4. ✅ TrintzPOS running locally or on Render
5. ✅ Admin access to TrintzPOS
6. ✅ A Google Drive folder to test with

---

## 🧪 Test 1: Authorization Flow

### **Objective:** Verify OAuth authorization works

### **Steps:**

1. **Start TrintzPOS**
   ```bash
   python app.py
   ```
   Should see: `TrintzPOS starting... open http://localhost:5001`

2. **Open Browser**
   - Go to: `http://localhost:5001`
   - Login with your TrintzPOS credentials

3. **Navigate to Backup Settings**
   - Click: **Backup** or **Settings** → **Backup**
   - Should see backup configuration options

4. **Click "Authorize with Google"** (or similar button)
   - Look for button on backup page
   - Click it

### **Expected Result:**

✅ Google login page opens
✅ Shows: "Sign in to your Google Account"
✅ You can enter your Google email

### **Troubleshooting:**

**Problem:** Button doesn't exist
- **Solution:** UI button might not be added yet (optional step in guide)
- **Workaround:** Use API endpoint directly (Test 2)

**Problem:** Authorization URL is malformed
- **Solution:** Check `GOOGLE_OAUTH_CLIENT_ID` in `.env`

---

## 🧪 Test 2: Authorization API (Without UI)

### **Objective:** Test OAuth authorization endpoint directly

### **Prerequisites:**
- Get your admin token from TrintzPOS
- You'll need: `Authorization: Bearer YOUR_TOKEN`

### **Steps:**

1. **Get Your Token**
   ```bash
   # Login to TrintzPOS
   # Open browser console (F12)
   # Type: localStorage.getItem('pos_token')
   # Copy the token value
   ```

2. **Call Authorization Endpoint**
   ```bash
   curl -X POST http://localhost:5001/api/backup/oauth/authorize \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json"
   ```

3. **Expected Response**
   ```json
   {
     "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=...",
     "message": "Open this URL to authorize Google Drive access"
   }
   ```

4. **Open the Auth URL**
   - Copy the `auth_url` from response
   - Paste in browser
   - Google login page appears ✅

### **Troubleshooting:**

**Error: "Google OAuth not configured"**
- **Solution:** Check `.env` has `GOOGLE_OAUTH_CLIENT_ID`

**Error: "Invalid redirect URI"**
- **Solution:** Redirect URI in .env doesn't match Google Cloud settings
- **Fix:** Update both to match

---

## 🧪 Test 3: OAuth Callback

### **Objective:** Verify OAuth callback works after authorization

### **Steps:**

1. **Start Authorization** (from Test 2)
   - Get auth_url
   - Open in browser

2. **Grant Permission**
   - Click "Sign in to your Google Account"
   - Enter your Google email
   - Enter password
   - Grant permission: "TrintzPOS wants to access your Google Drive"
   - Click **Allow**

3. **Callback Should Happen**
   - After allowing, you should see success page
   - Page says: "✅ Authorization Successful!"
   - Shows: "Google Drive access authorized for: your.email@gmail.com"

### **Expected Result:**

✅ Success message appears
✅ Window closes (if opened in popup)
✅ Parent page reloads (if opened in same window)

### **Troubleshooting:**

**Problem: "Authorization failed"**
- **Solution:** Check Google Cloud OAuth settings
- Verify: Redirect URI is correct

**Problem: "Invalid request: state token mismatch"**
- **Solution:** Session lost, try again
- Ensure cookies are enabled

**Problem: Window doesn't close**
- **Solution:** Manual close is fine
- Return to TrintzPOS and check status (Test 4)

---

## 🧪 Test 4: Check Authorization Status

### **Objective:** Verify token is stored after authorization

### **Steps:**

1. **Call Status Endpoint**
   ```bash
   curl http://localhost:5001/api/backup/oauth/status \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

2. **Expected Response (Authorized)**
   ```json
   {
     "authorized": true,
     "user_email": "your.email@gmail.com",
     "expires_at": "2026-06-05T16:00:00",
     "message": "OAuth authorized"
   }
   ```

3. **Expected Response (Not Authorized)**
   ```json
   {
     "authorized": false,
     "message": "No OAuth authorization found"
   }
   ```

### **Success Indicators:**

✅ `"authorized": true`
✅ Your Google email appears
✅ Expiry time is set

### **Troubleshooting:**

**Problem: Still showing "authorized": false**
- **Solution:** Authorization may have failed
- Try: Test 3 again

**Problem: User email is wrong**
- **Solution:** You authorized with different account
- Revoke and re-authorize with correct account

---

## 🧪 Test 5: Configure Backup Settings

### **Objective:** Set up folder ID and schedule

### **Steps:**

1. **Go to Backup Settings** (TrintzPOS UI)
   - Navigate to: **Backup** section

2. **Set Folder ID**
   - Find: "Google Drive Folder ID" field
   - Enter: `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`
   - (Your test folder ID)

3. **Set Backup Schedule**
   - Enable: "Enable automatic backups" (toggle ON)
   - Set time: `02:00` (2:00 AM)
   - Or pick any time in next 5 minutes for testing

4. **Save Settings**
   - Click: **Save**

### **Expected Result:**

✅ Settings saved
✅ No error messages
✅ Folder ID remains in field

### **Troubleshooting:**

**Problem: "Folder not found"**
- **Solution:** Check folder ID is correct
- Try with folder you have access to

**Problem: Settings don't save**
- **Solution:** Check browser console (F12) for errors
- Verify token is valid

---

## 🧪 Test 6: Manual Backup (Test Upload)

### **Objective:** Test actual upload to Google Drive

### **Steps:**

1. **Go to Backup Page**
   - Navigate to: **Backup**

2. **Click "Backup Now"**
   - Look for button
   - Click it

3. **Wait for Backup**
   - Should see progress/status
   - Takes 1-5 minutes depending on database size

4. **Check Response**
   - Look for success message
   - Should show file size uploaded

### **Expected Response:**

```json
{
  "success": true,
  "filename": "trintzpos_backup_20260605_143022.sql.gz",
  "size_bytes": 262144000,
  "destination": "oauth",
  "gdrive_id": "1ABC2DEF3GHI4JKL5MNO6PQR7STU8VWX",
  "log_id": 12345,
  "error": null
}
```

### **Success Indicators:**

✅ `"success": true`
✅ `"destination": "oauth"`
✅ `"gdrive_id": "1ABC2DEF..."`
✅ `"error": null`

### **Troubleshooting:**

**Problem: "destination": "local" (not "oauth")**
- **Solution:** OAuth not authorized
- Check: Test 4 (status check)

**Problem: Error about token**
- **Solution:** Token may be expired
- Workaround: System auto-refreshes, try again

**Problem: "Folder not found"**
- **Solution:** Folder ID incorrect
- Verify: Test 5 (folder configuration)

---

## 🧪 Test 7: Verify File in Google Drive

### **Objective:** Confirm backup file actually appears in Google Drive

### **Steps:**

1. **Open Google Drive**
   - Go to: `https://drive.google.com`
   - Login with your account

2. **Navigate to Test Folder**
   - Go to: `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

3. **Look for Backup File**
   - Should see file named: `trintzpos_backup_YYYYMMDD_HHMMSS.sql.gz`
   - Example: `trintzpos_backup_20260605_143022.sql.gz`

4. **Check File Details**
   - File size: Should be 200+ MB
   - Type: Gzip compressed
   - Created: Recent timestamp

### **Success Indicators:**

✅ File exists in folder
✅ File name has timestamp
✅ File size is reasonable (200+ MB)
✅ Created time matches backup time

### **Troubleshooting:**

**Problem: File not in folder**
- **Solution:** Wrong folder opened
- Double-check folder ID

**Problem: Old file still there, new one missing**
- **Solution:** Backup may have failed
- Check: Test 6 (backup response)
- Check: Backup logs in TrintzPOS

---

## 🧪 Test 8: Token Refresh

### **Objective:** Verify automatic token refresh works

### **Steps:**

1. **Get Current Token Expiry** (from Test 4)
   ```bash
   curl http://localhost:5001/api/backup/oauth/status \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```
   - Note the `expires_at` time

2. **Wait for Near Expiry** (or test manually)
   - Real test: Wait 55 minutes (token expires in 60)
   - Quick test: Code handles this automatically

3. **Run Another Backup** (before expiry)
   ```bash
   # Click "Backup Now" again in TrintzPOS
   # Or manually call backup endpoint
   ```

4. **Check Backup Success**
   - Should work without re-authorization
   - Status: `"destination": "oauth"` ✅

5. **Check New Expiry**
   ```bash
   curl http://localhost:5001/api/backup/oauth/status \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```
   - `expires_at` should be NEW time (1 hour from now)

### **Success Indicators:**

✅ Second backup succeeds
✅ No re-login required
✅ Token expiry time updated
✅ File uploaded to Google Drive

### **Troubleshooting:**

**Problem: Second backup fails with token error**
- **Solution:** Token refresh failed
- Check: Refresh token is valid
- Revoke and re-authorize

---

## 🧪 Test 9: Scheduled Backup

### **Objective:** Test automatic scheduled backup

### **Steps:**

1. **Configure Schedule** (Test 5)
   - Set backup time to: Next 5 minutes
   - Example: If it's 2:40 PM, set to 2:45 PM

2. **Wait for Scheduled Time**
   - Don't manually run backup
   - Let system run automatically

3. **Check System Logs**
   ```bash
   # On your server/Render
   # Look for logs around scheduled time
   # Should show backup starting
   ```

4. **Check Google Drive** (after scheduled time)
   - New file should appear in folder
   - Timestamp should match scheduled time

5. **Check Backup Logs** (in TrintzPOS UI)
   - Go to: Backup → History
   - Should see new backup with `destination: oauth`

### **Success Indicators:**

✅ Backup runs at scheduled time
✅ File appears in Google Drive
✅ Backup log shows success
✅ No manual intervention needed

### **Troubleshooting:**

**Problem: Scheduled backup doesn't run**
- **Solution:** Scheduler might be disabled
- Check: App logs for scheduler status
- Restart app if needed

**Problem: Backup runs but doesn't upload**
- **Solution:** OAuth issue
- Check: Test 4 (authorization status)

---

## 🧪 Test 10: Revoke Authorization

### **Objective:** Test revoking OAuth access

### **Steps:**

1. **Call Revoke Endpoint**
   ```bash
   curl -X POST http://localhost:5001/api/backup/oauth/revoke \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

2. **Expected Response**
   ```json
   {
     "success": true,
     "message": "OAuth authorization revoked"
   }
   ```

3. **Check Status**
   ```bash
   curl http://localhost:5001/api/backup/oauth/status \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```
   - Should return: `"authorized": false`

4. **Try Backup**
   - Click "Backup Now"
   - Should fail or fall back to service account

### **Success Indicators:**

✅ Status returns `"authorized": false`
✅ Can't backup via OAuth anymore
✅ Can re-authorize if needed

---

## 📊 Testing Checklist

- [ ] Test 1: Authorization flow (button/URL opens)
- [ ] Test 2: Authorization API (endpoint works)
- [ ] Test 3: OAuth callback (success page appears)
- [ ] Test 4: Check status (shows authorized)
- [ ] Test 5: Configure settings (folder ID saved)
- [ ] Test 6: Manual backup (upload succeeds)
- [ ] Test 7: File in Google Drive (appears in folder)
- [ ] Test 8: Token refresh (second backup works)
- [ ] Test 9: Scheduled backup (runs automatically)
- [ ] Test 10: Revoke (can revoke authorization)

---

## 🎯 Test Success Criteria

| Test | Success Indicator |
|---|---|
| Auth Flow | Google login page appears |
| Auth API | Returns auth_url |
| Callback | Success page, token stored |
| Status | Returns `"authorized": true` |
| Settings | Folder ID saved, no errors |
| Manual Backup | File uploaded, `"destination": "oauth"` |
| Google Drive | File appears in folder |
| Token Refresh | Second backup works, new expiry |
| Scheduled | Backup runs at scheduled time |
| Revoke | Status returns `"authorized": false` |

---

## 🔧 Debugging Tips

### **Enable Logging**
```python
# In app.py or routes/backup_oauth.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

### **Check Database**
```sql
-- Connect to PostgreSQL
SELECT * FROM backup_settings;

-- See if oauth_enabled is TRUE
-- See if oauth_tokens contains data
-- See if oauth_user_email is populated
```

### **Browser Developer Tools**
```javascript
// Open F12 console
// Check for JavaScript errors
// Check Network tab for API calls
// Check Storage → localStorage for tokens
```

### **Check Server Logs**
```bash
# If running locally
# Terminal should show Flask logs

# If on Render
# Go to Render dashboard → Logs
# Look for backup-related messages
```

---

## 📝 Test Report Template

```
Test Date: 2026-06-05
Tester: [Your Name]
Environment: Local / Render
TrintzPOS Version: [Version]

Test Results:
[ ] Test 1: Authorization Flow - PASS / FAIL
[ ] Test 2: Authorization API - PASS / FAIL
[ ] Test 3: OAuth Callback - PASS / FAIL
[ ] Test 4: Check Status - PASS / FAIL
[ ] Test 5: Configure Settings - PASS / FAIL
[ ] Test 6: Manual Backup - PASS / FAIL
[ ] Test 7: File in Google Drive - PASS / FAIL
[ ] Test 8: Token Refresh - PASS / FAIL
[ ] Test 9: Scheduled Backup - PASS / FAIL
[ ] Test 10: Revoke - PASS / FAIL

Issues Found:
1. [Issue description]
   - Status: [Open / Fixed]
   - Severity: [Critical / High / Medium / Low]

Notes:
[Any additional notes]
```

---

## Summary

**Complete Testing Flow:**

1. ✅ Start app
2. ✅ Authorize with Google (Test 1-3)
3. ✅ Verify authorization (Test 4)
4. ✅ Configure settings (Test 5)
5. ✅ Test manual backup (Test 6)
6. ✅ Verify file in Google Drive (Test 7)
7. ✅ Test token refresh (Test 8)
8. ✅ Test scheduled backup (Test 9)
9. ✅ Test revoke (Test 10)

**Expected Time:** ~30-45 minutes
**Success Rate:** All 10 tests should pass

If all tests pass, OAuth is working perfectly! 🎯
