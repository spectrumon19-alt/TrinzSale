# Google Drive Permission Levels - Critical Fix

## 🔴 Current Problem

✅ **Connection Test:** PASSED
```
Connected as trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
```

❌ **Backup Upload:** FAILED
```
File not found: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
```

**Why:** Service account has **READ** access but NOT **WRITE** access

---

## 🎯 The Solution: Change Permission to "Editor"

### **Current Permission (Wrong)**
```
trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
├─ Viewer         ← ❌ Can only READ, NOT write
```

### **Required Permission (Correct)**
```
trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
├─ Editor         ← ✅ Can READ and WRITE
```

---

## 📋 Step-by-Step Fix

### **Step 1: Go to Google Drive**
- Open https://drive.google.com
- Find your backup folder

### **Step 2: Open Share Dialog**
- Right-click the folder
- Click **Share**
- Or click the folder and click **Share** button at top

### **Step 3: Find the Service Account**
You should see:
```
trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
Viewer  ← This is the problem
```

### **Step 4: Change Permission**
1. Click on **"Viewer"** (the permission dropdown)
2. Select **"Editor"** from the dropdown
3. You should see:
```
trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
Editor  ← ✅ Fixed!
```

### **Step 5: Save**
- Click **Share** or close the dialog
- Permission is now updated

---

## ⏱️ Wait for Sync

After changing permission:
1. **Wait 30 seconds** - Google Drive needs time to propagate the change
2. Go back to TrintzPOS
3. Click **"Test Google Drive Connection"** again
4. Should still show: ✅ Connected
5. Click **"Backup Now"**
6. Should now upload successfully ✅

---

## 🔐 Permission Levels Explained

### **Viewer** ❌
- Can download files
- Can view folder contents
- **CANNOT create files** ❌
- **CANNOT upload files** ❌
- **CANNOT modify files** ❌

### **Commenter** ⚠️
- Can view files
- Can add comments
- **CANNOT create files** ❌
- **CANNOT upload files** ❌

### **Editor** ✅
- Can view files
- Can create files
- Can upload files ✅
- Can modify files ✅
- Can delete files ✅
- **This is what you need!**

---

## 📸 Visual Guide

**In Google Drive Share Dialog:**

```
Your name (Owner)
├─ Owner

trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
├─ [Dropdown showing "Viewer"]  ← Click here
   ├─ Viewer
   ├─ Commenter
   ├─ Editor  ← Select this
   └─ Remove access
```

---

## ✅ Verification

After changing to "Editor":

### **Check 1: Google Drive Folder**
Open folder → Click Share → Verify:
```
trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com
Editor ✅
```

### **Check 2: TrintzPOS Test**
1. Go to Backup Settings
2. Click "Test Google Drive Connection"
3. Should show: ✅ Connected successfully

### **Check 3: Run Backup**
1. Click "Backup Now"
2. Wait for completion
3. Check backup logs:
   - **Status:** `success` ✅
   - **Destination:** `gdrive` ✅
   - **File ID:** (alphanumeric) ✅

### **Check 4: Verify in Google Drive**
1. Go to your Google Drive backup folder
2. Should see file: `trintzpos_backup_YYYYMMDD_HHMMSS.sql.gz` ✅

---

## 🆘 Troubleshooting

### **Problem: Can't find the dropdown to change permission**
**Solution:** 
1. Make sure you're looking at the service account row
2. Look for the permission level on the right side of the email
3. Click on it to see dropdown options

### **Problem: Still get 404 error after changing to Editor**
**Solution:**
1. Wait another 30 seconds for Google Drive to sync
2. Refresh TrintzPOS page
3. Click "Test Google Drive Connection" again
4. Run backup again

### **Problem: The service account isn't in the share list**
**Solution:**
1. You might have added it with wrong email
2. Go back to "Share"
3. Remove the wrong entry
4. Add again with correct email: `trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com`
5. Make sure to select **"Editor"**

---

## 🎯 Summary

**Current State:**
- ✅ Service account email is correct
- ✅ Service account can access Google Drive (test passed)
- ❌ Service account doesn't have WRITE permission
- ❌ Backup can't create files in folder

**The Fix:**
1. Open folder in Google Drive
2. Right-click → Share
3. Find: `trintzserviceaccount@trintzsqlbkppostgresql.iam.gserviceaccount.com`
4. Change from **"Viewer"** to **"Editor"**
5. Wait 30 seconds
6. Run backup again ✅

**Expected Result:**
- Backup uploads to Google Drive
- File appears in folder
- Status shows `success` with `destination: gdrive`

---

## ⏱️ Time to Fix: 2 Minutes

1. Change permission (1 min)
2. Wait for sync (30 sec)
3. Run backup (30 sec)

That's it! 🎯
