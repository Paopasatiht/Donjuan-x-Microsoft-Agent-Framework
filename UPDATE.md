# Update DJ Agent on Hostinger VPS

## Step 1 — Push code จากเครื่องตัวเอง

```bash
git add .
git commit -m "your message"
git push origin donjuan_v2
```

---

## Step 2 — SSH เข้า VPS

```bash
ssh root@<your-vps-ip>
```

---

## Step 3 — Pull และ Rebuild

```bash
cd /opt/dj_project
git pull
docker compose build
docker compose up -d
```

ตรวจว่า container ขึ้นแล้ว:

```bash
docker compose logs -f app
```

ต้องเห็น:

```
INFO: DJ Agent v2 ready!
INFO: Application startup complete.
```

กด `Ctrl+C` เพื่อออก

---

## Step 4 — ทดสอบ

```bash
curl https://sprintai.cloud/dj_project/health
# ต้องได้: {"status":"ok","model":"gpt-4o-mini"}
```

---

## ⚠️ ต้องทำครั้งแรกเท่านั้น — แก้ Nginx สำหรับ Streaming

Feature streaming (SSE) ต้องการ config เพิ่มใน Nginx ไม่งั้น text จะไม่ stream จริง

```bash
nano /etc/nginx/sites-available/sprintai
```

เพิ่ม 3 บรรทัดนี้ใน `location /dj_project/`:

```nginx
location /dj_project/ {
    proxy_pass         http://127.0.0.1:8080/;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;

    proxy_buffering    off;
    proxy_cache        off;
    proxy_set_header   Connection '';
}
```

บันทึก: `Ctrl+O` → Enter → `Ctrl+X`

```bash
nginx -t && systemctl reload nginx
```
