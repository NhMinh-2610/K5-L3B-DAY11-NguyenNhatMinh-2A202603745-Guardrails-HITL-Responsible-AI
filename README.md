# Day 11 — Guardrails, HITL và Responsible AI

## Thông tin bài nộp

- Họ tên: Nguyễn Nhật Minh
- MSSV: 2A202603745
- Lớp: K5-L3B
- Phần thực hiện: CP2–CP4, chọn bonus B1

## Nội dung

Blue sử dụng OpenRouter `liquid/lfm-3-1.7b:free`. Red và Red Advance sử dụng
Gemini `gemini-3.5-flash`.

- **CP2:** phát hiện prompt injection, lọc chủ đề và che secret/PII trong phản hồi.
- **CP3:** ghép rate limiter, guardrails, audit, monitoring và kiểm tra egress.
- **CP4:** thử 5 kỹ thuật tấn công trên Red và Red Advance; lưu kết quả theo từng prompt.

Red Advance giữ nguyên các lớp regex và NeMo self-check. Các module
`src/hitl/`, `src/testing/` và LLM-as-Judge là phần tham khảo theo rubric.

## Cài đặt

Sử dụng Python 3.11. Với đường dẫn OneDrive dài trên Windows, đặt virtualenv
trong LocalAppData và tạo junction `.venv`:

```powershell
$labEnvPath = Join-Path $env:LOCALAPPDATA 'VinBankLab\2A202603745\.venv'
py -3.11 -m venv $labEnvPath
New-Item -ItemType Junction -Path .venv -Target $labEnvPath
.\scripts\python.ps1 -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Bỏ qua bước tạo môi trường nếu `.venv` đã có. Trên Linux hoặc đường dẫn ngắn,
có thể tạo virtualenv trong repo và gọi Python trực tiếp.

Điền key thật trong `.env`; không commit file này:

```dotenv
OPENROUTER_API_KEY=<OpenRouter key>
RED_TEAM_PROVIDER=gemini
GOOGLE_API_KEY=<Google AI Studio key>
GOOGLE_GENAI_USE_VERTEXAI=0
GEMINI_MODEL=gemini-3.5-flash
GEMINI_MIN_INTERVAL_SECONDS=15
GEMINI_MAX_RETRIES=2
GEMINI_MAX_OUTPUT_TOKENS=1024
```

Đề cũng cho phép OpenAI: dùng `RED_TEAM_PROVIDER=openai`,
`OPENAI_API_KEY` và `OPENAI_MODEL=gpt-4o-mini`.

## Chạy bài

Chạy các lệnh từ gốc repo:

```powershell
.\scripts\python.ps1 src/main.py --part 2
.\scripts\python.ps1 src/main.py --part 3
.\scripts\python.ps1 src/main.py --part 4 --resume
```

CP2 chạy offline; CP3 dùng OpenRouter; CP4 dùng provider của Red.
Khi đã có kết quả Blue, chỉ cần chạy lại CP4.

`--resume` dùng lại các prompt đã hoàn tất khi code, model và cấu hình khớp.
Chương trình lưu checkpoint sau mỗi prompt và dừng nếu gặp lỗi API hoặc
NeMo. Khi quota cho phép, chạy lại cùng lệnh để tiếp tục.

Khoảng cách mặc định giữa các lượt Gemini là 15 giây, kể cả NeMo self-check.
Lỗi tạm thời 429/503 được thử lại tối đa 2 lần theo thời gian server trả về.
Quota ngày, quota bằng 0 hoặc thời gian chờ vượt 60 giây sẽ làm chương trình dừng.
Đối chiếu giới hạn thực tế tại [AI Studio](https://aistudio.google.com/rate-limit)
và tăng khoảng cách nếu cần; không chạy nhiều cửa sổ đồng thời.

## Kiểm thử và kết quả

```powershell
.\scripts\python.ps1 -m pytest tests/smoke tests/public -q
.\scripts\python.ps1 scripts/grade.py --submission-dir . --out outputs/grade_report.json
```

Tests dùng model/HTTP giả và thư mục tạm, không gọi API thật. Kết quả nộp bài
trong `outputs/` được tạo từ các lần chạy lab:

| Hạng mục | Kết quả |
|---|---|
| Blue — câu an toàn | 5/5 được cho qua |
| Blue — câu tấn công | 7/7 bị chặn |
| Rate limit — 15 lượt | 10 được nhận, 5 bị chặn |
| Red — 5 prompt | 3 prompt làm lộ secret demo |
| Red Advance — 5 prompt | 5/5 bị chặn, không lộ secret |

Bài kiểm tra rate limit gửi liên tiếp 15 lượt vào bộ kiểm tra đầu vào,
không gọi model, để độ trễ API không ảnh hưởng cửa sổ 60 giây.

Các file cần kiểm tra trước khi nộp:

```text
outputs/
├── results.json
├── audit_log.json
├── metrics.json
├── attack_results.json
├── unsafe_attack_result.json
├── guards_attack_result.json
├── grade_report.json
└── lab_report.md
```

Xem [báo cáo](outputs/lab_report.md) và [kết quả chấm máy](outputs/grade_report.json).
Không sửa tay các file kết quả. Điểm leak và bonus được xác nhận bằng grader replay.

## Tài liệu đề bài

- [Các checkpoint](CHECKPOINTS.md)
- [Rubric](RUBRIC.md)
- [Hướng dẫn nộp](SUBMISSION.md)
- [Quy định lab](RULES.md)
