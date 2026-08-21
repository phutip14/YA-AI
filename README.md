# Discord AI Chatbot (Gemini) 🤖

โปรเจกต์บอต Discord เชื่อมโยงกับ Gemini API เพื่อทำหน้าที่เป็น AI Chatbot โต้ตอบแบบมีบริบทการคุยต่อเนื่อง (Multi-turn conversation)

---

## 🛠️ วิธีการติดตั้งและรันบอต

### 1. ตั้งค่า Workspace ใน IDE ของคุณ
เพื่อการเขียนโค้ดและจัดการไฟล์ที่สะดวกขึ้น แนะนำให้ตั้งค่าโฟลเดอร์นี้เป็น Workspace หลัก:
* เปิด IDE ของคุณ (เช่น VS Code หรือ Cursor)
* เปิดโฟลเดอร์: `C:\Users\ya\.gemini\antigravity\scratch\discord_gemini_bot`

### 2. ติดตั้ง Library ที่จำเป็น (Dependencies)
เปิด Terminal หรือ Command Prompt ในโฟลเดอร์นี้ แล้วรันคำสั่ง:
```bash
pip install -r requirements.txt
```

### 3. ตั้งค่า API Key ของ Gemini
1. ไปสมัครรับ API Key ฟรีที่: [Google AI Studio](https://aistudio.google.com/)
2. เปิดไฟล์ `.env` ในโปรเจกต์นี้
3. แทนที่ตัวอักษร `YOUR_GEMINI_API_KEY_HERE` ด้วย API Key จริงที่คุณได้มา
   * ตัวอย่างในไฟล์ `.env`:
     ```env
     DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE
     GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
     ```

### 4. เปิดใช้งานบอต
รันบอตผ่าน Terminal ด้วยคำสั่ง:
```bash
python bot.py
```

---

## ⚙️ การตั้งค่าที่จำเป็นใน Discord Developer Portal (ห้ามลืม!)
หากเปิดบอตแล้วแชทหาบอตแล้วบอตไม่ตอบ หรือบอตสตาร์ทไม่ผ่าน ให้เช็กสองจุดนี้ใน [Discord Developer Portal](https://discord.com/developers/applications):

1. **เปิด Gateway Intents**:
   * ไปที่ Application ของคุณ -> เมนู **Bot**
   * เลื่อนลงมาหาหัวข้อ **Privileged Gateway Intents**
   * เปิดสวิตช์ **Message Content Intent** (จำเป็นมาก เพื่อให้บอตสามารถมองเห็นข้อความที่พิมพ์ในแชนแนลได้)
   * กด **Save Changes**

2. **สิทธิ์ในการเชิญบอต (Permissions)**:
   * เวลาสร้างลิงก์เชิญ (Invite URL) จากเมนู **Installation** หรือ **OAuth2** ให้เลือก:
     * Scopes: `bot`
     * Bot Permissions: `Send Messages`, `Read Message History`, `View Channel`, `Read Messages/View Channels`

---

## 💬 วิธีการคุยกับบอต
* **ในห้องแชทธรรมดา**: พิมพ์แท็กบอตแล้วตามด้วยข้อความ เช่น `@MyBot ช่วยแต่งกลอนเกี่ยวกับท้องฟ้าหน่อย`
* **ในแชทส่วนตัว (DM)**: สามารถพิมพ์ข้อความคุยได้เลยโดยไม่ต้องแท็กบอต
* บอตจะจำบทสนทนาก่อนหน้าในห้องแชทนั้นๆ ทำให้สามารถคุยโต้ตอบต่อเนื่องกันได้ (จำ Context)
