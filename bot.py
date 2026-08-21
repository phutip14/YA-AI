import os
import json
import io
import datetime
import http.server
import socketserver
import threading
from PIL import Image
import discord
from discord.ext import commands
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
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash")
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL_NAME", "gemini-2.0-flash")

# Store chat sessions per Discord channel/DM to maintain context (Async sessions)
chat_sessions = {}
chat_models = {}

# Persistent storage for auto-respond channels
ACTIVE_CHANNELS_FILE = "active_channels.json"
KNOWLEDGE_DIR = "knowledge"

# Base fallback instruction in case knowledge folder is empty
BASE_SYSTEM_INSTRUCTION = """คุณคือ CBTU YA AI ผู้ช่วย AI ประจำศูนย์บริหารการจัดการองค์กรสากล (Center of Business Transformation and Universal Management - CBTU) คณะวิศวกรรมศาสตร์ มหาวิทยาลัยมหิดล
หน้าที่ของคุณคือตอบคำถามและให้ข้อมูลเกี่ยวกับศูนย์ CBTU, การจัดฝึกอบรม, หลักสูตร Upskill/Reskill, In-House Training, การขอใบเสนอราคา และการบริการวิชาการ อย่างสุภาพ เป็นมิตร และถูกต้องตามคลังความรู้"""

def load_knowledge_base():
    """Reads all markdown, txt, and json files from the knowledge directory in sorted order."""
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
                            knowledge_texts.append(f"--- [Knowledge File: {filename}] ---\n{content}")
                except Exception as e:
                    print(f"Error loading knowledge file {filename}: {e}")
                    
    if knowledge_texts:
        return "\n\n=== 📚 CBTU KNOWLEDGE BASE & GUIDELINES ===\n" + "\n\n".join(knowledge_texts) + "\n=========================================\n"
    return ""

def get_full_system_instruction():
    """Combines base instructions with all knowledge base files."""
    knowledge_str = load_knowledge_base()
    if knowledge_str:
        return f"{BASE_SYSTEM_INSTRUCTION}\n\n{knowledge_str}"
    return BASE_SYSTEM_INSTRUCTION

# JSON Persistence Helpers
def load_active_channels():
    """Load the set of channel IDs where the bot auto-responds without mentions."""
    if os.path.exists(ACTIVE_CHANNELS_FILE):
        try:
            with open(ACTIVE_CHANNELS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Error loading active channels: {e}")
    return set()

def save_active_channels(channels):
    """Save the set of active channel IDs to a JSON file."""
    try:
        with open(ACTIVE_CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(channels), f)
    except Exception as e:
        print(f"Error saving active channels: {e}")

active_channels = load_active_channels()

# Document / File Parsing Helpers
def extract_excel_text(file_bytes):
    """Extract text from an Excel sheet and convert it to a readable text format."""
    try:
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
    except Exception as e:
        return f"Error extracting Excel text: {e}"

def split_markdown(text, max_chars=2000):
    """Splits markdown text into chunks of at most max_chars without breaking paragraphs."""
    if len(text) <= max_chars:
        return [text]
    
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        added_len = len(para) + (2 if current_chunk else 0)
        if len(current_chunk) + added_len <= max_chars:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
        else:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            if len(para) <= max_chars:
                current_chunk = para
            else:
                lines = para.split("\n")
                for line in lines:
                    if len(current_chunk) + len(line) + 1 <= max_chars:
                        if current_chunk:
                            current_chunk += "\n" + line
                        else:
                            current_chunk = line
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = line
    
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

# Discord Bot Client Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

def get_chat_session(channel_id):
    """Retrieve or create an async chat session with knowledge-injected instructions."""
    if channel_id not in chat_sessions:
        chat_models[channel_id] = MODEL_NAME
        chat_sessions[channel_id] = client.aio.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(system_instruction=get_full_system_instruction())
        )
    return chat_sessions[channel_id]

# Discord Events & Slash Commands
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    print(f"Active auto-respond channels: {list(active_channels)}")
    print("CBTU YA AI Bot is ready to answer questions using knowledge base!")

# COMMAND: /activate
@bot.tree.command(name="activate", description="เปิดโหมดตอบกลับอัตโนมัติ (ตอบทุกข้อความโดยไม่ต้องแท็ก)")
async def activate_slash(interaction: discord.Interaction):
    active_channels.add(interaction.channel.id)
    save_active_channels(active_channels)
    await interaction.response.send_message("🤖 **เปิดใช้งานโหมดแชทอัตโนมัติในช่องนี้แล้วครับ!**\n(บอตจะตอบทุกข้อความในช่องนี้โดยไม่ต้องแท็ก `@`)")

# COMMAND: /deactivate
@bot.tree.command(name="deactivate", description="ปิดโหมดตอบกลับอัตโนมัติ (กลับไปใช้โหมดแท็กตามปกติ)")
async def deactivate_slash(interaction: discord.Interaction):
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
        config=types.GenerateContentConfig(system_instruction=get_full_system_instruction())
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
        title="🤖 CBTU YA AI Assistant",
        description="ผู้ช่วย AI ประจำศูนย์บริหารการจัดการองค์กรสากล (CBTU) คณะวิศวกรรมศาสตร์ ม.มหิดล ขับเคลื่อนด้วย Gemini",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="💬 วิธีการใช้งาน",
        value="• พิมพ์สอบถามข้อมูลเกี่ยวกับศูนย์ CBTU, หลักสูตรฝึกอบรม, In-House Training, การขอใบเสนอราคา ฯลฯ ได้ทันที\n"
              "• ในห้องทั่วไป: แท็ก `@บอต` เพื่อพูดคุย\n"
              "• ในห้องแชทส่วนตัว (DM): ทักคุยได้เลยโดยตรง",
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
    embed.set_footer(text=f"บอตขับเคลื่อนด้วยโมเดล {MODEL_NAME}")
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    # Do not respond to own messages
    if message.author == bot.user:
        return

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
                "❌ ยังไม่ได้ตั้งค่า Gemini API Key ใน Environment Variables ครับ"
            )
            return

        # Parse attachments (images, PDFs, Word, Excel, Text)
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
                await message.reply("สวัสดีครับ! มีอะไรให้ CBTU YA AI ช่วยเหลือ สอบถามข้อมูลได้เลยนะครับ 🤖")
            return

        try:
            chat = get_chat_session(message.channel.id)
            
            try:
                async with message.channel.typing():
                    try:
                        response = await chat.send_message(contents)
                    except Exception as e:
                        if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                            print(f"[Warning] Main model {MODEL_NAME} quota exhausted. Falling back to {FALLBACK_MODEL_NAME}...")
                            chat_models[message.channel.id] = FALLBACK_MODEL_NAME
                            chat_sessions[message.channel.id] = client.aio.chats.create(
                                model=FALLBACK_MODEL_NAME,
                                config=types.GenerateContentConfig(system_instruction=get_full_system_instruction())
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
                        print(f"[Warning] Main model {MODEL_NAME} quota exhausted. Falling back to {FALLBACK_MODEL_NAME}...")
                        chat_models[message.channel.id] = FALLBACK_MODEL_NAME
                        chat_sessions[message.channel.id] = client.aio.chats.create(
                            model=FALLBACK_MODEL_NAME,
                            config=types.GenerateContentConfig(system_instruction=get_full_system_instruction())
                        )
                        chat = chat_sessions[message.channel.id]
                        response = await chat.send_message(contents)
                    else:
                        raise e

            response_text = response.text
            chunks = split_markdown(response_text, max_chars=2000)
            for chunk in chunks:
                await message.reply(chunk)

        except discord.Forbidden:
            print(f"[Warning] Forbidden in channel: {message.channel.id}")
        except Exception as e:
            print(f"Error handling message: {e}")
            try:
                await message.reply("⚠️ เกิดข้อผิดพลาดในการประมวลผลคำถาม โปรดลองใหม่อีกครั้งครับ")
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
            pass

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        pass

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"[Health Server] Running on port {port}...")
    server.serve_forever()

# Start the bot
if __name__ == "__main__":
    if os.getenv("PORT"):
        t = threading.Thread(target=run_health_server, daemon=True)
        t.start()
    bot.run(DISCORD_TOKEN)
