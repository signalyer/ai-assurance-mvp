# Deployment Guide — Simple Single-Tenant Platform

**No Docker. No Kubernetes. Just Python + PostgreSQL.**

---

## Local Development

```bash
# 1. Clone and setup
git clone <repo>
cd ai-assurance-mvp

# 2. Create .env file
cp .env.example .env
# Edit .env with your API keys

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate encryption key (one-time)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add to .env as ENCRYPTION_KEY=...

# 5. Run dashboard
python dashboard.py

# 6. Run demos
python multi_domain_demo.py          # All domains
python run.py                         # With browser auto-open
```

Dashboard: **http://localhost:9007**

---

## Production Deployment (Linux Server)

### Prerequisites
- Ubuntu 22.04 LTS
- Python 3.12+
- PostgreSQL 15+ (or use managed service)

### Installation

```bash
# 1. SSH into server
ssh user@production-server

# 2. Clone repository
git clone <repo> /opt/ai-assurance
cd /opt/ai-assurance

# 3. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Setup database (if self-hosted)
sudo apt install postgresql
sudo -u postgres createdb ai_assurance
# Or use managed PostgreSQL (AWS RDS, Azure Database, etc.)

# 6. Configure environment
cp .env.example .env
# Edit: ANTHROPIC_API_KEY, OPENAI_API_KEY, DATABASE_URL, ENCRYPTION_KEY

# 7. Generate encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Run with Systemd (Recommended)

Create `/etc/systemd/system/ai-assurance.service`:

```ini
[Unit]
Description=AI Assurance Platform
After=network.target

[Service]
Type=simple
User=ai-assurance
WorkingDirectory=/opt/ai-assurance
Environment="PATH=/opt/ai-assurance/venv/bin"
ExecStart=/opt/ai-assurance/venv/bin/python dashboard.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Then:

```bash
# Create user
sudo useradd -m -d /opt/ai-assurance ai-assurance
sudo chown -R ai-assurance:ai-assurance /opt/ai-assurance

# Enable service
sudo systemctl enable ai-assurance
sudo systemctl start ai-assurance

# Check status
sudo systemctl status ai-assurance

# View logs
sudo journalctl -u ai-assurance -f
```

---

## With Nginx Reverse Proxy (HTTPS)

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://127.0.0.1:9007;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Install Let's Encrypt:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot certonly --nginx -d yourdomain.com
```

---

## Environment Variables

Required:
```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk_...
LANGFUSE_SECRET_KEY=sk_...
ENCRYPTION_KEY=...  # From: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Optional:
```
DATABASE_URL=postgresql://user:pass@localhost/ai_assurance  # If not using default
LOG_LEVEL=INFO
PORT=9007
```

---

## Database Setup

### Option A: Local PostgreSQL
```bash
sudo apt install postgresql
sudo -u postgres psql

CREATE DATABASE ai_assurance;
CREATE USER ai_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE ai_assurance TO ai_user;
```

### Option B: Managed Service
- **AWS RDS:** Create PostgreSQL instance, note endpoint
- **Azure Database for PostgreSQL:** Create instance, get connection string
- **DigitalOcean:** Create Managed Database

Update `.env`:
```
DATABASE_URL=postgresql://user:password@endpoint:5432/ai_assurance
```

---

## Monitoring

### View logs
```bash
# Systemd logs
sudo journalctl -u ai-assurance -f

# Application logs
tail -f audit.log
```

### Check health
```bash
curl https://yourdomain.com/api/health
```

### Expected response:
```json
{
  "status": "ready",
  "api_keys": {
    "ANTHROPIC_API_KEY": true,
    "OPENAI_API_KEY": true,
    "LANGFUSE": true
  }
}
```

---

## Backup & Maintenance

### Backup database
```bash
pg_dump ai_assurance > backup.sql
# Or with systemd timer for daily backups
```

### Rotate logs
```bash
# Logrotate config: /etc/logrotate.d/ai-assurance
/var/log/ai-assurance/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
}
```

### Update application
```bash
cd /opt/ai-assurance
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart ai-assurance
```

---

## Security Checklist

- [ ] `.env` file restricted to owner only: `chmod 600 .env`
- [ ] Database password in `.env`, not in code
- [ ] Encryption key stored securely (not in git)
- [ ] HTTPS enabled (Let's Encrypt)
- [ ] Firewall allows only 80, 443
- [ ] SSH key-based auth only
- [ ] Audit logs enabled
- [ ] Regular backups configured
- [ ] Updates applied monthly

---

## Troubleshooting

**Port already in use:**
```bash
lsof -i :9007
kill -9 <PID>
```

**Database connection error:**
```bash
# Check DATABASE_URL in .env
# Test connection:
psql $DATABASE_URL
```

**Encryption key error:**
```bash
# Regenerate and update .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## That's it.

No Docker complexity, no DevOps overhead. Just:
1. Install Python
2. Set env vars
3. Run: `python dashboard.py`
4. Optionally: Put behind Nginx + Let's Encrypt

**Ready for production.**
