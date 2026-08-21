# CBTU YA AI Assistant 🤖

บอต AI อัจฉริยะประจำศูนย์บริหารการจัดการองค์กรสากล (CBTU) คณะวิศวกรรมศาสตร์ มหาวิทยาลัยมหิดล ขับเคลื่อนด้วย Google Gemini API และระบบฐานความรู้ไดนามิก (Dynamic Knowledge Base)

---

## 🌟 จุดเด่นและความสามารถ
- **ฐานความรู้เฉพาะทาง (CBTU Knowledge Base)**: บอทอ่านไฟล์ข้อมูลความรู้จากโฟลเดอร์ `knowledge/` โดยอัตโนมัติ ตอบคำถามได้ถูกต้องแม่นยำ
- **รองรับการส่งไฟล์และเอกสาร (Multimodal Support)**: สามารถอัปโหลดไฟล์ Word (.docx), Excel (.xlsx), PDF, รูปภาพ หรือไฟล์ Text ให้บอทอ่านและวิเคราะห์ได้
- **Slash Commands**: มีคำสั่ง `/clear`, `/reload_knowledge`, `/activate`, `/deactivate`, `/help`
- **ระบบ Quota Fallback**: สลับโมเดลสำรองอัตโนมัติเมื่อโมเดลหลักติด Limit

---

## 📁 โครงสร้างคลังความรู้ (`knowledge/`)
```text
knowledge/
├── 00_system_role.md      # บุคลิก กฎการตอบ และ Tone of Voice
├── 01_cbtu_overview.md    # ข้อมูลทั่วไปของศูนย์ CBTU / พันธกิจ
├── 02_courses_services.md # รายละเอียดหลักสูตร อบรม และบริการให้คำปรึกษา
└── 03_faq.md              # คำถาม-คำตอบที่พบบ่อย (Q&A)
```
*สามารถเพิ่มหรือแก้ไขไฟล์ `.md`, `.txt`, `.json` ในโฟลเดอร์ `knowledge/` ได้ตลอดเวลา แล้วใช้คำสั่ง `/reload_knowledge` ใน Discord ได้ทันที*

---

## 🛠️ การติดตั้งและรันในเครื่อง (Local Setup)

1. ติดตั้ง Dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. คัดลอก `.env.example` เป็น `.env` แล้วใส่คีย์:
   ```env
   DISCORD_TOKEN=YOUR_DISCORD_TOKEN
   GEMINI_API_KEY=YOUR_GEMINI_API_KEY
   MODEL_NAME=gemini-2.5-flash
   FALLBACK_MODEL_NAME=gemini-2.0-flash
   ```
3. รันบอต:
   ```bash
   python bot.py
   ```
