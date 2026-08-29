# Observability Architecture & Incident Runbook

Tài liệu này chuyển yêu cầu của `LAB_GUIDE.md` thành cơ chế vận hành có thể kiểm
chứng. Mục tiêu không phải là “job chạy thành công”, mà là bảo đảm dữ liệu đủ đúng
và đủ mới để CEO dashboard và Support Agent được phép sử dụng.

## 1. Control plane

```text
orders/customers -> contract + GX -> dbt data/unit tests ----+
       |                 |                 |                 |
       +-> volume/null/distribution -------+                 v
       +-> SCD overlap/orphan key ---------+-> correlate -> publish gate
                                                           |  |  |
KB documents -> contract/freshness/version/content --------+  |  +-> runbook/owner
       |                                                      +----> lineage/blast radius
       +-> embedding telemetry coverage -> SLO burn windows -------> dashboard/report
```

Nguồn sự thật của mỗi lần chạy là `reports/latest_metrics.json`. Lịch sử SLI tối đa
200 lần chạy nằm ở `reports/monitoring_history.jsonl`; dashboard chỉ trình bày,
không tự suy diễn trạng thái khác với report.

## 2. Các kịch bản khó nhất và lớp phòng vệ

| Kịch bản | Vì sao khó | Tín hiệu chính | Tín hiệu dự phòng | Xử lý tự động |
|---|---|---|---|---|
| Pipeline xanh nhưng duplicate/null/type drift | SQL/job vẫn `SUCCESS` | Contract + GX | dbt generic tests | Critical: block và quarantine |
| Partial ingestion đúng schema | Rule cứng không biết số dòng kỳ vọng | same-weekday MAD volume | freshness, null/status mix | Quarantine batch, không publish |
| Weekend/seasonality hoặc campaign hợp lệ | Global Z-score dễ false positive | same-segment history | known-event context, distribution | Không page nếu chỉ spike ngắn |
| Outlier đầu độc baseline | Mean/std bị kéo lệch | median/MAD | quantile drift | Điều tra và giữ baseline sạch |
| Clock skew/future timestamp | Tuổi dữ liệu âm trông “siêu tươi” | future tolerance 5 phút | source scheduler logs | Quarantine, sửa clock/source |
| Hai SCD row cùng active | Join nhân bản revenue nhưng test output cơ bản vẫn pass | singular test + runtime overlap | dbt unit test | Block revenue build/publish |
| Orphan customer | Left join che mất lỗi tham chiếu | cross-table orphan check | join row-count reconciliation | Block |
| Amount/status đổi âm thầm, mean gần như cũ | Mean-only detector bị mù tail/shape | quantile distance + categorical TVD | dbt business tests | Quarantine hoặc investigate |
| KB timestamp mới nhưng version/content cũ | Freshness đơn lẻ bị đánh lừa | version rollback + content length | source URI/contract | Block RAG re-index |
| Embedding model/tokenizer đổi | Contract text vẫn pass nhưng retrieval giảm | embedding norm drift | retrieval hit-rate/answer eval | Hiện đánh dấu `not_instrumented`, không báo xanh giả |
| Một lần check lỗi gây page storm | SLO 99.9% làm burn rate rất lớn | multi-window burn | minimum sample guard | Page chỉ khi đủ mẫu và burn kéo dài |
| Detector/control plane không phát metric | “Không có dữ liệu” dễ bị hiểu là healthy | telemetry coverage | job heartbeat/report age | P3/P2 tùy thời gian mất tín hiệu |
| Nhiều fault đồng thời | Một root cause có thể che fault khác | signal correlation theo domain | lineage cột/dataset | Chọn severity cao nhất, hợp nhất blast radius |

## 3. Severity, ownership và publish gate

| Mức | Điều kiện | Publish | Phản ứng |
|---|---|---|---|
| P1 | Contract critical, orphan key, SCD overlap, KB rollback hoặc sustained fast burn | Đóng | Page owner, block, lưu batch quarantine |
| P2 | Freshness/volume/distribution cần containment hoặc nhiều signal đồng thời | Đóng | Quarantine, điều tra trong giờ trực |
| P3 | Signal đơn lẻ chỉ cần điều tra | Có thể mở | Ticket/warn, không đánh thức on-call |
| none | Không có active signal | Mở | Theo dõi bình thường |

Owners: `commerce-data` cho orders/customers, `support-ai` cho KB/RAG và
`data-reliability` cho SLO/control-plane.

## 4. Quy trình xử lý chuẩn

1. **Detect:** chạy `make baseline`, đọc `system_status`, active signals và thời điểm snapshot.
2. **Triage:** không chỉ nhìn pipeline exit code; xác nhận signal có actionable, có đủ history hay đang cold-start.
3. **RCA:** kiểm tra raw data có lý do, contract/GX, dbt tests và detector evidence. Với mystery incident, tuyệt đối không đọc script tạo fault.
4. **Blast radius:** dùng `affected_assets` và `column_blast_radius_from_order_amount`; xác định CEO dashboard hay Support Agent bị ảnh hưởng.
5. **Mitigate:** đóng publish gate; block critical batch hoặc quarantine warning batch; giữ last-known-good downstream output.
6. **Recover:** sửa/re-run upstream extract, sau đó chạy contract → GX → dbt → baseline theo thứ tự.
7. **Verify:** chỉ mở gate khi deterministic checks pass, freshness nằm trong SLO, anomaly trở lại baseline/được phê duyệt và downstream aggregate được đối soát.

## 5. Playbook theo signal

### Orders contract / duplicate / type drift

- Không sync seed hoặc build mart từ batch lỗi.
- Chạy `make gx`; file lỗi được sao chép vào `reports/quarantine/` và quyết định
  nằm trong `latest_gx_action.json`.
- Yêu cầu producer sửa schema hoặc replay batch; không coercion âm thầm.
- Recovery: contract không còn critical failure, dbt 19/19 và row reconciliation đúng.

### Volume, freshness hoặc distribution

- So sánh cùng thứ trong tuần trước khi kết luận; kiểm tra campaign trong
  `known_event` nếu được phê duyệt.
- Freshness: kiểm tra scheduler, watermark và source lag. Future timestamp phải
  được xem là clock skew, không phải fresh.
- Giữ CEO dashboard ở last-known-good cho tới khi batch replay đi qua toàn bộ gate.

### SCD overlap / orphan key

- Xác minh số active row trên từng `customer_id` và referential integrity.
- Không chỉ dựa vào model đã deduplicate: singular test vẫn phải fail để producer
  biết dimension bị hỏng.
- Đối soát `completed_order_rows` và `daily_revenue` với raw completed orders.

### KB/RAG

- Dừng re-index nếu KB stale, contract lỗi, content collapse hoặc version rollback.
- Giữ active index trước đó; xác minh policy mới bằng `doc_id`, `version`, source URI.
- Trước khi tuyên bố RAG healthy cần bổ sung current embedding norms, retrieval
  hit-rate@k và tập câu hỏi đánh giá. Hiện tại report cố ý ghi telemetry gap này.

## 6. Kiểm chứng và lưu ý về thời gian

```powershell
.\.venv\Scripts\python.exe -m pytest tests_observability -q
.\.venv\Scripts\python.exe scripts/run_baseline.py
.\.venv\Scripts\python.exe gx/validate_orders.py
.\.venv\Scripts\dbt.exe build --project-dir dbt_project --profiles-dir dbt_project
```

Freshness test phải inject `freshness.reference_time`; fixture dùng timestamp cố
định nhưng so với wall clock sẽ tự nhiên hết hạn. Production contract không đặt
`reference_time`, vì vậy luôn dùng UTC hiện tại và phát hiện cả dữ liệu stale lẫn
timestamp tương lai quá 5 phút.

