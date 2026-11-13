# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

> ## Bài làm: corpus quy chế đào tạo đại học (QĐ43/2007 và TT08/2021)
>
> **Corpus:** 2 PDF văn bản quy phạm, 42 trang vật lý, 40 trang nội dung (2 trang scan không OCR). Xem [starter/data/manifest.csv](starter/data/manifest.csv).
> **Embedding:** Gemini `gemini-embedding-001`, 768 chiều (API, cần `GEMINI_API_KEY` trong `starter/.env`). **Store:** PostgreSQL 16 + pgvector 0.8.7, cosine, exact search.
> **Chiến lược:** A = cố định 500/50 · B = theo Điều/khoản/điểm, tối đa 800 · C = B + filter `issued_year`. Chi tiết: [artifacts/experiment_log.csv](artifacts/experiment_log.csv).
>
> **Tái lập** (từ `starter/`, sau khi làm bước 1 của [starter/README.md](starter/README.md); cần mạng để gọi Gemini):
>
> ```bash
> python -m pip install -r requirements.txt          # gồm google-genai
> python scripts/build_manifest.py                   # đo PDF -> data/manifest*.csv
> python ../benchmark/verify_benchmark.py            # kiểm evidence của 20 câu hỏi
> python scripts/build_chunks.py                     # đọc, chuẩn hóa, log trang -> results/chunks_A|B.jsonl
> python scripts/index_chunks.py                     # embed + upsert pgvector (chạy lại = 0 request, không trùng)
> python -m src.run --split dev                      # A/B/C trên 15 câu dev -> results/traces_dev.jsonl
> python -m src.run --split test                     # chỉ sau khi chốt cấu hình -> results/traces_test.jsonl
> python scripts/make_audit_sheets.py                # tạo bảng chấm tay results/audit_*.csv
> python scripts/summarize_audit.py                  # tổng hợp nhãn tay -> results/audit_summary.json
> python scripts/verify_metadata_audit.py            # đối chiếu nhãn metadata với text thô của PDF (không cần API)
> python scripts/view_chunks.py                      # (tùy chọn) xem A/B cạnh nhau: results/chunks_view.html
> ```
>
> **Vị trí bài nộp:** code `starter/src/`, `starter/scripts/` · benchmark `benchmark/` · manifest `starter/data/` · kết quả, trace, nhãn tay `starter/results/` · nhật ký `artifacts/experiment_log.csv` · báo cáo `report/individual/`.

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
