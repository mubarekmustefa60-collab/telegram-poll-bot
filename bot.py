import json
import logging
import os
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

# 1. /start ሲሉ የሚመጣው መደበኛ (Normal) ምናሌ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📝 Model Exam"), KeyboardButton("🏛 Remedial National Exam")],
        [KeyboardButton("🎯 Exam Trainer Quiz")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 እንኳን ወደ **Remedial Matrix Quiz Bot** በደህና መጡ!\n\n"
        "እባክዎ ከታች ካሉት አማራጮች የሚፈልጉትን ይምረጡ:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# 2. መደበኛ ቁልፎችን ማስተናገጃ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📝 Model Exam":
        keyboard = [
            [InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"),
             InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif text == "🏛 Remedial National Exam":
        keyboard = [
            [InlineKeyboardButton("📅 2015", callback_data="rem_year_2015"),
             InlineKeyboardButton("📅 2016", callback_data="rem_year_2016")],
            [InlineKeyboardButton("📅 2017", callback_data="rem_year_2017"),
             InlineKeyboardButton("📅 2018", callback_data="rem_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await update.message.reply_text("📌 **Remedial National Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif text == "🎯 Exam Trainer Quiz":
        await update.message.reply_text("🎯 **Exam Trainer Quiz** በቅርቡ ይለቀቃል! ይጠብቁን።", parse_mode="Markdown")

# 3. የ Inline ቁልፎች እና የጥያቄዎች መላኪያ
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data

    if data == "close_menu":
        await query.message.delete()
        return

    elif data == "back_to_model":
        keyboard = [
            [InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"),
             InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await query.edit_message_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data == "back_to_remedial":
        keyboard = [
            [InlineKeyboardButton("📅 2015", callback_data="rem_year_2015"),
             InlineKeyboardButton("📅 2016", callback_data="rem_year_2016")],
            [InlineKeyboardButton("📅 2017", callback_data="rem_year_2017"),
             InlineKeyboardButton("📅 2018", callback_data="rem_year_2018")],
            [InlineKeyboardButton("❌ ዝጋ", callback_data="close_menu")]
        ]
        await query.edit_message_text("📌 **Remedial National Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data in ["model_year_2017", "model_year_2018"]:
        year = data.split("_")[2]
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data=f"q|model_{year}_biology|0"),
             InlineKeyboardButton("🧪 Chemistry", callback_data=f"q|model_{year}_chemistry|0")],
            [InlineKeyboardButton("📚 English", callback_data=f"q|model_{year}_english|0"),
             InlineKeyboardButton("📜 History", callback_data=f"q|model_{year}_history|0")],
            [InlineKeyboardButton("📐 Maths", callback_data=f"q|model_{year}_math|0"),
             InlineKeyboardButton("🌍 Geography", callback_data=f"q|model_{year}_geography|0")],
            [InlineKeyboardButton("⚡ Physics", callback_data=f"q|model_{year}_physics|0")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="back_to_model")]
        ]
        await query.edit_message_text(f"📌 **{year} Model Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data in ["rem_year_2015", "rem_year_2016", "rem_year_2017", "rem_year_2018"]:
        year = data.split("_")[2]
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data=f"q|remedial_{year}_biology|0"),
             InlineKeyboardButton("🧪 Chemistry", callback_data=f"q|remedial_{year}_chemistry|0")],
            [InlineKeyboardButton("📚 English", callback_data=f"q|remedial_{year}_english|0"),
             InlineKeyboardButton("📜 History", callback_data=f"q|remedial_{year}_history|0")],
            [InlineKeyboardButton("📐 Maths", callback_data=f"q|remedial_{year}_math|0"),
             InlineKeyboardButton("🌍 Geography", callback_data=f"q|remedial_{year}_geography|0")],
            [InlineKeyboardButton("⚡ Physics", callback_data=f"q|remedial_{year}_physics|0")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="back_to_remedial")]
        ]
        await query.edit_message_text(f"📌 **{year} Remedial National Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # 4. ጥያቄዎችን ተራ በተራ መላክ (Pagination)
    if data.startswith("q|"):
        parts = data.split("|")
        exam_key = parts[1]
        index = int(parts[2])

        questions_data = load_questions()
        exam_questions = questions_data.get(exam_key)

        if not exam_questions:
            await query.message.reply_text("⚠️ የዚህ ትምህርት ጥያቄዎች ገና አልተሞሉም!")
            return

        # ፋይሉ ላይ አንድ ጥያቄ ብቻ በነጠላ ከተቀመጠ ወደ List መቀየር
        if isinstance(exam_questions, dict):
            exam_questions = [exam_questions]

        if index < len(exam_questions):
            q = exam_questions[index]
            total = len(exam_questions)
            
            # Poll መላክ
            await context.bot.send_poll(
                chat_id=query.message.chat_id,
                question=f"[{index + 1}/{total}] {q['question']}",
                options=q["options"],
                is_anonymous=False,
                type="quiz",
                correct_option_id=q["correct"],
                explanation=q.get("explanation", "")
            )

            # ቀጣይ ጥያቄ ካለ "ቀጣይ ጥያቄ ➡️" የሚል በተን ማምጣት
            if index + 1 < total:
                next_kb = [[InlineKeyboardButton(f"ቀጣይ ጥያቄ ({index + 2}/{total}) ➡️", callback_data=f"q|{exam_key}|{index + 1}")]]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="ለመቀጠል ከታች ያለውን ቁልፍ ይጫኑ 👇",
                    reply_markup=InlineKeyboardMarkup(next_kb)
                )
            else:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="🎉 **የዚህን ምድብ ጥያቄዎች በሙሉ ጨርሰዋል!** ሌላ ትምህርት ለመምረጥ ከታች ያሉትን ዋና ቁልፎች ይጠቀሙ።",
                    parse_mode="Markdown"
                )

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
