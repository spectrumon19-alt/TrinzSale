# TrintzPOS Render Deployment Checklist

## Pre-Deployment (Local)
- [ ] All code changes committed and pushed to GitHub
- [ ] `.env` file has valid `SECRET_KEY` (not placeholder)
- [ ] `requirements.txt` is up-to-date with all dependencies
- [ ] `predeploy.py` is in root directory
- [ ] `render.yaml` is properly configured
- [ ] `wsgi.py` exists and is correct
- [ ] `init_database.sql` exists in root directory
- [ ] No hardcoded secrets in code (all in environment variables)

## Render Configuration
- [ ] GitHub account connected to Render
- [ ] Repository is public or Render has access
- [ ] Web service created in Render
- [ ] Repository connected to service
- [ ] Build/start commands are correct

## Environment Variables (Set in Render Dashboard)
### Essential
- [ ] `SECRET_KEY` = e1f93fd05d6213d6ddf9cc449d0f535edb84f7a8cfda5e959ba6c908110ebf73
- [ ] `PYTHON_VERSION` = 3.11.0
- [ ] `LICENSE_GUARD_ENABLED` = false

### Database (PostgreSQL)
- [ ] `DB_HOST` = pg-23a6e8b0-spectrumon19-21fe.j.aivencloud.com
- [ ] `DB_NAME` = defaultdb
- [ ] `DB_USER` = avnadmin
- [ ] `DB_PASSWORD` = AVNS_bYDT-EsaWYcD_KSaO4O
- [ ] `DB_PORT` = 13430

### Email (Brevo)
- [ ] `BREVO_API_KEY` = xkeysib-...
- [ ] `BREVO_SENDER_EMAIL` = spectrumon19@gmail.com
- [ ] `BREVO_SENDER_NAME` = TrintzPOS Support
- [ ] `BREVO_SMTP_USER` = aaa6fb001@smtp-brevo.com
- [ ] `BREVO_SMTP_PASSWORD` = xsmtpsib-...

## Deployment
- [ ] Click "Deploy" in Render dashboard
- [ ] Monitor build logs
- [ ] Wait for deployment to complete
- [ ] Check that pre-deployment checks passed
- [ ] Verify database initialization completed

## Post-Deployment Verification
- [ ] App is accessible at https://your-service.onrender.com
- [ ] Login page loads (no 500 errors)
- [ ] Login works with correct credentials
- [ ] Dashboard loads without errors
- [ ] Reports section works
  - [ ] P&L Report generates data
  - [ ] Export to Excel downloads file
  - [ ] Daily breakdown sheet present
- [ ] License system works
  - [ ] License activation page accessible
  - [ ] License verification works
- [ ] Email sending works (if tested)
  - [ ] License packages can be emailed
  - [ ] Emails arrive at destination

## Monitoring
- [ ] Set up Render alerts (optional)
- [ ] Check logs regularly for errors
- [ ] Monitor app performance metrics
- [ ] Set up error tracking (optional)

## Quick Reference

### Render Dashboard Links
- Service: https://dashboard.render.com/web/[service-id]
- Logs: Click "Logs" tab in service
- Settings: Click "Settings" in service
- Environment: Click "Environment" in service

### Useful Commands (Local)
```bash
# Test SECRET_KEY strength
python -c "print(len('e1f93fd05d6213d6ddf9cc449d0f535edb84f7a8cfda5e959ba6c908110ebf73'))"
# Should be >= 32

# Check requirements.txt is valid
pip install -r requirements.txt

# Run predeploy checks locally
python predeploy.py
```

## Common Issues & Fixes

| Issue | Solution |
|-------|----------|
| SECRET_KEY not set | Add to Render environment variables |
| Database connection fails | Verify DB_HOST, DB_USER, DB_PASSWORD |
| Pre-deploy check fails | Check logs, verify all env vars set |
| 502 Bad Gateway | Check app logs, increase timeout, check memory |
| App crashes on startup | Check requirements.txt, verify imports |
| Email not sending | Verify Brevo credentials, check logs |

---

**Status**: ✅ Ready to Deploy
**Files Required**: ✅ All present
**Config**: ✅ Updated with P&L features
**Environment**: ✅ Configured for Render
