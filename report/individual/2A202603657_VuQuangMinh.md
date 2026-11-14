# Báo cáo cá nhân — Day 6

Vũ Quang Minh · 2A202603657 · L3A. Mọi con số dưới đây lấy từ file trong `starter/results/` và `artifacts/experiment_log.csv`; số nào chưa đo được thì ghi rõ là chưa có.

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang, quy tắc tính trang:** quy chế đào tạo đại học, hai văn bản cùng chủ đề nhưng khác phiên bản.
  - `qd43-2007`: Quyết định 43/2007/QĐ-BGDĐT, bản hợp nhất không chính thức có chú thích sửa đổi theo TT 57/2012 (ins.htu.edu.vn), 20/20 trang tính.
  - `tt08-2021`: Quy chế kèm Thông tư 08/2021/TT-BGDĐT (spnttw.edu.vn), 22 trang vật lý, tính 20 trang (trang 3-22).
  - Tổng **42 trang vật lý, 40 trang nội dung** (≥30), 80.097 ký tự. Quy tắc: trang tính khi văn bản NFC sau cắt khoảng trắng có ≥200 ký tự. Quyền: văn bản quy phạm pháp luật, không thuộc phạm vi bảo hộ quyền tác giả (khoản 2 Điều 15 Luật SHTT). Manifest ghi URL, SHA-256, ngày truy cập, danh sách trang tính/loại: [manifest.csv](../../starter/data/manifest.csv), [manifest_pages.csv](../../starter/data/manifest_pages.csv).
- **Chuẩn hóa, lỗi, giới hạn:** pypdf 6.21.4, NFC, bỏ số trang và chú thích cuối trang QĐ43, giữ ngắt dòng để nhận diện Chương/Điều/khoản. Log từng trang: [ingest_log.csv](../../starter/results/ingest_log.csv).
  - Hai trang đầu của TT08 là ảnh scan, không có lớp chữ, **không OCR** nên bị loại (`no_text_layer`).
  - pypdf chèn khoảng trắng thừa trong từ ("Thông t ư", "ha i"); không có quy tắc sửa an toàn nên giữ nguyên, có thể làm nhiễu embedding.
  - QĐ43 là bản hợp nhất không chính thức, chưa đối chiếu với Văn bản hợp nhất 17/VBHN-BGDĐT. `issued_year = 2007` là năm ban hành gốc, trong khi nội dung đã gồm sửa đổi 2012.
- **Embedding, vector store, lệnh chạy, chi phí:** Gemini `gemini-embedding-001`, 768 chiều, `task_type` RETRIEVAL_DOCUMENT/RETRIEVAL_QUERY, L2-normalize; `google-genai==3.3.0`. PostgreSQL 16 + pgvector 0.8.7 (docker-compose), khoảng cách cosine, tìm kiếm chính xác (không ANN). Lệnh chạy ở [README.md](../../README.md).
  - Ingest (đọc + chuẩn hóa): 1,16 giây. Nạp lại: 0 request, 326/326 chunk bỏ qua vì không đổi, `deleted_obsolete = 0` ([index_log.json](../../starter/results/index_log.json)).
  - **Chi phí tiền và thời gian embedding lần nạp đầu chưa ghi nhận**: file log bị ghi đè bởi lần chạy lại (0 request). Chỉ biết quy mô: 158.273 ký tự chunk (A 80.420 + B 77.853) và 2.196 ký tự câu hỏi (dev 1.617 + test 579). Cần đối chiếu bảng giá/quota Gemini của tài khoản để có con số tiền.
- **Metadata:** bắt buộc `document_id`, `source`, `page` (trang vật lý). Bổ sung `article` (Điều), `issued_year`, `document_type`, `char_start/char_end`.
  - `issued_year` (2007/2021) là trường lọc: lấy từ ngày ban hành trong văn bản, ghi ở manifest. Chọn vì hai quy chế cùng chủ đề, cùng thuật ngữ, khác nội dung (vd. ngưỡng 2,00 so với "dưới điểm trung bình").
  - `article` dùng để truy vết, tính theo Điều chứa ký tự đầu chunk.

## Cấu hình và benchmark

- **A / B / C** ([experiment_log.csv](../../artifacts/experiment_log.csv)):
  - A: cố định 500 ký tự, overlap 50, trong từng trang, không lọc. 178 chunk.
  - B: theo cấu trúc Chương/Điều/khoản/điểm, tối đa 800 ký tự, không trộn hai Điều, chèn tiêu đề `[Điều N. ...]` khi chunk bắt đầu giữa Điều, không lọc. 148 chunk.
  - C: **giống hệt B** (cùng 148 chunk, cùng index), chỉ thêm lọc `issued_year` khi câu hỏi có filter. **Khác biệt duy nhất B–C là filter.**
  - A–B khác nhau ở hai điểm cùng lúc (ranh giới cấu trúc và tiêu đề Điều), nên không tách được đóng góp riêng.
- **Benchmark:** 20 câu ([questions.jsonl](../../benchmark/questions.jsonl)), 15 dev (q01-q15) / 5 test (q16-q20). Loại: trực tiếp, diễn đạt lại, điều kiện/ngoại lệ. **7 câu có filter** (dev q04, q05, q07, q12, q13; test q16, q17); giá trị filter nằm trong câu hỏi ("ban hành năm ...") nên được cung cấp trước truy xuất, không lấy từ gold. Evidence kiểm chứng bằng `benchmark/verify_benchmark.py`: kết quả "Evidence/fields OK" cho 20 câu; câu có nhiều nguồn hợp lệ ghi `alt_gold`.
  - Nguy cơ rò rỉ: các cặp q04/q16 và q05/q17 hỏi cùng chủ đề ở hai phiên bản (một bên dev, một bên test); q16/q17 là cặp đối xứng nhau.
- **Tiêu chí chọn chiến lược (chốt trước khi xem test):** (1) Evidence Hit@3 dev, (2) Hit@1 dev, (3) tuân thủ filter, (4) grounding thủ công, (5) số chunk/thời gian. Bằng chứng thứ tự: benchmark commit lúc 18:10, tiêu chí trong `experiment_log.csv` commit `f969dfb` lúc 19:21, trace test commit lúc 19:26.

## Kết quả

Thời gian là tổng thời gian tìm kiếm pgvector top-3 cho cả split, chưa gồm embedding câu hỏi (dev 1,02 s, test 1,65 s, dùng chung cho A/B/C). Chi phí tiền: chưa ghi nhận (xem trên).

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 8/15 | 11/15 | 178 | 0,402 s | chưa ghi |
| B | dev | 13/15 | 15/15 | 148 | 0,329 s | chưa ghi |
| C | dev | 14/15 | 15/15 | 148 | 0,374 s | chưa ghi |
| A | test | 3/5 | 3/5 | 178 | 0,078 s | chưa ghi |
| B | test | 2/5 | 4/5 | 148 | 0,068 s | chưa ghi |
| C | test | 2/5 | 5/5 | 148 | 0,062 s | chưa ghi |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,00 (10) | 11/15 | 0/2 (không dùng filter) | 0/1/4 → 1,8 |
| B | 1,90 (10) | 15/15 | 0/2 (không dùng filter) | 1/0/4 → 1,6 |
| C | 1,90 (10; dùng chunk của B) | 15/15 | 2/2 | 0/0/5 → 2,0 |

Filter tính trên 2 câu filter của test (q16, q17): top-3 toàn đúng năm hay không. Trên dev, 5 câu filter: A 0/5, B 0/5, C 5/5 ([metrics_dev.json](../../starter/results/metrics_dev.json)).

**Đường dẫn và cách chọn mẫu:**
- Trace top-3 đầy đủ (text, score, metadata): [traces_dev.jsonl](../../starter/results/traces_dev.jsonl), [traces_test.jsonl](../../starter/results/traces_test.jsonl). Chỉ số: [metrics_dev.json](../../starter/results/metrics_dev.json), [metrics_test.json](../../starter/results/metrics_test.json).
- Nhãn thủ công: [audit_coherence.csv](../../starter/results/audit_coherence.csv), [audit_metadata.csv](../../starter/results/audit_metadata.csv), [audit_grounding.csv](../../starter/results/audit_grounding.csv); tổng hợp: [audit_summary.json](../../starter/results/audit_summary.json).
- Mẫu: coherence = 10 vị trí cố định bằng quy tắc "sắp xếp page ID, lấy mỗi trang thứ 4, ký tự giữa trang" (`scripts/make_audit_sheets.py`), chọn trước khi chấm điểm. Metadata = 5 câu test × top-3 × 3 chiến lược = 45 bản ghi. Grounding = 5 câu test × 3 chiến lược = 15 dòng.
- **Người chấm và cách chấm (trung thực về nguồn nhãn):** bảng nhãn bị bỏ trống ở bản nộp đầu. Nhãn được bổ sung trong đợt chữa bài ngày 13/11/2026 bởi **Claude (AI, Sonnet 5.5)** chấm sơ bộ sau khi đọc từng chunk; không phải LLM judge tự động. Metadata được kiểm tra thêm bằng `starter/scripts/verify_metadata_audit.py`, đối chiếu text thô của PDF (page, Điều chứa ký tự đầu, tiêu đề Điều nằm giữa chunk); script cho cùng kết quả với nhãn tay (A 11/15, B 15/15, C 15/15). Ngày 14/11/2026 nhãn được rà soát lần 2: Claude (AI) đọc lại cả 90 nhãn, đồng ý toàn bộ, không đổi điểm; **tác giả đọc đối chiếu các bảng nhãn (`starter/results/audit_*.csv`) và xác nhận**. Ghi chú khi rà soát: (a) ở pos10, vị trí chấm rơi đúng khoảng trắng giữa hai chunk B; script chọn `p19:B:001` vì so sánh `<= char_end` trong khi `char_end` là exclusive. Nếu chấm `p19:B:002` (khoản 6) thì cũng được 2, nên điểm không đổi. (b) `article` được chấm theo tiêu chí "phản ánh nội dung chính của chunk", chặt hơn định nghĩa lưu trữ "Điều chứa ký tự đầu chunk"; 4 bản ghi A bị chấm sai đều là chunk chứa tiêu đề Điều mới. (c) q16 A được 2 dù top-2 là chunk TT08 có quy định khác: thang grounding chỉ đo độ đủ của bằng chứng, nhưng đây là rủi ro nhầm phiên bản khi sinh câu trả lời. Thiên lệch: người chấm đã biết chiến lược và kết quả Hit@3 (không mù); C dùng lại nhãn coherence của B.

## Phân tích và kết luận

- **A–B (đổi cách chia chunk):** Hit@3 dev 11/15 → 15/15, Hit@1 8/15 → 13/15; coherence 1,00 → 1,90; metadata đúng 11/15 → 15/15; chunk 178 → 148. 4 câu dev trượt ở A dù trang gold có trong top-3 (q03, q07, q09, q12) vì evidence bị cắt giữa hai chunk. Chunk A hay cắt giữa từ/số ("dưới 1|,20") và trộn đuôi Điều trước với đầu Điều sau nên `article` chỉ ghi Điều đầu (4/15 bản ghi sai ở test). Nhưng **trên test B không hơn A ở Hit@1** (2/5 so với 3/5) và grounding trung bình của B (1,6) còn thấp hơn A (1,8), vì ở q17 B không lọc năm nên chỉ lấy được chunk sai phiên bản (grounding 0) trong khi A vẫn có một chunk đúng văn bản (grounding 1): n=5 quá nhỏ, chênh 1 câu.
- **B–C (chỉ thêm filter `issued_year`):** Hit@1 dev 13/15 → 14/15, test Hit@3 4/5 → 5/5; filter tuân thủ 0/5 → 5/5 (dev), 0/2 → 2/2 (test); grounding 1,6 → 2,0. Tài nguyên không đổi (cùng 148 chunk). Lợi ích đến từ đúng 1 câu mỗi split (q05 dev, q17 test), không đủ để kết luận về mức độ.
- **Hai ví dụ sai:**
  1. **q17 (test, filter 2021, đáp án `tt08-2021` trang 19, Điều 18):** B không lọc nên top-1/2 là Điều 17 của QĐ43 (bản 2007, ngưỡng "dưới 2,00"), tức sai phiên bản; Hit@3 = 0 và grounding = 0. C lọc năm 2021 đưa trang 19 vào top-2 (Hit@3 đạt) nhưng Hit@1 vẫn 0 vì top-1 là chunk khoản 4-5 cùng Điều 18, không chứa điều kiện ở khoản 3. Filter sửa nhầm phiên bản chứ không sửa xếp hạng trong cùng văn bản.
  2. **q06 (dev, `tt08-2021` trang 13, Điều 10, "Từ 8,0 đến cận 9,0: Giỏi"):** cả A, B, C đều Hit@1 = 0 (hạng 2). Top-1 là chunk trang 12 cùng Điều 10, chứa khoản 5 "xếp loại học lực" nhưng chỉ tới bảng thang điểm 4 (bị cắt hết trang 12); bảng thang điểm 10 là evidence nằm đầu trang 13 (hạng 2). Điều 10 vắt qua hai trang mà chunking cắt ở ranh giới trang nên khoản 5 bị tách đôi. (Tương tự q20 test: B/C top-1 là khoản 3 Điều 17 nói "25%" cho hợp tác đào tạo, evidence ở khoản 2 hạng 2; còn A hạng 1.)
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** theo tiêu chí đã chốt, chọn **C** (Hit@3 dev 15/15 ngang B, Hit@1 14/15 cao nhất, tuân thủ filter 5/5, grounding test 2,0). Đánh đổi: B/C cần parser nhận diện cấu trúc Điều/khoản riêng cho văn bản quy phạm tiếng Việt và vẫn cắt ở ranh giới trang; C cần filter năm được cung cấp trước (nếu người dùng không nêu năm thì C = B). Chỉ áp dụng cho corpus 2 văn bản có cấu trúc Điều rõ ràng; không suy rộng.
- **Hạn chế:**
  - Test chỉ 5 câu, 1 câu bằng 20 điểm phần trăm; dev/test có cặp câu đối xứng (rò rỉ chủ đề).
  - Nhãn thủ công do AI chấm sơ bộ, chưa mù, chưa có người chấm thứ hai; coherence chỉ 10 vị trí.
  - Grounding chỉ đo độ đủ của bằng chứng, không phải độ chính xác câu trả lời LLM.
  - Chưa có chi phí tiền và thời gian embedding lần nạp đầu; thời gian search nhỏ và biến động theo lần chạy.
  - Hit@1 test của B/C thấp hơn A (2/5 so với 3/5): B/C xếp chunk "gần đúng" cùng Điều lên trước chunk đủ evidence.
  - Corpus có 2 trang scan chưa OCR, bản QĐ43 chưa đối chiếu với văn bản hợp nhất chính thức, text còn khoảng trắng chèn thừa.
- **Nếu làm lại / mở rộng:** (1) ghi log embedding riêng cho từng lần chạy, không ghi đè, và ghi chi phí; (2) gộp khoản liền kề thay vì cắt cứng ở ranh giới trang cho Điều vắt trang; (3) OCR 2 trang scan; (4) thêm hybrid BM25 để xếp khoản chứa số liệu ("25%", "30%") lên đầu; (5) viết thêm câu test độc lập và nhờ người thứ hai chấm mù.
- **Công cụ AI (theo RULES):** Claude Code dùng để viết code pipeline, chấm nhãn sơ bộ và soạn báo cáo; kiểm tra bằng cách chạy lại `verify_benchmark.py`, `summarize_audit.py` và `verify_metadata_audit.py`, đối chiếu chunk với PDF thô.
