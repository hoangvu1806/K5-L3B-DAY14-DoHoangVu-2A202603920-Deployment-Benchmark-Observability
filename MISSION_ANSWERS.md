# Day 14 Lab — Mission Answers (K5-L3B)

> **Học viên:** Do Hoang Vu (`2A202603920`)  
> **Lớp:** K5-L3B

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret trong source code (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` — nếu push lên GitHub sẽ lộ secret ngay lập tức.
2. **Hardcode cấu hình ứng dụng (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` không đọc từ biến môi trường, không thể đổi giữa `dev`/`staging`/`production` mà không sửa code.
3. **Dùng `print()` để log và in cả secret ra log (dòng 33–38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa khó parse/tìm kiếm khi vận hành (không phải JSON structured log), vừa làm rò rỉ API key ra stdout/log aggregator.
4. **Thiếu endpoint kiểm tra sức khỏe `/health` và `/ready` (dòng 42):** Cloud platform và load balancer không biết container còn sống hay sẵn sàng nhận traffic hay không để tự động restart hoặc ngắt route.
5. **Hardcode host/port và bật debug reload (dòng 49–53):** `host="localhost"` (không bind `0.0.0.0` nên bên ngoài container không truy cập được), `port=8000` cố định (không đọc biến `PORT` do Railway/Render cấp), và `reload=True` gây tốn tài nguyên/không an toàn ở production.
6. **Thiếu graceful shutdown & CORS policy:** Tắt đột ngột sẽ làm rớt các request đang xử lý dở.

### Exercise 1.2: Kết quả chạy `01-localhost-vs-production/develop/app.py`

Lệnh test theo chuẩn K5 (truyền `question` qua query param):

```bash
curl -i -X POST "http://localhost:8000/ask?question=Hello"
```

Output thực tế:

```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:03:21 GMT
server: uvicorn
content-length: 95
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
| --- | --- | --- | --- |
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `MAX_TOKENS` (dòng 17–22) | Đọc qua `os.getenv(...)` trong `Settings` (`config.py` dòng 14–46) + `validate()` fail-fast khi `ENVIRONMENT=production` thiếu `AGENT_API_KEY` | Tuân thủ 12-Factor App: tách biệt code và config, dùng chung 1 artifact cho mọi môi trường và không bao giờ commit secrets lên Git. |
| **Health & Readiness** | Không có `/health` hay `/ready` (dòng 42) | Có `GET /health` (liveness, dòng 135–149) và `GET /ready` (readiness trả 503 nếu chưa sẵn sàng, dòng 152–161) | Platform dựa vào `/health` để restart container bị treo; load balancer dựa vào `/ready` để không đẩy traffic vào instance đang khởi động hoặc lỗi dependency. |
| **Logging** | `print("[DEBUG] ...")`, log thẳng `OPENAI_API_KEY` (dòng 33–38) | `logging` format JSON (`{"time":...,"level":...,"msg":...}`, dòng 28–31), log `question_length` và `client_ip`, không log secret (dòng 111–122) | Log JSON dễ index, lọc và truy vết trên hệ thống tập trung (Loki, Datadog), đồng thời tránh rò rỉ thông tin nhạy cảm. |
| **Shutdown** | Tắt đột ngột, không dọn tài nguyên | Dùng FastAPI `lifespan` (dòng 39–68) đặt `is_ready = False` trước khi thoát và bắt `SIGTERM` (dòng 180–189) | Cho phép request đang chạy (in-flight) hoàn tất và đóng kết nối sạch sẽ khi deploy bản mới hoặc scale down, tránh lỗi 502 cho user. |
| **Network & CORS** | `host="localhost"`, `port=8000`, `reload=True` (dòng 49–53) | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ `PORT`), `reload=settings.debug`, cấu hình `CORSMiddleware` (dòng 77–82, 194–198) | Container và PaaS (Railway/Render) yêu cầu bind `0.0.0.0` và nhận cổng động từ biến `PORT`; tắt `reload` ở production đảm bảo ổn định. |

---

## Part 2: Docker

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?**  
   `python:3.11` (bản đầy đủ trên Debian kèm sẵn nhiều công cụ build/OS libraries nên dung lượng ~1 GB).
2. **Working directory là gì?**  
   `/app` (đặt bằng `WORKDIR /app`, mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy tương đối từ thư mục này).
3. **Tại sao `COPY requirements.txt` phải đứng trước `COPY . .`?**  
   Để tận dụng **Docker layer cache**. File `requirements.txt` ít thay đổi hơn source code; nếu copy và chạy `pip install` trước, khi chỉ sửa `app.py`, Docker tái sử dụng lại layer đã cài thư viện thay vì tải và cài lại toàn bộ dependencies từ đầu.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**  
   - `CMD` định nghĩa lệnh hoặc tham số mặc định khi chạy container và **có thể bị ghi đè dễ dàng** bằng tham số truyền ở cuối `docker run <image> <cmd>`.  
   - `ENTRYPOINT` định nghĩa file thực thi cố định cho container; các tham số truyền thêm vào `docker run` sẽ được nối vào sau `ENTRYPOINT` (trừ khi dùng cờ `--entrypoint`).

### Exercise 2.2: Build và test container `my-agent:develop`

Lệnh build từ gốc repo: `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`  
Test endpoint:

```bash
curl -i -X POST "http://localhost:8000/ask?question=What+is+Docker"
```

Output thực tế:

```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:04:18 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: So sánh Multi-stage build (`02-docker/production/Dockerfile`)

* **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài compiler `gcc`, `libpq-dev` rồi chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`. Image stage này không được đưa vào sản phẩm cuối.
* **Stage 2 (`runtime`):** Bắt đầu lại từ `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng code `main.py` và `utils/mock_llm.py`, cấu hình `HEALTHCHECK` và chạy `uvicorn`.
* **Vì sao image nhỏ hơn?** Loại bỏ hoàn toàn compiler (`gcc`, `binutils`, header files `libpq-dev`, `apt` cache) và dùng base `slim` thay vì full `python:3.11`.

**Kích thước đo thực tế trên máy (`docker images` & `docker image inspect`):**
* **Develop (`my-agent:develop`):** `1.15 GB` (`1,154,311,927` bytes ≈ `1100.84 MiB`)
* **Production (`my-agent:advanced`):** `163 MB` (`162,882,434` bytes ≈ `155.34 MiB`)
* **Mức giảm:** **85.9%**

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc:**

```text
               ┌────────────────────────────┐
               │       Client (Host)        │
               └─────────────┬──────────────┘
                             │ HTTP :80 (HTTPS :443)
                             ▼
               ┌────────────────────────────┐
               │   nginx (nginx:alpine)     │
               │   Rate limit + Sec headers │
               └─────────────┬──────────────┘
                             │ proxy_pass :8000 (network: internal)
                             ▼
               ┌────────────────────────────┐
               │   agent (FastAPI :8000)    │
               └──────┬──────────────┬──────┘
                      │              │
       :6379          ▼              ▼          :6333
        ┌──────────────────┐   ┌──────────────────┐
        │ redis:7-alpine   │   │  qdrant:v1.9.0   │
        │ (redis_data vol) │   │ (qdrant_data vol)│
        └──────────────────┘   └──────────────────┘
```

Các service giao tiếp qua bridge network nội bộ `internal` bằng service discovery DNS (`agent`, `redis`, `qdrant`). Chỉ `nginx` mở port `80`/`443` ra ngoài.

**Kết quả test thực tế qua Nginx (`http://localhost`):**

```http
HTTP/1.1 200 OK
Server: nginx
Date: Thu, 26 Nov 2026 04:05:21 GMT
Content-Type: application/json
Content-Length: 95
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":4.0,"version":"2.0.0","timestamp":"2026-11-26T04:05:21.954823"}
```

```http
HTTP/1.1 200 OK
Server: nginx
Date: Thu, 26 Nov 2026 04:05:22 GMT
Content-Type: application/json
Content-Length: 103
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 lên Cloud (Railway)

* **Public URL:** `[CHỜ DEPLOY RAILWAY — SẼ CẬP NHẬT SAU BƯỚC 3]`
* **Screenshots:**
  * Dashboard & biến môi trường: `screenshots/dashboard.png` *(chờ Bước 3)*
  * Trạng thái running / logs: `screenshots/running.png` *(chờ Bước 3)*
  * Kết quả kiểm tra 4 lệnh CP6: `screenshots/test.png` *(chờ Bước 3)*

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
| --- | --- | --- |
| **Định dạng & Mục đích** | TOML (`config-as-code`) cấu hình cho **1 service** hiện tại | YAML (`Blueprint IaC`) khai báo được **cả stack nhiều service** (`web` + `redis`) trong 1 file |
| **Build / Runtime** | `[build] builder = "DOCKERFILE"` (hoặc `NIXPACKS`), dùng `Dockerfile` | `runtime: docker` (hoặc `python` với `buildCommand` + `startCommand`) |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | `healthCheckPath: /health`, `autoDeploy: true`, chọn `region` (vd `singapore`) và `plan` (`free`) |
| **Quản lý Secrets** | Không khai báo secret trong `railway.toml`; nhập trực tiếp trên Railway Dashboard hoặc `railway variables set` | Khai báo tên biến trong `envVars:` nhưng dùng `generateValue: true` (tự sinh) hoặc `sync: false` (nhập tay trên dashboard), tuyệt đối không ghi plain text |
| **Kết nối Redis** | Tạo service Redis riêng trong Project rồi link biến `REDIS_URL=${{Redis.REDIS_URL}}` | Có thể khai báo ngay service `type: redis` trong cùng file và lấy `fromService: { property: connectionString }` |

*Lý do khác biệt:* Railway hướng tới trải nghiệm service-centric (mỗi service đọc `railway.toml` riêng và liên kết biến qua UI/CLI), còn Render Blueprint mô tả toàn bộ hạ tầng đa dịch vụ dưới dạng Infrastructure as Code trong một file YAML duy nhất.

### Exercise 3.3: Mô tả CI/CD Pipeline cho GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Dựa trên `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD tự động chạy khi push lên nhánh `main` qua 4 bước tuần tự:
1. **`test`:** Dùng container `python:3.11-slim` cài `requirements.txt` và chạy `pytest tests/ -v`; nếu test fail thì dừng toàn bộ pipeline.
2. **`build`:** Build Docker image gắn 2 tag (`$COMMIT_SHA` và `latest`), tận dụng `--cache-from` từ image `latest` để tăng tốc build.
3. **`push`:** Đẩy image với đủ các tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Gọi `gcloud run deploy ai-agent` lên region `asia-southeast1` với cấu hình trong `service.yaml`: scale tự động `minScale=1` (tránh cold start) đến `maxScale=10`, giới hạn `512Mi` RAM / `1` CPU, `containerConcurrency=80`, nạp secrets (`OPENAI_API_KEY`, `AGENT_API_KEY`) từ Secret Manager và gắn `livenessProbe` (`/health`) + `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

* API key được kiểm tra trong dependency `verify_api_key` thông qua `APIKeyHeader(name="X-API-Key", auto_error=False)` so với biến môi trường `AGENT_API_KEY`. Thiếu key trả `401`, sai key trả `403`. Để rotate key an toàn, thay đổi `AGENT_API_KEY` qua biến môi trường trên platform rồi restart/rollout (hoặc hỗ trợ danh sách key cũ/mới trong giai đoạn chuyển tiếp).

Output thực tế khi test:

```http
# Không gửi X-API-Key → 401
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 04:05:48 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

```http
# Có header X-API-Key: secret-key-123 → 200
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:05:48 GMT
server: uvicorn
content-length: 145
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

* `rate_limiter.py` dùng thuật toán **Sliding Window Counter** (lưu `deque` các timestamp trong cửa sổ 60 giây).
* Giới hạn mặc định: user thường (`student`) = **10 requests/phút** (`rate_limiter_user`), admin (`teacher`) = **100 requests/phút** (`rate_limiter_admin`). Khi `role == "admin"` sẽ dùng `rate_limiter_admin` (hoặc cấu hình bypass/tier riêng).

Kết quả test thực tế với tài khoản `student` / `demo123` qua `POST /auth/token` (token đã được che bớt):

```http
# Request #1 → 200 OK (requests_remaining: 9)
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:06:41 GMT
server: uvicorn
content-length: 179
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Test 1","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

# Request #2..#9 → HTTP/1.1 200 OK

# Request #10 → 200 OK (requests_remaining: 0)
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:06:43 GMT
server: uvicorn
content-length: 189
content-type: application/json
...

{"question":"Test 10","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000181}}

# Request #11 → 429 Too Many Requests
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 04:06:43 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795666063
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

# Request #12 → HTTP/1.1 429 Too Many Requests
```

### Exercise 4.4: Cách triển khai Cost Guard với Redis & lý do cần cả Rate Limit lẫn Cost Guard

* **Cách làm Cost Guard với Redis:** Lưu tổng tiền đã chi theo key theo ngày/tháng (ví dụ `cost:daily:{YYYY-MM-DD}` hoặc `budget:{user_id}:{YYYY-MM}`) kèm TTL tự hết hạn (`EXPIRE`). Trước khi gọi LLM, đọc giá trị hiện tại; nếu `>= budget` thì chặn ngay với mã **HTTP 402 Payment Required**. Sau khi LLM trả lời, tính chi phí thực theo `(input_tokens / 1000) * PRICE_INPUT + (output_tokens / 1000) * PRICE_OUTPUT` rồi cộng nguyên tử vào Redis bằng `INCRBYFLOAT`.
* **Tại sao cần cả hai?**
  - **Rate Limiting** bảo vệ **hạ tầng & thông lượng** (chống DDoS, spam request liên tục làm nghẽn CPU/event loop).
  - **Cost Guard** bảo vệ **ngân sách tiền API** (vì một vài request hợp lệ nhưng có prompt cực dài hoặc dùng model đắt như `gpt-4o`/`mock-llm-large` vẫn có thể tiêu hết tiền dù không vượt ngưỡng req/phút).

---

## Part 5: Scaling & Reliability

### Exercise 5.1 – 5.2: Health Check, Readiness Check & Graceful Shutdown

* **Liveness (`GET /health`) vs Readiness (`GET /ready`):**
  - `GET /health` kiểm tra **process còn sống hay không** — luôn trả `200` kể cả khi mất kết nối Redis. Nếu `/health` lỗi, orchestrator sẽ **restart container**.
  - `GET /ready` kiểm tra **ứng dụng đã sẵn sàng phục vụ chưa** (ping Redis thành công → `200`, mất Redis → `503`). Khi `/ready` trả `503`, Load Balancer tạm thời **ngừng đẩy traffic mới vào instance đó** chứ không kill/restart container một cách vô ích khi chỉ có dependency ngoài bị gián đoạn tạm thời.
* **Graceful Shutdown (`SIGTERM`):** Khi nhận `SIGTERM` từ Docker/Kubernetes (`docker stop`), app chuyển trạng thái không sẵn sàng, tiếp tục xử lý hoàn tất các request đang chạy (in-flight), đóng kết nối Redis/DB sạch sẽ và thoát với exit code `0` thay vì bị cắt ngang (`SIGKILL` exit 137).

### Exercise 5.3 – 5.5: Stateless Design & Kết quả test `test_stateless.py` (`--scale agent=3`)

Nếu lưu `conversation_history` trong RAM của từng process, khi chạy 3 instance sau Nginx Load Balancer theo round-robin, request 1 vào `agent-1` lưu vào RAM `agent-1`, request 2 sang `agent-2` sẽ không thấy lịch sử cũ. Chuyển toàn bộ state/session sang **Redis** giúp mọi instance đọc/ghi chung một nguồn dữ liệu, có thể scale ngang hoặc restart từng instance mà không mất phiên làm việc.

**Output thực tế khi chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: bd317508-6b27-4611-bb43-365f4d8ea014

Request 1: [instance-604b6b]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-97da3f]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-61e702]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-604b6b]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-97da3f]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-97da3f', 'instance-61e702', 'instance-604b6b'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

*Giải thích:* 5 request liên tiếp trong cùng một `session_id` được Nginx phân phối đều sang 3 container khác nhau (`instance-604b6b`, `instance-97da3f`, `instance-61e702`), nhưng nhờ lưu lịch sử vào Redis nên cuối phiên vẫn truy xuất đủ cả 10 message (5 user + 5 assistant).

---

## Part 6: Final Project (`06-lab-complete/`)

Kết quả chạy `python3 check_production_ready.py` đầy đủ trong môi trường POSIX + Docker:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

*(Chi tiết đo được khi chạy script chấm: Docker image `160 MB`, `docker stop` exit code `0` trong `1.0s`, 17 dòng log app đều parse JSON hợp lệ.)*

---

## AI Log (theo `RULES.md` mục 1)

| Mục | Nội dung hỏi / hỗ trợ | Kết quả nhận & cách tự sửa / tự kiểm tra |
| --- | --- | --- |
| **Part 1–5 (CP1–CP4)** | Giải thích các anti-pattern trong `develop/app.py`, kiểm tra lệnh test khớp chuẩn K5 (query param, `/auth/token`, `-p` cho Docker Compose). | Tự chạy từng app và container trên máy thật, ghi lại output `curl -i`, kích thước `docker images`, và output `test_stateless.py`. |
| **Part 6 (`06-lab-complete/`)** | Gợi ý triển khai các `TODO` (`config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py` dùng Redis sorted set, `cost_guard.py`, `JsonFormatter`, wrapper `SIGTERM`, multi-stage `Dockerfile`, `docker-compose.yml`, `railway.toml`, `render.yaml`). | Chạy `check_production_ready.py --static-only`, `--skip-docker` trên Windows và chạy đầy đủ trong container POSIX có gắn Docker socket → tự kiểm tra đạt `PASS 12/12 · 43/43 checks passed`. |
| **Part 7 (`benchmark-observability/`)** | Hướng dẫn thêm Histogram `agent_question_length_chars`, bổ sung 2 entry `hpa` và `jwt` vào `KNOWLEDGE_BASE`, phát hiện và sửa thiếu `ENV PYTHONUSERBASE=/home/agent/.local` trong `production/Dockerfile` (do `useradd -d /app` lệch `/home/agent/.local`). | Tự chạy lại `load_test.py`, `run_eval.py` (đạt 23/23 = 100%, 0 regression), `promtool test rules` (`SUCCESS`), và `docker compose` stack + Locust để thu thập số liệu JSON/CSV thật. |
