# Server Environment Setup Guide

This guide covers how to set up the telemetry API server and HTTPS static file hosting from scratch on a GCP VM (or any Linux machine with a public IP).

## Prerequisites

- Linux VM with a public IPv4 address
- Python 3 installed
- Root/sudo access (required for ports 80 and 443)

## 1. Clone the Repository

```bash
git clone https://github.com/geeningwang/llm-ondevice-server.git
cd llm-ondevice-server
```

## 2. Prepare the Static Files Directory

```bash
mkdir -p www
```

Download weight files into `www/` (see [weights_recovery.md](weights_recovery.md) for the full list).

## 3. Start the HTTP Static File Server (Port 80)

```bash
cd www
sudo bash -c 'nohup python3 -m http.server 80 > /dev/null 2>&1 &'
```

## 4. Set Up HTTPS with a Trusted Certificate

### 4.1 Install certbot

```bash
sudo apt-get update && sudo apt-get install -y certbot
```

### 4.2 Obtain a Let's Encrypt Certificate

Since raw IP addresses cannot get CA-signed certificates, use [nip.io](https://nip.io) to map your IP to a domain name. Replace `<YOUR_IP>` with your VM's public IPv4 address:

```bash
# Ensure port 80 is free (stop the HTTP server temporarily)
sudo kill $(pgrep -f 'http.server 80')

# Request the certificate
sudo certbot certonly --standalone \
  -d <YOUR_IP>.nip.io \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email

# Restart the HTTP server
cd www
sudo bash -c 'nohup python3 -m http.server 80 > /dev/null 2>&1 &'
```

The certificate and key will be stored at:
- `/etc/letsencrypt/live/<YOUR_IP>.nip.io/fullchain.pem`
- `/etc/letsencrypt/live/<YOUR_IP>.nip.io/privkey.pem`

### 4.3 Update `https_server.py`

Edit the `CERT_PATH` and `KEY_PATH` constants in `https_server.py` to match your domain:

```python
CERT_PATH = '/etc/letsencrypt/live/<YOUR_IP>.nip.io/fullchain.pem'
KEY_PATH = '/etc/letsencrypt/live/<YOUR_IP>.nip.io/privkey.pem'
```

Also update `WEB_ROOT` and `DB_PATH` if your project directory differs from the default.

### 4.4 Start the HTTPS Server (Port 443)

```bash
sudo bash -c 'nohup python3 https_server.py > /dev/null 2>&1 &'
```

## 5. Database

No manual setup is needed. The SQLite database (`telemetry.db`) is created automatically in the project root when `https_server.py` starts for the first time. The schema (sessions and samples tables) is initialized by the `init_db()` function on startup.

## 6. Verify

```bash
# HTTP static file
curl -s -o /dev/null -w "%{http_code}" http://<YOUR_IP>/gemma3-1b-it-int4.task -r 0-1023

# HTTPS static file
curl -s -o /dev/null -w "%{http_code}" https://<YOUR_IP>.nip.io/gemma3-1b-it-int4.task -r 0-1023

# Telemetry API
curl -s https://<YOUR_IP>.nip.io/api/telemetry/sessions
```

## 7. Certificate Renewal

Let's Encrypt certificates expire after 90 days. Renew with:

```bash
# Stop servers on 80/443 temporarily
sudo kill $(pgrep -f 'http.server 80')
sudo fuser -k 443/tcp

# Renew
sudo certbot renew

# Restart servers
cd www
sudo bash -c 'nohup python3 -m http.server 80 > /dev/null 2>&1 &'
sudo bash -c 'nohup python3 https_server.py > /dev/null 2>&1 &'
```

## 8. Stopping the Servers

```bash
sudo kill $(pgrep -f 'http.server 80')    # HTTP
sudo fuser -k 443/tcp                      # HTTPS + API
```

## Server Architecture

```
Port 80  (HTTP)  → Python http.server → www/ (static weight files only)
Port 443 (HTTPS) → https_server.py    → www/ (static files) + /api/* (telemetry API)
                                       → telemetry.db (SQLite, outside web root)
```
