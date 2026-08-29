# Báo cáo sự cố — Data Reliability Game Day

## 1. Mức độ nghiêm trọng

**SEV-2 — ảnh hưởng dữ liệu phân tích, cần chặn downstream output.**

Sự cố trong báo cáo này là fault `volume_drop`, dựa trên public practice fault. Khi giảng viên cung cấp mystery dataset riêng, cần thay phần root cause/evidence cụ thể bằng kết quả điều tra dataset đó.

## 2. Tóm tắt

Batch orders khỏe có 600 dòng. Sau partial ingestion, incoming batch chỉ còn 150 dòng, giảm 75%.

Contract validation không báo lỗi vì các dòng còn lại vẫn đúng schema. Anomaly detector phát hiện volume bất thường bằng MAD với score **13.36**. Điều này chứng minh pipeline `SUCCESS` không đồng nghĩa dữ liệu đúng.

Nếu batch được publish, doanh thu trong `fct_daily_revenue` và CEO dashboard có thể bị thiếu đáng kể.

## 3. Phát hiện và triage

- **Signal đầu tiên:** `row_count_anomaly.is_anomaly = True`.
- **Metric:** số dòng orders trong batch hiện tại.
- **Healthy baseline:** 600 dòng, anomaly `False`.
- **Batch lỗi:** 150 dòng, anomaly `True`, method `auto:mad`, score `13.36`.
- **Contract:** không fail vì volume chưa phải deterministic row-count rule.
- **Quyết định:** không publish batch; quarantine và điều tra ingestion.

## 4. Root cause

Root cause là **partial ingestion**: chỉ 25% số dòng orders được đưa vào incoming dataset.

Các giả thuyết bị loại trừ:

1. Sai schema/type: không phù hợp vì contract checks pass.
2. Duplicate primary key: là failure mode khác, được kiểm tra riêng bằng deterministic validation.
3. Lỗi transformation: chưa có bằng chứng trong batch này; dbt build và unit test pass trên baseline healthy.

Kết luận dựa trên row-count history và các lớp kiểm tra, không dựa trên việc đoán từ fault script trong mystery incident.

## 5. Evidence

1. Healthy baseline:

   ```text
   orders rows              : 600
   contract failed checks   : 0
   row-count anomaly        : False
   freshness minutes        : 5.0
   KB contract failures     : 0
   ```

2. Volume-drop baseline:

   ```text
   orders rows              : 150
   contract failed checks   : 0
   row-count anomaly        : True (auto:mad, score=13.36)
   freshness minutes        : 5.0
   KB contract failures     : 0
   ```

3. dbt build trên baseline healthy: `PASS=18 WARN=0 ERROR=0`, gồm 12 data tests và 1 native unit test.

4. Great Expectations Checkpoint trên batch healthy: `PASS`.

5. Lineage xác định blast radius:

   ```text
   stg_orders
   └── fct_daily_revenue
       └── ceo_revenue_dashboard
   ```

## 6. Blast radius

```text
raw_orders / incoming orders
└── stg_orders
    └── fct_daily_revenue
        └── ceo_revenue_dashboard
```

Consumer ảnh hưởng gồm CEO revenue dashboard và các quyết định kinh doanh dựa trên daily revenue. KB/support-agent không nằm trong blast radius của volume-drop orders.

## 7. Mitigation

1. Chặn publish `fct_daily_revenue` và CEO dashboard.
2. Đưa incoming orders batch vào quarantine.
3. Kiểm tra ingestion source, file completeness và checkpoint cuối.
4. Giữ healthy output gần nhất cho dashboard.
5. Re-run ingestion sau khi xác nhận đủ dữ liệu.

## 8. Recovery

Sau khi reset về healthy baseline:

- Contract: không có failure.
- Anomaly: row-count anomaly `False`.
- KB freshness: không có failure.
- dbt: 18/18 resources pass.
- GX: Checkpoint pass.

## 9. SLO và error budget

Với SLO `99.5%`, 2 bad checks trên 100 checks:

```text
allowed_bad_rate = 1 - 0.995 = 0.005 = 0.5%
actual_bad_rate  = 2 / 100 = 0.02 = 2%
burn_rate        = 0.02 / 0.005 = 4.0
breached         = True
```

Multi-window policy:

- Spike ngắn: short burn cao, long burn thấp → không page.
- Lỗi kéo dài: short burn cao và long burn cao → page, severity `critical`.

## 10. Verification checklist

- [x] Contract healthy sau recovery.
- [x] Type drift được kiểm tra riêng.
- [x] Freshness được kiểm tra với UTC reference time có thể test.
- [x] dbt generic data tests pass.
- [x] dbt singular business tests pass.
- [x] dbt unit test chống revenue inflation pass.
- [x] Anomaly detector bắt được volume drop.
- [x] Distribution drift detector xử lý shape shift ngoài mean ratio.
- [x] Dataset và column lineage transitive hoạt động.
- [x] SLO/error budget/burn rate được tính đúng.
- [x] RAG text-length và embedding-norm signals có implementation.
- [x] GX Suite/ValidationDefinition/Checkpoint chạy pass.
- [x] Public và regression tests pass: `18 passed`.
- [x] Dữ liệu fault đã được reset trước khi nộp.

## 11. Phòng ngừa / action items

| Hành động | Owner | Thời hạn | Lý do |
|---|---|---|---|
| Chạy volume anomaly trước khi publish mart | Data Reliability | Ngay lập tức | Bắt partial ingestion dù schema đúng |
| Block/quarantine khi có critical contract failure | Data Platform | Sprint kế tiếp | Không đưa dữ liệu hỏng xuống downstream |
| Duy trì history theo metric/segment đáng tin cậy | Observability | Sprint kế tiếp | Giảm false positive do seasonality |
| Lưu dbt test failures để điều tra | Analytics Engineering | Sprint kế tiếp | Có record lỗi cụ thể |
| Kiểm tra unique active customer version | Data Modeling | Ngay lập tức | Tránh revenue inflation do join |
| Theo dõi KB freshness và embedding drift | Support AI | Sprint kế tiếp | Tránh dùng policy cũ hoặc index lệch |
| Duy trì incident report và AI decision log | Reliability Team | Mỗi incident | Có audit trail để defend solution |

## 12. Mystery incident

Public `volume_drop` chỉ dùng để xác minh detector và quy trình. Với mystery incident thật, không đọc fault-injection script; cần thay nội dung bằng evidence thực tế cho bảy câu hỏi: what happened, when, root cause, blast radius, mitigation, recovery verification và prevention.
