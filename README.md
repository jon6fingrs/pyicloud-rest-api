# pyicloud-rest-api

# 100% vibe-coded

A lightweight REST API wrapper around **pyicloud** that lets you trigger **Apple Find My → Play Sound** for your devices **on demand**, without continuous iCloud polling or battery drain.

This project was built specifically to replace the Home Assistant iCloud integration *only for the “find my phone” use‑case*, but it works anywhere you can make HTTP requests.

---

## 🚀 What This Solves

If you:
- want to say *“Hey Google, find Jon’s phone”*
- do **not** want constant iCloud location polling
- do **not** want massive iPhone battery drain
- only care about ringing devices when asked

…this is the correct tool.

---

## ✨ Features

- 🔔 Trigger **Find My → Play Sound** via REST
- 🔒 Token-based authentication
- 🧠 Persistent iCloud session with cookies
- 🔋 **Zero background polling**
- 🐳 Docker-first, stateless API
- 🏠 Native Home Assistant support
- 🗣️ Voice assistant friendly
- 🛑 Safe rate-limiting + cooldowns

---

## ❌ What This Is NOT

- ❌ Location tracking
- ❌ Device presence detection
- ❌ Continuous Find My polling
- ❌ A replacement for iCloud location services

This service does *one thing* well: **ring devices when asked**.

---

## 🧱 Architecture Overview

```
Voice Assistant / HA
        |
        v
Home Assistant rest_command
        |
        v
pyicloud-rest-api (Docker)
        |
        v
Apple Find My (on demand only)
```

Apple is contacted **only** when `/ring/*` is called.

---

## 🐳 Installation (Docker)

### 1. Clone the repo

```bash
git clone https://github.com/jon6fingrs/pyicloud-rest-api.git
cd pyicloud-rest-api
```

---

### 2. Create persistent storage

```bash
mkdir -p data/pyicloud
chmod -R 775 data
```

This stores:
- iCloud cookies
- trusted session tokens

Deleting this directory forces re-authentication.

---

### 3. Docker Compose (example)

```yaml
services:
  findmy-ring:
    container_name: findmy-ring
    build: .
    restart: unless-stopped

    # IMPORTANT: avoid root-owned cookie files
    user: "1000:100"

    environment:
      - ICLOUD_USERNAME=your_apple_id@gmail.com
      - ICLOUD_PASSWORD=your_apple_id_password
      - API_TOKEN=change-me-to-a-long-random-token

      - 'DEVICE_MAP_JSON={
        "jon_phone":"Jon\'s iPhone",
        "jon_ipad":"Jon\'s iPad",
        "jon_watch":"Jon\'s Apple Watch",
        etc
      }'

    volumes:
      - ./data/pyicloud:/data/pyicloud

    ports:
      - "8000:8000"
```

> ⚠️ Use **real Apple ID password**, not app‑specific passwords.

---

### 4. Build & run

```bash
docker compose up -d --build
```

---

## 🔐 Authentication Flow

### 1️⃣ Check auth status

```bash
curl -H "X-API-Token: YOUR_TOKEN" http://localhost:8000/auth/status
```

First run:
```json
{"requires_2fa":true,"requires_2sa":false}
```

---

### 2️⃣ Submit 2FA code

When Apple sends a verification code:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Token: YOUR_TOKEN" \
  -d '{"code":"123456"}' \
  http://localhost:8000/auth/2fa
```

Expected:
```json
{"ok":true,"message":"2FA accepted","trusted":true}
```

If `trusted` is `false`, Apple will expire the session quickly.

---

### 3️⃣ Verify authenticated

```bash
curl -H "X-API-Token: YOUR_TOKEN" http://localhost:8000/auth/status
```

```json
{"requires_2fa":false,"requires_2sa":false}
```

---

## 📱 List Devices

```bash
curl -H "X-API-Token: YOUR_TOKEN" http://localhost:8000/devices
```

Use the output to confirm **exact device names or IDs**.

---

## 🔔 Ring a Device

```bash
curl -X POST \
  -H "X-API-Token: YOUR_TOKEN" \
  http://localhost:8000/ring/jon_phone
```

Response:
```json
{"ok":true,"who":"jon_phone"}
```

---

## 🏠 Home Assistant Integration

### 1️⃣ Add `rest_command`

```yaml
rest_command:
  findmy_ring:
    url: "http://findmy-ring:8000/ring/{{ device_key }}"
    method: POST
    headers:
      X-API-Token: "change-me-to-a-long-random-token"
    timeout: 20
```

Restart Home Assistant.

---

### 2️⃣ Call from HA

Service: `rest_command.findmy_ring`

```yaml
device_key: jon_phone
```

---

### 3️⃣ Optional scripts (voice-friendly)

```yaml
script:
  find_jon_phone:
    alias: Find Jon's phone
    sequence:
      - service: rest_command.findmy_ring
        data:
          device_key: jon_phone

  find_lauren_phone:
    alias: Find Jon's ipad
    sequence:
      - service: rest_command.findmy_ring
        data:
          device_key: jon_ipad
```

Expose scripts to Google Assistant / Alexa / Assist.

---

## 🔁 Re-authentication Behavior

- No background traffic
- No polling
- No battery drain
- Apple may invalidate sessions every **weeks to months**
- When expired:
  - `/ring/*` returns **HTTP 409**
  - Re-run `/auth/2fa`

---

## 🛡️ Security Notes

- Protect `API_TOKEN`
- Do not expose port 8000 publicly
- Prefer Docker internal networking

---

## 🧠 Design Philosophy

- One job, done well
- Explicit user intent
- Predictable failure
- Minimal Apple API exposure

---

## 📜 License

MIT License
