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
    keyboard = [
        [KeyboardButton("📝 Model Exam"), KeyboardButton("🏛 Remedial National Exam 🔒")],
        [KeyboardButton("🎯 Exam Trainer Quiz"), KeyboardButton("📚 Tutorial PDF+Video 🔒")],
        [KeyboardButton("👨‍💻 Contact Admin"), KeyboardButton("🎓 Go to Tutorial Class 🔒")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 እንኳን ወደ **Remedial Matrix Quiz Bot** በደህና መጡ!\n\n"
        "📌 *ማስታወሻ:* በ 🔒 ምልክት የተደረገባቸው አገልግሎቶች ለ **Premium** ተጠቃሚዎች ብቻ ክፍት ናቸው።\n"
        "እባክዎ ከታች ካሉት አማራጮች የሚፈልጉትን ይምረጡ:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📝 Model Exam":
        keyboard = [
            [InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"),
             InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif text == "🏛 Remedial National Exam 🔒":
        keyboard = [
            [InlineKeyboardButton("💎 ፕሪሚየም አካውንት ማግኘት ይፈልጋሉ?", callback_data="contact_admin_prem")]
        ]
        await update.message.reply_text(
            "🔒 **ይህ አገልግሎት ለፕሪሚየም (Premium) ተጠቃሚዎች ብቻ የተፈቀደ ነው!**\n\n"
            "ይህንን አገልግሎት ለመክፈት አድምንን ያነጋግሩ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif text == "🎯 Exam Trainer Quiz":
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data="trainer|Biology"),
             InlineKeyboardButton("🧪 Chemistry", callback_data="trainer|Chemistry")],
            [InlineKeyboardButton("📚 English", callback_data="trainer|English"),
             InlineKeyboardButton("📜 History", callback_data="trainer|History")],
            [InlineKeyboardButton("📐 Maths", callback_data="trainer|Maths"),
             InlineKeyboardButton("🌍 Geography", callback_data="trainer|Geography")],
            [InlineKeyboardButton("⚡ Physics", callback_data="trainer|Physics")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text(
            "🎯 **Exam Trainer Quiz**\n\n"
            "እባክዎ መለማመድ የሚፈልጉትን የትምህርት አይነት ይምረጡ:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif text == "📚 Tutorial PDF+Video 🔒" or text == "🎓 Go to Tutorial Class 🔒":
        keyboard = [
            [InlineKeyboardButton("💎 አድምንን በማነጋገር ፕሪሚየም ይሁኑ", callback_data="contact_admin_prem")]
        ]
        await update.message.reply_text(
            "🔒 **ይህ የትምህርት መደብ ለፕሪሚየም (Premium) ተጠቃሚዎች ብቻ የተዘጋጀ ነው!**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif text == "👨‍💻 Contact Admin":
        await update.message.reply_text(
            "👨‍💻 **የአድሚን ማነጋገሪያ አድራሻ፡**\n\n"
            "📩 አድሚን: `@YourAdminUsername`",
            parse_mode="Markdown"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data

    if data == "close_menu":
        await query.message.delete()
        return

    elif data == "contact_admin_prem":
        await query.message.reply_text("📩 ፕሪሚየም ለመሆን አድምንን `@YourAdminUsername` ያነጋግሩ!")
        return

    # Model Exam ዓመት ሲመረጥ የትምህርት አይነቶችን ማሳየት (ይህ ነበር የጠፋው!)
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
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await query.edit_message_text(f"📌 **{year} Model Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data.startswith("trainer|"):
        subject = data.split("|")[1]
        user_id = query.from_user.id
        
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

            feedback = ""
            if percentage >= 80:
                feedback = "🌟 በጣም ድንቅ ስራ! በእጅጉ አሪፍ ውጤት ነው፤ በዚህሁ ቀጥል!"
            elif percentage >= 50:
                feedback = "👍 ጥሩ ጥረት ነው! ነገር ግን ውጤትዎ የተሻለ እንዲሆን በደንብ መጠንከር ይኖርብዎታል።"
            else:
                feedback = "⚠️ ብዙ መሥራት ይጠበቅብዎታል። በድጋሚ ይሞክሩ!"

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

            if index + 1 < total:
                next_kb = [[InlineKeyboardButton(f"ቀጣይ ጥያቄ ({index + 2}/{total}) ➡️", callback_data=f"q|{category}|{year}|{subject}|{index + 1}")]]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="ለመቀጠል ከታች ያለውን ቁልፍ ይጫኑ 👇",
                    reply_markup=InlineKeyboardMarkup(next_kb)
                )
            else:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"🎉 **የ {year} {subject} ጥያቄዎችን በሙሉ ጨርሰዋል!**",
                    parse_mode="Markdown"
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
        f"እባክዎ ትክክለኛውን መልስ ይምረጡ:"
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Telegram Bot በመጀመር ላይ ነው...")
    application.run_polling()

if __name__ == '__main__':
    main()
