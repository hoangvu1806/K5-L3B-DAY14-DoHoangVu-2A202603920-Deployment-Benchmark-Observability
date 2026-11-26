# Deployment Information

## Public URL
`[CHỜ DEPLOY RAILWAY — SẼ CẬP NHẬT SAU BƯỚC 3]`

## Platform
Railway (Docker + Managed Redis)

## Test Commands

Đặt `BASE` là Public URL và `AGENT_API_KEY` là key cấu hình trên Railway Dashboard:

### 1. Health Check (Liveness — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200
```

### 2. Readiness Check (Redis connection — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200
```

### 3. Authentication Check (không gửi `X-API-Key` — mong đợi `401`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Expected: 401
```

### 4. API Test (có `X-API-Key` — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Expected: 200
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
- [Deployment dashboard](screenshots/dashboard.png) *(chờ Bước 3)*
- [Service running](screenshots/running.png) *(chờ Bước 3)*
- [Test results](screenshots/test.png) *(chờ Bước 3)*
