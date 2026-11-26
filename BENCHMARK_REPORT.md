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
* [ ] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`) — *[CHỜ BƯỚC 4]*
* [ ] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`) — *[CHỜ BƯỚC 4]*
* [ ] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`) — *[CHỜ BƯỚC 4]*
* [ ] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`) — *[CHỜ BƯỚC 4]*

*(Phần giải đáp Exercise 7.4 sẽ được cập nhật số liệu thực tế từ dashboard ngay sau Bước 4: khoảng cách `avg` vs `p95`, tỉ lệ phân phối tải của Nginx giữa các instance, và lý do `input tokens/s` > `output tokens/s` vì prompt `v2` chứa cả system prompt + context tài liệu retrieval).*

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* |
| B | `MOCK_SLOW_RATE=0.3` | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* |
| C | `LLM_MODEL=mock-llm-large` | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* |
| D | `docker pause` 1 instance | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* | *[CHỜ BƯỚC 4]* |
| E | `AGENT_VERSION=v1` | Không có | N/A | Retrieval hit ratio & `agent_info` |

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**
Alert hạ tầng chỉ đo availability, latency, error rate (5xx) và chi phí — khi đổi sang `v1`, các chỉ số này vẫn xanh nhưng chất lượng câu trả lời tụt mạnh. Cần phát hiện bằng: (1) **CI Eval Quality Gate** chạy golden dataset trước khi deploy; (2) **Online evaluation / user feedback** (thumbs up/down, LLM-as-judge sampling trên traffic thật); và (3) **Alert theo metric chất lượng/RAG** như `retrieval_hit_ratio` giảm đột ngột dưới ngưỡng.

### 4.3 Debug bằng trace

*[CHỜ BƯỚC 4 — sẽ lấy `trace_id`, thời gian từng span từ Jaeger và dòng log JSON tương ứng từ `docker compose logs agent`.]*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` — dòng `Aggregated` / `POST /ask`.)*

| Số instance | RPS (Aggregated / `/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 *(lưu ý: `compose` mặc định `replicas: 2` khi chạy `run locust` thiếu `--no-deps`)* | 65.43 / 59.53 | 190 / 190 | 240 / 250 | 1700 / 1700 | 84 / 7811 (1.08%) |
| 3 | 66.08 / 59.92 | 190 / 190 | 250 / 260 | 1700 / 1700 | 64 / 7884 (0.81%) |

**Giải thích kết quả:** Khi scale số container `agent`, `p50` (`190 ms`), `p95` (`240–260 ms`) và `p99` (`1700 ms`) gần như không đổi. Nguyên nhân là nút thắt không nằm ở CPU/RAM của FastAPI (vốn xử lý `async` rất nhẹ), mà nằm ở **latency của upstream LLM call** (~120–180 ms cho request thường và +1500 ms cho ~3% tail latency) và **wait time cố định giữa các request trong `locustfile.py`** (mỗi user Locust chờ giữa các lượt gọi nên 100 user tạo ra ~60–66 req/s ổn định). Lưu ý ở Bước 4 sẽ chạy lại `scale_1` kèm `--no-deps` trên Locust nếu cần đối chiếu chính xác 1 vs 3 container khi Docker Desktop hoạt động lại.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Average biết nói dối, phải đo percentile (`p95`/`p99`)**: chỉ 3%–10% request chậm đã đủ làm trải nghiệm người dùng tệ đi rõ rệt dù trung bình vẫn đẹp.
  2. **Eval tự động là lưới an toàn cho chất lượng AI**: metric hạ tầng xanh không có nghĩa agent trả lời đúng — cần golden dataset + quality gate trong CI.
  3. **3 trụ cột (Metrics + Traces + JSON Logs) bổ trợ lẫn nhau**: Metrics báo *khi nào* có vấn đề, Trace chỉ ra *bước nào* chậm (`chat mock-llm-*` vs retrieval), và `trace_id` giúp truy thẳng ra dòng log chi tiết.
- **Nếu đưa agent này lên production thật, sẽ thêm metric / alert:**
  - Metric & alert cho **RAG retrieval hit ratio** (bắt ngay suy giảm chất lượng giống Thí nghiệm E) và tỉ lệ **rate limit `429` / budget `402`**.
  - Giám sát ở tầng **Nginx / synthetic blackbox probe** từ bên ngoài để bắt lỗi `502`/`504` khi request không tới được backend agent.
