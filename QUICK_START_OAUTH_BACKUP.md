# Quick Start: Send SQL Backups to Google Drive

## 🎯 Your Goal
Send backups to: `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

## ✅ 3 Steps to Complete Setup

---

## STEP 1: Create Google OAuth Credentials (5 minutes)

### 1.1 Go to Google Cloud Console
- Visit: https://console.cloud.google.com
- Create new project or select existing one

### 1.2 Enable Google Drive API
- Search for "Google Drive API"
- Click it
- Click **ENABLE**

### 1.3 Create OAuth Credentials
- Go to **Credentials** (left sidebar)
- Click **Create Credentials** → **OAuth client ID**
- Choose: **Web application**
- Add authorized redirect URIs:
  ```
  http://localhost:5001/api/backup/oauth/callback
  https://git-6ryt.onrender.com/api/backup/oauth/callback
  ```
- Click **Create**

### 1.4 Copy Credentials
- Click **Download** (JSON icon)
- Save the file
- Open it and note:
  - `client_id` (looks like: `xxx.apps.googleusercontent.com`)
  - `client_secret` (looks like: `xxxxx`)

---

## STEP 2: Configure TrintzERP (.env file) (2 minutes)

### 2.1 Open `.env` file
Location: `c:\Users\abhis\OneDrive\Desktop\t\pos\qa\git-main\.env`

### 2.2 Add these lines
```env
GOOGLE_OAUTH_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=YOUR_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5001/api/backup/oauth/callback
```

Replace:
- `YOUR_CLIENT_ID` - from step 1.4
- `YOUR_CLIENT_SECRET` - from step 1.4

### 2.3 Save file

---

## STEP 3: Run Database Migration (1 minute)

### 3.1 Extract Folder ID from Your URL
From: `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

Your folder ID is: `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

### 3.2 Run Migration
Connect to your database and run:

**For Local PostgreSQL:**
```bash
psql -U postgres -d trintzerp < migrate_add_oauth_to_backup_settings.sql
```

**For Render:**
1. Go to Render Dashboard
2. Click PostgreSQL database
3. Click **PostgreSQL Console**
4. Copy-paste contents of `migrate_add_oauth_to_backup_settings.sql`
5. Execute

---

## STEP 4: Start TrintzERP and Authorize (5 minutes)

### 4.1 Start the Application
```bash
# In terminal
cd c:\Users\abhis\OneDrive\Desktop\t\pos\qa\git-main
python app.py
```

### 4.2 Open in Browser
```
http://localhost:5001
```

### 4.3 Authorize Google Drive
- Navigate to: **Backup** settings
- Look for: **"Authorize with Google"** button
- Click it
- Google login page opens
- Enter your Google email
- Enter password
- Grant permission: **Allow**

### 4.4 Verify Authorization
- You should see: ✅ Authorization Successful
- Shows your email address

---

## STEP 5: Configure Backup Settings (2 minutes)

### 5.1 Go to Backup Settings
- In TrintzERP → **Backup**

### 5.2 Enter Your Folder ID
- Find: **Google Drive Folder ID**
- Paste: `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

### 5.3 Enable Automatic Backups
- Toggle: **Enable automatic backups** → ON
- Set time: **02:00** (2:00 AM)
- Or any time you prefer

### 5.4 Save
- Click **Save**

---

## STEP 6: Test Backup (2 minutes)

### 6.1 Click "Backup Now"
- In Backup page
- Click **Backup Now** button

### 6.2 Wait for Upload
- Takes 1-5 minutes (depends on database size)
- You should see success message

### 6.3 Verify in Google Drive
- Open: https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
- Look for file: `trintzerp_backup_YYYYMMDD_HHMMSS.sql.gz`
- Example: `trintzerp_backup_20260605_143022.sql.gz`

### 6.4 If File Appears ✅
**SUCCESS!** Backups are now uploading to your Google Drive!

---

## 🔄 After Setup

### **What Happens Automatically:**
- Every day at 2:00 AM (or your time): 
  - ✅ Database backup created
  - ✅ Uploaded to Google Drive folder
  - ✅ Token auto-refreshes (you don't see it)
  - ✅ File appears in your folder

### **What You Do:**
- Nothing! It's fully automatic
- Backups accumulate in your folder
- 30-day retention (old ones auto-delete)

### **To Download a Backup:**
- Go to your Google Drive folder
- Right-click any `.sql.gz` file
- Click **Download**
- You can restore it anytime

---

## 🛠️ Troubleshooting

### Problem: "Google OAuth not configured"
**Solution:** Check `.env` file has correct `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`

### Problem: Authorization doesn't work
**Solution:** 
- Make sure redirect URI in Google Cloud matches `.env`
- Clear browser cache and try again

### Problem: Backup uploads but file doesn't appear in Google Drive
**Solution:**
- Wrong folder ID? Double-check it's correct
- Check folder permissions? Make sure you have access
- Try refreshing Google Drive

### Problem: "Folder not found" error
**Solution:** 
- Verify folder ID is correct
- Make sure folder still exists
- Try another folder to test

### Problem: Backup doesn't run automatically at scheduled time
**Solution:**
- Is app still running? Check if TrintzERP is running
- Check app logs for errors
- Try manually clicking "Backup Now" to test

---

## ✅ Success Indicators

You'll know it's working when:

1. ✅ Authorization shows your Google email
2. ✅ Manual backup succeeds (file uploads)
3. ✅ File appears in your Google Drive folder
4. ✅ Scheduled backup runs at set time
5. ✅ Multiple days of backups accumulate

---

## 📊 What You Get

```
Your Google Drive Folder:
├─ 2026-06-05 → trintzerp_backup_20260605_020000.sql.gz (250 MB)
├─ 2026-06-06 → trintzerp_backup_20260606_020000.sql.gz (250 MB)
├─ 2026-06-07 → trintzerp_backup_20260607_020000.sql.gz (250 MB)
├─ ... (more daily backups)
└─ 2026-07-05 → trintzerp_backup_20260705_020000.sql.gz (250 MB)

Total: 30 days of backups = ~7.5 GB
(Auto-cleanup: older than 30 days deleted)
```

---

## 🎯 Complete Timeline

```
SETUP (First Time):
Step 1: Create OAuth credentials (5 min)
Step 2: Configure .env (2 min)
Step 3: Database migration (1 min)
Step 4: Authorize in TrintzERP (5 min)
Step 5: Configure backup settings (2 min)
Step 6: Test backup (2 min)
Total: ~17 minutes ⏱️

AFTERWARDS:
- Every day at 2:00 AM: Automatic backup to Google Drive
- Zero manual work
- Files accumulate in folder
- 30 days of backups always available
```

---

## 📚 For More Details

- Setup guide: `OAUTH_SETUP_GUIDE.md`
- How it works: `HOW_OAUTH_WORKS.md`
- Testing guide: `OAUTH_TESTING_GUIDE.md`

---

## Summary

**You want:** SQL backups → Google Drive folder
**Setup time:** ~17 minutes
**After setup:** Completely automatic
**Cost:** FREE
**Result:** Daily backups in your Google Drive! ✅

Let me know if you need help with any step! 🎯
