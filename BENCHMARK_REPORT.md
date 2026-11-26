# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được ghi nhận trực tiếp từ các file trong `reports/`, `benchmark-results/` và các lần chạy thực tế.

**Họ tên:** Do Hoang Vu (MSSV: `2A202603920` — Lớp `K5-L3B`)  
**Ngày chạy:** 2026-11-26  
**Môi trường:** Windows 11 · Python 3.11.9 · Docker Desktop 27.5.1

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | Mock LLM cơ bản mất ~120–180 ms (+ ~20 ms retrieval cho v2); ngưỡng 500 ms đảm bảo 95% người dùng nhận phản hồi nhanh ngay cả khi tải trung bình, đồng thời phát hiện kịp thời khi queue nghẽn hoặc tail latency tăng cao. |
| Error rate `/ask` | ≤ 2.0 % | Mock LLM có lỗi upstream ngẫu nhiên mặc định ~1% (`MOCK_ERROR_RATE=0.01`); error budget 2% cho phép dung sai lỗi nền tối thiểu nhưng báo động ngay khi tỉ lệ lỗi tăng bất thường. |
| Accuracy trên golden dataset | ≥ 85 % (mục tiêu 100%) | Đảm bảo chất lượng trả lời sau khi thay đổi retrieval/prompt không bị suy giảm; đặt ngưỡng chặn CI `0.85` (đã đạt `100.0%` / `23/23` sau khi bổ sung Knowledge Base). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

*(Nguồn: `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json` — mỗi mức 300 requests, `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`.)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.96 | 193.8 | 239.6 | 1698.9 | 0.67% | PASS |
| 10 | 43.53 | 191.3 | 225.0 | 1681.1 | 0.67% | PASS |
| 50 | 105.52 | 202.1 | 260.7 | 1708.6 | 1.33% | PASS |
| 100 | 59.38 | 399.1 | 4069.7 | 4385.0 | 0.33% | FAIL |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency mãi mãi. Từ `c=1` lên `c=10` và `c=50`, nhờ `async`/`await` không block event loop khi chờ LLM I/O, throughput tăng mạnh từ `3.96` → `43.53` → `105.52 req/s` trong khi `p95` giữ ổn định quanh `225–261 ms`. Tuy nhiên khi đẩy lên `c=100` trên một process uvicorn đơn (Windows), tranh chấp socket/event loop và hàng đợi tăng vọt khiến `p50` tăng gấp đôi (`399.1 ms`), `p95` nhảy lên `4069.7 ms` (vi phạm SLO `≤ 500 ms`), kéo RPS tụt xuống còn `59.38 req/s`.

### 2.2 Tail latency

*(Nguồn: `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json` — 300 requests, `concurrency=20`.)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.6 | 229.8 | 236.4 |
| 0.03 (mặc định) | 261.2 | 262.4 | 1695.0 |
| 0.1 | 327.0 | 1694.7 | 1724.3 |

**Nhận xét:** `p99` (và `p95` khi slow rate ≥ 5%) nhạy nhất với request chậm: ở `MOCK_SLOW_RATE=0.03`, `avg` chỉ tăng từ `189.6 ms` lên `261.2 ms` (vẫn dưới 300 ms) nhưng `p99` đã vọt từ `236.4 ms` lên **`1695.0 ms`**. Ở `MOCK_SLOW_RATE=0.1` (10% request chậm > 5%), cả `p95` cũng vọt lên `1694.7 ms` (FAIL SLO) trong khi `avg` mới ở mức `327.0 ms`. Vì `average` bị làm mượt bởi 90–97% request nhanh và che giấu nhóm người dùng đang phải chờ gần 2 giây, SLO bắt buộc phải đặt theo percentile (`p95`/`p99`).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` — `MOCK_ERROR_RATE=0`, 23 câu hỏi trong `golden_dataset.jsonl`.)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.8 | 108.8 | 113.7 |
| Tổng cost (USD) | $0.000400 | $0.000757 | $0.000790 |
| Cost / câu đúng (USD) | $0.00039975 | $0.00003607 | $0.00003436 |
| Quality gate | FAIL | PASS (≥ 80%) | PASS (≥ 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database.")` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và `production/utils/mock_llm.py`. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA (Horizontal Pod Autoscaler) scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi.")` vào `KNOWLEDGE_BASE`. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
Agent `v2` thêm bước retrieval (~20 ms) và chèn context vào prompt nên `avg tokens/câu` tăng gần gấp đôi (`56.8` → `108.8–113.7`), `p95 latency` tăng từ `179.4 ms` lên `216.3–240.6 ms` và tổng chi phí chạy 23 câu tăng từ `$0.000400` lên `$0.000790`. Tuy nhiên, accuracy nhảy từ `4.3%` lên `100.0%`, kéo **cost / câu đúng** giảm hơn **11 lần** (từ `$0.00039975` xuống `$0.00003436`).

**CI Quality Gate (Exercise 7.3):**
Đã tạo workflow [.github/workflows/eval.yml](.github/workflows/eval.yml) chạy trên mỗi Pull Request: khởi động agent `v2` (`MOCK_ERROR_RATE=0`) và chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`. Khi thử chạy `v1` với `--baseline reports/eval_v2.json`, script phát hiện 20 câu bị regression và trả về **exit code `1`**, khiến CI job fail và chặn merge PR vào nhánh chính.

---

## 4. Observability stack (production)

### 4.1 Screenshot & kiểm tra stack

* Đã unit test alert rules bằng `promtool test rules /p/alert_rules_test.yml` → **`SUCCESS`**.
* Đã kiểm tra bảo mật endpoint metrics qua Nginx: `curl -i http://localhost:8080/metrics` trả về **`404 Not Found`** vì Nginx chỉ proxy `/ask` và `/health`, chặn `/metrics` từ bên ngoài để tránh lộ số liệu nội bộ và tránh bị spam scrape; chỉ Prometheus trong mạng nội bộ Docker (`obs_net`) mới scrape trực tiếp `agent:8000/metrics`.
* [x] Dashboard Grafana khi đang có tải ([screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png))
* [x] Một trace chậm trong Jaeger ([screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png))
* [x] Một trace lỗi trong Jaeger ([screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png))
* [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** ([screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png))

**Trả lời Exercise 7.4 (số liệu đo thực tế từ stack 2 instance + Locust 30 users):**
1. **p95 và avg:** Khi chạy tải nền 30 users, `avg latency` đo được là **`247.1 ms`**, `p95 latency` trên Grafana đạt **`295.79 ms`** (`296.5 ms` qua PromQL, lỗi `0.68%`–`0.95%`), trong khi `p99` vọt lên gần **`~1.8 s`** (đường xanh dương trên biểu đồ Latency). Khoảng cách nhỏ giữa `avg` và `p95` cho thấy 95% request đều nhanh bình thường, nhưng khoảng cách lớn tới `p99` phản ánh nhóm ~3% request dính tail latency.
2. **Nginx có chia đều traffic cho 2 instance không?** Có — Nginx phân phối gần như 50/50 theo round-robin: instance `172.18.0.3:8000` nhận **`9.49 req/s`** và `172.18.0.8:8000` nhận **`9.58 req/s`**.
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?** Thực tế đo được `input` ≈ **`1463.4 tokens/s`** so với `output` ≈ **`765.1 tokens/s`** (gần gấp đôi), vì ở agent `v2`, mỗi prompt gửi cho LLM phải kẹp thêm `SYSTEM_PROMPT` + đoạn context tài liệu lấy từ bước retrieval cùng câu hỏi của user, dài hơn câu trả lời ngắn gọn đầu ra.
4. **`curl http://localhost:8080/metrics` trả về gì và vì sao?** Trả về **`404 Not Found`** do Nginx chặn endpoint `/metrics` ở tầng edge để không công khai số liệu vận hành ra internet; Prometheus vẫn scrape bình thường qua mạng nội bộ Docker.

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`severity="critical"`, value `20.05%`) | **90.6 s** *(for: 1m)* | Golden Signals — Error rate & Requests/s status `503` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`severity="warning"`, value `1.895 s`) | **150.8 s** *(for: 2m)* | Golden Signals — Latency p95 & Latency `/ask` |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`severity="warning"`, burn rate `$16.59/giờ`) | **150.4 s** *(for: 2m)* | LLM — Cost burn rate (USD/giờ) & LLM latency p95 |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`severity="critical"`) | **40.1 s** *(for: 30s)* | Golden Signals — Instances up (giảm từ 2 → 1) |
| E | `AGENT_VERSION=v1` | Không có alert mới firing từ thay đổi này | N/A | Instances table (`version="v1"`), Tokens/s (`1463→560` input tok/s) & Retrieval hit ratio |

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**
Alert hạ tầng chỉ đo availability, latency, error rate (5xx) và chi phí — khi đổi sang `v1`, các chỉ số này vẫn xanh nhưng chất lượng câu trả lời tụt mạnh. Cần phát hiện bằng: (1) **CI Eval Quality Gate** chạy golden dataset trước khi deploy; (2) **Online evaluation / user feedback** (thumbs up/down, LLM-as-judge sampling trên traffic thật); và (3) **Alert theo metric chất lượng/RAG** như `retrieval_hit_ratio` giảm đột ngột dưới ngưỡng.

### 4.3 Debug bằng trace

Trace chậm điển hình lấy từ Jaeger (`Duration: 1.7s`) và log JSON tương ứng của container agent:

- `trace_id`: `a64065927be4936321082574e15184d1`
- Tổng thời gian: **1.7 s** (`~1712.7 ms` gồm `16.7 ms` retrieval + `1694.8 ms` LLM)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**`1694.8 ms`**, chiếm **~99.0%** tổng thời gian; `agent.retrieve_context` chỉ mất `16.7 ms`)
- Dòng log tương ứng (lấy từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-26T08:00:40.802142+00:00", "level": "INFO", "service": "observable-agent", "instance": "cf19f6b9da0b", "event": "llm_call", "trace_id": "a64065927be4936321082574e15184d1", "span_id": "1654a7896e455d6c", "request_id": "95e0b08863a9", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1694.8}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn: `benchmark-results/scale_1_stats.csv` chạy đúng 1 container với `--no-deps` và `benchmark-results/scale_3_stats.csv` chạy 3 container — dòng `Aggregated` / `POST /ask`.)*

| Số instance | RPS (Aggregated / `/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.77 / 59.56 | 190 / 200 | 320 / 340 | 1700 / 1700 | 69 / 7832 (0.88%) |
| 3 | 66.08 / 59.92 | 190 / 190 | 250 / 260 | 1700 / 1700 | 64 / 7884 (0.81%) |

**Giải thích kết quả:** Khi scale từ 1 lên 3 container `agent`, `p95` của `POST /ask` cải thiện rõ rệt từ **`340 ms`** xuống **`260 ms`** (và `Aggregated p95` giảm từ **`320 ms`** xuống **`250 ms`**) do giảm tải cạnh tranh trên event loop khi 100 user gửi đồng thời. Tuy nhiên, RPS tổng (~`66 req/s`), `p50` (`190 ms`) và `p99` (`1700 ms`) gần như giữ nguyên. Nguyên nhân là nút thắt chính nằm ở **latency của upstream LLM** (mỗi request mất ~120–180 ms và ~3% tail latency +1500 ms) cùng **thời gian nghỉ giữa các lượt của user trong `locustfile.py`** nên 100 user chỉ tạo tối đa ~66 req/s. Scale thêm instance giúp giảm queueing ở tầng API/CPU nhưng không rút ngắn được thời gian chờ câu trả lời từ model LLM bên ngoài.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Average biết nói dối, phải đo percentile (`p95`/`p99`)**: chỉ 3%–10% request chậm đã đủ làm trải nghiệm người dùng tệ đi rõ rệt dù trung bình vẫn đẹp.
  2. **Eval tự động là lưới an toàn cho chất lượng AI**: metric hạ tầng xanh không có nghĩa agent trả lời đúng — cần golden dataset + quality gate trong CI.
  3. **3 trụ cột (Metrics + Traces + JSON Logs) bổ trợ lẫn nhau**: Metrics báo *khi nào* có vấn đề, Trace chỉ ra *bước nào* chậm (`chat mock-llm-*` vs retrieval), và `trace_id` giúp truy thẳng ra dòng log chi tiết.
- **Nếu đưa agent này lên production thật, sẽ thêm metric / alert:**
  - Metric & alert cho **RAG retrieval hit ratio** (bắt ngay suy giảm chất lượng giống Thí nghiệm E) và tỉ lệ **rate limit `429` / budget `402`**.
  - Giám sát ở tầng **Nginx / synthetic blackbox probe** từ bên ngoài để bắt lỗi `502`/`504` khi request không tới được backend agent.
