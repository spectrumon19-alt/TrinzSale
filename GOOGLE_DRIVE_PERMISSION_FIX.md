# Google Drive Backup - Permission Fix

## 🔴 Error Analysis

**Error:** `File not found: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

**Cause:** The folder exists, but the **service account does NOT have permission** to access it.

This is a **sharing/permission issue**, not a folder ID issue.

---

## ⚠️ The Problem

When Google Drive says "File not found" for a service account upload, it actually means:
- ✅ The folder ID is correct
- ✅ The folder exists
- ❌ The service account email is **NOT** shared with the folder
- ❌ Or doesn't have **Editor** permissions

---

## ✅ Solution: Share Folder with Service Account

### **Step 1: Get Service Account Email**

1. Open your downloaded JSON file in a text editor
2. Look for the `client_email` field:
   ```json
   {
     "type": "service_account",
     "project_id": "trintzerp-backup-123",
     "private_key_id": "...",
     "private_key": "...",
     "client_email": "trintzerp-backup@trintzerp-backup-123.iam.gserviceaccount.com",  ← THIS ONE
     ...
   }
   ```
3. **Copy the `client_email` value**
   - Example: `trintzerp-backup@trintzerp-backup-123.iam.gserviceaccount.com`

---

### **Step 2: Share Folder with Service Account**

1. **Open Google Drive**
   - Go to https://drive.google.com

2. **Find Your Backup Folder**
   - Locate the folder ID: `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`
   - Right-click the folder → **Share**
   - Or click folder → Click **Share** button at top

3. **Add Service Account Email**
   - In the "Share" dialog, paste the service account email
   - Example: `trintzerp-backup@trintzerp-backup-123.iam.gserviceaccount.com`
   - Press Enter/Tab to add

4. **Set Permission Level**
   - Click on the permission dropdown (shows "Viewer" by default)
   - Change to **"Editor"** (service account needs write access)
   - Click **Share**

5. **Confirm Sharing**
   - You should see the service account email listed with "Editor" access
   - Close the share dialog

---

## 🔍 Verify Sharing is Correct

### **Check 1: Google Drive Folder Permissions**
1. Open the backup folder in Google Drive
2. Click the **Share** button
3. You should see:
   ```
   trintzerp-backup@trintzerp-backup-123.iam.gserviceaccount.com
   Editor access
   ```

If you don't see this, go back to **Step 2** and add it again.

### **Check 2: Test Connection in TrintzERP**
1. Go to **TrintzERP Backup Settings**
2. Click **"Test Google Drive Connection"** button
3. Should see: ✅ Connected successfully
4. If it fails, re-check sharing and refresh

---

## 🚀 How to Fix (Step-by-Step)

### **For Your Folder `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`:**

1. **Get Service Account Email from JSON**
   - Extract `client_email` from your JSON file
   - Copy it exactly (including the @...iam.gserviceaccount.com part)

2. **Go to Google Drive**
   - Link: https://drive.google.com
   - Search for folder `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`
   - Or navigate to it manually

3. **Share with Service Account**
   - Right-click folder → Share
   - Paste service account email
   - Change permission to **Editor**
   - Click Share

4. **Test in TrintzERP**
   - Go to Backup Settings
   - Click "Test Google Drive Connection"
   - Should pass ✅

5. **Run Backup**
   - Click "Backup Now"
   - Should upload successfully ✅

---

## 🆘 Troubleshooting

### **Issue: "File not found" still appears after sharing**

**Solutions:**
1. **Wait 30 seconds** - Google Drive takes time to sync permissions
2. **Refresh page** - Reload TrintzERP in browser
3. **Test again** - Click "Test Google Drive Connection" button
4. **Verify sharing:**
   - Go to Google Drive folder
   - Click Share
   - Confirm service account email is listed with "Editor" access

### **Issue: "User doesn't exist" when adding service account email**

**Problem:** The email format is wrong

**Solution:**
1. Re-check the JSON file `client_email` field
2. Make sure you're copying the entire email (e.g., `xxx@xxx.iam.gserviceaccount.com`)
3. Don't include any extra spaces or characters
4. Try again

### **Issue: Can't find the backup folder in Google Drive**

**Problem:** You don't have access to it or it's in a different account

**Solution:**
1. Make sure you're logged into the correct Google account
2. Go to https://drive.google.com
3. Search for folder ID: `1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`
4. If not found, the folder might have been deleted
   - Create a new folder
   - Get its ID from URL
   - Update in TrintzERP Backup Settings

---

## 📋 Permission Checklist

Before running backup, verify:

- [ ] Service account JSON file downloaded from Google Cloud Console
- [ ] `client_email` extracted from JSON file
- [ ] Google Drive backup folder exists
- [ ] Service account email is shared with folder (Right-click → Share)
- [ ] Permission is set to **"Editor"** (not "Viewer" or "Commenter")
- [ ] "Test Google Drive Connection" passes ✅
- [ ] Backup folder ID matches in TrintzERP settings

---

## 🎯 Common Mistakes

❌ **Mistake 1:** Shared folder with wrong email
- **Fix:** Copy the exact `client_email` from JSON file

❌ **Mistake 2:** Set permission to "Viewer" instead of "Editor"
- **Fix:** Change to "Editor" - service account needs write access

❌ **Mistake 3:** Shared with personal account instead of service account
- **Fix:** Share with the service account email (ends in `.iam.gserviceaccount.com`)

❌ **Mistake 4:** Didn't wait for permissions to sync
- **Fix:** Wait 30 seconds, then test again

❌ **Mistake 5:** Wrong folder shared
- **Fix:** Verify folder ID matches in TrintzERP settings

---

## Summary

**The Fix in 3 Steps:**

1. **Extract** service account email from JSON file
2. **Share** Google Drive folder with that email (Editor access)
3. **Test** connection in TrintzERP → Should work ✅

**Most Common Cause:** Forgot to share folder with service account email!

---

## 📞 If Still Not Working

If you've followed all steps and still get 404 error:

1. Confirm the error is still: `File not found: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`
2. Verify sharing is correct in Google Drive
3. Check that "Test Google Drive Connection" passes
4. Try running backup again

If error persists, you might need to:
- Create a new Google Drive folder
- Generate a new service account in Google Cloud Console
- Re-upload the new JSON to TrintzERP
- Test connection and run backup

---

## ✅ Expected Result

After fixing permissions:

```
✅ Test Google Drive Connection: PASS
✅ Backup Now: Completes successfully
✅ Destination: gdrive
✅ Status: success
✅ File appears in Google Drive folder
```

You're 99% done! Just need to share the folder with the service account. 🎯
