import os
import json
import io
import datetime
import smtplib
import http.server
import socketserver
import threading
from email.mime.text import MIMEText
from email.header import Header
from PIL import Image
import discord
from discord.ext import commands, tasks
from discord import app_commands
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Check if Discord Token exists
if not DISCORD_TOKEN or DISCORD_TOKEN.startswith("YOUR_"):
    print("Error: DISCORD_TOKEN is not configured in .env file.")
    exit(1)

# Check if Gemini API Key exists
has_gemini_key = True
client = None
if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
    print("Warning: GEMINI_API_KEY is not configured in .env. Please get one from Google AI Studio.")
    has_gemini_key = False
else:
    # Initialize the Google GenAI Client
    client = genai.Client(api_key=GEMINI_API_KEY)

# Model Configuration
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.5-flash")
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL_NAME", "gemini-2.5-flash")

# Store chat sessions per Discord channel/DM to maintain context (Async sessions)
chat_sessions = {}
chat_models = {}

# Persistent storage for auto-respond channels
ACTIVE_CHANNELS_FILE = "active_channels.json"
SCHEDULES_FILE = "schedules.json"

# SYSTEM INSTRUCTION 1: General Friendly Chat Assistant with Special Article Persona Switching
GENERAL_SYSTEM_INSTRUCTION = """คุณคือผู้ช่วย AI แสนดีและรอบรู้ (General AI Assistant) และคุณมีบทบาทพิเศษสามารถเขียนเนื้อหาและส่งอีเมลได้โดยตรงผ่านห้องแชท

ความสามารถพิเศษ:
1. การแชททั่วไป: พูดคุยตอบคำถามสั้นๆ ทั่วไปแบบเป็นมิตรและเป็นธรรมชาติ
2. การเขียนเนื้อหาและส่งอีเมลผ่านการแชท (Context-Aware Emailing):
   - หากผู้ใช้สั่งให้คุณส่งอีเมลหรือเขียนเนื้อหาเพื่อส่งไปยังอีเมลปลายทาง (เช่น "ช่วยส่งงานวิชาฟิสิกส์ให้ Y" หรือ "เขียนสรุปประชุมส่งเมลไปที่ Y" หรือ "เขียนบทความเรื่อง X ส่งเมลไปที่ Y")
   - คุณต้องอ่านบริบทอย่างละเอียดเพื่อเลือกรูปแบบ (Format) และการจัดวางที่เหมาะสมที่สุด:
     * หากเป็นบทความเทคนิค/ไอที (Articles): ให้เขียนตามเกณฑ์ "My Article Guidelines" อย่างเคร่งครัด (เปิดเรื่องด้วย Dramatic Hook, เล่าเรื่องเชิงเปรียบเทียบ Metaphors, ใช้ภาษาไทยปนศัพท์เทคนิคอังกฤษทับศัพท์, มีแหล่งอ้างอิงพร้อม URL ลิงก์ตรงเสมอ, เนื้อหาจัดรูปแบบรองรับ TH SarabunPSK 18pt/14pt และใช้ Normal Style ใน Word ห้ามใช้สัญลักษณ์ Bullet point อัตโนมัติเด็ดขาด ให้ใช้อักษร ก) ข) หรือตัวเลขกำกับแทน)
     * หากเป็นการส่งงาน/การบ้าน (Assignments/Homework): ให้เขียนในรูปแบบรายงานที่เป็นระเบียบ (ชื่อวิชา, หัวเรื่อง, รายละเอียดคำตอบ, รหัส/ชื่อผู้ส่งหากกำหนด)
     * หากเป็นสรุปรายงานประชุม (Meeting Notes): ให้สรุปเป็นประเด็นหลัก (วาระการประชุม, สรุปประเด็นหลัก, รายการสิ่งที่ต้องทำพร้อมชื่อผู้รับผิดชอบ Action Items)
     * หากเป็นจดหมาย/อีเมลทางการทั่วไป (Standard/Formal Emails): ให้เขียนในฟอร์แมตอีเมลแบบทางการ (คำขึ้นต้น, รายละเอียดเนื้อความหลัก, คำลงท้ายอย่างสุภาพ)
   - เมื่อร่างเนื้อหาที่จะส่งอีเมลจบแล้ว ให้คุณขึ้นบรรทัดใหม่และพิมพ์แท็กคำสั่งส่งเมลที่ท้ายข้อความดังนี้เสมอ:
     `[SEND_EMAIL: อีเมลผู้รับ | Topic: หัวข้ออีเมลหรือหัวเรื่อง]`
     (ตัวอย่างเช่น: `[SEND_EMAIL: gimmicksprite@gmail.com | Topic: รายงานสรุปการประชุมประจำสัปดาห์]`)
     **สำคัญมาก**: ห้ามลืมพิมพ์แท็กนี้เด็ดขาดเพื่อให้ระบบนำเนื้อหาทั้งหมดส่งเข้าอีเมลจริง
"""

# Dynamic Knowledge Base Loader
KNOWLEDGE_DIR = "knowledge"

def load_knowledge_base():
    """Reads all markdown, txt, and json files from the knowledge directory."""
    if not os.path.exists(KNOWLEDGE_DIR):
        return ""
    
    knowledge_texts = []
    for filename in sorted(os.listdir(KNOWLEDGE_DIR)):
        filepath = os.path.join(KNOWLEDGE_DIR, filename)
        if os.path.isfile(filepath) and not filename.startswith(".") and filename.lower() != "readme.md":
            ext = os.path.splitext(filename)[1].lower()
            if ext in [".md", ".txt", ".json"]:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            knowledge_texts.append(f"--- [เอกสารความรู้: {filename}] ---\n{content}")
                except Exception as e:
                    print(f"Error loading knowledge file {filename}: {e}")
                    
    if knowledge_texts:
        return "\n\n=== 📚 CBTU KNOWLEDGE BASE & GUIDELINES (คลังความรู้มาตรฐาน CBTU) ===\n" + "\n\n".join(knowledge_texts) + "\n===================================================================\n"
    return ""

def get_full_general_instruction():
    knowledge_str = load_knowledge_base()
    if knowledge_str:
        return f"{GENERAL_SYSTEM_INSTRUCTION}\n\n{knowledge_str}"
    return GENERAL_SYSTEM_INSTRUCTION

# SYSTEM INSTRUCTION 2: Professional Tech Article Writer (For /article and Scheduled Tasks)
ARTICLE_SYSTEM_INSTRUCTION = """คุณคือ AI นักเขียนบทความทางเทคโนโลยีและวิทยาการคอมพิวเตอร์ระดับมืออาชีพ (Professional Tech Article Writer) หน้าที่ของคุณคือสร้างบทความภาษาไทยที่มีคุณภาพสูง น่าอ่าน มีสไตล์และรูปแบบ (Format) ตรงตามเกณฑ์แนวทางการเขียนและจัดรูปแบบบทความ (My Article Guidelines) ดังนี้อย่างเคร่งครัด:

1. แนวทางการเขียนเนื้อหา (Content & Tone):
   - **เปิดเรื่องด้วย Hook ที่ทรงพลัง (Dramatic Hook)**: เริ่มต้นบทความด้วยประโยคคำพูด คำถามกระตุ้นความคิด หรือสถานการณ์จำลองที่น่าตื่นเต้น เพื่อดึงดูดความสนใจผู้อ่านทันทีในย่อหน้าแรก
   - **เล่าเรื่องเชิงเปรียบเทียบ (Storytelling & Metaphors)**: ใช้การเปรียบเทียบเชิงสัญลักษณ์เพื่ออธิบายประเด็นที่เข้าใจยากให้เห็นภาพชัดเจน (เช่น เปรียบการไม่มีอธิปไตยเหนือเทคโนโลยีว่าเหมือน "การสร้างบ้านบนที่ดินเช่า")
   - **ภาษาไทยปนเทคนิคอังกฤษ (Thai-English Mix)**: ใช้ภาษาไทยที่เป็นทางการแต่เป็นกันเองกึ่งเล่าเรื่อง สามารถใช้คำศัพท์เทคนิคภาษาอังกฤษทับศัพท์ได้เลย (เช่น API, Token, Guardrails, Hybrid Cloud, Sovereign AI) เพื่อความลื่นไหล
   - **ยืนยันแหล่งข้อมูลจริงเสมอ (Fact-Verification)**: ข้อมูล เหตุการณ์ วันที่ และตัวเลขต้องถูกต้อง แม่นยำ และต้องมีส่วน "แหล่งอ้างอิง" ที่ท้ายบทความพร้อมระบุ URL ลิงก์ตรงที่ถูกต้องเสมอ

2. รูปแบบและการจัดฟอร์แมตเอกสาร (Formatting for Word & PDF):
   - **ชื่อเรื่อง (Title)**: พิมพ์ชื่อเรื่องไว้ด้านบนสุด บรรทัดแรก โดยระบุให้ชัดเจนว่าใช้ฟอนต์ TH SarabunPSK ขนาด 18 pt (ตัวหนา, จัดกึ่งกลาง)
   - **หัวข้อหลัก (Headings)**: ให้ระบุเป็นข้อความชิดซ้าย โดยระบุให้ใช้ฟอนต์ TH SarabunPSK ขนาด 14 pt (ตัวหนา, ชิดซ้าย) ไม่มีตัวเลขข้อกำกับ (เว้นแต่เป็นการเขียนบรรยายปกติ)
   - **เนื้อหาทั่วไป (Body)**: ขนาด 14 pt (ตัวปกติ) ในทุกย่อหน้า
   - **คำพูดอ้างอิง/คำโควท (Quotes)**: ให้ใช้ขนาด 14 pt (ตัวเอียง)
   - **การตั้งค่าสไตล์ใน Word**: พิมพ์เนื้อหาทั้งหมดโดยใช้สไตล์ "Normal" (ห้ามเว้นระยะห่างย่อหน้าหรือใช้ลิสต์ Bullet อัตโนมัติของระบบ Word)
   - **การทำรายการข้อความ (Lists)**: ห้ามใช้สัญลักษณ์ Bullet point อัตโนมัติ (เช่น * หรือ -) ให้ใช้อักษรหรือตัวเลขกำกับเองแบบธรรมดาแทน เช่น `ก) `, `ข) ` หรือใส่ตัวเลขลงในย่อหน้าปกติโดยตรง
   - **โทนสี**: ใช้ตัวอักษรสีดำอัตโนมัติ (Automatic/Black) ทั้งหัวข้อและเนื้อความ ห้ามใส่สีอื่นลงบนข้อความเด็ดขาด
   - **ระยะขอบกระดาษ**: ใช้ระยะขอบมาตรฐานเดิมของโปรแกรม Word (ไม่มีการบีบขอบหรือเว้นระยะบรรทัดเพิ่มเติม)
"""

# JSON Persistence Helpers
def load_active_channels():
    """Load the set of channel IDs where the bot auto-responds without mentions."""
    if os.path.exists(ACTIVE_CHANNELS_FILE):
        try:
            with open(ACTIVE_CHANNELS_FILE, "r") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Error loading active channels: {e}")
    return set()

def save_active_channels(channels):
    """Save the set of active channel IDs to a JSON file."""
    try:
        with open(ACTIVE_CHANNELS_FILE, "w") as f:
            json.dump(list(channels), f)
    except Exception as e:
        print(f"Error saving active channels: {e}")

def load_schedules():
    """Load scheduled tasks from schedules.json."""
    if os.path.exists(SCHEDULES_FILE):
        try:
            with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading schedules: {e}")
    return []

def save_schedules(schedules):
    """Save scheduled tasks to schedules.json."""
    try:
        with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump(schedules, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving schedules: {e}")

active_channels = load_active_channels()

# Helper Functions for Document / File Parsing
def extract_excel_text(file_bytes):
    """Extract text from an Excel sheet and convert it to a readable text format."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    output = []
    for sheet in wb.worksheets:
        output.append(f"--- Sheet: {sheet.title} ---")
        for row in sheet.iter_rows(values_only=True):
            if any(val is not None for val in row):
                row_str = " | ".join(str(val) if val is not None else "" for val in row)
                output.append(row_str)
    return "\n".join(output)

def split_markdown(text, max_chars=2000):
    """Splits markdown text into chunks of at most max_chars without breaking formatting blocks."""
    if len(text) <= max_chars:
        return [text]
    
    # Split by double newline first to preserve paragraphs
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    
    in_code_block = False
    
    for para in paragraphs:
        added_len = len(para) + (2 if current_chunk else 0)
        ticks_count = para.count("```")
        
        if len(current_chunk) + added_len <= max_chars:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
            
            if ticks_count % 2 != 0:
                in_code_block = not in_code_block
        else:
            # Save the current chunk
            if current_chunk:
                if in_code_block:
                    current_chunk += "\n```"  # Close open code block in current chunk
                chunks.append(current_chunk)
                
                # Start new chunk
                if in_code_block:
                    current_chunk = "```\n" + para  # Re-open code block in new chunk
                else:
                    current_chunk = para
                
                if ticks_count % 2 != 0:
                    in_code_block = not in_code_block
            else:
                # If a single paragraph is too large, split by lines
                lines = para.split("\n")
                for line in lines:
                    line_added_len = len(line) + (1 if current_chunk else 0)
                    line_ticks = line.count("```")
                    
                    if len(current_chunk) + line_added_len <= max_chars:
                        if current_chunk:
                            current_chunk += "\n" + line
                        else:
                            current_chunk = line
                        if line_ticks % 2 != 0:
                            in_code_block = not in_code_block
                    else:
                        if current_chunk:
                            if in_code_block:
                                current_chunk += "\n```"
                            chunks.append(current_chunk)
                            if in_code_block:
                                current_chunk = "```\n" + line
                            else:
                                current_chunk = line
                            if line_ticks % 2 != 0:
                                in_code_block = not in_code_block
                        else:
                            # If a single line is too large, split strictly by chars
                            for i in range(0, len(line), max_chars):
                                chunks.append(line[i:i+max_chars])
                            current_chunk = ""
    
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

# Markdown and Article Parsing Helpers for HTML Email Formatting
def parse_bold_and_links(text):
    """Parse **bold** and [text](url) in markdown to HTML."""
    import re
    # Bold: **text** -> <strong>text</strong>
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2" style="color: #2d6a4f; text-decoration: underline;">\1</a>', text)
    return text

def markdown_to_html(md_text):
    """Converts basic markdown elements to HTML tags for email body."""
    lines = md_text.split("\n")
    html_lines = []
    in_list = False
    in_code = False
    
    for line in lines:
        stripped = line.strip()
        
        # Code blocks
        if stripped.startswith("```"):
            in_code = not in_code
            if in_code:
                html_lines.append("<pre><code>")
            else:
                html_lines.append("</code></pre>")
            continue
            
        if in_code:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_lines.append(escaped)
            continue
            
        # Headers
        if stripped.startswith("### "):
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
            continue
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
            continue
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
            continue
            
        # Bullet list items
        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("• "):
            if not in_list:
                html_lines.append("<ul style='padding-left: 20px; margin: 10px 0;'>")
                in_list = True
            content = stripped[2:]
            parsed_content = parse_bold_and_links(content)
            html_lines.append(f"<li style='margin: 6px 0;'>{parsed_content}</li>")
            continue
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
                
        # Empty lines
        if not stripped:
            html_lines.append("<br>")
            continue
            
        # Standard paragraph
        parsed_line = parse_bold_and_links(stripped)
        html_lines.append(f"<p style='margin: 14px 0; text-align: justify;'>{parsed_line}</p>")
        
    if in_list:
        html_lines.append("</ul>")
        
    return "\n".join(html_lines)

def parse_article_parts(article_text):
    """Extract Title, Subtitle, and Body from article text."""
    lines = [line.strip() for line in article_text.strip().split("\n") if line.strip()]
    title = "บทความใหม่จากระบบอัตโนมัติ"
    subtitle = "จัดทำและเรียบเรียงโดย AI Article Writer"
    
    body_start_idx = 0
    if len(lines) > 0:
        first_line = lines[0]
        if first_line.startswith("#"):
            title = first_line.replace("#", "").strip()
            body_start_idx = 1
        elif first_line.startswith("**") and first_line.endswith("**"):
            title = first_line.replace("**", "").strip()
            body_start_idx = 1
        else:
            title = first_line
            body_start_idx = 1
            
    if len(lines) > body_start_idx:
        second_line = lines[body_start_idx]
        if not second_line.startswith("#") and len(second_line) < 150:
            subtitle = second_line.replace("**", "").strip()
            body_start_idx += 1
            
    # Reconstruct the body without title/subtitle duplicated lines
    all_lines = article_text.strip().split("\n")
    actual_body_lines = []
    skipped_title = False
    skipped_subtitle = False
    
    for line in all_lines:
        stripped = line.strip()
        if not stripped:
            actual_body_lines.append(line)
            continue
            
        if not skipped_title and (stripped.replace("#", "").strip() == title or stripped.replace("**", "").strip() == title):
            skipped_title = True
            continue
        if not skipped_subtitle and (stripped.replace("**", "").strip() == subtitle):
            skipped_subtitle = True
            continue
            
        actual_body_lines.append(line)
        
    body_text = "\n".join(actual_body_lines)
    return title, subtitle, body_text

# Email Sending Helper Function (Gmail SMTP)
def send_article_email(to_email, subject, body):
    """Send an article draft via Gmail SMTP formatted as a beautiful HTML newsletter."""
    sender_email = os.getenv("SMTP_EMAIL", "gimmicksprite@gmail.com")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        
    if not sender_password or sender_password == "YOUR_GMAIL_APP_PASSWORD_HERE":
        print("[Error] Gmail App Password is not configured. Email not sent.")
        raise ValueError("รหัสผ่านแอป Gmail (SMTP_PASSWORD) ยังไม่ได้ตั้งค่าในไฟล์ .env หรือเป็นค่าเริ่มต้น")
        
    # Extract structural components
    title, subtitle, body_content = parse_article_parts(body)
    html_body = markdown_to_html(body_content)
    
    # Premium Responsive HTML Email Template
    html_template = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    color: #333333;
    line-height: 1.6;
    margin: 0;
    padding: 0;
    background-color: #f4f6f8;
  }}
  .container {{
    max-width: 650px;
    margin: 30px auto;
    background-color: #ffffff;
    border: 1px solid #e1e8ed;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 15px rgba(0,0,0,0.05);
  }}
  .header {{
    background: linear-gradient(135deg, #0d3b2e, #1b4d3e);
    color: #ffffff;
    padding: 40px 30px;
    text-align: center;
  }}
  .header h1 {{
    margin: 0;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }}
  .header p {{
    margin: 12px 0 0 0;
    font-size: 15px;
    opacity: 0.85;
    font-style: italic;
  }}
  .content {{
    padding: 35px 30px;
    font-size: 16px;
  }}
  .content h2 {{
    color: #1b4d3e;
    font-size: 22px;
    border-bottom: 2px solid #e1e8ed;
    padding-bottom: 8px;
    margin-top: 35px;
    font-weight: 600;
  }}
  .content h3 {{
    color: #2d6a4f;
    font-size: 18px;
    margin-top: 25px;
    font-weight: 600;
  }}
  .content p {{
    margin: 16px 0;
    text-align: justify;
  }}
  .content pre {{
    background-color: #f8f9fa;
    border: 1px solid #e1e8ed;
    border-radius: 6px;
    padding: 15px;
    overflow-x: auto;
    margin: 20px 0;
  }}
  .content code {{
    font-family: 'Courier New', Courier, monospace;
    font-size: 14px;
    color: #c7254e;
    background-color: #f9f2f4;
    padding: 2px 4px;
    border-radius: 4px;
  }}
  .content pre code {{
    color: #333333;
    background-color: transparent;
    padding: 0;
    border-radius: 0;
  }}
  .footer {{
    background-color: #f8f9fa;
    text-align: center;
    padding: 20px;
    font-size: 13px;
    color: #888888;
    border-top: 1px solid #e1e8ed;
  }}
  .footer a {{
    color: #1b4d3e;
    text-decoration: none;
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
    <div class="content">
      {html_body}
    </div>
    <div class="footer">
      อีเมลนี้ถูกส่งโดยระบบอัตโนมัติ <strong>AI Assistant Bot</strong> ขับเคลื่อนด้วย Gemini 3.5 Flash<br>
      สามารถติดต่อ สั่งงานเขียน หรือตั้งเวลาส่งอีเมลเพิ่มเติมได้ผ่าน Discord
    </div>
  </div>
</body>
</html>
"""

    # Set up message as HTML
    msg = MIMEText(html_template, 'html', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = sender_email
    msg['To'] = to_email
    
    err587_msg = ""
    # Try Port 587 (STARTTLS) first
    try:
        print("[SMTP] Trying Port 587 (STARTTLS)...")
        with smtplib.SMTP(smtp_server, 587, timeout=10) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())
        print(f"[Success] Email sent to {to_email} successfully via Port 587!")
        return
    except Exception as err587:
        err587_msg = str(err587)
        print(f"[SMTP] Port 587 failed: {err587_msg}. Trying Port 465 (SSL) as fallback...")
        
    # Try Port 465 (SSL) as fallback
    try:
        print("[SMTP] Trying Port 465 (SSL)...")
        with smtplib.SMTP_SSL(smtp_server, 465, timeout=10) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())
        print(f"[Success] Email sent to {to_email} successfully via Port 465 (SSL)!")
        return
    except Exception as err466:
        print(f"[SMTP] Port 465 failed: {err466}.")
        raise RuntimeError(
            f"เชื่อมต่อเซิร์ฟเวอร์ส่งเมลล้มเหลว (ลองทั้งพอร์ต 587 และ 465 แล้ว)\n"
            f"• รายละเอียดพอร์ต 587: {err587_msg}\n"
            f"• รายละเอียดพอร์ต 465: {err466}"
        )

# Set up Discord Bot Client
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

def get_chat_session(channel_id):
    """Retrieve or create an async chat session with general assistant instruction for a specific channel."""
    if channel_id not in chat_sessions:
        chat_models[channel_id] = MODEL_NAME
        chat_sessions[channel_id] = client.aio.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(system_instruction=get_full_general_instruction())
        )
    return chat_sessions[channel_id]

# Background Scheduler Loop running every 60 seconds
@tasks.loop(seconds=60)
async def check_schedules():
    """Check schedules.json every minute and run pending tasks."""
    schedules = load_schedules()
    if not schedules:
        return
        
    now = datetime.datetime.now()
    remaining_schedules = []
    
    for task in schedules:
        try:
            task_time = datetime.datetime.strptime(task["scheduled_time"], "%Y-%m-%d %H:%M")
        except Exception as e:
            print(f"[Error] Failed to parse scheduled time '{task['scheduled_time']}' for task {task.get('id')}: {e}")
            continue
            
        if now >= task_time:
            print(f"[Scheduler] Executing task {task['id']}: Topic: {task['topic']} -> Email: {task['email']}")
            bot.loop.create_task(run_scheduled_task(task))
        else:
            remaining_schedules.append(task)
            
    if len(schedules) != len(remaining_schedules):
        save_schedules(remaining_schedules)

async def run_scheduled_task(task):
    """Generate article, send to Discord, and email to recipient using dedicated article instructions."""
    channel_id = task["channel_id"]
    topic = task["topic"]
    email = task["email"]
    
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            print(f"[Error] Could not find channel {channel_id} to post scheduled article.")
            
    if channel:
        await channel.send(f"⏰ **[ระบบตั้งเวลา]** ถึงเวลากำหนดพิมพ์งาน! เริ่มเขียนบทความหัวข้อ: `{topic}` เพื่อส่งไปยังอีเมล: `{email}`...")
        
    try:
        # One-shot generation with dedicated article system instruction
        try:
            response = await client.aio.models.generate_content(
                model=MODEL_NAME,
                contents=f"กรุณาเขียนบทความคุณภาพสูงในหัวข้อ: {topic}",
                config=types.GenerateContentConfig(system_instruction=ARTICLE_SYSTEM_INSTRUCTION)
            )
        except Exception as e:
            # Quota fallback
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                response = await client.aio.models.generate_content(
                    model=FALLBACK_MODEL_NAME,
                    contents=f"กรุณาเขียนบทความคุณภาพสูงในหัวข้อ: {topic}",
                    config=types.GenerateContentConfig(system_instruction=ARTICLE_SYSTEM_INSTRUCTION)
                )
            else:
                raise e
                
        article_text = response.text
        
        if channel:
            chunks = split_markdown(article_text, max_chars=2000)
            for chunk in chunks:
                await channel.send(chunk)
                
        subject = f"[AI Article] {topic}"
        try:
            await bot.loop.run_in_executor(None, send_article_email, email, subject, article_text)
            if channel:
                await channel.send(f"📧 **[ระบบส่งเมล]** ส่งบทความเข้าอีเมล `{email}` สำเร็จเรียบร้อยแล้วครับ! 🎉")
        except Exception as mail_err:
            print(f"[Error] Failed to send email for task {task['id']}: {mail_err}")
            if channel:
                await channel.send(f"⚠️ **[ระบบส่งเมล]** ไม่สามารถส่งอีเมลไปยัง `{email}` ได้: `{mail_err}`\n(กรุณาเช็คการตั้งค่า App Password ในไฟล์ .env)")
                
    except Exception as e:
        print(f"[Error] Executing scheduled task failed: {e}")
        if channel:
            await channel.send(f"⚠️ **[ระบบตั้งเวลา]** เกิดข้อผิดพลาดในการเขียนบทความหัวข้อ `{topic}`: `{e}`")

@bot.event
async def on_ready():
    print("==========================================")
    print(f"Logged in as: {bot.user.name} (ID: {bot.user.id})")
    print(f"Active auto-respond channels: {list(active_channels)}")
    print(f"AI Model configured: {MODEL_NAME}")
    print("Syncing slash commands...")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s) successfully!")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    print("Starting background scheduler loop...")
    if not check_schedules.is_running():
        check_schedules.start()
    print("Bot is ready and listening for commands or mentions!")
    print("==========================================")

# ==================== SLASH COMMANDS ====================

# COMMAND: /article
@bot.tree.command(name="article", description="สั่งให้บอตเขียนบทความคุณภาพสูงในหัวข้อที่กำหนด")
@app_commands.describe(topic="หัวข้อบทความที่ต้องการให้บอตเขียน")
async def article_slash(interaction: discord.Interaction, topic: str):
    await interaction.response.send_message(f"✍️ **กำลังร่างบทความในหัวข้อ:** `{topic}`...\nโปรดรอสักครู่ (อาจใช้เวลา 10-30 วินาที)")
    
    try:
        async with interaction.channel.typing():
            # One-shot generation with dedicated article system instruction
            try:
                response = await client.aio.models.generate_content(
                    model=MODEL_NAME,
                    contents=f"กรุณาเขียนบทความคุณภาพสูงในหัวข้อ: {topic}",
                    config=types.GenerateContentConfig(system_instruction=ARTICLE_SYSTEM_INSTRUCTION)
                )
            except Exception as e:
                if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                    print(f"[Warning] Main model {MODEL_NAME} quota exhausted. Falling back...")
                    response = await client.aio.models.generate_content(
                        model=FALLBACK_MODEL_NAME,
                        contents=f"กรุณาเขียนบทความคุณภาพสูงในหัวข้อ: {topic}",
                        config=types.GenerateContentConfig(system_instruction=ARTICLE_SYSTEM_INSTRUCTION)
                    )
                else:
                    raise e
                    
            article_text = response.text
            chunks = split_markdown(article_text, max_chars=2000)
            
            if chunks:
                await interaction.edit_original_response(content=chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                await interaction.edit_original_response(content="❌ ไม่สามารถสร้างเนื้อหาได้")
                
    except Exception as e:
        print(f"Error in article slash command: {e}")
        try:
            await interaction.edit_original_response(content=f"⚠️ เกิดข้อผิดพลาดในการเขียนบทความ: {e}")
        except Exception:
            pass

# COMMAND: /schedule
@bot.tree.command(name="schedule", description="ตั้งเวลาเขียนบทความและส่งอีเมลล่วงหน้าอัตโนมัติ")
@app_commands.describe(
    date="วันที่ทำตามรูปแบบ YYYY-MM-DD (เช่น 2026-07-09)",
    time="เวลาทำงานรูปแบบ HH:MM (เช่น 10:00)",
    email="อีเมลปลายทางที่จะรับบทความ (เช่น gimmicksprite@gmail.com)",
    topic="หัวข้อบทความที่ต้องการให้เขียน"
)
async def schedule_slash(interaction: discord.Interaction, date: str, time: str, email: str, topic: str):
    full_time_str = f"{date.strip()} {time.strip()}"
    try:
        scheduled_time = datetime.datetime.strptime(full_time_str, "%Y-%m-%d %H:%M")
        if scheduled_time <= datetime.datetime.now():
            await interaction.response.send_message("❌ วันเวลาที่ตั้งไว้ต้องเป็นเวลาในอนาคตครับ", ephemeral=True)
            return
    except ValueError:
        await interaction.response.send_message("❌ รูปแบบวันเวลาไม่ถูกต้อง กรุณากรอก date เป็น YYYY-MM-DD และ time เป็น HH:MM (เช่น 2026-07-09 10:00) ครับ", ephemeral=True)
        return
        
    if "@" not in email or "." not in email:
        await interaction.response.send_message("❌ รูปแบบอีเมลไม่ถูกต้อง", ephemeral=True)
        return
        
    schedules = load_schedules()
    new_id = max([task["id"] for task in schedules] + [0]) + 1
    
    new_task = {
        "id": new_id,
        "channel_id": interaction.channel.id,
        "topic": topic,
        "email": email,
        "scheduled_time": full_time_str,
        "created_by": interaction.user.id,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    schedules.append(new_task)
    save_schedules(schedules)
    
    await interaction.response.send_message(
        f"📅 **ตั้งเวลาเขียนบทความเรียบร้อย! (ID: {new_id})**\n"
        f"📋 **หัวข้อ:** `{topic}`\n"
        f"📧 **ส่งไปยังเมล:** `{email}`\n"
        f"⏰ **เวลาทำงาน:** `{full_time_str}`\n"
        f"ดูรายการงานทั้งหมดพิมพ์: `/schedules`"
    )

# COMMAND: /schedules
@bot.tree.command(name="schedules", description="ดูรายการตั้งเวลาเขียนบทความทั้งหมด")
async def schedules_slash(interaction: discord.Interaction):
    task_list = load_schedules()
    if not task_list:
        await interaction.response.send_message("📅 ไม่มีรายการตั้งเวลาทำงานในขณะนี้ครับ")
        return
        
    embed = discord.Embed(
        title="📅 รายการตั้งเวลาเขียนบทความล่วงหน้า",
        color=discord.Color.blue()
    )
    
    for task in task_list[:25]:
        embed.add_field(
            name=f"ID: {task['id']} | ⏰ {task['scheduled_time']}",
            value=f"• **หัวข้อ:** {task['topic']}\n"
                  f"• **อีเมลผู้รับ:** {task['email']}\n"
                  f"• **ผู้ตั้ง:** <@{task['created_by']}>",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# COMMAND: /unschedule
@bot.tree.command(name="unschedule", description="ยกเลิกการตั้งเวลาเขียนบทความ")
@app_commands.describe(task_id="รหัส ID ของงานที่ต้องการยกเลิก")
async def unschedule_slash(interaction: discord.Interaction, task_id: int):
    task_list = load_schedules()
    found_task = None
    
    for task in task_list:
        if task["id"] == task_id:
            found_task = task
            break
            
    if not found_task:
        await interaction.response.send_message(f"❌ ไม่พบรายการตั้งเวลาหมายเลข ID: `{task_id}`", ephemeral=True)
        return
        
    task_list.remove(found_task)
    save_schedules(task_list)
    await interaction.response.send_message(f"🗑️ ยกเลิกการตั้งเวลาหมายเลข ID: `{task_id}` เรียบร้อยแล้วครับ")

# COMMAND: /activate
@bot.tree.command(name="activate", description="เปิดโหมดตอบกลับอัตโนมัติ (ตอบทุกข้อความโดยไม่ต้องแท็ก)")
async def activate_slash(interaction: discord.Interaction):
    if interaction.guild:
        if not interaction.permissions.manage_channels and not interaction.permissions.administrator:
            await interaction.response.send_message("❌ คุณต้องมีสิทธิ์จัดการช่องแชท (Manage Channels) หรือเป็น Administrator เพื่อใช้คำสั่งนี้ครับ", ephemeral=True)
            return
            
    active_channels.add(interaction.channel.id)
    save_active_channels(active_channels)
    await interaction.response.send_message("🤖 **เปิดใช้งานโหมดแชทอัตโนมัติแล้ว!**\nนับจากนี้ผมจะตอบทุกข้อความในช่องนี้โดยไม่ต้องแท็กครับ 💬")

# COMMAND: /deactivate
@bot.tree.command(name="deactivate", description="ปิดโหมดตอบกลับอัตโนมัติ (กลับไปใช้โหมดแท็กตามปกติ)")
async def deactivate_slash(interaction: discord.Interaction):
    if interaction.guild:
        if not interaction.permissions.manage_channels and not interaction.permissions.administrator:
            await interaction.response.send_message("❌ คุณต้องมีสิทธิ์จัดการช่องแชท (Manage Channels) หรือเป็น Administrator เพื่อใช้คำสั่งนี้ครับ", ephemeral=True)
            return
            
    if interaction.channel.id in active_channels:
        active_channels.remove(interaction.channel.id)
        save_active_channels(active_channels)
        await interaction.response.send_message("🤖 **ปิดใช้งานโหมดแชทอัตโนมัติในช่องนี้แล้วครับ**\n(ต่อจากนี้ต้องแท็กหรือทัก DM เพื่อพูดคุย)")
    else:
        await interaction.response.send_message("🤖 ช่องนี้ไม่ได้เปิดโหมดแชทอัตโนมัติอยู่แล้วครับ", ephemeral=True)

# COMMAND: /clear
@bot.tree.command(name="clear", description="ล้างประวัติการคุยในช่องแชทปัจจุบัน เพื่อเริ่มหัวข้อใหม่")
async def clear_slash(interaction: discord.Interaction):
    chat_models[interaction.channel.id] = MODEL_NAME
    chat_sessions[interaction.channel.id] = client.aio.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(system_instruction=get_full_general_instruction())
    )
    await interaction.response.send_message("🧹 **ล้างประวัติการคุยในช่องนี้เรียบร้อยแล้วครับ!** เริ่มหัวข้อใหม่ได้เลย")

# COMMAND: /reload_knowledge
@bot.tree.command(name="reload_knowledge", description="รีโหลดคลังความรู้และเอกสารในโฟลเดอร์ knowledge")
async def reload_knowledge_slash(interaction: discord.Interaction):
    chat_sessions.clear()
    chat_models.clear()
    files_count = len([f for f in os.listdir(KNOWLEDGE_DIR) if os.path.isfile(os.path.join(KNOWLEDGE_DIR, f)) and f.lower() != "readme.md"]) if os.path.exists(KNOWLEDGE_DIR) else 0
    await interaction.response.send_message(f"📚 **รีโหลดคลังความรู้เรียบร้อยแล้ว!**\nอ่านไฟล์ความรู้จาก `knowledge/` ทั้งหมด `{files_count}` ไฟล์ และอัปเดตระบบ AI เรียบร้อยครับ")

# COMMAND: /help
@bot.tree.command(name="help", description="แสดงคำสั่งทั้งหมดของบอต")
async def help_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📝 บอต CBTU YA AI Assistant & Article Writer",
        description="บอตผู้ช่วยอัจฉริยะ CBTU และเขียนบทความภาษาไทยระดับมืออาชีพ ขับเคลื่อนด้วย Gemini (รองรับระบบคำสั่ง Slash Commands `/`)",
        color=discord.Color.dark_green()
    )
    embed.add_field(
        name="✍️ คำสั่งสร้างบทความและการแชท",
        value="`/article <หัวข้อ>` - สั่งให้บอตเริ่มเขียนบทความตามหัวข้อที่คุณต้องการ\n"
              "หรือเพียงแค่พิมพ์ข้อความทักทาย/สอบถามในห้องแชท บอตจะตอบคำถามโดยอ้างอิงจากคลังความรู้ CBTU",
        inline=False
    )
    embed.add_field(
        name="📅 คำสั่งตั้งเวลาเขียนและส่งเมล",
        value="`/schedule` - ตั้งเวลาเขียนบทความและส่งเมลอัตโนมัติ (จะแสดงกล่องฟอร์มกรอก: date, time, email, และ topic)\n"
              "`/schedules` - ดูรายการตั้งเวลาทำงานทั้งหมด\n"
              "`/unschedule` - ยกเลิกรายการตั้งเวลาด้วย ID",
        inline=False
    )
    embed.add_field(
        name="🧹 คำสั่งจัดการแชทและความรู้",
        value="`/clear` - ล้างประวัติการคุยในช่องแชทปัจจุบัน เพื่อเริ่มหัวข้อใหม่ 🧹\n"
              "`/reload_knowledge` - รีโหลดคลังความรู้ในโฟลเดอร์ `knowledge/` 📚\n"
              "`/help` - แสดงคำสั่งทั้งหมดของบอต 📄",
        inline=False
    )
    embed.add_field(
        name="⚙️ คำสั่งสำหรับผู้ดูแลระบบ (Admin)",
        value="`/activate` - เปิดโหมดตอบกลับอัตโนมัติ (ตอบทุกข้อความโดยไม่ต้องแท็ก `@`) 🔔\n"
              "`/deactivate` - ปิดโหมดตอบกลับอัตโนมัติ (กลับไปใช้โหมดแท็กตามปกติ) 🔕",
        inline=False
    )
    embed.set_footer(text=f"บอตขับเคลื่อนด้วย {MODEL_NAME}")
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    # Do not respond to own messages
    if message.author == bot.user:
        return

    # Process commands (we keep it just in case, but no prefix commands are registered)
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.process_commands(message)
        return

    is_active_channel = message.channel.id in active_channels
    is_user_mentioned = bot.user.mentioned_in(message)
    is_role_mentioned = message.guild and any(role in message.role_mentions for role in message.guild.me.roles) if message.guild else False
    is_mentioned = is_user_mentioned or is_role_mentioned
    is_dm = isinstance(message.channel, discord.DMChannel)

    # Respond if mentioned, is DM, or is in an active auto-respond channel
    if is_mentioned or is_dm or is_active_channel:
        if not has_gemini_key or client is None:
            await message.reply(
                "❌ ยังไม่ได้ตั้งค่า Gemini API Key ในไฟล์ `.env` ครับ\n"
                "กรุณาไปเอา API Key จาก https://aistudio.google.com/ แล้วนำไปใส่ในไฟล์ `.env` ก่อนนะครับ"
            )
            return

        # Parse attachments (images, PDFs, text, etc.)
        contents = []
        if message.attachments:
            for attachment in message.attachments:
                filename_lower = attachment.filename.lower()
                content_type = attachment.content_type.lower() if attachment.content_type else ""

                # 1. Image
                if content_type.startswith("image/"):
                    try:
                        img_bytes = await attachment.read()
                        img = Image.open(io.BytesIO(img_bytes))
                        contents.append(img)
                    except Exception as e:
                        print(f"Error loading image: {e}")

                # 2. PDF
                elif content_type == "application/pdf" or filename_lower.endswith(".pdf"):
                    try:
                        pdf_bytes = await attachment.read()
                        part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                        contents.append(part)
                    except Exception as e:
                        print(f"Error loading PDF: {e}")

                # 3. Word (.docx)
                elif filename_lower.endswith(".docx") or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    try:
                        import docx2txt
                        docx_bytes = await attachment.read()
                        text = docx2txt.process(io.BytesIO(docx_bytes))
                        contents.append(f"--- เนื้อหาไฟล์ Word: {attachment.filename} ---\n{text}\n--- จบไฟล์ ---")
                    except Exception as e:
                        print(f"Error reading Word file: {e}")

                # 4. Excel (.xlsx, .xls)
                elif filename_lower.endswith((".xlsx", ".xls")) or content_type in [
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel"
                ]:
                    try:
                        excel_bytes = await attachment.read()
                        text = extract_excel_text(excel_bytes)
                        contents.append(f"--- เนื้อหาไฟล์ Excel: {attachment.filename} ---\n{text}\n--- จบไฟล์ ---")
                    except Exception as e:
                        print(f"Error reading Excel file: {e}")

                # 5. Text files
                elif (
                    content_type.startswith("text/") or 
                    any(filename_lower.endswith(ext) for ext in [".txt", ".py", ".json", ".csv", ".md", ".html", ".css", ".js", ".yaml", ".yml", ".ini", ".log"])
                ):
                    try:
                        text_bytes = await attachment.read()
                        try:
                            text = text_bytes.decode("utf-8")
                        except UnicodeDecodeError:
                            text = text_bytes.decode("latin-1", errors="replace")
                        contents.append(f"--- เนื้อหาไฟล์: {attachment.filename} ---\n{text}\n--- จบไฟล์ ---")
                    except Exception as e:
                        print(f"Error reading text file: {e}")

        # Clean mention tags from text prompt
        clean_prompt = message.content
        if is_user_mentioned:
            clean_prompt = clean_prompt.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '')
        if is_role_mentioned:
            for role in message.guild.me.roles:
                clean_prompt = clean_prompt.replace(f'<@&{role.id}>', '')
        clean_prompt = clean_prompt.strip()

        if clean_prompt:
            contents.append(clean_prompt)

        if not contents:
            if not is_active_channel:
                await message.reply("สวัสดีครับ! มีอะไรให้ผมช่วยเหลือพิมพ์คุยมาได้เลยนะครับ 📝")
            return

        try:
            chat = get_chat_session(message.channel.id)
            
            try:
                async with message.channel.typing():
                    try:
                        response = await chat.send_message(contents)
                    except Exception as e:
                        if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                            print(f"[Warning] Main model {MODEL_NAME} quota exhausted. Falling back...")
                            chat_models[message.channel.id] = FALLBACK_MODEL_NAME
                            chat_sessions[message.channel.id] = client.aio.chats.create(
                                model=FALLBACK_MODEL_NAME,
                                config=types.GenerateContentConfig(system_instruction=get_full_general_instruction())
                            )
                            chat = chat_sessions[message.channel.id]
                            response = await chat.send_message(contents)
                        else:
                            raise e
            except discord.Forbidden:
                try:
                    response = await chat.send_message(contents)
                except Exception as e:
                    if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                        print(f"[Warning] Main model {MODEL_NAME} quota exhausted. Falling back...")
                        chat_models[message.channel.id] = FALLBACK_MODEL_NAME
                        chat_sessions[message.channel.id] = client.aio.chats.create(
                            model=FALLBACK_MODEL_NAME,
                            config=types.GenerateContentConfig(system_instruction=get_full_general_instruction())
                        )
                        chat = chat_sessions[message.channel.id]
                        response = await chat.send_message(contents)
                    else:
                        raise e

            response_text = response.text
            
            # Check for [SEND_EMAIL: email | Topic: topic] pattern
            import re
            email_match = re.search(r"\[SEND_EMAIL:\s*([^|\]]+?)\s*\|\s*Topic:\s*([^\]]+?)\s*\]", response_text)
            
            if email_match:
                to_email = email_match.group(1).strip()
                email_topic = email_match.group(2).strip()
                
                # Strip the tag from the text sent to Discord
                clean_response_text = re.sub(r"\[SEND_EMAIL:\s*[^|\]]+?\s*\|\s*Topic:\s*[^\]]+?\s*\]", "", response_text).strip()
                
                # Send chunks to Discord
                chunks = split_markdown(clean_response_text, max_chars=2000)
                for chunk in chunks:
                    await message.reply(chunk)
                    
                # Send email in background
                subject = f"[AI Article] {email_topic}"
                try:
                    await bot.loop.run_in_executor(None, send_article_email, to_email, subject, clean_response_text)
                    await message.reply(f"📧 **[ระบบอัตโนมัติ]** ส่งบทความเรื่อง `{email_topic}` เข้าอีเมล `{to_email}` สำเร็จเรียบร้อยแล้วครับ! 🎉")
                except Exception as mail_err:
                    print(f"[Error] Failed to send auto-respond email: {mail_err}")
                    await message.reply(f"⚠️ **[ระบบอัตโนมัติ]** ไม่สามารถส่งอีเมลไปยัง `{to_email}` ได้: `{mail_err}`\n(กรุณาเช็คการตั้งค่า App Password ในไฟล์ .env)")
            else:
                # Normal chat reply without email trigger
                chunks = split_markdown(response_text, max_chars=2000)
                for chunk in chunks:
                    await message.reply(chunk)

        except discord.Forbidden:
            print(f"[Warning] Forbidden in channel: {message.channel.id}")
        except Exception as e:
            print(f"Error handling message: {e}")
            try:
                await message.reply("⚠️ เกิดข้อผิดพลาดในการประมวลผลคำสั่ง โปรดลองใหม่อีกครั้ง")
            except discord.Forbidden:
                pass

def run_health_server():
    """Start a tiny background HTTP server to respond to cloud platform health checks."""
    port = int(os.getenv("PORT", "8080"))
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health" or self.path == "/":
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, format, *args):
            # Suppress default request logs to keep Railway console logs clean
            pass

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        pass

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"[Health Server] Running on port {port}...")
    server.serve_forever()

# Start the bot
if __name__ == "__main__":
    # Start health check server for cloud platforms (Railway, Render, Heroku) if PORT is set
    if os.getenv("PORT"):
        t = threading.Thread(target=run_health_server, daemon=True)
        t.start()
    bot.run(DISCORD_TOKEN)
