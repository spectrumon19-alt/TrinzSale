# OAuth Diagnostic - What's Wrong

## 🔴 Current Error
```
Service Accounts do not have storage quota.
Leverage shared drives or use OAuth delegation instead.
```

## 🔍 What This Means

The system is **still using the wrong JSON type** (Service Account instead of OAuth Client)

---

## ✅ Quick Diagnostic

### **Question 1: Did you use OAuth Client JSON?**

**If you're seeing this error:** NO, you're still using Service Account

### **Question 2: What JSON did you provide?**

The error shows the system tried to use a **Service Account**, which can't upload to personal Google Drive.

---

## 🎯 The Real Problem

You probably did ONE of these:

### **Problem 1: Still using old Service Account JSON**
- You have an old file from earlier attempts
- It's still in the system
- Need to delete it and use OAuth Client JSON

### **Problem 2: Uploaded JSON to wrong place**
- The JSON file got saved somewhere else
- System is reading the old Service Account version
- Need to update the correct location

### **Problem 3: Didn't update .env file**
- Downloaded correct OAuth JSON
- But forgot to update .env with new credentials
- System still using old values

---

## ✅ Complete Fix (4 Steps)

### **STEP 1: Check Your JSON File**

Open the JSON file you downloaded and look for:

```json
{
  "installed": {  ← If you see this: ✅ CORRECT
    "client_id": "...",
    "client_secret": "...",
    ...
  }
}
```

OR

```json
{
  "type": "service_account",  ← If you see this: ❌ WRONG
  "client_email": "...",
  "token_uri": "...",
  ...
}
```

**If you see "type": "service_account":**
- DELETE this file
- Download the correct OAuth Client JSON again
- Follow STEP 2

### **STEP 2: Download Correct OAuth Client JSON**

1. Go to: https://console.cloud.google.com
2. Click: **Credentials** (left menu)
3. Look for: **OAuth 2.0 Client IDs** (NOT Service Accounts)
4. Find: **Web application** (or Desktop)
5. Click: **Download** → **JSON**

**Verify the file:**
- Open it in text editor
- Look for: `"installed"` or `"web"` field
- NOT: `"type": "service_account"`

### **STEP 3: Extract Credentials**

Open the JSON file and find:

```json
{
  "installed": {
    "client_id": "123456789.apps.googleusercontent.com",
    "client_secret": "GOCSPX-xxxxx",
    ...
  }
}
```

Copy these two values:
- `client_id` = The long number with ".apps.googleusercontent.com"
- `client_secret` = The short GOCSPX-xxxxx value

### **STEP 4: Update .env File**

Edit: `c:\Users\abhis\OneDrive\Desktop\t\pos\qa\git-main\.env`

Replace:
```env
GOOGLE_OAUTH_CLIENT_ID=YOUR_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET=YOUR_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001
```

With your actual values from STEP 3:
```env
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001
```

**Save the file**

### **STEP 5: Restart TrintzERP**

Kill the running process:
```bash
# Press Ctrl+C in the terminal running TrintzERP
```

Start it again:
```bash
python app.py
```

### **STEP 6: Re-authorize**

1. Go to TrintzERP
2. Click "Authorize with Google"
3. You should get a different response (not the 403 error)

---

## 🔍 How to Verify It's Working

After re-authorization, check:

```bash
curl http://localhost:5001/api/backup/oauth/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

You should see:
```json
{
  "authorized": true,
  "user_email": "your.email@gmail.com",
  "expires_at": "2026-06-05T16:00:00"
}
```

**If you still see errors:** The new JSON hasn't been picked up yet

---

## 🛠️ Troubleshooting

### **Still Getting 403 Error?**

**Reason:** System is still using old Service Account

**Fix:**
1. Check `.env` file - does it have YOUR actual client_id and client_secret?
2. If not - update it with the NEW values
3. Restart app: `python app.py`
4. Try authorization again

### **Can't Find OAuth 2.0 Client ID in Google Cloud?**

You probably only created a Service Account.

**Fix:**
1. Go to Google Cloud Console
2. Click **Credentials**
3. Look for: **OAuth 2.0 Client IDs** section
4. If it's empty - you need to CREATE one:
   - Click: **Create Credentials** → **OAuth client ID**
   - Choose: **Web application**
   - Add redirect URI: `http://localhost:5001`
   - Create
   - Download as JSON

---

## 📊 Current State vs Correct State

### **Current (Wrong):**
```
Google Cloud: Service Account
.env: Old values (or wrong service account creds)
TrintzERP: Trying to use service account
Error: ❌ "Service Accounts do not have storage quota"
```

### **Correct:**
```
Google Cloud: OAuth 2.0 Client ID
.env: client_id + client_secret from OAuth JSON
TrintzERP: Using OAuth
Result: ✅ Uploads to your Google Drive
```

---

## ✅ Verification Checklist

- [ ] Downloaded OAuth Client JSON (not Service Account)
- [ ] JSON has `"installed"` or `"web"` field
- [ ] Extracted client_id and client_secret
- [ ] Updated .env with NEW values
- [ ] Restarted TrintzERP app
- [ ] Re-authorized with Google
- [ ] No more 403 errors
- [ ] Test backup succeeds
- [ ] File appears in Google Drive ✅

---

## 🎯 Summary

**Current Error:** Service Account trying to upload

**Root Cause:** Still using wrong JSON type

**Solution:** 
1. Delete Service Account JSON
2. Download OAuth Client JSON (with "installed" field)
3. Update .env with new credentials
4. Restart app
5. Re-authorize

**Result:** Should work! ✅

---

## 📖 Related Guides

- `OAUTH_JSON_FORMAT_FIX.md` - Detailed JSON format guide
- `OAUTH_SETUP_GUIDE.md` - Full setup instructions
- `GOOGLE_DRIVE_UPLOAD_COMPLETE_GUIDE.md` - Upload guide

---

## 🚀 Next Steps

**Right now:**
1. Check your JSON file
2. Make sure it has `"installed"` (not `"type": "service_account"`)
3. Update `.env` with new credentials
4. Restart app
5. Try again

**Expected result:** Authorization should work, file uploads to Google Drive! ✅
