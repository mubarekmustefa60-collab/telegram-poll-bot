import json
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# የሎግ ማስተካከያ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# የ JSON ፋይልን የሚጭን ተግባር
def load_questions():
    if os.path.exists("questions.json"):
        with open("questions.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# /start ወይም /exams ሲሉ የሚመጣው ምናሌ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📐 Mathematics (2018 ሞዴል)", callback_data="math_2018_model"),
            InlineKeyboardButton("⚡ Physics (2015 ሪሚዲያል)", callback_data="physics_2015_remedial")
        ],
        [
            InlineKeyboardButton("🧬 Biology (2017 ሞዴል)", callback_data="biology_2017_model"),
            InlineKeyboardButton("🧪 Chemistry", callback_data="coming_soon")
        ],
        [
            InlineKeyboardButton("🌍 Geography & History", callback_data="coming_soon"),
            InlineKeyboardButton("📚 English", callback_data="coming_soon")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 እንኳን ወደ **Remedial Matrix Quiz Bot** በደህና መጡ!\n\n"
        "ከዚህ በታች ያሉትን科目 (Subjects) እና ዓመታት በመምረጥ የፈተና ጥያቄዎችን በ Poll መልክ ይውሰዱ:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# ተማሪው በተጫነው ቁልፍ መሰረት ከ JSON ፋይል ጥያቄውን አምጥቶ በ Poll የሚልክ ተግባር
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_key = query.data
    
    if data_key == "coming_soon":
        await query.message.reply_text("⏳ ይህ 科目 እና የፈተና ዓመት በቅርቡ ይጫናል! ይጠብቁን።")
        return

    # ጥያቄዎችን ከ JSON ፋይል ማንበብ
    questions_data = load_questions()
    exam = questions_data.get(data_key)
    
    if exam:
        await context.bot.send_poll(
            chat_id=query.message.chat_id,
            question=exam["question"],
            options=exam["options"],
            is_anonymous=False,
            type="quiz",
            correct_option_id=exam["correct"],
            explanation=exam["explanation"]
        )
    else:
        await query.message.reply_text("ይቅርታ፣ የተመረጠው ጥያቄ በፋይሉ ውስጥ አልተገኘም!")

def main():
    # ከ Render Environment Variables ቶከኑን ማንበብ (አስተማማኝ መንገድ)
    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        print("ስህተት: የቦት ቶከን (BOT_TOKEN) አልተገኘም!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("exams", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Remedial Matrix Quiz Bot በ JSON ድጋፍ በመጀመር ላይ ነው...")
    app.run_polling()

if __name__ == '__main__':
    main()
