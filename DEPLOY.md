# Deploy Don Juan Agent v2 to Hostinger VPS

## Prerequisites
- VPS มี Docker + Docker Compose + Git + Nginx ติดตั้งแล้ว
- Domain `sprintai.cloud` ชี้มาที่ IP ของ VPS แล้ว
- มี SSH access เข้า VPS

---

## Step 1 — SSH เข้า VPS

```bash
ssh root@<your-vps-ip>
```

---

## Step 2 — Clone repo

```bash
cd /opt
git clone -b donjuan_v2 https://github.com/Paopasatiht/Donjuan-x-Microsoft-Agent-Framework.git dj_project
cd dj_project
```

---

## Step 3 — สร้าง .env

```bash
cp .env.example .env
nano .env
```

ใส่ค่าจริงทุกบรรทัด:

```env
OPENAI_API_KEY=sk-proj-ใส่-key-จริงตรงนี้
OPENAI_MODEL=gpt-4o-mini

REDIS_URL=redis://redis:6379

MONTHLY_BUDGET_USD=50
DAILY_QUOTA_PER_USER=20
MAX_RESPONSE_TOKENS=600

ADMIN_API_KEY=paopow

ROOT_PATH=/dj_project
```

> **หมายเหตุ:** `REDIS_URL` ต้องเป็น `redis://redis:6379` (ชื่อ service ใน docker-compose) ไม่ใช่ localhost

บันทึก: `Ctrl+O` → Enter → `Ctrl+X`

---

## Step 4 — Build และ Start container

```bash
docker compose build
docker compose up -d
```

ตรวจว่า container ขึ้นแล้ว:

```bash
docker compose ps
```

ต้องเห็น `Status: Up` ตรง service `app` และ `redis`

ดู log:

```bash
docker compose logs -f app
```

ต้องเห็นบรรทัดนี้แสดงว่า OK:

```
INFO: DJ Agent v2 ready!
INFO: Application startup complete.
```

กด `Ctrl+C` เพื่อออกจาก log

ทดสอบตรงๆ จาก server:

```bash
curl http://localhost:8080/dj_project/health
# ต้องได้: {"status":"ok","model":"gpt-4o-mini"}
```

---

## Step 5 — ตั้ง Nginx reverse proxy

เปิดไฟล์ config:

```bash
nano /etc/nginx/sites-available/sprintai
```

วางเนื้อหานี้ลงไป:

```nginx
server {
    listen 80;
    server_name sprintai.cloud;

    # Don Juan Agent — https://sprintai.cloud/dj_project
    location /dj_project/ {
        proxy_pass         http://127.0.0.1:8080/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

เปิดใช้งาน:

```bash
ln -s /etc/nginx/sites-available/sprintai /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

ทดสอบ:

```bash
curl http://sprintai.cloud/dj_project/health
# ต้องได้: {"status":"ok","model":"gpt-4o-mini"}
```

---

## Step 6 — ติดตั้ง SSL (Let's Encrypt)

```bash
certbot --nginx -d sprintai.cloud
```

เลือก option **2: Redirect** (force HTTPS)

ทดสอบ:

```bash
curl https://sprintai.cloud/dj_project/health
# ต้องได้: {"status":"ok","model":"gpt-4o-mini"}
```

---

## Step 7 — ทดสอบ End-to-End

เปิด browser ไปที่ URL ต่อไปนี้:

| URL | ผลที่ต้องเห็น |
|-----|--------------|
| `https://sprintai.cloud/dj_project` | Landing page — aurora animations, wordmark Don Juan |
| `https://sprintai.cloud/dj_project/admin` | หน้าใส่รหัสผ่าน (พิมพ์ `paopow`) |

ทดสอบ chat API:

```bash
curl -X POST https://sprintai.cloud/dj_project/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test01","message":"สวัสดีครับ"}'
```

ต้องได้ response จาก DJ Agent กลับมา

ดู log ขณะใช้งาน:

```bash
docker compose logs -f app
```

ต้องเห็น flow ตามนี้:

```
INFO: [query_logger] user=test01 query=สวัสดีครับ
INFO: POST /chat HTTP/1.1 200 OK
```

---

## Future Deploy (เมื่อมี code update)

```bash
cd /opt/dj_project
git pull
docker compose build
docker compose up -d
docker compose logs -f app
```

---

## Troubleshooting

| อาการ | วิธีแก้ |
|-------|--------|
| `curl localhost:8080/dj_project/health` ไม่ตอบ | เช็ค `docker compose ps` — app ต้อง Up |
| หน้าเว็บขึ้นแต่ chat ไม่ตอบ | เช็ค `OPENAI_API_KEY` ใน `.env` |
| Admin login ไม่ผ่าน | ตรวจ `ADMIN_API_KEY` ใน `.env` ตรงกับที่พิมพ์หรือเปล่า |
| `https://` ไม่ทำงาน | รัน `certbot --nginx -d sprintai.cloud` อีกครั้ง |
| Nginx 502 Bad Gateway | app ยังไม่ขึ้น — รอ 30 วิ แล้วลอง reload อีกครั้ง |
| Redis ไม่ connect | `REDIS_URL` ต้องเป็น `redis://redis:6379` ไม่ใช่ localhost |
| ยังไม่มี quota (เหลือ 0 ทันที) | เช็ค Redis เชื่อมต่อได้จริง: `docker compose exec redis redis-cli ping` |
