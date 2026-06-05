# How OAuth Works - Simple Explanation

## 🎯 Your Question

**"Can I get files on this folder with scheduled backup?"**

**Answer: YES! ✅** 

Here's exactly how it works:

---

## 📊 The Complete Flow (Step by Step)

### **Step 1: You Authorize Once**

```
You (Admin)
    ↓
Click "Authorize with Google" button
    ↓
Google login page appears
    ↓
You grant permission: "TrintzPOS can access my Google Drive"
    ↓
Permission granted ✅
```

**Result:** TrintzPOS gets a special token (like a permanent key) to access your Google Drive

---

### **Step 2: Token Gets Stored Securely**

```
Google gives TrintzPOS:
├─ Access Token (temporary, expires in ~1 hour)
├─ Refresh Token (permanent, used to get new access tokens)
└─ User Email (for reference)

TrintzPOS stores in database:
├─ Encrypted tokens
├─ Your email
└─ Expiry time
```

**Result:** TrintzPOS can now access your Google Drive anytime without asking again

---

### **Step 3: Scheduled Backup Runs**

```
Time: 2:00 AM (your scheduled time)
    ↓
System checks: Is token expired?
    ├─ If expired → Refresh token (automatic)
    └─ If fresh → Use as-is
    ↓
Create database backup file
    ↓
Upload to YOUR Google Drive folder
    ↓
File appears in the folder ✅
```

**Result:** Backup automatically saves to your folder every day

---

## 🎬 Visual Timeline

```
Day 1 (2:00 AM):
  Backup starts
  ├─ Create: trintzpos_backup_20260605_020000.sql.gz
  ├─ Upload to: https://drive.google.com/drive/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
  └─ ✅ File appears in folder
    
Day 2 (2:00 AM):
  Backup starts again
  ├─ Create: trintzpos_backup_20260606_020000.sql.gz
  ├─ Token refreshed automatically (if expired)
  ├─ Upload to SAME folder
  └─ ✅ Another file in folder
    
Day 3, 4, 5... (2:00 AM):
  Same thing repeats
  └─ ✅ Daily backups accumulate in folder
```

---

## 🔄 How Token Refresh Works

### **When Token is About to Expire**

```
Token Status Check:
├─ Created: 10:00 AM
├─ Expires: 11:00 AM (1 hour)
├─ Current time: 10:55 AM
├─ Time until expiry: 5 minutes
    
System thinks: "Better refresh before it expires"
    ↓
Refresh happens automatically (no user action)
    ↓
New token received: 11:00 AM
├─ New access token
├─ Same refresh token
└─ New expiry: 12:00 PM
    ↓
Backup continues using new token ✅
```

**Result:** User never needs to login again!

---

## 📂 Your Google Drive Folder

### **Before OAuth Setup**
```
Google Drive Folder
└─ Empty
   ├─ (nothing here)
   └─ (waiting for backups)
```

### **After Setup (Day 1)**
```
Google Drive Folder: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
├─ trintzpos_backup_20260605_020000.sql.gz (250 MB)
└─ (more files added tomorrow)
```

### **After Setup (Day 7)**
```
Google Drive Folder: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
├─ trintzpos_backup_20260605_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260606_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260607_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260608_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260609_020000.sql.gz (250 MB)
├─ trintzpos_backup_20260610_020000.sql.gz (250 MB)
└─ trintzpos_backup_20260611_020000.sql.gz (250 MB)
```

**Result:** Week of backups, all in YOUR Google Drive!

---

## 🔐 Security at Each Step

### **Step 1: Authorization**
```
Google asks you: "Let TrintzPOS access your Drive?"
You: "Yes, I authorize"

Security: Google verifies it's really you
├─ Password check ✅
├─ 2FA if enabled ✅
└─ Only you can grant permission ✅
```

### **Step 2: Token Storage**
```
TrintzPOS stores token in database:
├─ Location: PostgreSQL database
├─ Encryption: Encrypted at rest
├─ Access: Admin-only
└─ Logging: All access is logged

Security:
├─ Only TrintzPOS can use token ✅
├─ Not exposed in logs ✅
├─ Not accessible via API ✅
└─ Can be revoked anytime ✅
```

### **Step 3: Automatic Upload**
```
Scheduled backup runs:
├─ Creates temporary backup file
├─ Uses token to upload to YOUR folder
├─ Deletes temporary file
└─ Logs the action

Security:
├─ Only authenticated with YOUR token ✅
├─ File only goes to YOUR folder ✅
├─ Token automatically refreshes ✅
└─ Zero manual interaction needed ✅
```

---

## 📋 Setup Steps (To Make This Work)

### **1. One-Time Authorization** (2 minutes)
```
Admin visits TrintzPOS → Backup Settings
          ↓
Click "Authorize with Google"
          ↓
Google login page opens
          ↓
Grant permission
          ↓
Window closes automatically ✅
Done! (never need to login again)
```

### **2. Configure Settings** (1 minute)
```
Backup Settings:
├─ Enable automatic backups: ON
├─ Backup time: 2:00 AM
├─ Folder ID: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
└─ Save ✅
```

### **3. Files Appear Automatically** (Ongoing)
```
Every day at 2:00 AM:
├─ Backup creates SQL file
├─ Uploads to your folder
├─ Token refreshes if needed
└─ Done ✅ (no manual work)
```

---

## 🎯 What Happens Behind the Scenes

### **When You Authorize**

```
TrintzPOS                Google                       You
    |                      |                          |
    |--[Authorize]-------->|                          |
    |                      |--[Send to login]-------->|
    |                      |                          |--[Login]
    |                      |<-[Grant permission]------|
    |<--[Token response]----|                          |
    |                      |                          |
```

### **When Backup Runs (Every Day)**

```
TrintzPOS                Google Drive                 Your Folder
    |                      |                          |
Backup created
    |                      |                          |
    |--[Check token]      |                          |
    |  (still valid?)      |                          |
    |                      |                          |
    |--[Upload file with token]                       |
    |                      |--[Save to folder]------->|
    |<--[File saved]-------|                          |
    |                      |                          |
Log complete ✅            |                          |
```

---

## 💾 Your Folder Gets These Files

### **File Structure**
```
Folder: TrintzPOS Backups (1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E)
│
├─ 2026-06-05 → trintzpos_backup_20260605_020000.sql.gz
├─ 2026-06-06 → trintzpos_backup_20260606_020000.sql.gz
├─ 2026-06-07 → trintzpos_backup_20260607_020000.sql.gz
├─ 2026-06-08 → trintzpos_backup_20260608_020000.sql.gz
├─ 2026-06-09 → trintzpos_backup_20260609_020000.sql.gz
├─ 2026-06-10 → trintzpos_backup_20260610_020000.sql.gz
└─ 2026-06-11 → trintzpos_backup_20260611_020000.sql.gz

Total: ~1.75 GB (7 days × 250 MB)
```

### **Retention**
```
By default: Keep last 30 days of backups
├─ 30 days × 250 MB = 7.5 GB needed
├─ Google Drive free = 15 GB (so you have room)
└─ Old backups auto-delete after 30 days

You can configure:
├─ Retention period (30, 60, 90 days)
├─ Manual backup also available
└─ You can download any backup anytime
```

---

## ✅ Once Set Up, It Just Works!

### **Admin Perspective**
```
Day 1:
├─ Click "Authorize with Google" ← Only thing you do
├─ Grant permission ← Only thing you do
├─ Set backup time to 2:00 AM ← Only thing you do
├─ Save settings ← Only thing you do
└─ Done! ✅

Days 2, 3, 4, ... 365:
└─ Backups run automatically, every day ✅
   (No admin action needed)
```

### **System Perspective**
```
Every Day at 2:00 AM:
├─ Check if token is valid
├─ Refresh if expired (automatic)
├─ Create backup file
├─ Upload to folder
├─ Log success
├─ Delete temp file
└─ Done ✅

Repeat next day...
```

---

## 🎯 Your Exact Scenario

**Your folder:** `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`

### **What Happens**

```
STEP 1: Authorization (One time)
  You → Click "Authorize with Google"
     → Google login
     → Grant permission
     ✅ TrintzPOS can now access this folder

STEP 2: Configuration (One time)
  You → Enter folder ID: 1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E
     → Set backup time: 2:00 AM
     → Enable automatic backups
     ✅ Settings saved

STEP 3: Automated (Every day)
  2:00 AM: Backup starts
     → Creates database backup
     → Uses OAuth token (auto-refreshed if needed)
     → Uploads to YOUR folder
     ✅ File appears in folder

STEP 4: Repeat (Every day)
  2:01 AM: Log cleanup
     ✅ Backup complete, ready for tomorrow
```

---

## 📊 Timeline Example

```
2026-06-05 02:00 AM:
  Backup #1 created → Uploaded ✅
  
2026-06-06 02:00 AM:
  Backup #2 created → Token auto-refreshed → Uploaded ✅
  
2026-06-07 02:00 AM:
  Backup #3 created → Uploaded ✅
  
... (continues daily)

2026-07-05 02:00 AM:
  Backup #30 created → Uploaded ✅
  Backup #1 deleted (30-day retention)
  
... (continues forever)
```

---

## 🔄 Token Refresh (Behind the Scenes)

```
When token needs refresh:
├─ System checks: "Is token about to expire?"
├─ If yes: "Let me refresh before it expires"
│   └─ Uses refresh token (permanent)
│   └─ Gets new access token
│   └─ Updates database
│   └─ Continues backup ✅
├─ If no: "Still valid, use as-is" ✅
└─ Backup continues → File uploads ✅
```

---

## Summary

**Your Question:** "Can I get files on this folder with scheduled backup?"

**Answer:** YES! ✅

**How:**
1. ✅ You authorize once (2 min)
2. ✅ System runs backups daily (automatic)
3. ✅ Files appear in YOUR Google Drive folder
4. ✅ Token refreshes automatically
5. ✅ Zero manual work after setup

**Result:**
- Files in your folder: `https://drive.google.com/drive/u/1/folders/1zjnwYo3OXgnpDDru6wOUXCnZ_XY8YG7E`
- Backups added daily at 2:00 AM
- 30-day retention (auto-cleanup)
- Download anytime you need
- No passwords stored
- No re-login ever needed

**Setup Time:** ~15 minutes
**Ongoing Work:** ZERO (it's automatic!)

🎯
