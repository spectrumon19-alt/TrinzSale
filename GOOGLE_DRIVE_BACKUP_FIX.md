# Google Drive Backup - Issue & Fix

## 🔴 Problem: Files Not Being Saved to Google Drive

**Symptoms:**
- Backups are created locally
- Google Drive upload is enabled but not working
- Files don't appear in Google Drive
- Backup logs show `destination: 'local'` instead of `'gdrive'`

---

## 🔍 Root Cause Analysis

The issue is in the backup flow:

1. **Credentials Not Stored:** Google Drive service account JSON is not being properly stored in `backup_settings.gdrive_credentials`
2. **Missing Test:** No way to verify Google Drive connection is working
3. **Silent Failures:** If upload fails, the system falls back to local storage without alerting the user

---

## ✅ Solution

### **Step 1: Set Up Google Drive Service Account (One-Time)**

1. **Go to Google Cloud Console:**
   - Visit https://console.cloud.google.com
   - Create a new project (if needed)
   - Enable **Google Drive API**

2. **Create Service Account:**
   - Go to Service Accounts
   - Click **Create Service Account**
   - Name: `trintzpos-backup`
   - Click **Create and Continue**

3. **Create Key:**
   - Click on the service account
   - Go to **Keys** tab
   - Click **Add Key** → **Create new key**
   - Choose **JSON**
   - Download the JSON file

4. **Share Google Drive Folder:**
   - In Google Drive, create a folder (e.g., "TrintzPOS Backups")
   - Right-click → **Share**
   - Copy the service account email from the JSON file (looks like: `xxx@xxx.iam.gserviceaccount.com`)
   - Paste in Share dialog
   - Make sure it has **Editor** access
   - Copy the **Folder ID** from the URL: `https://drive.google.com/drive/folders/[FOLDER_ID]`

---

### **Step 2: Configure in TrintzPOS**

1. **Go to Backup Settings Page**
   - Navigate to **TrintzPOS | Backup**
   - Look for **Google Drive Upload** section

2. **Enable Google Drive:**
   - Toggle **"Upload backups to Google Drive"** ON

3. **Enter Folder ID:**
   - Paste the **Google Drive Folder ID** you copied earlier
   - Example: `1a2B3c4D5e6F7g8H9i0J`

4. **Upload Service Account JSON:**
   - Click **"Choose JSON file"** or **"Upload Credentials"**
   - Select the JSON file downloaded from Google Cloud Console
   - Click **"Test Google Drive Connection"**
   - Wait for success message

5. **Save Settings:**
   - Click **Save**
   - You should see a success toast message

---

## 🧪 Test the Setup

### **Test 1: Manual Backup**
1. Click **"Backup Now"** button
2. Wait for backup to complete
3. Check backup logs:
   - **Destination** should be `gdrive` (not `local`)
   - **Status** should be `success`
   - **GDrive File ID** should be populated

### **Test 2: Verify in Google Drive**
1. Open your Google Drive folder
2. You should see files like: `trintzpos_backup_20260605_143022.sql.gz`
3. Download and verify it's a valid SQL backup file

### **Test 3: Scheduled Backup**
1. Enable **"Enable automatic backups"** toggle
2. Set **Backup Time** (e.g., 02:00 AM)
3. Backups will run automatically at the scheduled time

---

## 🔧 Troubleshooting

### **Issue: "Test Google Drive Connection" Fails**

**Problem:** Connection test shows error

**Solutions:**
1. **Check JSON Format:** Make sure you selected JSON format when downloading
2. **Check Folder ID:** Verify folder ID is correct (get from URL)
3. **Check Sharing:** Make sure service account email has **Editor** access to the folder
4. **Regenerate Key:** If old, generate a new key in Google Cloud Console

**Error:** `"error": "No credentials configured"`
- You haven't uploaded the JSON credentials yet
- Click the file upload button and select your JSON file

**Error:** `"error": "Service account is not authorized"`
- The service account email is not shared with the Google Drive folder
- Go to Google Drive folder → Share → Add the service account email

---

### **Issue: Backups Created but Not in Google Drive**

**Problem:** Local backups exist but don't appear in Google Drive

**Check Backup Log:**
1. Click **Backup** → **View History**
2. Look at the latest backup:
   - If **Destination** is `local` → Google Drive was disabled when backup ran
   - If **Destination** is `gdrive` but **Status** is `partial` → Check **Error Message**

**Solutions:**
1. Re-enable Google Drive
2. Test connection again
3. Run **"Backup Now"** again
4. Check logs for error details

---

### **Issue: Files Upload but Can't Find Folder**

**Problem:** Backups are uploading but folder path is wrong

**Solution:**
1. In Google Drive, find your backup folder
2. Click on folder name
3. Look at the URL: `https://drive.google.com/drive/folders/[THIS_IS_FOLDER_ID]`
4. Copy the folder ID (long alphanumeric string)
5. Update in Backup Settings
6. Run test again

---

## 📊 What Gets Backed Up

Every backup includes:
- ✅ All users and login history
- ✅ All products and inventory
- ✅ All purchase orders and items
- ✅ All sales invoices and items
- ✅ All returns and adjustments
- ✅ Customer credit information
- ✅ Supplier transactions
- ✅ License data
- ✅ All settings

---

## 🔒 Security

**Important Security Notes:**

1. **Service Account JSON is Sensitive:**
   - Don't share the JSON file
   - Regenerate the key if leaked
   - The JSON is stored encrypted in the database

2. **Google Drive Folder:**
   - Only shared with service account (not your personal account)
   - Backups are stored in Google's secure cloud
   - You can download/restore anytime

3. **Database:**
   - Local backups are compressed (SQL.gz)
   - Can be deleted manually if storage is full
   - Old backups auto-delete based on retention policy (default: 30 days)

---

## 📋 Backup Configuration Checklist

- [ ] **Google Cloud Project Created**
- [ ] **Google Drive API Enabled**
- [ ] **Service Account Created**
- [ ] **JSON Key Downloaded**
- [ ] **Google Drive Folder Created**
- [ ] **Service Account Email Shared with Folder**
- [ ] **Folder ID Copied**
- [ ] **JSON Uploaded to TrintzPOS**
- [ ] **Google Drive Connection Test Passed**
- [ ] **Settings Saved**
- [ ] **Manual Backup Run Successfully**
- [ ] **File Appears in Google Drive**
- [ ] **Automatic Backup Enabled** (Optional)

---

## 🚀 Automated Backup Schedule

Once configured, backups will run automatically:

1. **Daily Backup:** Set time in **Backup Settings** (e.g., 2:00 AM)
2. **Local Storage:** Backup created in `backups/` folder
3. **Google Drive Upload:** If enabled, automatically uploads
4. **Retention Policy:** Old backups deleted after 30 days (configurable)

**Benefits:**
- ✅ No manual backup needed
- ✅ Redundant storage (local + Google Drive)
- ✅ Zero chance of data loss
- ✅ Restore from any point in time

---

## Summary

**To enable Google Drive backups:**

1. ✅ Create Google service account & JSON key
2. ✅ Share Google Drive folder with service account
3. ✅ Upload JSON to TrintzPOS backup settings
4. ✅ Test connection
5. ✅ Run manual backup to verify
6. ✅ Enable automatic daily backups

**Result:** Your database is backed up to Google Drive daily! 🎯
