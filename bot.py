import json
import logging
import os
import random
import sqlite3
import threading
from io import BytesIO
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Remedial Matrix Quiz Bot is running successfully!"

# ─── DATABASE SETUP ───
DB_FILE = "bot_database.db"
TUTORIAL_GROUP_ID = -1003196904052  
ADMIN_ID = 6183608197

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            is_premium INTEGER DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0
        )
    ''')
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN total_score INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN total_quizzes INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN vip_expiry TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
        
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leaderboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            score INTEGER,
            subject TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def db_add_user(user_id, full_name, username, referred_by=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()
    
    if not exists:
        cursor.execute("INSERT INTO users (user_id, full_name, username, is_premium, referred_by, referral_count) VALUES (?, ?, ?, 0, ?, 0)", 
                       (user_id, full_name, username, referred_by))
        if referred_by and referred_by != user_id:
            cursor.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (referred_by,))
            cursor.execute("SELECT referral_count FROM users WHERE user_id = ?", (referred_by,))
            ref_row = cursor.fetchone()
            # ሪፈራል መስፈርት ከ 30 ወደ 50 አድጓል
            if ref_row and ref_row[0] >= 50:
                cursor.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (referred_by,))
        conn.commit()
    conn.close()

def db_set_premium(user_id, status=1):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_premium = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

def db_is_premium(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1

def db_get_referral_count(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT referral_count FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def db_update_user_score(user_id, score_added):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET total_score = total_score + ?, total_quizzes = total_quizzes + 1 WHERE user_id = ?", (score_added, user_id))
    conn.commit()
    conn.close()

def db_get_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 0")
    free_count = cursor.fetchone()[0]
    cursor.execute("SELECT user_id, full_name, username, is_premium, referral_count FROM users")
    rows = cursor.fetchall()
    conn.close()
    users_list = [f"ID: {row[0]} | Name: {row[1]} | Username: @{row[2] or 'None'} | Status: {'[VIP]' if row[3]==1 else '[Free]'} | Refs: {row[4]}" for row in rows]
    return total_users, premium_count, free_count, users_list

def db_get_users_by_type(is_prem):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_premium = ?", (1 if is_prem else 0,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def db_add_leaderboard(name, score, subject):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO leaderboard (user_name, score, subject) VALUES (?, ?, ?)", (name, score, subject))
    conn.commit()
    conn.close()

def db_get_leaderboard():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_name, score, subject FROM leaderboard ORDER BY score DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "score": r[1], "subject": r[2]} for r in rows]

# ───────────────────────────────

def load_questions():
    if os.path.exists("questions.json"):
        with open("questions.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

user_quiz_sessions = {}

def get_all_questions_for_subject(data, subject):
    all_qs = []
    subject_lower = subject.lower()
    for cat in ["model_exams", "remedial_exams"]:
        if cat in data:
            for year, subjects in data[cat].items():
                for s_name, q_list in subjects.items():
                    if s_name.lower() == subject_lower or (subject_lower in ["math", "maths"] and s_name.lower() in ["math", "maths", "mathematics"]):
                        all_qs.extend(q_list)
    for k, q_list in data.items():
        if isinstance(q_list, list) and subject_lower in k.lower():
            all_qs.extend(q_list)
    return all_qs

def parse_question_data(q):
    q_text = q.get("question", "ጥያቄ አልተገኘም")
    options_raw = q.get("options", [])
    if isinstance(options_raw, dict): options_list = list(options_raw.values())
    elif isinstance(options_raw, list): options_list = options_raw
    else: options_list = ["Option A", "Option B", "Option C", "Option D"]

    correct_id = q.get("correct_option_id", None)
    if correct_id is None:
        answer_letter = q.get("answer", q.get("correct", 0))
        if isinstance(answer_letter, str):
            correct_id = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}.get(answer_letter.upper(), 0)
        elif isinstance(answer_letter, int): correct_id = answer_letter
        else: correct_id = 0

    if not isinstance(correct_id, int) or correct_id < 0 or correct_id >= len(options_list): correct_id = 0
    return q_text, options_list, correct_id, q.get("explanation", "")

async def check_and_update_membership(user_id, context):
    try:
        member = await context.bot.get_chat_member(chat_id=TUTORIAL_GROUP_ID, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            db_set_premium(user_id, 1)
            return True
    except Exception:
        pass
    return False

def get_main_keyboard(is_admin):
    keyboard = [
        [KeyboardButton("📝 Model Exam"), KeyboardButton("🏛 Remedial National Exam 🔒")],
        [KeyboardButton("🎯 Exam Trainer Quiz"), KeyboardButton("📚 Tutorial PDF & Video / Class 🔒")],
        [KeyboardButton("🏫 Private Tutorial Class ምዝገባ")], 
        [KeyboardButton("👥 ሪፈራል (Invite & VIP)"), KeyboardButton("💎 VIP / ፕሪሚየም ለመሆን")],
        [KeyboardButton("🔥 የዕለቱ ጥያቄ"), KeyboardButton("🏆 Leaderboard")],
        [KeyboardButton("📊 የኔ ፕሮፋይል"), KeyboardButton("📢 ቻናል እና ግሩፕ")],
        [KeyboardButton("👨‍💻 Contact Admin")]
    ]
    if is_admin: keyboard.append([KeyboardButton("⚙️ Admin Control")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def add_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        db_set_premium(target_id, 1)
        await update.message.reply_text(f"✅ ተጠቃሚ {target_id} በተሳካ ሁኔታ VIP ሆኗል!")
        await context.bot.send_message(chat_id=target_id, text="🎉 **እንኳን ደስ አለዎት!** አድሚኑ የ VIP ፕሪሚየም አባልነትዎን ከፍቶልዎታል!", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ አጠቃቀም: /addvip <የተጠቃሚው_ID_ቁጥር>")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    referred_by = None
    if context.args:
        try:
            ref = int(context.args[0])
            if ref != user.id: referred_by = ref
        except ValueError: pass

    db_add_user(user.id, user.full_name, user.username, referred_by)
    await check_and_update_membership(user.id, context)

    if chat.type in ["group", "supergroup"]:
        await update.message.reply_text(f"ሰላም {user.first_name}! 🎓 እባክዎ ሙሉውን አገልግሎት ለማግኘት ወደ ፕራይቬት ቦታችን ይምጡ 👇\n\n👉 [@{context.bot.username}](https://t.me/{context.bot.username})", parse_mode="Markdown")
        return

    banner_text = (
        "🌟━━━━━━━━━━━━━━━━━━🌟\n"
        "   🎓 **REMEDIAL MATRIX** 🎓\n"
        "      *የስኬትዎ መንገድ!* 🚀\n"
        "🌟━━━━━━━━━━━━━━━━━━🌟\n\n"
        f"👋 እንኳን ደህና መጡ, **{user.first_name}**!\n\n"
        "📌 *ማስታወሻ:* በ 🔒 ምልክት የተደረገባቸው አገልግሎቶች ለ **VIP / Premium** አባላት ብቻ ክፍት ናቸው።"
    )
    
    is_prot = False if user.id == ADMIN_ID else True
    await update.message.reply_text(banner_text, reply_markup=get_main_keyboard(user.id == ADMIN_ID), parse_mode="Markdown", protect_content=is_prot)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]: return

    db_add_user(user.id, user.full_name, user.username)
    await check_and_update_membership(user.id, context)
    is_prot = False if user.id == ADMIN_ID else True

    # Broadcast Check (ይህ ፎቶ ከማየቱ በፊት ስለሚሰራ የ Broadcast ፍሰትን አይቆርጥም)
    if user.id == ADMIN_ID and user.id in user_quiz_sessions.get("broadcasting_mode", set()):
        target_group = user_quiz_sessions.pop("broadcasting_target", "all")
        user_quiz_sessions["broadcasting_mode"].remove(user.id)
        
        recipients = db_get_users_by_type(is_prem=True) if target_group == "vip" else db_get_users_by_type(is_prem=False)
        success_count = 0
        for uid in recipients:
            try:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                success_count += 1
            except Exception: pass
        await update.message.reply_text(f"✅ ብሮድካስቱ በተሳካ ሁኔታ ለ **{success_count}** ተጠቃሚዎች ተልኳል!")
        return

    # Payment Screenshot handler
    if update.message.photo:
        photo_file = update.message.photo[-1].file_id
        approval_kb = [
            [InlineKeyboardButton("✅ Approve (አጽድቅ)", callback_data=f"approve|{user.id}"), InlineKeyboardButton("❌ Dismiss (ውድቅ)", callback_data=f"dismiss|{user.id}")]
        ]
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo_file,
            caption=f"🚨 **አዲስ የክፍያ ስክሪንሾት መጣ!**\n\n👤 ስም: {user.full_name}\n🆔 ID: `{user.id}`\nዩዘርናም: @{user.username or 'None'}",
            reply_markup=InlineKeyboardMarkup(approval_kb), parse_mode="Markdown"
        )
        await update.message.reply_text("✅ ስክሪንሾትዎ ለአድሚን ተልኳል! ክፍያዎ ተረጋግጦ ፕሪሚየም አካውንትዎ በቅርቡ ይከፈታል።", protect_content=is_prot)
        return

    text = update.message.text
    if not text: return

    # Auto-Update Menu
    if text not in ["/start", "📝 Model Exam", "🏛 Remedial National Exam 🔒", "🎯 Exam Trainer Quiz", "📚 Tutorial PDF & Video / Class 🔒", "🏫 Private Tutorial Class ምዝገባ", "👥 ሪፈራል (Invite & VIP)", "💎 VIP / ፕሪሚየም ለመሆን", "🔥 የዕለቱ ጥያቄ", "🏆 Leaderboard", "📊 የኔ ፕሮፋይል", "📢 ቻናል እና ግሩፕ", "👨‍💻 Contact Admin", "⚙️ Admin Control"]:
        await update.message.reply_text("👇 እባክዎ ከታች ካለው ሜኑ የሚፈልጉትን ይምረጡ:", reply_markup=get_main_keyboard(user.id == ADMIN_ID))

    if text == "📝 Model Exam":
        keyboard = [[InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"), InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")], [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]]
        await update.message.reply_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=is_prot)

    elif text == "🏛 Remedial National Exam 🔒":
        if db_is_premium(user.id):
            keyboard = [[InlineKeyboardButton("📅 2015", callback_data="rem_year_2015"), InlineKeyboardButton("📅 2016", callback_data="rem_year_2016")],
                        [InlineKeyboardButton("📅 2017", callback_data="rem_year_2017"), InlineKeyboardButton("📅 2018", callback_data="rem_year_2018")],
                        [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]]
            await update.message.reply_text("🔓 **ፕሪሚየም ነዎት!** እባክዎ የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=is_prot)
        else:
            await update.message.reply_text("ሰላም! ፕሪሚየም ተጠቃሚ አይደሉም። VIP ለመሆን ከሜኑ ላይ 💎 VIP የሚለውን ይጫኑ።", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 VIP / ፕሪሚየም ለመሆን", callback_data="vip_info")]]), protect_content=is_prot)

    elif text == "📚 Tutorial PDF & Video / Class 🔒":
        if await check_and_update_membership(user.id, context) or db_is_premium(user.id):
            await update.message.reply_text("🎓📚 **የፕሪሚየም ትምህርት ማዕከል እና ቪዲዮ/PDF ሊንክዎ፦**\nhttps://t.me/+yQdJM7LxN8VmNWY0", parse_mode="Markdown", protect_content=is_prot)
        else:
            await update.message.reply_text("ሰላም! የፕሪሚየም ግሩፓችን አባል አይደሉም። በመጀመሪያ ይጋብዙ ወይም ፕሪሚየም ይግዙ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 VIP / ፕሪሚየም ለመሆን", callback_data="vip_info")]]), protect_content=is_prot)

    elif text == "🏫 Private Tutorial Class ምዝገባ":
        keyboard = [
            [InlineKeyboardButton("🧬 Natural Science", callback_data="tut_reg_nat")],
            [InlineKeyboardButton("🌍 Social Science", callback_data="tut_reg_soc")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("የትኛውን የትምህርት ዘርፍ (Stream) መመዝገብ ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard), protect_content=is_prot)

    elif text == "💎 VIP / ፕሪሚየም ለመሆን":
        vip_text = (
            "💎 **የ VIP / ፕሪሚየም አባልነት መረጃ** 💎\n\n"
            "1️⃣ **50 የ 2019 Remedial ተማሪዎችን** ይጋብዙ (በራስ-ሰር ቪአይፒ ይሆናሉ!)\n"
            "2️⃣ የኛን Private Tutorial Group ይቀላቀሉ\n"
            "3️⃣ **300 ብር** ብቻ በባንክ ይክፈሉ:\n\n"
            "🏦 **CBE:** `1000667301673`\n"
            "📱 **TELEBIRR:** `0929698365`\n"
            "💵 ከፍለው **የክፍያ ስክሪንሾት (Screenshot)** በቀጥታ እዚህ ይላኩ!"
        )
        await update.message.reply_text(vip_text, parse_mode="Markdown", protect_content=is_prot)

    elif text == "📊 የኔ ፕሮፋይል":
        conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
        cursor.execute("SELECT total_score, total_quizzes, is_premium, vip_expiry FROM users WHERE user_id = ?", (user.id,))
        row = cursor.fetchone(); conn.close()
        if row:
            t_score, t_quizzes, is_prem, expiry = row
            profile_text = f"👤 **ስም:** {user.full_name}\n🆔 **ID:** `{user.id}`\n🔰 **ደረጃ:** {'💎 VIP Premium' if is_prem == 1 else '🆓 Free Member'}\n\n🎯 **የተሳተፉባቸው ፈተናዎች:** {t_quizzes or 0}\n✅ **ትክክለኛ መልሶች ድምር:** {t_score or 0}"
            await update.message.reply_text(profile_text, parse_mode="Markdown", protect_content=is_prot)

    elif text == "🔥 የዕለቱ ጥያቄ":
        q_data = load_questions()
        all_qs = []
        for s in ["Biology", "Chemistry", "Physics", "Maths", "English", "Geography", "History"]:
            all_qs.extend(get_all_questions_for_subject(q_data, s))
        if not all_qs:
            await update.message.reply_text("⚠️ ጥያቄዎች አልተገኙም!", protect_content=is_prot)
            return
        random.shuffle(all_qs)
        selected_daily_qs = all_qs[:min(20, len(all_qs))]
        await update.message.reply_text(f"🔥 **የዕለቱ ፈተና ተጀምሯል!** 🚀", parse_mode="Markdown", protect_content=is_prot)
        for idx, q in enumerate(selected_daily_qs, 1):
            q_text_raw, options_list, correct_id, explanation_raw = parse_question_data(q)
            await context.bot.send_poll(
                chat_id=update.effective_chat.id, question=f"[{idx}/{len(selected_daily_qs)}] {q_text_raw}",
                options=[str(opt)[:100] for opt in options_list], is_anonymous=False, type="quiz", correct_option_id=correct_id,
                explanation=explanation_raw if explanation_raw else None, protect_content=is_prot
            )

    elif text == "👥 ሪፈራል (Invite & VIP)":
        ref_count = db_get_referral_count(user.id)
        ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
        ref_text = (
            "👥 **የሪፈራል ፕሮግራም** 👥\n\n"
            "📌 **መስፈርት:** 50 ትክክለኛ የ 2019 Remedial ተማሪዎችን መጋበዝ አለብዎት።\n"
            "(ማሳሰቢያ፡ የውሸት አካውንት ወይም ሌላ ተማሪ መጋበዝ አይቻልም!)\n\n"
            f"📊 **የጋበዟቸው ተማሪዎች:** `{ref_count} / 50`\n\n"
            "🔗 **ልዩ መጋበዣ ሊንክ:**\n"
            f"`{ref_link}`\n"
        )
        await update.message.reply_text(ref_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 ሊንኩን ኮፒ አድርግ", callback_data=f"copy_ref|{ref_link}")]]), parse_mode="Markdown", protect_content=False)

    elif text == "🎯 Exam Trainer Quiz":
        keyboard = [[InlineKeyboardButton("🧬 Biology", callback_data="trainer|Biology"), InlineKeyboardButton("🧪 Chemistry", callback_data="trainer|Chemistry")],
                    [InlineKeyboardButton("📚 English", callback_data="trainer|English"), InlineKeyboardButton("📜 History", callback_data="trainer|History")],
                    [InlineKeyboardButton("📐 Maths", callback_data="trainer|Maths"), InlineKeyboardButton("🌍 Geography", callback_data="trainer|Geography"), InlineKeyboardButton("⚡ Physics", callback_data="trainer|Physics")],
                    [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]]
        await update.message.reply_text("🎯 **Exam Trainer Quiz** - ትምህርት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=is_prot)

    elif text == "🏆 Leaderboard":
        lb_list = db_get_leaderboard()
        if not lb_list: await update.message.reply_text("🏆 እስካሁን የሊደርቦርድ መረጃ የለም።", protect_content=is_prot)
        else:
            lb_text = "🏆 **Top 10 Students Leaderboard** 🏆\n\n"
            for i, st in enumerate(lb_list, 1): lb_text += f"{i}. {st['name']} - *{st['score']} ነጥብ* ({st['subject']})\n"
            await update.message.reply_text(lb_text, parse_mode="Markdown", protect_content=is_prot)

    elif text == "📢 ቻናል እና ግሩፕ":
        text_links = (
            "📢 **የኛን ቻናል እና ግሩፕ በመቀላቀል መረጃዎችን በፍጥነት ያግኙ!**\n\n"
            "1️⃣ **ቻናል:** [REMEDIAL MATRIX](https://t.me/REMEDIAL_MATRIX)\n"
            "2️⃣ **ግሩፕ:** [ADDIS REMEDIAL Chat](https://t.me/ADDIS_REMEDIAL_Chat)"
        )
        await update.message.reply_text(text_links, parse_mode="Markdown", disable_web_page_preview=True)

    elif text == "👨‍💻 Contact Admin":
        await update.message.reply_text("👨‍💻 **የአድሚን ማነጋገሪያ:**\n@rmedial_matrix_support", parse_mode="Markdown", protect_content=is_prot)

    elif text == "⚙️ Admin Control" and user.id == ADMIN_ID:
        total_count, prem_count, free_count, _ = db_get_stats()
        admin_kb = [[InlineKeyboardButton("📄 ተጠቃሚዎችን በ TXT አውርድ", callback_data="download_users_txt")],
                    [InlineKeyboardButton("📢 Broadcast to VIP", callback_data="bc_vip"), InlineKeyboardButton("📢 Broadcast to Free", callback_data="bc_free")]]
        admin_text = f"⚙️ **Admin Control Panel**\n\n👥 ጠቅላላ: **{total_count}**\n💎 VIP: **{prem_count}**\n🆓 ነፃ: **{free_count}**"
        await update.message.reply_text(admin_text, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data; user = query.from_user

    if data.startswith("copy_ref|"):
        await query.answer(text=f"ሊንኩ ተኮርጇል: {data.split('|')[1]}", show_alert=True)
        return
    await query.answer()

    if data == "close_menu":
        await query.message.delete()
        return

    # Tutorial Registration Callbacks
    elif data == "tut_reg_nat":
        text = "🧬 **Natural Science Package**\n\n📌 ኮርሶች፦ Biology, Chemistry, English, Physics, እና Mathematics\n\n✅ የሁሉም ኮርሶች Short Notes, PDFs, እና Video Tutorials ሙሉ በሙሉ ተካተዋል!\n\nአሁን ትመዘገባለህ?"
        kb = [[InlineKeyboardButton("✅ አዎ፣ አሁን እመዘገባለሁ", callback_data="vip_info")], [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return
        
    elif data == "tut_reg_soc":
        text = "🌍 **Social Science Package**\n\n📌 ኮርሶች፦ Geography, History, Mathematics, እና English\n\n✅ የሁሉም ኮርሶች Short Notes, PDFs, እና Video Tutorials ሙሉ በሙሉ ተካተዋል!\n\nአሁን ትመዘገባለህ?"
        kb = [[InlineKeyboardButton("✅ አዎ፣ አሁን እመዘገባለሁ", callback_data="vip_info")], [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    elif data == "vip_info":
        vip_text = (
            "💎 **ክፍያ ለመፈፀም** 💎\n\n"
            "እባክዎ **300 ብር** ከታች ባሉት አማራጮች ይክፈሉ:\n\n"
            "🏦 **CBE:** `1000667301673`\n"
            "📱 **TELEBIRR:** `0929698365`\n\n"
            "💵 ከፍለው እንደጨረሱ **የክፍያ ስክሪንሾት (Screenshot)** ፎቶውን በቀጥታ እዚሁ ይላኩልኝ!"
        )
        await query.message.reply_text(vip_text, parse_mode="Markdown")
        return

    elif data == "download_users_txt" and user.id == ADMIN_ID:
        _, _, _, users_list_rows = db_get_stats()
        bio = BytesIO(("\n".join(users_list_rows)).encode("utf-8")); bio.name = "users.txt"
        await context.bot.send_document(chat_id=user.id, document=InputFile(bio), caption="📋 ተጠቃሚዎች")
        return

    elif data in ["bc_vip", "bc_free"] and user.id == ADMIN_ID:
        user_quiz_sessions.setdefault("broadcasting_mode", set()).add(user.id)
        user_quiz_sessions["broadcasting_target"] = "vip" if data == "bc_vip" else "free"
        await query.message.reply_text("📢 መላክ የሚፈልጉትን መልዕክት፣ ፎቶ ወይም ዶክመንት አሁን ይላኩሱልኝ:")
        return

    elif data.startswith("approve|") or data.startswith("dismiss|"):
        if user.id != ADMIN_ID: return
        action, target_id_str = data.split("|"); target_id = int(target_id_str)
        if action == "approve":
            db_set_premium(target_id, 1)
            await context.bot.send_message(chat_id=target_id, text="🎉 **ክፍያዎ ጸድቋል!** አሁን ፕሪሚየም ነዎት!", protect_content=True)
            try: await query.message.edit_caption(caption=query.message.caption + "\n\n✅ **Status: APPROVED**")
            except Exception: pass
        else:
            await context.bot.send_message(chat_id=target_id, text="❌ የክፍያ ስክሪንሾትዎ ውድቅ ተደርጓል። እባክዎ አድሚኑን ያነጋግሩ @rmedial_matrix_support", protect_content=True)
            try: await query.message.edit_caption(caption=query.message.caption + "\n\n❌ **Status: DISMISSED**")
            except Exception: pass
        return

    elif data == "back_to_main":
        await query.message.delete()
        return

    elif data.startswith("trainer|"):
        subject = data.split("|")[1]
        all_subject_qs = get_all_questions_for_subject(load_questions(), subject)
        if not all_subject_qs:
            await query.message.reply_text(f"⚠️ ጥያቄ አልተገኘም!")
            return
        random.shuffle(all_subject_qs)
        selected_qs = all_subject_qs[:min(len(all_subject_qs), random.randint(30, 60))]
        user_quiz_sessions[user.id] = {"subject": subject, "questions": selected_qs, "index": 0, "score": 0, "total": len(selected_qs)}
        await send_trainer_question(context, query.message.chat_id, user.id)
        return

    if data.startswith("t_ans|"):
        parts = data.split("|")
        user_id = int(parts[1]); selected_option = int(parts[2])
        session = user_quiz_sessions.get(user_id)
        if not session:
            await query.message.reply_text("⚠️ የፈተና ጊዜዎ አልቋል።")
            return

        q_list = session["questions"]; idx = session["index"]
        _, _, correct_id, _ = parse_question_data(q_list[idx])
        if selected_option == correct_id: session["score"] += 1
        session["index"] += 1

        if session["index"] < len(q_list):
            await send_trainer_question(context, query.message.chat_id, user_id)
        else:
            score = session["score"]; total = session["total"]
            db_add_leaderboard(user.full_name, score, session['subject'])
            db_update_user_score(user_id, score) # ውጤት ትራክ ማድረግ
            
            percentage = (score / total) * 100
            feedback = "🌟 ድንቅ ስራ!" if percentage >= 80 else ("👍 ጥሩ ጥረት!" if percentage >= 50 else "⚠️ በድጋሚ ይሞክሩ!")
            await query.message.reply_text(f"🎯 **ውጤትዎ**\n\n📚 ትምህርት: *{session['subject']}*\n✅ ትክክል: **{score} / {total}**\n📊 መቶኛ: **{percentage:.1f}%**\n\n{feedback}", parse_mode="Markdown")
            if user_id in user_quiz_sessions: del user_quiz_sessions[user_id]
        return

async def send_trainer_question(context, chat_id, user_id):
    session = user_quiz_sessions.get(user_id)
    if not session: return
    q = session["questions"][session["index"]]
    q_text, options_list, _, _ = parse_question_data(q)
    
    keyboard = [[InlineKeyboardButton(f"{chr(65 + i)}. {opt}", callback_data=f"t_ans|{user_id}|{i}")] for i, opt in enumerate(options_list)]
    await context.bot.send_message(
        chat_id=chat_id, text=f"🎯 **Exam Trainer** [{session['index'] + 1}/{session['total']}]\n\n❓ *{q_text}*",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=(chat_id != ADMIN_ID)
    )

def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN: return print("BOT_TOKEN አልተገኘም!")
    threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), use_reloader=False), daemon=True).start()

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addvip", add_vip_command))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == '__main__':
    main()
