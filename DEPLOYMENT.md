# Deployment Information

## Public URL
https://thungphasanh.up.railway.app

## Platform
Railway (Docker + Managed Redis)

## Test Commands

Đặt `BASE=https://thungphasanh.up.railway.app` và `AGENT_API_KEY` là key cấu hình trên Railway Dashboard:

### 1. Health Check (Liveness — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://thungphasanh.up.railway.app/health"
# Output thực tế: 200
# {"status":"ok","environment":"production","uptime_seconds":310.1}
```

### 2. Readiness Check (Redis connection — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://thungphasanh.up.railway.app/ready"
# Output thực tế: 200
# {"status":"ready","redis":"ok"}
```

### 3. Authentication Check (không gửi `X-API-Key` — mong đợi `401`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "https://thungphasanh.up.railway.app/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Output thực tế: 401
```

### 4. API Test (có `X-API-Key` — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "https://thungphasanh.up.railway.app/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Output thực tế: 200
```

## Environment Variables Set
- `PORT` (Railway tự inject động)
- `ENVIRONMENT` (`production`)
- `AGENT_API_KEY` *(cấu hình trên Railway Variables, không lưu trong code/git)*
- `REDIS_URL` (`${{Redis.REDIS_URL}}` — trỏ tới service Redis trên Railway)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
