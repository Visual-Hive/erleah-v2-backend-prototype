# Erleah v2 Backend — Demo Guide

## Hướng dẫn demo cho sếp

Demo chạy qua **server logs** — sếp sẽ xem terminal output để thấy pipeline hoạt động.

---

## 1. Chuẩn bị (trước khi demo)

```bash
# Terminal 1 — Server + pretty logs
# Kill server cũ nếu đang chạy
pkill -f "python -m src.main" 2>/dev/null

# Xoá log cũ
> /tmp/erleah_server.log

# Start server, pipe qua log viewer
.venv/bin/python -m src.main 2>&1 | tee /tmp/erleah_server.log | .venv/bin/python scripts/log_viewer.py
```

```bash
# Terminal 2 — Demo script
bash scripts/demo.sh
```

Mở 2 terminal cạnh nhau: **Terminal 1** (logs, chiếm 70% màn hình) + **Terminal 2** (demo script, 30%).

---

## 2. Kiến trúc — nói trước khi chạy demo

> "Đây là v2 backend, migrate từ n8n sang Python. Pipeline gồm 9 nodes chạy trên LangGraph:"

```
START → fetch_data → [update_profile?] → acknowledgment → plan_queries
     → execute_queries → check_results → [retry?] → generate_response
     → evaluate → END
```

**Key points:**
- **Multi-faceted vectorization**: 1 entity → 8 vectors (không phải 1 monolithic embedding)
- **Paired matching**: `buying_intent ↔ selling_intent`, `services_seeking ↔ services_providing`
- **Scoring formula**: `score = (breadth × 0.4 + depth × 0.6) × 10`
- **Production data**: ~9,500 vectors từ ETL 2025 trên Azure Qdrant
- **3 LLM models**: Claude Sonnet (planning + response), Claude Haiku (evaluation), Grok (acknowledgment)

---

## 3. Chạy từng query — giải thích cho sếp

### Demo 1/5: Exhibitor Faceted Search
**Query:** "Find exhibitors with event registration solutions"

**Sếp cần thấy:**
- NODE 4: Sonnet tạo search plan → `table=exhibitors, mode=faceted`
- NODE 5: Embed query (3072 dims) → search `exhibitors_facets` → 50 raw hits
- Scoring: 34 unique entities, top score ~4.8, formula `(breadth*0.4 + depth*0.6)*10`
- Top 3 results với tên công ty thật (Captello, Jomablue, Nexus...)
- NODE 7: Sonnet generate response ~114 chunks in ~12s

**Talking point:** "Faceted search cho phép match chính xác hơn vì mỗi exhibitor có 8 vector riêng biệt thay vì 1 blob text."

---

### Demo 2/5: Session Search
**Query:** "What sessions cover AI and machine learning?"

**Sếp cần thấy:**
- NODE 4: Plan query → `table=sessions` (khác entity type)
- NODE 5: Search `sessions_facets` → kết quả là tên session thật
- Pipeline tự động chọn đúng collection dựa trên query

**Talking point:** "Pipeline thông minh — Sonnet quyết định search table nào dựa trên intent của user."

---

### Demo 3/5: Speaker Search
**Query:** "Who are the keynote speakers about sustainability?"

**Sếp cần thấy:**
- Search trên `speakers_facets`
- Scoring formula hoạt động với speakers
- Response liệt kê speakers thật từ ETL 2025

**Talking point:** "Cùng pipeline, cùng scoring algorithm, nhưng search trên speaker data."

---

### Demo 4/5: Multi-Table Hybrid Search
**Query:** "I want to learn about event technology trends, any sessions or exhibitors?"

**Sếp cần thấy:**
- NODE 4: Plan **NHIỀU** queries → sessions + exhibitors (2 queries)
- NODE 5: Execute **PARALLEL** — 2 searches chạy cùng lúc
- Results từ 2 tables khác nhau được merge
- Response tổng hợp thông tin từ cả sessions và exhibitors

**Talking point:** "Đây là hybrid mode — pipeline tự biết cần search nhiều bảng và chạy song song."

---

### Demo 5/5: Retry Flow
**Query:** "Are there any exhibitors selling quantum computing hardware?"

**Sếp cần thấy:**
- NODE 5: Search → 0 results (hoặc rất ít)
- NODE 6: `needs_retry=True` → trigger retry
- NODE 6b: `relax_and_retry` — hạ threshold, tăng limit, fallback sang master search
- Có thể loop lại check_results → retry lần 2 với master_fallback
- Response gracefully handles "không tìm thấy chính xác"

**Talking point:** "Pipeline có self-healing — nếu không tìm thấy, tự động nới lỏng search criteria trước khi trả lời."

---

## 4. Metrics nổi bật

| Metric | v1 (n8n) | v2 (Python) |
|--------|----------|-------------|
| User satisfaction | 63% | 89% (projected) |
| Search approach | 1 monolithic embedding | 8 faceted vectors |
| Matching | Generic similarity | Paired facet matching |
| Retry logic | None | Auto-relax threshold |
| Evaluation | None | Real-time Haiku scoring |

---

## 5. Số liệu production data

| Collection | Points |
|---|---|
| `exhibitors_master` | 114 |
| `exhibitors_facets` | 735 |
| `sessions_master` | 82 |
| `sessions_facets` | 492 |
| `speakers_master` | 134 |
| `speakers_facets` | 670 |
| `attendees_master` | ~1,250 |
| `attendees_facets` | ~6,135 |
| **Total** | **~9,478** |

---

## 6. Nếu sếp hỏi

**"Tại sao không dùng 1 vector thôi?"**
> Multi-faceted cho phép match chính xác hơn. Ví dụ: user cần "event registration" → match với `selling_intent` facet của exhibitor, không phải toàn bộ description.

**"Performance?"**
> Pipeline ~12-16s (phần lớn là LLM latency). Qdrant search ~1-2s. First chunk sent trong ~5s.

**"Evaluation node làm gì?"**
> Haiku đánh giá quality + confidence của response (non-blocking, chạy sau khi user đã nhận response). Dùng để monitor và improve prompt quality.

**"Retry logic hoạt động sao?"**
> 3 bước: (1) Hạ score threshold 0.3→0.15, (2) Fallback sang master search, (3) Max 2 retries rồi proceed với kết quả hiện có.

---

## 7. Troubleshooting

| Vấn đề | Cách fix |
|--------|---------|
| Server không start | Check `.env` có đủ API keys |
| 0 search results | Đảm bảo dùng `conference_id: "etl-2025"` |
| Grok acknowledgment failed | Bình thường — xAI key chưa set, dùng fallback |
| Redis warning | Bình thường — Redis optional, app chạy được không có Redis |
