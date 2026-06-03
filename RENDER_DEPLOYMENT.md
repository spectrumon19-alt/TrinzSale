# TrintzPOS — Render.com Deployment Guide

## Quick Start

### Step 1: Push Code to GitHub
```bash
git add -A
git commit -m "Deploy TrintzPOS with P&L reports to Render"
git push origin main
```

### Step 2: Create Render Account
1. Go to https://render.com
2. Sign up with GitHub
3. Authorize Render to access your GitHub repositories

### Step 3: Create Web Service
1. Click **New +** → **Web Service**
2. Select your GitHub repository
3. Set the following:
   - **Name**: `trintzpos` (or your preferred name)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --preload wsgi:application`
   - **Plan**: Starter ($7/month) or Professional as needed

### Step 4: Configure Environment Variables
In Render dashboard, go to your service → **Environment** and add:

#### Required Variables
```
SECRET_KEY=e1f93fd05d6213d6ddf9cc449d0f535edb84f7a8cfda5e959ba6c908110ebf73
DB_HOST=pg-23a6e8b0-spectrumon19-21fe.j.aivencloud.com
DB_NAME=defaultdb
DB_USER=avnadmin
DB_PASSWORD=AVNS_bYDT-EsaWYcD_KSaO4O
DB_PORT=13430
```

#### Email Configuration (Brevo)
```
BREVO_API_KEY=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
BREVO_SENDER_EMAIL=spectrumon19@gmail.com
BREVO_SENDER_NAME=TrintzPOS Support
BREVO_SMTP_USER=aaa6fb001@smtp-brevo.com
BREVO_SMTP_PASSWORD=xsmtpsib-ce9e3ec480e6368ee757ec1cb07b965d3db8769a32ae664a0b86765ef4fd2238-YbqYgalqcq8MEgJg
```

### Step 5: Deploy
Click **Deploy** to start the deployment. Monitor the logs to ensure:
- ✅ Pre-deployment checks pass
- ✅ Dependencies install successfully
- ✅ Database migrations complete
- ✅ App starts without errors

---

## Pre-Deployment Checks

The `predeploy.py` script automatically:
1. **Validates environment variables** - Ensures all required vars are set
2. **Checks SECRET_KEY strength** - Warns if weak (but non-blocking)
3. **Tests database connection** - Verifies PostgreSQL is reachable
4. **Initializes database schema** - Runs `init_database.sql` if tables don't exist
5. **Verifies all tables** - Confirms all 18+ required tables are present

If any check fails, deployment is blocked.

---

## Post-Deployment

### Access Your App
Your app will be available at:
```
https://trintzpos.onrender.com
```
(Replace "trintzpos" with your service name)

### Initial Login
1. Go to `https://your-app.onrender.com/login.html`
2. Use default credentials (see `create_superadmin.py`)

### Monitor Logs
In Render dashboard → **Logs** tab, check:
- App startup status
- Any runtime errors
- Request metrics

---

## Features Deployed

✅ **Sales Management** - Invoice creation, tracking, reporting  
✅ **Inventory Management** - Stock levels, purchase orders  
✅ **License System** - RSA-2048 signing, hardware binding  
✅ **Reports** - Sales, inventory, **Profit & Loss with Excel export**  
✅ **Email Delivery** - Brevo SMTP for distribution packages  
✅ **Security** - Token-based auth, session management, license guard  

---

## Troubleshooting

### Deployment Fails: SECRET_KEY Not Set
**Fix**: Add `SECRET_KEY` to environment variables in Render dashboard
```
SECRET_KEY=e1f93fd05d6213d6ddf9cc449d0f535edb84f7a8cfda5e959ba6c908110ebf73
```

### Deployment Fails: Database Connection Error
**Fix**: Verify database credentials:
```
DB_HOST=pg-23a6e8b0-spectrumon19-21fe.j.aivencloud.com
DB_NAME=defaultdb
DB_USER=avnadmin
DB_PASSWORD=AVNS_bYDT-EsaWYcD_KSaO4O
DB_PORT=13430
```

### App Crashes After Deploy
**Fix**: Check logs in Render dashboard → Logs
- Look for import errors (missing dependencies)
- Check for database connection timeouts
- Verify environment variables are correctly set

### Email Not Sending
**Fix**: Verify Brevo credentials:
```
BREVO_API_KEY=xkeysib-...
BREVO_SENDER_EMAIL=spectrumon19@gmail.com
BREVO_SMTP_USER=aaa6fb001@smtp-brevo.com
BREVO_SMTP_PASSWORD=xsmtpsib-...
```

---

## Monitoring & Updates

### View App Health
```
Render Dashboard → Your Service → Metrics
```

### Check Request Performance
```
Render Dashboard → Your Service → Logs
```

### Update the App
1. Make changes locally and commit:
```bash
git add -A
git commit -m "Update: feature description"
git push origin main
```
2. Render automatically redeploys on push

---

## Scaling

### Increase Workers (Handle More Concurrent Users)
In `render.yaml`, increase workers:
```yaml
startCommand: gunicorn --bind 0.0.0.0:$PORT --workers 4 --timeout 120 --preload wsgi:application
```

### Upgrade Plan
```
Render Dashboard → Your Service → Settings → Instance Type
- Starter: $7/month (low traffic)
- Standard: $12/month (medium traffic)
- Pro: $29/month (high traffic)
```

---

## Security Best Practices

1. **Never commit secrets** - Use Render's environment variables, not `.env` files
2. **Enable HTTPS** - Render provides free SSL/TLS certificates
3. **Rotate API keys** - Change BREVO_API_KEY and BREVO_SMTP_PASSWORD regularly
4. **Use strong passwords** - Database passwords should be 20+ characters
5. **Monitor logs** - Check for unauthorized access attempts

---

## Support

For issues:
1. Check Render logs: `Render Dashboard → Logs`
2. Check pre-deployment script: `predeploy.py`
3. Verify all environment variables are set
4. Test database connection locally if possible

---

**Happy deploying!** 🚀
