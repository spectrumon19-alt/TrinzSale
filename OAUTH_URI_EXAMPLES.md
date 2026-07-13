# OAuth Redirect URI - Examples & Samples

## 🎯 What is a Redirect URI?

A **Redirect URI** is the URL where Google sends you back after you authorize TrintzERP to access your Google Drive.

It's like:
```
You → Click "Authorize with Google"
      ↓
Google asks: "Can TrintzERP access your Drive?"
      ↓
You click: "Yes, allow"
      ↓
Google sends you BACK to: https://example.com/api/backup/oauth/callback
```

---

## 📋 Redirect URI Samples

### **Sample 1: Local Development**
```
http://localhost:5001/api/backup/oauth/callback
```

**When to use:** When testing on your computer
**How it works:** 
- Run TrintzERP locally on port 5001
- Authorize with Google
- Google redirects to: `http://localhost:5001/api/backup/oauth/callback`
- TrintzERP processes the response

---

### **Sample 2: Render Deployment (Production)**
```
https://git-6ryt.onrender.com/api/backup/oauth/callback
```

**When to use:** When running on Render server
**How it works:**
- Your app is deployed on Render
- Authorize with Google
- Google redirects to your Render domain
- TrintzERP processes the response

---

### **Sample 3: Custom Domain (Your Own Domain)**
```
https://trintzerp.yourcompany.com/api/backup/oauth/callback
https://backup.myserver.com/api/backup/oauth/callback
https://app.yourdomain.com/api/backup/oauth/callback
```

**When to use:** When using your own domain name
**Examples:**
- If you own `mycompany.com` → `https://pos.mycompany.com/api/backup/oauth/callback`
- If you own `example.org` → `https://trintz.example.org/api/backup/oauth/callback`

---

### **Sample 4: Different Ports (Advanced)**
```
http://localhost:3000/api/backup/oauth/callback
http://localhost:8080/api/backup/oauth/callback
http://localhost:9000/api/backup/oauth/callback
```

**When to use:** If TrintzERP runs on a different port
**Note:** Change `5001` to your actual port number

---

### **Sample 5: Different Path (Advanced)**
```
http://localhost:5001/callback
http://localhost:5001/oauth/callback
http://localhost:5001/auth/google/callback
http://localhost:5001/api/auth/google/redirect
```

**When to use:** If using a different endpoint path
**Default:** `/api/backup/oauth/callback` (recommended)

---

## ✅ Common URI Examples

| Environment | Redirect URI |
|---|---|
| **Local (Port 5001)** | `http://localhost:5001/api/backup/oauth/callback` |
| **Local (Port 3000)** | `http://localhost:3000/api/backup/oauth/callback` |
| **Render** | `https://git-6ryt.onrender.com/api/backup/oauth/callback` |
| **Heroku** | `https://your-app.herokuapp.com/api/backup/oauth/callback` |
| **AWS** | `https://your-domain.us-east-1.elasticbeanstalk.com/api/backup/oauth/callback` |
| **Custom Domain** | `https://trintzerp.yourcompany.com/api/backup/oauth/callback` |

---

## 🔧 How to Find Your Redirect URI

### **For Local Development:**
```
Your app runs on: http://localhost:5001
Redirect URI: http://localhost:5001/api/backup/oauth/callback
```

### **For Render Deployment:**
1. Go to: https://dashboard.render.com
2. Click your service
3. See URL: `https://git-6ryt.onrender.com`
4. Redirect URI: `https://git-6ryt.onrender.com/api/backup/oauth/callback`

### **For Custom Domain:**
1. Your domain: `https://trintzerp.mycompany.com`
2. Redirect URI: `https://trintzerp.mycompany.com/api/backup/oauth/callback`

---

## 📝 Step-by-Step: Add URI to Google Cloud

### **1. Go to Google Cloud Console**
```
https://console.cloud.google.com
→ Select your project
→ Credentials (left menu)
→ Find your OAuth 2.0 Client ID
→ Click it to edit
```

### **2. Find "Authorized redirect URIs" Section**
```
Look for: "Authorized redirect URIs"
This is where you add URIs
```

### **3. Add Your URI**
- Click: **Add URI**
- Paste: `http://localhost:5001/api/backup/oauth/callback`
- (or your actual URI)

### **4. Add Multiple URIs (Recommended)**
Add BOTH local and production:
```
http://localhost:5001/api/backup/oauth/callback
https://git-6ryt.onrender.com/api/backup/oauth/callback
```

This lets you test locally AND use production

### **5. Save**
- Click: **Save** button

---

## 🎯 Your Setup (Sample)

### **Your Situation:**
- Local testing: Yes
- Production: Render
- Domain: `git-6ryt.onrender.com`

### **Your URIs Should Be:**
```
http://localhost:5001/api/backup/oauth/callback
https://git-6ryt.onrender.com/api/backup/oauth/callback
```

### **Your .env File Should Have:**
```env
# For local development
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback

# For production (change when deploying)
# GOOGLE_OAUTH_REDIRECT_URI=https://git-6ryt.onrender.com/api/backup/oauth/callback
```

---

## ⚠️ Important Rules

### **✅ DO:**
```
✅ Include protocol (http:// or https://)
✅ Match EXACTLY (case-sensitive)
✅ Include /api/backup/oauth/callback path
✅ No trailing slash usually (but some accept it)
✅ Use https:// for production
✅ Use http:// for local testing
```

### **❌ DON'T:**
```
❌ Forget http:// or https://
❌ Change the path (/api/backup/oauth/callback)
❌ Use different port than your app
❌ Mix up localhost with your domain
❌ Use http:// for production (security risk)
❌ Include extra parameters or #hash
```

---

## 🔍 Troubleshooting URIs

### **Problem: "Invalid redirect_uri"**
```
Cause: URI in .env doesn't match Google Cloud
Fix: Make sure they're EXACTLY the same
```

### **Problem: "Redirect URI mismatch"**
```
Cause: URI in code different from Google Cloud
Fix: Copy exact URI from Google Cloud
    Paste into .env
    Test again
```

### **Problem: "localhost doesn't work"**
```
Cause: Using wrong port
Fix: Make sure TrintzERP runs on port 5001
    Or update URI to match your port
```

### **Problem: "https shows certificate error"**
```
Cause: Self-signed certificate (local testing)
Fix: Use http:// for local testing instead
    Or fix certificate
```

---

## 📊 URI Components Explained

```
https://git-6ryt.onrender.com/api/backup/oauth/callback
│        │                    │  │  │      │     │
│        │                    │  │  │      │     └─ Endpoint name
│        │                    │  │  │      └─ Feature (backup)
│        │                    │  │  └─ API version
│        │                    │  └─ API prefix
│        │                    └─ Path/route
│        └─ Domain/host
└─ Protocol (https)
```

### **Breaking it Down:**
- **Protocol:** `https://` (secure connection)
- **Host:** `git-6ryt.onrender.com` (your server)
- **Path:** `/api/backup/oauth/callback` (where Google sends response)

---

## 🎬 Full Flow with URI

```
USER AUTHORIZES:
Step 1: TrintzERP redirects to Google
        https://accounts.google.com/o/oauth2/v2/auth?
          client_id=YOUR_ID&
          redirect_uri=http://localhost:5001/api/backup/oauth/callback&
          response_type=code&
          scope=drive

Step 2: User logs in and grants permission

Step 3: Google redirects BACK to your app with code
        http://localhost:5001/api/backup/oauth/callback?
          code=4/0AY0e-g...&
          state=...

Step 4: TrintzERP exchanges code for token
        (happens behind the scenes)

Step 5: Token stored in database ✅

Step 6: Backups can now upload to Google Drive ✅
```

---

## 📋 Complete Example Setup

### **Google Cloud Console:**
```
OAuth 2.0 Client ID: 123456789.apps.googleusercontent.com
Client Secret: GOCSPX-xxxxx

Authorized redirect URIs:
  • http://localhost:5001/api/backup/oauth/callback
  • https://git-6ryt.onrender.com/api/backup/oauth/callback
```

### **.env File (Local):**
```env
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback
```

### **.env File (Render):**
```env
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_OAUTH_REDIRECT_URI=https://git-6ryt.onrender.com/api/backup/oauth/callback
```

### **Authorization Request (from TrintzERP):**
```
GET https://accounts.google.com/o/oauth2/v2/auth?
  client_id=123456789.apps.googleusercontent.com&
  redirect_uri=http://localhost:5001/api/backup/oauth/callback&
  response_type=code&
  scope=https://www.googleapis.com/auth/drive&
  state=random_state_token
```

### **Google's Response (to your app):**
```
GET http://localhost:5001/api/backup/oauth/callback?
  code=4/0AY0e-g1a2b3c4d5e6f7g8h9i&
  state=random_state_token
```

---

## ✅ Quick Reference

| What | Example |
|---|---|
| Local URI | `http://localhost:5001/api/backup/oauth/callback` |
| Render URI | `https://git-6ryt.onrender.com/api/backup/oauth/callback` |
| Custom Domain | `https://trintzerp.company.com/api/backup/oauth/callback` |
| Protocol | `http://` (local) or `https://` (production) |
| Host | `localhost:5001` or `your-domain.com` |
| Path | Always: `/api/backup/oauth/callback` |
| Match Required | Yes - must match EXACTLY in Google Cloud |
| Case Sensitive | Yes - `Callback` ≠ `callback` |

---

## 🎯 Summary

**Redirect URI** = Where Google sends you back after you authorize

**Common URIs:**
- Local: `http://localhost:5001/api/backup/oauth/callback`
- Render: `https://git-6ryt.onrender.com/api/backup/oauth/callback`
- Custom: `https://yourdomain.com/api/backup/oauth/callback`

**Important:** Must match EXACTLY between:
1. Google Cloud Console
2. .env file
3. Your app

**For your setup:** Use both local AND Render URIs in Google Cloud so you can test locally and run production! ✅
