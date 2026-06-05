# Complete Guide: How to Upload Backups to Google Drive

## 🎯 What You Want
Upload SQL backups automatically to: `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

## ✅ Complete Solution

There are 2 ways to upload backups to Google Drive:

### **Method 1: OAuth (Recommended) - FREE ✅**
- Uses YOUR Google account
- Works with personal Drive
- Works with "anyone with link" folders
- Automatic token refresh
- NO Google Workspace needed
- Cost: FREE

### **Method 2: Service Account - Paid ⚠️**
- Uses a bot account (service account)
- Only works with Google Workspace Shared Drives
- Requires Google Workspace ($6-14/month)
- More complex setup
- Cost: $6-14/month

---

## 📋 METHOD 1: OAuth (RECOMMENDED)

### **Why Choose OAuth:**
✅ Simplest setup
✅ Works with your Google Drive
✅ No Google Workspace needed
✅ Free forever
✅ Automatic token refresh
✅ Your data, your folder

---

## 🚀 OAuth Setup (Step by Step)

### **STEP 1: Create Google OAuth Credentials**

#### 1.1 Go to Google Cloud Console
```
https://console.cloud.google.com
```

#### 1.2 Create New Project
- Click: **"Select a Project"**
- Click: **"New Project"**
- Name: `TrintzPOS`
- Create

#### 1.3 Enable Google Drive API
- Search for: **"Google Drive API"**
- Click it
- Click: **ENABLE**

#### 1.4 Create OAuth Client ID
- Go to: **Credentials** (left menu)
- Click: **Create Credentials**
- Choose: **OAuth client ID**
- Application type: **Web application**
- Name: `TrintzPOS Backup`

#### 1.5 Add Authorized Redirect URIs
Add these URLs:
```
http://localhost:5001/api/backup/oauth/callback
https://git-6ryt.onrender.com/api/backup/oauth/callback
```

If you have a custom domain:
```
https://yourdomain.com/api/backup/oauth/callback
```

#### 1.6 Create and Copy
- Click: **Create**
- Click: **Download** (download as JSON)
- Save the file

#### 1.7 Get Your Credentials
Open the JSON file and find:
```json
{
  "client_id": "123456789.apps.googleusercontent.com",
  "client_secret": "GOCSPX-xxxxx",
  ...
}
```

Copy:
- `client_id`
- `client_secret`

---

### **STEP 2: Configure TrintzPOS Environment**

#### 2.1 Open .env File
```
Location: c:\Users\abhis\OneDrive\Desktop\t\pos\qa\git-main\.env
```

#### 2.2 Add OAuth Credentials
```env
# Google OAuth Configuration
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback
```

Replace with your actual values from Step 1.7

#### 2.3 Save File

---

### **STEP 3: Run Database Migration**

#### 3.1 What It Does
Adds OAuth columns to database:
- `oauth_enabled`
- `oauth_tokens`
- `oauth_user_email`

#### 3.2 Run Migration (Local)
```bash
psql -U postgres -d trintzpos < migrate_add_oauth_to_backup_settings.sql
```

#### 3.3 Run Migration (Render)
1. Go to: https://dashboard.render.com
2. Click your PostgreSQL database
3. Click: **PostgreSQL Console**
4. Copy entire contents of: `migrate_add_oauth_to_backup_settings.sql`
5. Paste into console
6. Click: **Execute**

---

### **STEP 4: Start TrintzPOS and Authorize**

#### 4.1 Start the App
```bash
cd c:\Users\abhis\OneDrive\Desktop\t\pos\qa\git-main
python app.py
```

#### 4.2 Open in Browser
```
http://localhost:5001
```

#### 4.3 Login to TrintzPOS
- Use your admin credentials
- Navigate to: **Backup** section

#### 4.4 Find Authorization Button
Look for: **"Authorize with Google"** button or similar

**If button doesn't exist**, you can use the API directly:

```bash
# Get authorization URL
curl -X POST http://localhost:5001/api/backup/oauth/authorize \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"
```

Response will include `auth_url` → copy and open in browser

#### 4.5 Grant Permission
- Click authorization link/button
- Google login page opens
- Enter your Google email
- Enter password
- Grant permission: Click **Allow**
- You should see: "✅ Authorization Successful"

#### 4.6 Verify Authorization
```bash
curl http://localhost:5001/api/backup/oauth/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Expected response:
```json
{
  "authorized": true,
  "user_email": "your.email@gmail.com",
  "expires_at": "2026-06-05T16:00:00"
}
```

---

### **STEP 5: Configure Backup Settings**

#### 5.1 Extract Folder ID
From your URL: `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

**Folder ID:** `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

#### 5.2 Open Backup Settings in TrintzPOS
- Navigate to: **Backup**
- Look for: **Backup Settings** or **Configure Backup**

#### 5.3 Fill in Settings
```
Google Drive Folder ID: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
Backup Schedule Time: 02:00 (2:00 AM)
Enable Automatic Backups: ON
```

#### 5.4 Save Settings
- Click: **Save**
- You should see: Success message ✅

---

### **STEP 6: Test the Backup**

#### 6.1 Run Manual Backup
- In TrintzPOS Backup page
- Click: **"Backup Now"** button
- Wait for upload (1-5 minutes)

#### 6.2 Check Result
Expected success message:
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

Look for:
- ✅ `"success": true`
- ✅ `"destination": "oauth"`
- ✅ `"error": null`

#### 6.3 Verify in Google Drive
- Open: https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
- Look for file: `trintzpos_backup_YYYYMMDD_HHMMSS.sql.gz`
- Example: `trintzpos_backup_20260605_143022.sql.gz`

**If file appears:** 🎉 SUCCESS! Backups are uploading!

---

## 🔄 How It Works After Setup

### **Automatic Daily Backup**
```
Every day at 2:00 AM:
├─ System creates SQL backup file
├─ Uses OAuth token (auto-refreshed)
├─ Uploads to your Google Drive folder
└─ File appears in folder ✅

You do: NOTHING
```

### **Token Refresh (Automatic)**
```
Token lasts: 1 hour
Before expiry:
├─ System detects expiration
├─ Uses refresh token
├─ Gets new access token
├─ Backup continues ✅

You do: NOTHING (automatic)
```

### **File Accumulation**
```
Day 1: trintzpos_backup_20260605_020000.sql.gz
Day 2: trintzpos_backup_20260606_020000.sql.gz
Day 3: trintzpos_backup_20260607_020000.sql.gz
...
Day 30: trintzpos_backup_20260704_020000.sql.gz

After 30 days:
Day 1 backup deleted (retention policy)
Day 31 backup added
```

---

## 📊 Your Google Drive Folder (After Setup)

```
Folder: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
│
├─ trintzpos_backup_20260605_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260606_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260607_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260608_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260609_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260610_020000.sql.gz (250 MB)
└─ trintzpos_backup_20260611_020000.sql.gz (250 MB)

Total: 1.75 GB (7 days of backups)
Retention: 30 days (auto-cleanup)
```

---

## ✅ Success Checklist

After completing all steps:

- [ ] OAuth credentials created in Google Cloud
- [ ] .env file has GOOGLE_OAUTH_CLIENT_ID
- [ ] .env file has GOOGLE_OAUTH_CLIENT_SECRET
- [ ] Database migration ran successfully
- [ ] Authorized with Google (token stored)
- [ ] Backup settings saved (folder ID set)
- [ ] Manual backup succeeded
- [ ] File appears in Google Drive folder
- [ ] Status shows `"destination": "oauth"`

If all checks pass: ✅ **SETUP COMPLETE!**

---

## 🆘 Troubleshooting

### Problem: "Google OAuth not configured"
**Solution:**
```
Check .env file has:
✅ GOOGLE_OAUTH_CLIENT_ID (not empty)
✅ GOOGLE_OAUTH_CLIENT_SECRET (not empty)
```

### Problem: "Invalid redirect URI"
**Solution:**
```
Ensure .env GOOGLE_OAUTH_REDIRECT_URI matches exactly
in Google Cloud Console Credentials settings
```

### Problem: Authorization fails
**Solution:**
```
1. Clear browser cache (Ctrl+Shift+Del)
2. Incognito mode
3. Check email/password
4. Try different Google account
```

### Problem: Backup succeeds but file doesn't appear
**Solution:**
```
1. Wait 1-2 minutes (syncing delay)
2. Refresh Google Drive (F5)
3. Check folder ID is correct
4. Check you have access to folder
```

### Problem: "Folder not found" error
**Solution:**
```
1. Verify folder ID is correct
2. Make sure folder still exists
3. Check you have access
4. Try using a different folder
```

### Problem: Token expired
**Solution:**
```
System auto-refreshes, but if stuck:
1. Revoke authorization
2. Re-authorize with Google
3. Try backup again
```

---

## 📈 Daily Backup Timeline

```
2026-06-05 02:00 AM: Backup #1 ✅
2026-06-06 02:00 AM: Backup #2 ✅
2026-06-07 02:00 AM: Backup #3 ✅
...
2026-07-04 02:00 AM: Backup #29 ✅
2026-07-05 02:00 AM: Backup #30 ✅ → Backup #1 deleted
2026-07-06 02:00 AM: Backup #31 ✅ → Backup #2 deleted
...
(continues indefinitely)
```

**Result:** Always have last 30 days of backups

---

## 🎯 What You Get

✅ **Automatic daily backups** to Google Drive
✅ **Your folder** receives files automatically
✅ **30 days history** of backups
✅ **Auto-cleanup** (old ones deleted)
✅ **Token refresh** (automatic)
✅ **Zero manual work** after setup
✅ **Free** (no Google Workspace)
✅ **Secure** (encrypted in Google's cloud)

---

## 📋 API Endpoints (If Using Programmatically)

### **Start Authorization**
```bash
POST /api/backup/oauth/authorize
Authorization: Bearer YOUR_TOKEN
```

### **Check Status**
```bash
GET /api/backup/oauth/status
Authorization: Bearer YOUR_TOKEN
```

### **Revoke Authorization**
```bash
POST /api/backup/oauth/revoke
Authorization: Bearer YOUR_TOKEN
```

### **Run Backup**
```bash
POST /api/backup/run
Authorization: Bearer YOUR_TOKEN
```

---

## 🎓 How OAuth Works (Simple Explanation)

```
Step 1: You click "Authorize with Google"
         ↓
Step 2: Google asks: "Can TrintzPOS access your Drive?"
         ↓
Step 3: You say: "Yes, I allow it"
         ↓
Step 4: Google gives TrintzPOS a permanent token
         ↓
Step 5: TrintzPOS stores token safely
         ↓
Step 6: Every day, TrintzPOS uses token to upload
         ↓
Step 7: Token auto-refreshes before expiring
         ↓
Step 8: You never need to login again
```

---

## Summary

**Your Goal:** Upload backups to Google Drive

**Solution:** Use OAuth (FREE, easiest)

**Setup Time:** ~20 minutes

**After Setup:** Completely automatic

**Files:** Daily backups in your Google Drive folder

**Result:** 30 days of backups, always available

🎯 **Ready?** Follow the 6 steps above!
