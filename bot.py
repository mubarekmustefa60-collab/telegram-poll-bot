import json
import logging
import os
import random
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

def load_questions():
    if os.path.exists("questions.json"):
        with open("questions.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

user_quiz_sessions = {}
user_bot_stats = {"total_users": set(), "users_list": {}}
premium_users = set()
leaderboard_data = []
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
    user_bot_stats["total_users"].add(user.id)
    user_bot_stats["users_list"][user.id] = f"{user.full_name} (@{user.username})"

    keyboard = [
        [KeyboardButton("📝 Model Exam"), KeyboardButton("🏛 Remedial National Exam 🔒")],
        [KeyboardButton("🎯 Exam Trainer Quiz"), KeyboardButton("📚 Tutorial PDF+Video 🔒")],
        [KeyboardButton("🏆 Leaderboard"), KeyboardButton("🎓 Go to Tutorial Class 🔒")],
        [KeyboardButton("👨‍💻 Contact Admin")]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("⚙️ Admin Control")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"👋 እንኳን ወደ **Remedial Matrix Quiz Bot** በደህና መጡ, {user.first_name}!\n\n"
        "📌 *ማስታወሻ:* በ 🔒 ምልክት የተደረገባቸው አገልግሎቶች ለ **Premium** ተጠቃሚዎች ብቻ ክፍት ናቸው።",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_bot_stats["total_users"].add(user.id)
    
    # 1. ተጠቃሚው ስሙን እና ስትሪሙን ከጻፈ በኋላ የሚቀበለው ክፍል
    if user.id in user_quiz_sessions.get("awaiting_name_stream", set()):
        user_quiz_sessions["awaiting_name_stream"].remove(user.id)
        user_quiz_sessions.setdefault("awaiting_payment_approval", set()).add(user.id)
        
        bank_text = (
            "መልካም! ፕሪሚየም ለመሆን ተቃርበዋል 🎉\n\n"
            "በሚከተሉት የባንክ አካውንት አማራጮች **300 ብር** ብቻ በመክፈል ሙሉ ዓመቱን ከኛ ጋር ፕሪሚየም ሆነው መማር ይችላሉ፦\n\n"
            "🏦 **CBE:** `1000667301673`\n"
            "📱 **TELEBIRR:** `0929698365`\n"
            "📱 **CBE BIRR:** `0929698365`\n\n"
            "ከነዚህ ውስጥ በተመቸዎት አማራጭ 300 ብር ከፍለው **የክፍያ ስክሪንሾት (Screenshot)** ፎቶ እዚህ ጋ ይላኩ 👇\n\n"
            "ስክሪንሾቱን ሲልኩልኝ አድሚኑ አረጋግጦ ፕሪሚየም ያደርግዎታል።"
        )
        await update.message.reply_text(bank_text, parse_mode="Markdown")
        return

    # 2. ተጠቃሚው የክፍያ ስክሪንሾት (ፎቶ) ከላከ
    if update.message.photo:
        if user.id in user_quiz_sessions.get("awaiting_payment_approval", set()):
            photo_file = update.message.photo[-1].file_id
            
            approval_kb = [
                [InlineKeyboardButton("✅ Approve (አጽድቅ)", callback_data=f"approve|{user.id}"),
                 InlineKeyboardButton("❌ Dismiss (ውድቅ አድርግ)", callback_data=f"dismiss|{user.id}")]
            ]
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_file,
                caption=f"🚨 **አዲስ የክፍያ ስክሪንሾት መጣ!**\n\n👤 ስም: {user.full_name}\n🆔 ID: `{user.id}`\nዩዘርናም: @{user.username}",
                reply_markup=InlineKeyboardMarkup(approval_kb),
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ ስክሪንሾትዎ ለአድሚን ተልኳል። አድሚኑ ሲያረጋግጠው ፕሪሚየም አካውንትዎ በቅርቡ ይከፈታል!")
            return

    text = update.message.text

    if text == "📝 Model Exam":
        keyboard = [
            [InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"),
             InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif text in ["🏛 Remedial National Exam 🔒", "📚 Tutorial PDF+Video 🔒", "🎓 Go to Tutorial Class 🔒"]:
        if user.id in premium_users:
            if "Tutorial Class" in text:
                await update.message.reply_text("🎓 **Private Tutorial Class ሊንክዎ፦**\nhttps://t.me/+yQdJM7LxN8VmNWY0", parse_mode="Markdown")
            elif "PDF+Video" in text:
                await update.message.reply_text("📚 **Tutorial Videos & PDFs ሊንክዎ፦**\nhttps://t.me/+yQdJM7LxN8VmNWY0", parse_mode="Markdown")
            else:
                await update.message.reply_text("🔓 ፕሪሚየም ነዎት! እባክዎ የሚፈልጉትን ዓመት ይምረጡ:", parse_mode="Markdown")
        else:
            keyboard = [
                [InlineKeyboardButton("✅ አዎ፣ ፕሪሚየም መሆን እፈልጋለሁ", callback_data="want_premium")]
            ]
            msg = (
                f"ሰላም {user.full_name}\n"
                "እስካሁን premium ተጠቃሚ አደሉም።\n"
                "premium ሲሆኑ ሁሉም buttun ጨምሮ private tutorial class ክፍት ይደረግልዎታል።\n\n"
                "premium መሆን ይፈልጋሉ?"
            )
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

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
        await update.message.reply_text("🎯 **Exam Trainer Quiz** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif text == "🏆 Leaderboard":
        if not leaderboard_data:
            await update.message.reply_text("🏆 እስካሁን የተመዘገበ የሊደርቦርድ መረጃ የለም። ፈተናዎችን በመስራት የመጀመሪያው ይሁኑ!")
        else:
            top_10 = sorted(leaderboard_data, key=lambda x: x['score'], reverse=True)[:10]
            lb_text = "🏆 **Top 10 Students Leaderboard** 🏆\n\n"
            for i, st in enumerate(top_10, 1):
                lb_text += f"{i}. {st['name']} - *{st['score']} ነጥብ* ({st['subject']})\n"
            await update.message.reply_text(lb_text, parse_mode="Markdown")

    elif text == "👨‍💻 Contact Admin":
        await update.message.reply_text("👨‍💻 **የአድሚን ማነጋገሪያ አድራሻ፡**\n@rmedial_matrix_support", parse_mode="Markdown")

    elif text == "⚙️ Admin Control" and user.id == ADMIN_ID:
        total_count = len(user_bot_stats["total_users"])
        active_list = "\n".join([f"• {name}" for uid, name in user_bot_stats["users_list"].items()])
        admin_text = (
            f"⚙️ **Admin Control Panel**\n\n"
            f"👥 ቦቱን የተጠቀሙ ጠቅላላ ተማሪዎች ብዛት: **{total_count}**\n\n"
            f"📋 **የተማሪዎች ዝርዝር:**\n{active_list}"
        )
        await update.message.reply_text(admin_text, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user

    if data == "close_menu":
        await query.message.delete()
        return

    elif data == "want_premium":
        # ተጠቃሚው አዎ ካለ ስሙን እና ስትሪሙን እንዲጽፍ በ state ውስጥ እንመዝግበዋለን
        user_quiz_sessions.setdefault("awaiting_name_stream", set()).add(user.id)
        await query.message.reply_text(
            "መልካም! ሙሉ ስምዎን እና (Natural ወይስ Social) stream መሆንዎን ይንገሩኝ።\n"
            "(እባክዎ መልዕክትዎትን እዚህ ይጻፉልን 👇)"
        )
        return

    elif data == "contact_admin_prem":
        await query.message.reply_text("📩 አድሚንን ለማነጋገር: @rmedial_matrix_support")
        return

    elif data.startswith("approve|") or data.startswith("dismiss|"):
        if user.id != ADMIN_ID:
            return
        action, target_id_str = data.split("|")
        target_id = int(target_id_str)

        if action == "approve":
            premium_users.add(target_id)
            if target_id in user_quiz_sessions.get("awaiting_payment_approval", set()):
                user_quiz_sessions["awaiting_payment_approval"].remove(target_id)
            
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 **እንኳን ደስ አለዎት!** ክፍያዎ በአድሚን ጸድቋል። አሁን ሁሉም ፕሪሚየም አዝራሮች እና Private Tutorial Class ተከፍተውልዎታል!"
            )
            await query.message.edit_caption(caption=query.message.caption + "\n\n✅ **Status: APPROVED (ጸድቋል)**")
        else:
            if target_id in user_quiz_sessions.get("awaiting_payment_approval", set()):
                user_quiz_sessions["awaiting_payment_approval"].remove(target_id)
            
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ ይቅርታ፣ የክፍያ ስክሪንሾትዎ ውድቅ ተደርጓል። እባክዎ እንደገና ትክክለኛውን ክፍያ ፈጽመው ያረጋግጡ ወይም አድሚኑን ያነጋግሩ @rmedial_matrix_support"
            )
            await query.message.edit_caption(caption=query.message.caption + "\n\n❌ **Status: DISMISSED (ውድቅ ሆኗል)**")
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
             InlineKeyboardButton("🌍 Geography", callback_data=f"q|model|{year}|Geography|0")],
            [InlineKeyboardButton("⚡ Physics", callback_data=f"q|model|{year}|Physics|0")],
            [InlineKeyboardButton("🏠 ዋና ምናሌ", callback_data="back_to_main")]
        ]
        await query.edit_message_text(f"📌 **{year} Model Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data.startswith("trainer|"):
        subject = data.split("|")[1]
        user_id = user.id
        
        q_data = load_questions()
        all_subject_qs = get_all_questions_for_subject(q_data, subject)

        if not all_subject_qs:
            await query.message.reply_text(f"⚠️ በ {subject} ትምህርት ስር እስካሁን የተሞላ ጥያቄ አልተገኘም!")
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
            await query.message.reply_text("⚠️ የፈተና ጊዜዎ አልቋል ወይም እንደገና መጀመር አለብዎት።")
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

            leaderboard_data.append({
                "name": user.full_name,
                "score": score,
                "subject": session['subject']
            })

            feedback = "🌟 በጣም ድንቅ ስራ! በዚህሁ ቀጥል!" if percentage >= 80 else ("👍 ጥሩ ጥረት ነው!" if percentage >= 50 else "⚠️ በድጋሚ ይሞክሩ!")

            result_text = (
                f"🎯 **የ Exam Trainer Quiz ውጤትዎ**\n\n"
                f"📚 ትምህርት: *{session['subject']}*\n"
                f"✅ ትክክለኛ መልሶች: **{score} / {total}**\n"
                f"📊 መቶኛ: **{percentage:.1f}%**\n\n"
                f"{feedback}"
            )
            await query.message.reply_text(result_text, parse_mode="Markdown")
            
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
            await query.message.reply_text(f"⚠️ የ {year} {subject} ጥያቄዎች በፋይሉ ውስጥ ገና አልተሞሉም!")
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
                explanation=explanation if explanation else None
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
                reply_markup=InlineKeyboardMarkup(nav_buttons)
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
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

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
    # ፎቶዎችን (ስክሪንሾት) እና ጽሁፎችን በአግባቡ የሚቀበለው ሀንድለር
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Telegram Bot በመጀመር ላይ ነው...")
    application.run_polling()

if __name__ == '__main__':
    main()
