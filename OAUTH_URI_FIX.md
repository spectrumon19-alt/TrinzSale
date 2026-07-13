# OAuth Redirect URI - Error Fix

## 🔴 Error Message
```
Invalid Origin: URIs must not contain a path or end with "/".
```

## ✅ The Fix

Google Cloud requires Redirect URIs to have **NO path** - just the base URL.

### **WRONG (Will cause error):**
```
❌ http://localhost:5001/api/backup/oauth/callback
❌ https://git-6ryt.onrender.com/api/backup/oauth/callback
❌ https://yourdomain.com/api/backup/oauth/callback/
```

### **CORRECT (What Google expects):**
```
✅ http://localhost:5001
✅ https://git-6ryt.onrender.com
✅ https://yourdomain.com
```

---

## 🔧 How to Fix

### **Step 1: Go to Google Cloud Console**
- https://console.cloud.google.com
- Click your project
- Go to **Credentials**
- Click your OAuth 2.0 Client ID to edit

### **Step 2: Find "Authorized redirect URIs"**
- Look for the section: "Authorized redirect URIs"

### **Step 3: Replace with Correct URIs**

**Delete these (WRONG):**
```
http://localhost:5001/api/backup/oauth/callback
https://git-6ryt.onrender.com/api/backup/oauth/callback
```

**Add these instead (CORRECT):**
```
http://localhost:5001
https://git-6ryt.onrender.com
```

### **Step 4: Save**
- Click **Save**

---

## 📋 Correct URI Format Examples

### **Local Development:**
```
✅ http://localhost:5001
```

### **Render Deployment:**
```
✅ https://git-6ryt.onrender.com
```

### **Custom Domain:**
```
✅ https://trintzerp.mycompany.com
✅ https://backup.example.org
```

### **Different Ports:**
```
✅ http://localhost:3000
✅ http://localhost:8080
```

---

## 🎯 What Google Will Do (Behind the Scenes)

Even though you only register the base URL:
```
https://git-6ryt.onrender.com
```

Google will redirect to the FULL path:
```
https://git-6ryt.onrender.com/api/backup/oauth/callback?code=...&state=...
```

TrintzERP receives it at the `/api/backup/oauth/callback` endpoint and processes it. ✅

---

## 📝 Update Your .env File

Your `.env` file can still have the full path (TrintzERP uses it internally):

```env
# Google Cloud Console URIs (NO path)
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx

# TrintzERP uses the full path internally (but Google only needs the base)
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback
```

**Note:** The code automatically handles the full path, Google only needs the base URL.

---

## ✅ Step-by-Step: Google Cloud Fix

### **Current Wrong State:**
```
Google Cloud Authorized Redirect URIs:
- http://localhost:5001/api/backup/oauth/callback  ❌
- https://git-6ryt.onrender.com/api/backup/oauth/callback  ❌
```

### **Corrected State:**
```
Google Cloud Authorized Redirect URIs:
- http://localhost:5001  ✅
- https://git-6ryt.onrender.com  ✅
```

### **Your .env (Can be full path):**
```env
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback
```

---

## 🔍 Why Google Requires This

Google's security model:
```
1. You register: http://localhost:5001
2. Google trusts ANYTHING under that origin
3. Including: /api/backup/oauth/callback
4. Or: /callback
5. Or: /any/path/here

This is intentional - gives flexibility to your app
```

---

## 📊 Correct URIs Reference

| Environment | Correct URI | Common Mistake |
|---|---|---|
| **Local** | `http://localhost:5001` | `http://localhost:5001/api/backup/oauth/callback` |
| **Render** | `https://git-6ryt.onrender.com` | `https://git-6ryt.onrender.com/api/backup/oauth/callback` |
| **Custom** | `https://mycompany.com` | `https://mycompany.com/api/backup/oauth/callback` |
| **Port 3000** | `http://localhost:3000` | `http://localhost:3000/callback` |
| **Port 8080** | `http://localhost:8080` | `http://localhost:8080/api/oauth` |

---

## ✅ Complete Fixed Setup

### **Google Cloud Console (Authorized redirect URIs):**
```
http://localhost:5001
https://git-6ryt.onrender.com
```

### **.env File:**
```env
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback
```

### **How It Works:**
1. You click "Authorize with Google"
2. Google redirects to: `http://localhost:5001/api/backup/oauth/callback?code=...`
3. TrintzERP endpoint receives it
4. Token stored ✅
5. Backups upload to Google Drive ✅

---

## 🎯 Summary

**Error:** "URIs must not contain a path"

**Cause:** You added the full path in Google Cloud

**Solution:** 
- Remove path from Google Cloud URIs
- Use only the base URL:
  ```
  http://localhost:5001
  https://git-6ryt.onrender.com
  ```

**Your .env can still have the full path** - TrintzERP handles it internally

---

## ✅ Next Steps

1. Go to Google Cloud Console
2. Edit your OAuth 2.0 Client ID
3. Replace URIs with **base URLs only** (no path)
4. Save
5. Try authorization again ✅

You're all set! 🎯
