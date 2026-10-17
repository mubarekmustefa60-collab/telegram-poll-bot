import json
import logging
import os
import threading
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# የሎግ ማስተካከያ
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

# 1. ዋናው ምናሌ: Model Exam ወይስ Remedial National Exam?
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Model Exam", callback_data="type_model"),
         InlineKeyboardButton("🏛 Remedial National Exam", callback_data="type_remedial")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 እንኳን ወደ **Remedial Matrix Quiz Bot** በደህና መጡ!\n\n"
        "እባክዎ የሚፈልጉትን የፈተና ምድብ ይምረጡ:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data

    # ----------------------------------------------------
    # 2. MODEL EXAM ከሆኑ -> 2017 ወይስ 2018 ያስመርጣል
    # ----------------------------------------------------
    if data == "type_model":
        keyboard = [
            [InlineKeyboardButton("📅 2017 Model", callback_data="model_year_2017"),
             InlineKeyboardButton("📅 2018 Model", callback_data="model_year_2018")],
            [InlineKeyboardButton("⬅️ ወደ ዋናው ምናሌ", callback_data="back_home")]
        ]
        await query.edit_message_text("📌 **Model Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data == "model_year_2017":
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data="model_2017_biology"),
             InlineKeyboardButton("🧪 Chemistry", callback_data="model_2017_chemistry")],
            [InlineKeyboardButton("📚 English", callback_data="model_2017_english"),
             InlineKeyboardButton("📜 History", callback_data="model_2017_history")],
            [InlineKeyboardButton("📐 Maths", callback_data="model_2017_math"),
             InlineKeyboardButton("🌍 Geography", callback_data="model_2017_geography")],
            [InlineKeyboardButton("⚡ Physics", callback_data="model_2017_physics")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="type_model")]
        ]
        await query.edit_message_text("📌 **2017 Model Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data == "model_year_2018":
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data="model_2018_biology"),
             InlineKeyboardButton("🧪 Chemistry", callback_data="model_2018_chemistry")],
            [InlineKeyboardButton("📚 English", callback_data="model_2018_english"),
             InlineKeyboardButton("📜 History", callback_data="model_2018_history")],
            [InlineKeyboardButton("📐 Maths", callback_data="model_2018_math"),
             InlineKeyboardButton("🌍 Geography", callback_data="model_2018_geography")],
            [InlineKeyboardButton("⚡ Physics", callback_data="model_2018_physics")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="type_model")]
        ]
        await query.edit_message_text("📌 **2018 Model Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # ----------------------------------------------------
    # 3. REMEDIAL NATIONAL EXAM ከሆኑ -> 2015, 2016, 2017 ወይስ 2018 ያስመርጣል
    # ----------------------------------------------------
    elif data == "type_remedial":
        keyboard = [
            [InlineKeyboardButton("📅 2015", callback_data="rem_year_2015"),
             InlineKeyboardButton("📅 2016", callback_data="rem_year_2016")],
            [InlineKeyboardButton("📅 2017", callback_data="rem_year_2017"),
             InlineKeyboardButton("📅 2018", callback_data="rem_year_2018")],
            [InlineKeyboardButton("⬅️ ወደ ዋናው ምናሌ", callback_data="back_home")]
        ]
        await query.edit_message_text("📌 **Remedial National Exam** - የሚፈልጉትን ዓመት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data in ["rem_year_2015", "rem_year_2016", "rem_year_2017", "rem_year_2018"]:
        year = data.split("_")[2] # ዓመቱን ይወስዳል (2015, 2016, ወዘተ)
        keyboard = [
            [InlineKeyboardButton("🧬 Biology", callback_data=f"remedial_{year}_biology"),
             InlineKeyboardButton("🧪 Chemistry", callback_data=f"remedial_{year}_chemistry")],
            [InlineKeyboardButton("📚 English", callback_data=f"remedial_{year}_english"),
             InlineKeyboardButton("📜 History", callback_data=f"remedial_{year}_history")],
            [InlineKeyboardButton("📐 Maths", callback_data=f"remedial_{year}_math"),
             InlineKeyboardButton("🌍 Geography", callback_data=f"remedial_{year}_geography")],
            [InlineKeyboardButton("⚡ Physics", callback_data=f"remedial_{year}_physics")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="type_remedial")]
        ]
        await query.edit_message_text(f"📌 **{year} Remedial National Exam** - የትምህርት አይነት ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # 4. ወደ ዋናው ምናሌ መመለሻ
    elif data == "back_home":
        keyboard = [
            [InlineKeyboardButton("📝 Model Exam", callback_data="type_model"),
             InlineKeyboardButton("🏛 Remedial National Exam", callback_data="type_remedial")]
        ]
        await query.edit_message_text("👋 እባክዎ የሚፈልጉትን የፈተና ምድብ ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # ----------------------------------------------------
    # 5. ጥያቄውን ከ JSON ፈልጎ በ Poll መልክ መላክ
    # ----------------------------------------------------
    questions_data = load_questions()
    exam = questions_data.get(data)
    
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
        await query.message.reply_text("⚠️ ይህ ጥያቄ በፋይሉ ውስጥ ገና አልተሞላም!")

def run_telegram_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("ስህተት: የቦት ቶከን (BOT_TOKEN) አልተገኘም!")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("exams", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Telegram Bot በመጀመር ላይ ነው...")
    application.run_polling()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_telegram_bot)
    bot_thread.daemon = True
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)
