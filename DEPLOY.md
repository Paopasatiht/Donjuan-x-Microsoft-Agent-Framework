# Deploy Don Juan Agent v2 — Hostinger VPS

**Target URL:** `https://sprintai.cloud/dj_project`

---

## สิ่งที่ต้องมีบน Server

- Ubuntu 22.04+ (Hostinger VPS)
- Docker + Docker Compose
- Nginx (reverse proxy)
- Domain `sprintai.cloud` ชี้มาที่ VPS แล้ว + SSL (Let's Encrypt)

---

## Step 1: SSH เข้า Server

```bash
ssh root@sprintai.cloud
```

## Step 2: ติดตั้ง Docker (ถ้ายังไม่มี)

```bash
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin
```

## Step 3: Upload โปรเจค

จากเครื่อง Mac:

```bash
# สร้าง folder บน server
ssh root@sprintai.cloud "mkdir -p /opt/dj_project"

# rsync ขึ้นไป (ไม่รวม .git, __pycache__, .env)
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.env' \
  /Volumes/INVADER_DB/Claude_Space/SPRINT/Donjuan/Donjuan-x-Microsoft-Agent-Framework/ \
  root@sprintai.cloud:/opt/dj_project/
```

## Step 4: สร้าง .env บน Server

```bash
ssh root@sprintai.cloud
cd /opt/dj_project

cat > .env << 'EOF'
# OpenAI
OPENAI_API_KEY=sk-proj-ใส่-key-จริง-ตรงนี้
OPENAI_MODEL=gpt-4o-mini

# Redis
REDIS_URL=redis://redis:6379

# Cost control
MONTHLY_BUDGET_USD=50
DAILY_QUOTA_PER_USER=20
MAX_RESPONSE_TOKENS=600

# Admin
ADMIN_API_KEY=paopow

# Deployment — ต้องตรงกับ path ที่ Nginx proxy_pass
ROOT_PATH=/dj_project

# OpenTelemetry (optional)
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_SERVICE_NAME=dj-agent-v2
EOF
```

> **สำคัญ:** `REDIS_URL=redis://redis:6379` ใช้ชื่อ service ใน docker-compose (ไม่ใช่ localhost)

## Step 5: Build & Run

```bash
cd /opt/dj_project
docker compose up -d --build
```

ตรวจสอบ:
```bash
# ดู logs
docker compose logs -f app

# ทดสอบ health (จากใน server)
curl http://localhost:8080/health
# → {"status":"ok","model":"gpt-4o-mini"}
```

## Step 6: ตั้งค่า Nginx Reverse Proxy

เพิ่ม config ใน Nginx (อาจอยู่ที่ `/etc/nginx/sites-available/sprintai.cloud` หรือ `/etc/nginx/conf.d/`):

```nginx
# ── Don Juan Agent ──────────────────────────────
location /dj_project/ {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket support (ถ้าต้องใช้ในอนาคต)
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # Timeout สำหรับ LLM response ที่อาจช้า
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}
```

Test & reload:
```bash
nginx -t && systemctl reload nginx
```

## Step 7: ทดสอบ

```bash
# Health check
curl https://sprintai.cloud/dj_project/health

# หน้าเว็บ
# เปิด browser → https://sprintai.cloud/dj_project

# Admin dashboard
# เปิด browser → https://sprintai.cloud/dj_project/admin
# ใส่รหัส: paopow

# ทดสอบ chat API
curl -X POST https://sprintai.cloud/dj_project/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test_user","message":"สวัสดีครับ"}'
```

---

## โครงสร้าง URL

| URL | หน้าที่ |
|-----|--------|
| `sprintai.cloud/dj_project` | Landing page (aurora, animations) |
| `sprintai.cloud/dj_project/admin` | Admin login → dashboard |
| `sprintai.cloud/dj_project/health` | Health check API |
| `sprintai.cloud/dj_project/chat` | Chat API (POST) |
| `sprintai.cloud/dj_project/usage/{user_id}` | Quota check API |
| `sprintai.cloud/dj_project/admin/stats` | Admin stats API |
| `sprintai.cloud/dj_project/admin/users` | Admin user list API |

---

## การอัปเดต

```bash
# จากเครื่อง Mac — sync ไฟล์ใหม่ขึ้นไป
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.env' \
  /Volumes/INVADER_DB/Claude_Space/SPRINT/Donjuan/Donjuan-x-Microsoft-Agent-Framework/ \
  root@sprintai.cloud:/opt/dj_project/

# บน server — rebuild
ssh root@sprintai.cloud "cd /opt/dj_project && docker compose up -d --build"
```

---

## การดูแล

```bash
# ดู logs แบบ real-time
docker compose logs -f app

# restart
docker compose restart app

# ดู resource usage
docker stats

# ดู Redis data
docker compose exec redis redis-cli
> KEYS dj:*
> GET dj:cost:monthly:2026-04

# Jaeger traces (ถ้าเปิดใช้)
# http://sprintai.cloud:16686 (ควร bind localhost เท่านั้น)
```

---

## Cost Monitor

- Budget: **$50/เดือน**
- Model: gpt-4o-mini (~$0.0007/request)
- Auto-scaling:
  - spend < $30 → 20 คำถาม/วัน
  - spend > $30 → 15/วัน
  - spend > $40 → 10/วัน  
  - spend > $48 → 5/วัน
  - spend >= $50 → ปิดบริการอัตโนมัติ

ดูได้ที่ `https://sprintai.cloud/dj_project/admin` (รหัส: paopow)

---

## Security Checklist

- [x] Admin API ต้องใช้ `X-Admin-Key` header
- [x] Admin dashboard ต้องใส่รหัส
- [x] `.env` ไม่ได้ commit ลง git
- [x] CORS allow all (ปลอดภัยเพราะ API ไม่มี cookie auth)
- [ ] เปลี่ยน `ADMIN_API_KEY` จาก `paopow` เป็นอะไรที่แข็งแรงกว่า (ถ้าต้องการ)
- [ ] Jaeger UI ควร bind localhost เท่านั้น (อย่า expose port 16686)
