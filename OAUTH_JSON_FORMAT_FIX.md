# OAuth JSON Format Error - Fix Guide

## 🔴 Error Message
```
Service account info was not in the expected format, 
missing fields client_email, token_uri.
```

## ❌ What Went Wrong

You uploaded a **Service Account JSON** instead of an **OAuth Client JSON**

These are TWO DIFFERENT THINGS:
- ❌ Service Account JSON → For bots/automation (not what we need)
- ✅ OAuth Client JSON → For user login (what we need!)

---

## 🎯 The Real Issue

You probably downloaded the **wrong type** of credentials from Google Cloud.

### **Wrong Type (Service Account):**
```json
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----...",
  "client_email": "trintzpos@trintzpos-backup.iam.gserviceaccount.com",
  "client_id": "117...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

**Don't use this!** ❌ This is for service accounts, not OAuth.

### **Correct Type (OAuth Client):**
```json
{
  "installed": {
    "client_id": "123456789.apps.googleusercontent.com",
    "project_id": "trintzpos-backup",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "GOCSPX-xxxxx",
    "redirect_uris": ["http://localhost:8080/"]
  }
}
```

**Use this!** ✅ This is the correct OAuth format.

---

## ✅ How to Get the CORRECT JSON

### **Step 1: Go to Google Cloud Console**
```
https://console.cloud.google.com
```

### **Step 2: Navigate to Credentials**
- Left menu → **Credentials**

### **Step 3: Find OAuth 2.0 Client ID**
- Look for: **OAuth 2.0 Client IDs**
- Type should be: **Desktop application** or **Web application**
- NOT: **Service account**

### **Step 4: Download the Correct One**
- Click the **OAuth 2.0 Client ID** (NOT Service Account)
- Click the **Download** button (looks like ⬇️)
- Choose: **JSON**

### **Step 5: Check the JSON**
Open the downloaded file and look for:
```json
{
  "installed": {
    "client_id": "...",
    "client_secret": "...",
    ...
  }
}
```

If you see `"installed"` → ✅ Correct!
If you see `"type": "service_account"` → ❌ Wrong!

---

## 🔍 How to Identify You Have the WRONG File

Your file probably says:
```json
{
  "type": "service_account",  ← THIS IS WRONG!
  "project_id": "trintzpos-backup",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----",
  "client_email": "trintzpos@trintzpos-backup.iam.gserviceaccount.com",
  "client_id": "117...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

---

## ✅ How to Identify You Have the CORRECT File

Your file should say:
```json
{
  "installed": {  ← THIS MEANS IT'S CORRECT!
    "client_id": "123456789.apps.googleusercontent.com",
    "project_id": "trintzpos-backup",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "GOCSPX-xxxxx",
    "redirect_uris": ["http://localhost:8080/"]
  }
}
```

---

## 📋 Step-by-Step: Get Correct OAuth Credentials

### **Step 1: Open Google Cloud Console**
Visit: https://console.cloud.google.com

### **Step 2: Select Your Project**
- At top: Click project dropdown
- Select: `trintzpos-backup` (or your project)

### **Step 3: Go to Credentials**
- Left sidebar → Click **Credentials**

### **Step 4: Look for OAuth 2.0 Client IDs**
In the credentials list, you should see:
```
OAuth 2.0 Client IDs
├─ Web application (recommended)
└─ Desktop application
```

Select the **Web application** one (or Desktop if that's what you set up)

**NOT:** Service Accounts

### **Step 5: Click to Edit**
- Click the **Web application** OAuth 2.0 Client ID
- You'll see its details

### **Step 6: Download as JSON**
- Click the **download icon** (⬇️) at top right
- Choose **JSON**
- File will download

### **Step 7: Verify It's Correct**
Open the downloaded JSON file:
- Look for `"installed"` or `"web"` → ✅ Correct
- Look for `"type": "service_account"` → ❌ Wrong

---

## 🚫 Common Mistake

You probably:
1. Created a **Service Account** (wrong)
2. Downloaded the Service Account JSON (wrong)
3. Tried to use it for OAuth (wrong)

### **What You Should Have Done:**
1. Create an **OAuth 2.0 Client ID** (correct)
2. Download **OAuth Client JSON** (correct)
3. Use it for OAuth (correct)

---

## 🔧 Quick Fix

### **DO THIS NOW:**

1. **Delete** the old Service Account JSON file
2. **Go to Google Cloud** → Credentials
3. **Find** the OAuth 2.0 Client ID (Web application)
4. **Download** it as JSON
5. **Verify** it has `"installed"` or `"web"` field
6. **Copy** the `client_id` and `client_secret`
7. **Update .env** with correct values:

```env
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001
```

8. **Try authorization again** ✅

---

## 📊 Comparison: Service Account vs OAuth Client

| Aspect | Service Account | OAuth Client |
|---|---|---|
| **Use Case** | Bot/automation | User login |
| **JSON Field** | `"type": "service_account"` | `"installed"` or `"web"` |
| **Has client_email** | Yes | No |
| **Has token_uri** | Yes | No |
| **Has client_secret** | No (uses private_key) | Yes |
| **For backups** | ❌ Wrong | ✅ Correct |
| **Needs Google Workspace** | Yes ($$$) | No (FREE) |

---

## ✅ Correct OAuth JSON Structure

```json
{
  "installed": {
    "client_id": "123456789.apps.googleusercontent.com",
    "project_id": "trintzpos-backup",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "GOCSPX-xxxxxxxxxxxxxxxxxxxxxx",
    "redirect_uris": ["http://localhost:8080/"]
  }
}
```

**What you need from this:**
- `client_id` → Goes in `.env` as `GOOGLE_OAUTH_CLIENT_ID`
- `client_secret` → Goes in `.env` as `GOOGLE_OAUTH_CLIENT_SECRET`

---

## 🎯 Summary

**Error:** Missing `client_email`, `token_uri`

**Cause:** Using Service Account JSON instead of OAuth Client JSON

**Solution:**
1. Download the **correct** OAuth 2.0 Client ID JSON
2. Verify it has `"installed"` or `"web"` field (not `"type": "service_account"`)
3. Extract `client_id` and `client_secret`
4. Update `.env`
5. Try again ✅

**Key Difference:**
- Service Account = Bot login (wrong for this)
- OAuth Client = User login (correct!)

---

## 📚 Complete Guides

See also:
- `OAUTH_SETUP_GUIDE.md` - Full setup guide
- `GOOGLE_DRIVE_UPLOAD_COMPLETE_GUIDE.md` - Complete upload guide
- `OAUTH_URI_FIX.md` - URI format fix

---

## ✅ Next Steps

1. **Get the correct OAuth Client JSON** (not Service Account)
2. **Extract client_id and client_secret**
3. **Update .env file**
4. **Try authorization** - should work now! ✅
