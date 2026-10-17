import json
import logging
import os
import random
import sqlite3
import threading
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Remedial Matrix Quiz Bot is running successfully!"

# ─── DATABASE SETUP (SQLite) ───
DB_FILE = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            is_premium INTEGER DEFAULT 0
        )
    ''')
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

def db_add_user(user_id, full_name, username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, full_name, username, is_premium) VALUES (?, ?, ?, 0)", 
                   (user_id, full_name, username))
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

def db_get_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 0")
    free_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT user_id, full_name, username, is_premium FROM users")
    rows = cursor.fetchall()
    conn.close()
    
    users_list = [f"• {row[1]} (@{row[2] or 'No Username'}) - {'[Premium]' if row[3]==1 else '[Free]'}" for row in rows]
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
ADMIN_ID = 6183608197

def get_all_questions_for_subject(data, subject):
    all_qs = []
    subject_lower = subject.lower()

    model_exams = data.get("model_exams", {})
    for year, subjects in model_exams.items():
        for s_name, q_list in subjects.items():
            if s_name.lower() == subject_lower or (subject_lower in ["math", "maths"] and s_name.lower() in ["math", "maths", "mathematics"]):
                all_qs.extend(q_list)

    remedial_exams = data.get("remedial_exams", {})
    for year, subjects in remedial_exams.items():
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
    if isinstance(options_raw, dict):
        options_list = list(options_raw.values())
    elif isinstance(options_raw, list):
        options_list = options_raw
    else:
        options_list = ["Option A", "Option B", "Option C", "Option D"]

    correct_id = q.get("correct_option_id", None)
    if correct_id is None:
        answer_letter = q.get("answer", q.get("correct", 0))
        if isinstance(answer_letter, str):
            letter_to_index = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
            correct_id = letter_to_index.get(answer_letter.upper(), 0)
        elif isinstance(answer_letter, int):
            correct_id = answer_letter
        else:
            correct_id = 0

    if not isinstance(correct_id, int) or correct_id < 0 or correct_id >= len(options_list):
        correct_id = 0

    explanation = q.get("explanation", "")
    return q_text, options_list, correct_id, explanation

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    db_add_user(user.id, user.full_name, user.username)

    if chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            f"ሰላም {user.first_name}! 🎓 **Remedial Matrix** ግሩፕ ውስጥ ስለሆኑ እባክዎ ሙሉውን አገልግሎት ለማግኘት ከታች ባለው ሊንክ ወደ ፕራይቬት ቦታችን ይምጡ 👇\n\n"
            f"👉 [@{context.bot.username}](https://t.me/{context.bot.username})",
            parse_mode="Markdown"
        )
        return

    keyboard = [
        [KeyboardButton("📝 Model Exam"), KeyboardButton("🏛 Remedial National Exam 🔒")],
        [KeyboardButton("🎯 Exam Trainer Quiz"), KeyboardButton("📚 Tutorial PDF+Video 🔒")],
        [KeyboardButton("💎 VIP / ፕሪሚየም ለመሆን"), KeyboardButton("🏆 Leaderboard")],
        [KeyboardButton("🎓 Go to Tutorial Class 🔒"), KeyboardButton("👨‍💻 Contact Admin")]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("⚙️ Admin Control")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    banner_text = (
        "🌟━━━━━━━━━━━━━━━━━━🌟\n"
        "   🎓 **REMEDIAL MATRIX** 🎓\n"
        "      *የስኬትዎ መንገድ!* 🚀\n"
        "🌟━━━━━━━━━━━━━━━━━━🌟\n\n"
        f"👋 እንኳን ደህና መጡ, **{user.first_name}**!\n\n"
        "📌 *ማስታወሻ:* በ 🔒 ምልክት የተደረገባቸው አገልግሎቶች ለ **Premium** ተጠቃሚዎች ብቻ ክፍት ናቸው።"
    )
    
    await update.message.reply_text(
        banner_text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
        protect_content=True
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type in ["group", "supergroup"]:
        return

    db_add_user(user.id, user.full_name, user.username)
    
    # 1. ፎቶ (ስክሪንሾት) ሲላክ
    if update.message.photo:
        photo_file = update.message.photo[-1].file_id
        
        approval_kb = [
            [InlineKeyboardButton("✅ Approve (አጽድቅ)", callback_data=f"approve|{user.id}"),
             InlineKeyboardButton("❌ Dismiss (ውድቅ አድርግ)", callback_data=f"dismiss|{user.id}")]
        ]
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file,
            caption=f"🚨 **አዲስ የክፍያ ስክሪንሾት መጣ!**\n\n👤 ስም: {user.full_name}\n🆔 ID: `{user.id}`\nዩዘርናም: @{user.username or 'None'}",
            reply_markup=InlineKeyboardMarkup(approval_kb),
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ ስክሪንሾትዎ ለአድሚን ተልኳል! አድሚኑ ክፍያዎን አረጋግጦ ፕሪሚየም አካውንትዎን በሰከንዶች ውስጥ ይከፍታል።", protect_content=True)
        return

    text = update.message.text
    if not text:
        return

    # 2. አድሚን ብሮድካስት ሲልክ
    if user.id == ADMIN_ID and user.id in user_quiz_sessions.get("broadcasting_mode", set()):
        target_group = user_quiz_sessions.pop("broadcasting_target", "all")
        user_quiz_sessions["broadcasting_mode"].remove(user.id)
        
        recipients = db_get_users_by_type(is_prem=True) if target_group == "premium" else db_get_users_by_type(is_prem=False)
        success_count = 0
        
        for uid in recipients:
            try:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                success_count += 1
            except Exception:
                pass
                
        await update.message.reply_text(f"✅ ብሮድካስቱ በተሳካ ሁኔታ ለ **{success_count}** ተጠቃሚዎች ተልኳል!")
        return

    if text == "📝 Model Exam":
        keyboard = [
            [InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"),
             InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=True)

    elif text == "🏛 Remedial National Exam 🔒":
        if db_is_premium(user.id):
            keyboard = [
                [InlineKeyboardButton("📅 2015", callback_data="rem_year_2015"),
                 InlineKeyboardButton("📅 2016", callback_data="rem_year_2016")],
                [InlineKeyboardButton("📅 2017", callback_data="rem_year_2017"),
                 InlineKeyboardButton("📅 2018", callback_data="rem_year_2018")],
                [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
            ]
            await update.message.reply_text("🔓 **ፕሪሚየም ነዎት!** እባክዎ የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=True)
        else:
            keyboard = [[InlineKeyboardButton("💎 VIP / ፕሪሚየም ለመሆን ይጫኑ", callback_data="vip_info")]]
            msg = f"ሰላም {user.full_name}\nእስካሁን ፕሪሚየም ተጠቃሚ አይደሉም። ፕሪሚየም ሲሆኑ ሁሉንም ጥያቄዎች እና ቱቶሪያሎች ማግኘት ይችላሉ።"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), protect_content=True)

    elif text in ["📚 Tutorial PDF+Video 🔒", "🎓 Go to Tutorial Class 🔒"]:
        if db_is_premium(user.id):
            await update.message.reply_text("🎓📚 **የፕሪሚየም ትምህርት ማዕከል ሊንክዎ፦**\nhttps://t.me/+yQdJM7LxN8VmNWY0", parse_mode="Markdown", protect_content=True)
        else:
            keyboard = [[InlineKeyboardButton("💎 VIP / ፕሪሚየም ለመሆን ይጫኑ", callback_data="vip_info")]]
            msg = f"ሰላም {user.full_name}\nእስካሁን ፕሪሚየም ተጠቃሚ አይደሉም። ፕሪሚየም በመሆን Private Tutorial Class ይክፈቱ!"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), protect_content=True)

    elif text == "💎 VIP / ፕሪሚየም ለመሆን":
        vip_text = (
            "💎 **የ VIP / ፕሪሚየም አባልነት መረጃ** 💎\n\n"
            "ሙሉ ዓመቱን ከኛ ጋር ሆኖ ለመማር እና ሁሉንም ጥያቄዎች/ቪዲዮዎች ለመክፈት **300 ብር** ብቻ በመክፈል ፕሪሚየም ይሁኑ!\n\n"
            "🏦 **CBE:** `1000667301673`\n"
            "📱 **TELEBIRR:** `0929698365`\n"
            "📱 **CBE BIRR:** `0929698365`\n\n"
            "💵 ከላይ ባሉት አማራጮች 300 ብር ከፍለው **የክፍያ ስክሪንሾት (Screenshot)** ፎቶውን በቀጥታ በዚህ ቻት ውስጥ ይላኩሉኝ!"
        )
        await update.message.reply_text(vip_text, parse_mode="Markdown", protect_content=True)

    elif text == "🎯 Exam Trainer Quiz":
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data="trainer|Biology"),
             InlineKeyboardButton("🧪 Chemistry", callback_data="trainer|Chemistry")],
            [InlineKeyboardButton("📚 English", callback_data="trainer|English"),
             InlineKeyboardButton("📜 History", callback_data="trainer|History")],
            [InlineKeyboardButton("📐 Maths", callback_data="trainer|Maths"),
             InlineKeyboardButton("🌍 Geography", callback_data="trainer|Geography"),
             InlineKeyboardButton("⚡ Physics", callback_data="trainer|Physics")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("🎯 **Exam Trainer Quiz** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", protect_content=True)

    elif text == "🏆 Leaderboard":
        lb_list = db_get_leaderboard()
        if not lb_list:
            await update.message.reply_text("🏆 እስካሁን የተመዘገበ የሊደርቦርድ መረጃ የለም። ፈተናዎችን በመስራት የመጀመሪያው ይሁኑ!", protect_content=True)
        else:
            lb_text = "🏆 **Top 10 Students Leaderboard** 🏆\n\n"
            for i, st in enumerate(lb_list, 1):
                lb_text += f"{i}. {st['name']} - *{st['score']} ነጥብ* ({st['subject']})\n"
            await update.message.reply_text(lb_text, parse_mode="Markdown", protect_content=True)

    elif text == "👨‍💻 Contact Admin":
        await update.message.reply_text("👨‍💻 **የአድሚን ማነጋገሪያ አድራሻ፡**\n@rmedial_matrix_support", parse_mode="Markdown", protect_content=True)

    elif text == "⚙️ Admin Control" and user.id == ADMIN_ID:
        total_count, prem_count, free_count, active_list_rows = db_get_stats()
        active_list = "\n".join(active_list_rows) if active_list_rows else "ምንም ተጠቃሚ የለም"
        
        admin_kb = [
            [InlineKeyboardButton("📢 Broadcast to Premium", callback_data="bc_premium"),
             InlineKeyboardButton("📢 Broadcast to Free", callback_data="bc_free")]
        ]
        admin_text = (
            f"⚙️ **Admin Control Panel**\n\n"
            f"👥 ጠቅላላ ተጠቃሚዎች: **{total_count}**\n"
            f"💎 ፕሪሚየም ተጠቃሚዎች: **{prem_count}**\n"
            f"🆓 ነፃ ተጠቃሚዎች: **{free_count}**\n\n"
            f"📋 **የተማሪዎች ዝርዝር:**\n{active_list}"
        )
        await update.message.reply_text(admin_text, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode="Markdown", protect_content=True)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user

    if data == "close_menu":
        await query.message.delete()
        return

    elif data == "bc_premium" and user.id == ADMIN_ID:
        user_quiz_sessions.setdefault("broadcasting_mode", set()).add(user.id)
        user_quiz_sessions["broadcasting_target"] = "premium"
        await query.message.reply_text("📢 ለ **Premium** ተጠቃሚዎች መላክ የሚፈልጉትን መልዕክት (ወይም ፎቶ) አሁን ይላኩሱልኝ:")
        return

    elif data == "bc_free" and user.id == ADMIN_ID:
        user_quiz_sessions.setdefault("broadcasting_mode", set()).add(user.id)
        user_quiz_sessions["broadcasting_target"] = "free"
        await query.message.reply_text("📢 ለ **Free** ተጠቃሚዎች መላክ የሚፈልጉትን መልዕክት (ወይም ፎቶ) አሁን ይላኩሱልኝ:")
        return

    elif data == "vip_info":
        vip_text = (
            "💎 **የ VIP / ፕሪሚየም አባልነት መረጃ** 💎\n\n"
            "ሙሉ ዓመቱን ከኛ ጋር ሆኖ ለመማር እና ሁሉንም ጥያቄዎች/ቪዲዮዎች ለመክፈት **300 ብር** ብቻ በመክፈል ፕሪሚየም ይሁኑ!\n\n"
            "🏦 **CBE:** `1000667301673`\n"
            "📱 **TELEBIRR:** `0929698365`\n"
            "📱 **CBE BIRR:** `0929698365`\n\n"
            "💵 ከላይ ባሉት አማራጮች 300 ብር ከፍለው **የክፍያ ስክሪንሾት (Screenshot)** ፎቶውን በቀጥታ በዚህ ቻት ውስጥ ይላኩሉኝ!"
        )
        await query.message.reply_text(vip_text, parse_mode="Markdown")
        return

    elif data.startswith("approve|") or data.startswith("dismiss|"):
        if user.id != ADMIN_ID:
            return
        action, target_id_str = data.split("|")
        target_id = int(target_id_str)

        if action == "approve":
            db_set_premium(target_id, 1)
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 **እንኳን ደስ አለዎት!** ክፍያዎ በአድሚን ጸድቋል። አሁን ሁሉም ፕሪሚየም አዝራሮች እና Private Tutorial Class ተከፍተውልዎታል!",
                protect_content=True
            )
            try:
                await query.message.edit_caption(caption=query.message.caption + "\n\n✅ **Status: APPROVED (ጸድቋል)**")
            except Exception:
                pass
        else:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ ይቅርታ፣ የክፍያ ስክሪንሾትዎ ውድቅ ተደርጓል። እባክዎ አድሚኑን ያነጋግሩ @rmedial_matrix_support",
                protect_content=True
            )
            try:
                await query.message.edit_caption(caption=query.message.caption + "\n\n❌ **Status: DISMISSED (ውድቅ ሆኗል)**")
            except Exception:
                pass
        return

    elif data == "back_to_main":
        await query.message.delete()
        await start(update, context)
        return

    elif data in ["model_year_2017", "model_year_2018"]:
        year = data.split("_")[2]
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data=f"q|model|{year}|Biology|0"),
             InlineKeyboardButton("🧪 Chemistry", callback_data=f"q|model|{year}|Chemistry|0")],
            [InlineKeyboardButton("📚 English", callback_data=f"q|model|{year}|English|0"),
             InlineKeyboardButton("📜 History", callback_data=f"q|model|{year}|History|0")],
            [InlineKeyboardButton("📐 Maths", callback_data=f"q|model|{year}|Maths|0"),
             InlineKeyboardButton("🌍 Geography", callback_data=f"q|model|{year}|Geography|0"),
             InlineKeyboardButton("⚡ Physics", callback_data=f"q|model|{year}|Physics|0")],
            [InlineKeyboardButton("🏠 ዋና ምናሌ", callback_data="back_to_main")]
        ]
        await query.edit_message_text(f"📌 **{year} Model Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data in ["rem_year_2015", "rem_year_2016", "rem_year_2017", "rem_year_2018"]:
        year = data.split("_")[2]
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data=f"q|remedial|{year}|Biology|0"),
             InlineKeyboardButton("🧪 Chemistry", callback_data=f"q|remedial|{year}|Chemistry|0")],
            [InlineKeyboardButton("📚 English", callback_data=f"q|remedial|{year}|English|0"),
             InlineKeyboardButton("📜 History", callback_data=f"q|remedial|{year}|History|0")],
            [InlineKeyboardButton("📐 Maths", callback_data=f"q|remedial|{year}|Maths|0"),
             InlineKeyboardButton("🌍 Geography", callback_data=f"q|remedial|{year}|Geography|0"),
             InlineKeyboardButton("⚡ Physics", callback_data=f"q|remedial|{year}|Physics|0")],
            [InlineKeyboardButton("🏠 ዋና ምናሌ", callback_data="back_to_main")]
        ]
        await query.edit_message_text(f"📌 **{year} Remedial National Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data.startswith("trainer|"):
        subject = data.split("|")[1]
        user_id = user.id
        
        q_data = load_questions()
        all_subject_qs = get_all_questions_for_subject(q_data, subject)

        if not all_subject_qs:
            await query.message.reply_text(f"⚠️ በ {subject} ትምህርት ስር እስካሁን የተሞላ ጥያቄ አልተገኘም!", protect_content=True)
            return

        random.shuffle(all_subject_qs)
        total_to_pick = min(len(all_subject_qs), random.randint(30, 60))
        selected_qs = all_subject_qs[:total_to_pick]

        user_quiz_sessions[user_id] = {
            "subject": subject,
            "questions": selected_qs,
            "index": 0,
            "score": 0,
            "total": len(selected_qs)
        }

        await send_trainer_question(context, query.message.chat_id, user_id)
        return

    if data.startswith("t_ans|"):
        parts = data.split("|")
        user_id = int(parts[1])
        selected_option = int(parts[2])

        session = user_quiz_sessions.get(user_id)
        if not session:
            await query.message.reply_text("⚠️ የፈተና ጊዜዎ አልቋል ወይም እንደገና መጀመር አለብዎት።", protect_content=True)
            return

        q_list = session["questions"]
        idx = session["index"]
        q = q_list[idx]

        _, _, correct_id, _ = parse_question_data(q)

        if selected_option == correct_id:
            session["score"] += 1

        session["index"] += 1

        if session["index"] < len(q_list):
            await send_trainer_question(context, query.message.chat_id, user_id)
        else:
            score = session["score"]
            total = session["total"]
            percentage = (score / total) * 100

            db_add_leaderboard(user.full_name, score, session['subject'])

            feedback = "🌟 በጣም ድንቅ ስራ! በዚህሁ ቀጥል!" if percentage >= 80 else ("👍 ጥሩ ጥረት ነው!" if percentage >= 50 else "⚠️ በድጋሚ ይሞክሩ!")

            result_text = (
                f"🎯 **የ Exam Trainer Quiz ውጤትዎ**\n\n"
                f"📚 ትምህርት: *{session['subject']}*\n"
                f"✅ ትክክለኛ መልሶች: **{score} / {total}**\n"
                f"📊 መቶኛ: **{percentage:.1f}%**\n\n"
                f"{feedback}"
            )
            await query.message.reply_text(result_text, parse_mode="Markdown", protect_content=True)
            
            if user_id in user_quiz_sessions:
                del user_quiz_sessions[user_id]
        return

    if data.startswith("q|"):
        parts = data.split("|")
        category = parts[1]
        year = parts[2]
        subject = parts[3]
        index = int(parts[4])

        questions_data = load_questions()
        cat_key = "model_exams" if category == "model" else "remedial_exams"
        exam_questions = []
        if cat_key in questions_data and year in questions_data[cat_key]:
            year_data = questions_data[cat_key][year]
            for k, v in year_data.items():
                if k.lower() == subject.lower():
                    exam_questions = v

        if not exam_questions:
            await query.message.reply_text(f"⚠️ የ {year} {subject} ጥያቄዎች በፋይሉ ውስጥ ገና አልተሞሉም!", protect_content=True)
            return

        if index < len(exam_questions):
            q = exam_questions[index]
            total = len(exam_questions)
            q_text_raw, options_list, correct_id, explanation_raw = parse_question_data(q)

            q_text = f"[{index + 1}/{total}] {q_text_raw}"
            if len(q_text) > 300:
                q_text = q_text[:297] + "..."
            options = [str(opt)[:100] for opt in options_list]
            explanation = explanation_raw if explanation_raw else ""
            if explanation and len(explanation) > 200:
                explanation = explanation[:197] + "..."

            await context.bot.send_poll(
                chat_id=query.message.chat_id,
                question=q_text,
                options=options,
                is_anonymous=False,
                type="quiz",
                correct_option_id=correct_id,
                explanation=explanation if explanation else None,
                protect_content=True
            )

            nav_buttons = []
            row = []
            if index > 0:
                row.append(InlineKeyboardButton("⬅️ ተመለስ (Back)", callback_data=f"q|{category}|{year}|{subject}|{index - 1}"))
            if index + 1 < total:
                row.append(InlineKeyboardButton(f"ቀጣይ ({index + 2}/{total}) ➡️", callback_data=f"q|{category}|{year}|{subject}|{index + 1}"))
            
            if row:
                nav_buttons.append(row)
            nav_buttons.append([InlineKeyboardButton("🏠 ዋና ምናሌ (Main Menu)", callback_data="back_to_main")])

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="ለማስተካከል ወይም ለመቀጠል ከታች ያሉትን ቁልፎች ይጠገቡ 👇",
                reply_markup=InlineKeyboardMarkup(nav_buttons),
                protect_content=True
            )

async def send_trainer_question(context, chat_id, user_id):
    session = user_quiz_sessions.get(user_id)
    if not session:
        return

    q_list = session["questions"]
    idx = session["index"]
    q = q_list[idx]
    total = session["total"]

    q_text, options_list, correct_id, explanation = parse_question_data(q)

    keyboard = []
    for i, opt in enumerate(options_list):
        letter = chr(65 + i)
        keyboard.append([InlineKeyboardButton(f"{letter}. {opt}", callback_data=f"t_ans|{user_id}|{i}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"🎯 **Exam Trainer Quiz** [{idx + 1}/{total}]\n\n"
        f"❓ *{q_text}*\n\n"
        f"👉 **እባክዎ ከታች ካሉት አማራጮች አንዱን ምርጫ ይምረጡ:**"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="Markdown", protect_content=True)

def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("ስህተት: የቦት ቶከን (BOT_TOKEN) አልተገኘም!")
        return

    port = int(os.environ.get("PORT", 5000))
    flask_thread = threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=port, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("exams", start))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Telegram Bot በመጀመር ላይ ነው...")
    application.run_polling()

if __name__ == '__main__':
    main()
