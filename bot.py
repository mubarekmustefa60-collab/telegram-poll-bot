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

# ─── ADMIN COMMANDS ───
async def add_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        db_set_premium(target_id, 1)
        await update.message.reply_text(f"✅ ተጠቃሚ {target_id} በተሳካ ሁኔታ VIP ሆኗል!")
        await context.bot.send_message(chat_id=target_id, text="🎉 **እንኳን ደስ አለዎት!** አድሚኑ የ VIP ፕሪሚየም አባልነትዎን ከፍቶልዎታል!", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ አጠቃቀም: /addvip <የተጠቃሚው_ID_ቁጥር>")

async def restore_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    raw_data = """
ID: 920393254 | Name: Nati@ | Username: @NA57TI | Status: [Free] | Refs: 0
ID: 1046576726 | Name: Etsuty💞 | Username: @Etsubjunior | Status: [Free] | Refs: 0
ID: 1087968824 | Name: Group | Username: @GroupAnonymousBot | Status: [Free] | Refs: 0
ID: 1243192392 | Name: 💞seni | Username: @Arikutokafuchi | Status: [Free] | Refs: 0
ID: 1267581764 | Name: Ketoo 💖💖💖💖💖💖 | Username: @Keto_4133 | Status: [Free] | Refs: 0
ID: 1269450919 | Name: æ | Username: @kiya8471 | Status: [Free] | Refs: 0
ID: 1793764484 | Name: Brk | Username: @Call_me_babuji | Status: [Free] | Refs: 0
ID: 1874094659 | Name: ᴹᴿメ | Username: @B2kff1 | Status: [Free] | Refs: 0
ID: 1955042540 | Name: Birukti | Username: @Birukti502 | Status: [Free] | Refs: 0
ID: 1970713830 | Name: @Kal🍫 | Username: @None | Status: [Free] | Refs: 0
ID: 2027109416 | Name: Engida27 👍👍👍 | Username: @NahomFik27Lij | Status: [Free] | Refs: 0
ID: 5069182890 | Name: MEHOኒ. Z | Username: @HGZGB | Status: [Free] | Refs: 0
ID: 5211478913 | Name: @𝓷𝓭𝓾 𝓪𝓵𝓮𝓶 | Username: @ndu113 | Status: [Free] | Refs: 0
ID: 5391159738 | Name: 𝕷𝖎𝖉𝖚🕸️ | Username: @lidu1213 | Status: [Free] | Refs: 0
ID: 5436142396 | Name: BAD BOY | Username: @None | Status: [Free] | Refs: 0
ID: 5442994593 | Name: 💥🔥 | Username: @N00ne43 | Status: [Free] | Refs: 0
ID: 5504727111 | Name: Once and for all | Username: @None | Status: [Free] | Refs: 0
ID: 5510331030 | Name: KIDISTTT | Username: @None | Status: [Free] | Refs: 0
ID: 5521624660 | Name: .........??? | Username: @Helena_wit16 | Status: [Free] | Refs: 0
ID: 5597495720 | Name: John 3:16 | Username: @Oritdega | Status: [Free] | Refs: 0
ID: 5640315130 | Name: M3d!ta🎀 | Username: @Creamlateeel | Status: [Free] | Refs: 0
ID: 5643498451 | Name: asrestefera60@gmail.com0233981 Tefera | Username: @None | Status: [Free] | Refs: 0
ID: 5695324501 | Name: Danii Begn | Username: @DB40Z | Status: [VIP/Premium] | Refs: 0
ID: 5697268992 | Name: Sisay worku | Username: @Sis123abc | Status: [VIP/Premium] | Refs: 0
ID: 5729512331 | Name: 𝐁𝐢𝐧𝐢𝐲𝐚𝐦 𝐓𝐞𝐬𝐟𝐚𝐲𝐞 | Username: @Beniiyam | Status: [Free] | Refs: 0
ID: 5735087110 | Name: 𝗚𝗮𝗱𝗼𝗵 | Username: @Gadoh227 | Status: [Free] | Refs: 0
ID: 5794197421 | Name: Mam 💝 Love | Username: @None | Status: [Free] | Refs: 0
ID: 5795179542 | Name: נַחוּם | Username: @K16_G19 | Status: [Free] | Refs: 0
ID: 5841869623 | Name: Negash | Username: @None | Status: [Free] | Refs: 0
ID: 5849759993 | Name: Keren Akriya | Username: @Emasavio | Status: [Free] | Refs: 0
ID: 5853796366 | Name: Efinan | Username: @efi43 | Status: [Free] | Refs: 0
ID: 5879960718 | Name: (❁‿❁) | Username: @Yesena19 | Status: [Free] | Refs: 0
ID: 5900104877 | Name: True lovers yesus | Username: @Belexe333 | Status: [Free] | Refs: 0
ID: 5928238147 | Name: O.prop Valu | Username: @obsajim | Status: [Free] | Refs: 0
ID: 5955597536 | Name: It's_Abrsh🎗 | Username: @NEAx6 | Status: [Free] | Refs: 0
ID: 5983710988 | Name: N.E.S.R.U | Username: @Nesruij | Status: [Free] | Refs: 0
ID: 6044703056 | Name: Kalye❤😍😘 | Username: @Kalye10 | Status: [Free] | Refs: 0
ID: 6064810939 | Name: ♱∑ᔑ®U♱ | Username: @ESRU_01 | Status: [Free] | Refs: 0
ID: 6101567736 | Name: 🦋나비🦋 | Username: @Pop_corn16 | Status: [Free] | Refs: 0
ID: 6126967934 | Name: Ab | Username: @cukuvera7 | Status: [Free] | Refs: 0
ID: 6128169335 | Name: @haymi🥰 🥰 | Username: @None | Status: [Free] | Refs: 1
ID: 6144447911 | Name: ሜልኮል | Username: @Yokalg | Status: [Free] | Refs: 0
ID: 6150149407 | Name: Helu ye 12 | Username: @None | Status: [Free] | Refs: 0
ID: 6169666132 | Name: 𝐅𝐋𝐀𝐒𝐇 𝐖𝐀𝐕𝐄𝐑 ⚡🃏 | Username: @Flashwaver | Status: [Free] | Refs: 0
ID: 6183608197 | Name: Dreamer 🇪🇹 🇺🇸🇺🇸 | Username: @dream4488 | Status: [VIP/Premium] | Refs: 0
ID: 6220189464 | Name: Sifen | Username: @None | Status: [Free] | Refs: 0
ID: 6226096931 | Name: Eyoba | Username: @Eyoba12335 | Status: [Free] | Refs: 0
ID: 6241469346 | Name: Barok Million | Username: @BarokMillion | Status: [Free] | Refs: 0
ID: 6279014727 | Name: Kêñêñîsâ | Username: @None | Status: [Free] | Refs: 0
ID: 6323977780 | Name: Suzana | Username: @Sumii132 | Status: [Free] | Refs: 0
ID: 6327967127 | Name: EsubeJunior | Username: @Iammoodboy | Status: [Free] | Refs: 0
ID: 6345680442 | Name: Aduman @ | Username: @Aduman1221 | Status: [Free] | Refs: 0
ID: 6348027167 | Name: ✷ | Username: @Eden027 | Status: [Free] | Refs: 0
ID: 6351924738 | Name: Optimistic | Username: @Hin_hafu | Status: [Free] | Refs: 0
ID: 6357405084 | Name: 🌎👈🖤 | Username: @Gajjjjr655555 | Status: [Free] | Refs: 0
ID: 6360710025 | Name: Bethel | Username: @betyy21s | Status: [Free] | Refs: 0
ID: 6362570480 | Name: Yosef | Username: @akiiman21 | Status: [Free] | Refs: 0
ID: 6367868046 | Name: Addis Fitret | Username: @None | Status: [Free] | Refs: 0
ID: 6373486463 | Name: Bloom | Username: @None | Status: [Free] | Refs: 0
ID: 6375234111 | Name: YISAK ABA ✝️ | Username: @yiso248 | Status: [VIP/Premium] | Refs: 0
ID: 6376627650 | Name: 𝖒𝖊𝖗𝖈𝖞.. | Username: @Nova_Soulx | Status: [Free] | Refs: 0
ID: 6380066027 | Name: JESUS | Username: @None | Status: [Free] | Refs: 0
ID: 6391244956 | Name: ህሊና🍂 | Username: @hlu_sh | Status: [Free] | Refs: 0
ID: 6405150689 | Name: 𝐈𝖓𝖓𝖚 | Username: @None | Status: [Free] | Refs: 0
ID: 6449295088 | Name: 𝕬𝖘𝖍𝖊𝖇𝖎𝖗 OG | Username: @ashebiraka | Status: [Free] | Refs: 0
ID: 6450525927 | Name: 𝓫𝓪𝓫𝓪💛 | Username: @Ababi0624 | Status: [Free] | Refs: 0
ID: 6451828020 | Name: Beta Love | Username: @Bety_Official | Status: [Free] | Refs: 0
ID: 6457669904 | Name: 🧑‍💻🗺️🌐 | Username: @None | Status: [Free] | Refs: 0
ID: 6471692943 | Name: MAREK📖 | Username: @None | Status: [Free] | Refs: 0
ID: 6474059935 | Name: Ephrembogale Lema | Username: @None | Status: [Free] | Refs: 0
ID: 6481480071 | Name: Kasim | Username: @None | Status: [Free] | Refs: 0
ID: 6482657500 | Name: Obkalna | Username: @None | Status: [Free] | Refs: 0
ID: 6488199700 | Name: 👉 S.....A | Username: @selin1221 | Status: [Free] | Refs: 0
ID: 6551795447 | Name: Nahom | Username: @Nahom006 | Status: [Free] | Refs: 15
ID: 6557162143 | Name: Chala Lema | Username: @Chalalema | Status: [Free] | Refs: 0
ID: 6604866064 | Name: ⚡ | Username: @Oddrbtfdnd | Status: [Free] | Refs: 0
ID: 6618617791 | Name: B.H | Username: @se0_8am | Status: [Free] | Refs: 0
ID: 6659388097 | Name: Talile.G🥰🫰 | Username: @Seem21215 | Status: [Free] | Refs: 0
ID: 6681999503 | Name: Keddy | Username: @alxkeddy | Status: [Free] | Refs: 0
ID: 6721402665 | Name: Ewnetu Nohe | Username: @None | Status: [Free] | Refs: 0
ID: 6730147203 | Name: سبر | Username: @None | Status: [Free] | Refs: 0
ID: 6747440515 | Name: Bõni🦋 | Username: @Boni_A72 | Status: [Free] | Refs: 0
ID: 6783452236 | Name: Beka | Username: @None | Status: [Free] | Refs: 0
ID: 6786835192 | Name: 𖢘︙ 🇮‌🇧‌🇪‌🇽‌ 𓃶 | Username: @xo_V99 | Status: [Free] | Refs: 0
ID: 6790411304 | Name: •. •. •. •. •. •. • | Username: @Abiah_40001 | Status: [Free] | Refs: 0
ID: 6822543557 | Name: Saad | Username: @S_a_a_d05 | Status: [Free] | Refs: 0
ID: 6826945540 | Name: S.Mïñtès | Username: @mintes01 | Status: [Free] | Refs: 0
ID: 6853335392 | Name: Evan | Username: @Black19218 | Status: [Free] | Refs: 0
ID: 6876057653 | Name: @hi_yab1921 | Username: @hi_yab1921 | Status: [Free] | Refs: 0
ID: 6896232977 | Name: Yo | Username: @Merrliy_05 | Status: [Free] | Refs: 0
ID: 6898878064 | Name: BLACK MOOD | Username: @None | Status: [Free] | Refs: 0
ID: 6901219139 | Name: ༎꯭ࠫ⃟≛⃝R҉O҉M҉I҉Y҉O҉ ≛⃞𝄟 | Username: @MARK_41_X | Status: [VIP/Premium] | Refs: 42
ID: 6947735808 | Name: AB☂️ | Username: @None | Status: [Free] | Refs: 0
ID: 6972563710 | Name: KIDUS | Username: @None | Status: [Free] | Refs: 0
ID: 6981194824 | Name: 🦋𝓴𝓪𝓵 16🙏 | Username: @kal6075 | Status: [Free] | Refs: 0
ID: 6999984689 | Name: Alemitu | Username: @None | Status: [Free] | Refs: 3
ID: 7006165903 | Name: 🎀🎀🎀 | Username: @None | Status: [Free] | Refs: 0
ID: 7027831377 | Name: 𖣔𓄂꯭꯭‌≛𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭𑲭ᥫ᭡፝֟፝‌ØSCAŘ🃜‌⸼‌‌꯭𝆬𝆭‌𝑳⃞‌‌𝒊፝֟ؖ۬‌֒‌𝒇꯭꯭‌𝒆꯭፝֟֯ؖ۬ | Username: @Burabarcola16 | Status: [Free] | Refs: 0
ID: 7038614542 | Name: .. | Username: @Mekdi_1425 | Status: [Free] | Refs: 0
ID: 7040154690 | Name: 𝙰𝚖𝚊𝚗 💥 | Username: @Aman_72_y | Status: [Free] | Refs: 0
ID: 7041907444 | Name: Rediet | Username: @None | Status: [Free] | Refs: 0
ID: 7052744625 | Name: K A | Username: @korentlove | Status: [Free] | Refs: 0
ID: 7077968202 | Name: Mohammed Umare siraj | Username: @None | Status: [Free] | Refs: 0
ID: 7104181571 | Name: 🦠𓆣𝄟𓆩𝐋✿𝐑♪𝐄✘𓆪𝄟 ♱‎🦠 | Username: @sixpice | Status: [Free] | Refs: 0
ID: 7119251139 | Name: 𝓶𝓮𝓻𝓬𝔂 | Username: @shitaye6m | Status: [Free] | Refs: 0
ID: 7120577105 | Name: Bethel | Username: @Bethel_Degife | Status: [Free] | Refs: 0
ID: 7125976354 | Name: REKIB On telegram | Username: @REKIBjimma | Status: [Free] | Refs: 0
ID: 7130447288 | Name: SAM🐾 | Username: @Vipppp_1 | Status: [Free] | Refs: 0
ID: 7147246225 | Name: NAHOM | Username: @Yared122146 | Status: [Free] | Refs: 0
ID: 7153234296 | Name: Eyerusalem | Username: @None | Status: [Free] | Refs: 0
ID: 7154218229 | Name: Zufi | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 7163774213 | Name: Zufan aynalem | Username: @None | Status: [Free] | Refs: 0
ID: 7190893536 | Name: ♡... | Username: @None | Status: [Free] | Refs: 0
ID: 7219002037 | Name: 🄻🄴🄾 | Username: @hunde_19 | Status: [Free] | Refs: 0
ID: 7233734828 | Name: ℮¥◎♭🇯🇲 | Username: @Xoexoe | Status: [Free] | Refs: 0
ID: 7238880127 | Name: ... | Username: @Lielt12 | Status: [Free] | Refs: 0
ID: 7246669994 | Name: Temple | Username: @Templ_e78225 | Status: [Free] | Refs: 0
ID: 7280604035 | Name: Melala | Username: @Meshyebaki | Status: [VIP/Premium] | Refs: 0
ID: 7284098969 | Name: Tola Hordofa | Username: @None | Status: [Free] | Refs: 0
ID: 7291112703 | Name: Dirshu | Username: @Eyaenate2dirshu | Status: [Free] | Refs: 0
ID: 7292178920 | Name: @marti | Username: @None | Status: [Free] | Refs: 0
ID: 7306626202 | Name: Suahibe | Username: @AMIRU_1925 | Status: [VIP/Premium] | Refs: 0
ID: 7314271800 | Name: Aschu እሁየ | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 7314296630 | Name: 𝓤𝓶𝓾 𝓴𝓾𝓵𝓼𝓾𝓶 | Username: @Bint_hassen1 | Status: [Free] | Refs: 0
ID: 7358166286 | Name: 𝐴𝑚𝑒𝑒𝑛🍎 | Username: @God_Glorified2000 | Status: [Free] | Refs: 0
ID: 7382434201 | Name: M£E€N¥G¢G¤S©T®U~ R¿o~b™el | Username: @None | Status: [Free] | Refs: 0
ID: 7388043448 | Name: S...19 | Username: @Lilinawiti | Status: [Free] | Refs: 0
ID: 7390019704 | Name: Yemaryam | Username: @Absalat212 | Status: [Free] | Refs: 0
ID: 7416028754 | Name: tsion Eshetu | Username: @None | Status: [Free] | Refs: 0
ID: 7419592469 | Name: Abdii Huseen | Username: @None | Status: [Free] | Refs: 0
ID: 7424580387 | Name: Kalbim | Username: @betina_21 | Status: [Free] | Refs: 0
ID: 7442346470 | Name: Betiy | Username: @BetiyW | Status: [Free] | Refs: 0
ID: 7467010372 | Name: 🌧🌧🌧 | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 7467517566 | Name: Hana Getachew | Username: @None | Status: [Free] | Refs: 0
ID: 7475522511 | Name: 𝕊𝔼ℕ𝔸 | Username: @tS3NA | Status: [Free] | Refs: 0
ID: 7476093791 | Name: Melkamu Mekonen | Username: @melke128 | Status: [Free] | Refs: 0
ID: 7492050688 | Name: A.,Zulbijadeyn. | Username: @Abuturab27 | Status: [Free] | Refs: 0
ID: 7518454279 | Name: Samuel@ | Username: @None | Status: [Free] | Refs: 0
ID: 7520033440 | Name: 𝔢𝔷𝔲 𝔫𝔞𝔫𝔞𝔱𝔦 | Username: @Eyuyen | Status: [Free] | Refs: 0
ID: 7528711667 | Name: ...🎧🥀 M̶a̶🤴 | Username: @kebama21 | Status: [Free] | Refs: 0
ID: 7553295808 | Name: Abusalih | Username: @Sirajkasi | Status: [Free] | Refs: 0
ID: 7556454219 | Name: Ŝêgñî 🇲 🇦 🇳 | Username: @SegniBk | Status: [Free] | Refs: 0
ID: 7563885292 | Name: Radiet Abera | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 7583562500 | Name: Hiwot🌺 | Username: @None | Status: [Free] | Refs: 0
ID: 7590327262 | Name: Kidi 21 | Username: @None | Status: [Free] | Refs: 0
ID: 7593300976 | Name: Tesmamu Tariku | Username: @te12ta | Status: [Free] | Refs: 0
ID: 7594110138 | Name: Özil | Username: @Rayadavi | Status: [Free] | Refs: 0
ID: 7602452774 | Name: KRTAH 16 | Username: @DKRTAH | Status: [Free] | Refs: 0
ID: 7616853226 | Name: Håppįñę§ | Username: @loveu1437 | Status: [Free] | Refs: 0
ID: 7626824661 | Name: Alhamdulilh alakulihal | Username: @Sitra123mifta | Status: [Free] | Refs: 0
ID: 7639882548 | Name: Abebech Gosa | Username: @Dec1130 | Status: [Free] | Refs: 0
ID: 7641346255 | Name: 🇰‌𝐞𝐧𝐚𝐟𝐚𝐧 | Username: @Kenafan5 | Status: [Free] | Refs: 0
ID: 7647360684 | Name: .ASHU.. Rasu | Username: @ashu_ras | Status: [Free] | Refs: 0
ID: 7651804392 | Name: ሷሂቡል ደረሳ | Username: @Gdgdg6wo | Status: [Free] | Refs: 0
ID: 7652042412 | Name: የሚካኤል ልጅ 12 | Username: @None | Status: [Free] | Refs: 0
ID: 7665041528 | Name: Elsu | Username: @None | Status: [Free] | Refs: 0
ID: 7673493050 | Name: memar Alebachew | Username: @None | Status: [Free] | Refs: 0
ID: 7674046033 | Name: Frank | Username: @ffy12 | Status: [Free] | Refs: 0
ID: 7681782670 | Name: Řêÿũ Ľövë | Username: @None | Status: [Free] | Refs: 0
ID: 7685395898 | Name: Mol | Username: @Melekotddd | Status: [Free] | Refs: 0
ID: 7689760197 | Name: Hana | Username: @None | Status: [Free] | Refs: 0
ID: 7699020301 | Name: Lukas | Username: @Lukas12198 | Status: [Free] | Refs: 0
ID: 7701835594 | Name: Tizu 🦋 | Username: @bamayt | Status: [Free] | Refs: 0
ID: 7702946669 | Name: H K | Username: @Rut21_12 | Status: [Free] | Refs: 0
ID: 7707131950 | Name: ╾━╤デ╦︻(•⤙•)Σίγμα( ͡° ͜ʖ ͡°)︻̷┻ ═━一- | Username: @Ggad123 | Status: [Free] | Refs: 0
ID: 7707946650 | Name: Everything.... | Username: @noth325 | Status: [Free] | Refs: 0
ID: 7715549021 | Name: ¥€£®© | Username: @Yiun1 | Status: [VIP/Premium] | Refs: 0
ID: 7727125206 | Name: @Gammee | Username: @None | Status: [Free] | Refs: 0
ID: 7727218258 | Name: Dirshaye Desalegn | Username: @None | Status: [Free] | Refs: 0
ID: 7728174389 | Name: 𝕞𝕒𝕞𝕖 🅗🅐🅑🅔🅢🅗🅘🅨 | Username: @mame0032 | Status: [Free] | Refs: 0
ID: 7731274286 | Name: Sami | Username: @None | Status: [Free] | Refs: 0
ID: 7733250174 | Name: 𝐃𝐮🎀 | Username: @Lia0916 | Status: [Free] | Refs: 2
ID: 7745606349 | Name: Promis | Username: @None | Status: [Free] | Refs: 0
ID: 7755059243 | Name: ቃል | Username: @Kalkedan0612 | Status: [Free] | Refs: 0
ID: 7757864364 | Name: Gebremedin Birhanu | Username: @gebremedin21 | Status: [Free] | Refs: 0
ID: 7791421068 | Name: Rahmat | Username: @None | Status: [Free] | Refs: 0
ID: 7802683903 | Name: Frtu Ad | Username: @None | Status: [Free] | Refs: 0
ID: 7814276330 | Name: @baredu11j1 | Username: @None | Status: [Free] | Refs: 0
ID: 7816219241 | Name: Lij Rediet⚔️ | Username: @Redi2730 | Status: [Free] | Refs: 0
ID: 7823642115 | Name: Afi | Username: @None | Status: [Free] | Refs: 0
ID: 7834822828 | Name: ​mantel... | Username: @Lil_abel_1 | Status: [Free] | Refs: 0
ID: 7835003997 | Name: Tom Diaz | Username: @None | Status: [Free] | Refs: 0
ID: 7837333478 | Name: Whatale Miktil | Username: @None | Status: [Free] | Refs: 0
ID: 7838568174 | Name: 𝓶𝓾𝓫𝓪✨ | Username: @Mubaofficialaccount | Status: [Free] | Refs: 0
ID: 7842624874 | Name: Exodus | Username: @exodus_3 | Status: [Free] | Refs: 0
ID: 7851457744 | Name: . | Username: @None | Status: [Free] | Refs: 0
ID: 7858476082 | Name: . | Username: @None | Status: [Free] | Refs: 0
ID: 7862542853 | Name: 𝑠𝑤𝑒𝑒𝑡 ℎ𝑒𝑎𝑟𝑡 🥰 | Username: @Bintnur56 | Status: [Free] | Refs: 0
ID: 7892618864 | Name: 🌸✨️ | Username: @Blenn192 | Status: [VIP/Premium] | Refs: 0
ID: 7901613698 | Name: Dan Pro | Username: @Unityprom1234 | Status: [Free] | Refs: 0
ID: 7913696676 | Name: Eyu | Username: @Millal2 | Status: [Free] | Refs: 0
ID: 7922899347 | Name: Jerusalem | Username: @Jeru_salemmm | Status: [Free] | Refs: 0
ID: 7930057650 | Name: BbTt | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 7932566023 | Name: አማኑኤል 28 | Username: @None | Status: [VIP/Premium] | Refs: 64
ID: 7934967793 | Name: Sebeha Temam | Username: @None | Status: [Free] | Refs: 0
ID: 7944736400 | Name: emanuel | Username: @emanuel_38 | Status: [Free] | Refs: 0
ID: 7950393278 | Name: Liyo🥶 | Username: @Liyo435 | Status: [Free] | Refs: 5
ID: 7957532951 | Name: Han Aaaa | Username: @None | Status: [Free] | Refs: 0
ID: 7957747758 | Name: Novali🍫🍫 Last lesson | Username: @None | Status: [Free] | Refs: 0
ID: 7962005787 | Name: H🌸 | Username: @None | Status: [Free] | Refs: 0
ID: 7965152987 | Name: M K | Username: @Kad0960 | Status: [Free] | Refs: 0
ID: 7968394165 | Name: Mekdi | Username: @None | Status: [Free] | Refs: 0
ID: 7970232603 | Name: ♟️🖋️ | Username: @dannb1953 | Status: [Free] | Refs: 3
ID: 7970477019 | Name: Birhanu Mangistuu | Username: @None | Status: [Free] | Refs: 0
ID: 7978403364 | Name: Rishan mebrahtu Members | Username: @Me9579 | Status: [Free] | Refs: 0
ID: 7990374192 | Name: Cher man | Username: @Chere717 | Status: [Free] | Refs: 0
ID: 7995245006 | Name: 𝒯𝒶𝒹𝓁𝒶 𝒢𝒶𝓈𝒽𝒶𝓌 | Username: @None | Status: [Free] | Refs: 0
ID: 7997594900 | Name: H.✨👑 | Username: @B16haymi | Status: [Free] | Refs: 0
ID: 8004065418 | Name: Нєяαи:% | Username: @None | Status: [Free] | Refs: 0
ID: 8004567110 | Name: ꪶꪑ¹⁰ | Username: @Brk_Jss | Status: [Free] | Refs: 20
ID: 8005218721 | Name: Abel Ø | Username: @None | Status: [Free] | Refs: 0
ID: 8010459782 | Name: 𝘼𝙗𝙞𝙕𝙚𝙧🔥 | Username: @AbI_fy | Status: [Free] | Refs: 0
ID: 8024612172 | Name: Iᗷ ᔕ | Username: @Ibsapro | Status: [VIP/Premium] | Refs: 31
ID: 8033288328 | Name: One day 📈 I hope 🙏 | Username: @Onlymybloodforever | Status: [Free] | Refs: 0
ID: 8038843167 | Name: ወይኩን ፈቃድከ🙏 | Username: @None | Status: [Free] | Refs: 0
ID: 8044984537 | Name: 𝐂𝐑 𝟕 🇵🇹 | Username: @mubasesko | Status: [Free] | Refs: 0
ID: 8049588051 | Name: @yoni🥶 | Username: @None | Status: [Free] | Refs: 0
ID: 8056962594 | Name: Redu @kidi | Username: @kidi_k24 | Status: [Free] | Refs: 0
ID: 8057027304 | Name: Abduselam Ahmed | Username: @None | Status: [Free] | Refs: 0
ID: 8067539361 | Name: M | Username: @Firmis1234 | Status: [Free] | Refs: 0
ID: 8070633644 | Name: Źŏýã ... | Username: @Zoya909 | Status: [VIP/Premium] | Refs: 0
ID: 8078793180 | Name: @As7 | Username: @Asrrr764 | Status: [Free] | Refs: 0
ID: 8083857453 | Name: Nyra | Username: @nayri24 | Status: [Free] | Refs: 0
ID: 8104483675 | Name: Sami | Username: @Wall_7725 | Status: [Free] | Refs: 0
ID: 8108395100 | Name: ታብ_ሲያ | Username: @None | Status: [Free] | Refs: 0
ID: 8110702899 | Name: Netsanet Wube | Username: @None | Status: [Free] | Refs: 0
ID: 8119887961 | Name: Whats App | Username: @wassie23 | Status: [Free] | Refs: 0
ID: 8135664231 | Name: Áriéla🦁 | Username: @Be_ni_el | Status: [Free] | Refs: 0
ID: 8135667771 | Name: ...... | Username: @None | Status: [Free] | Refs: 0
ID: 8141661296 | Name: Ms Ms | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8143692238 | Name: @merina | Username: @None | Status: [Free] | Refs: 0
ID: 8170652972 | Name: Sis | Username: @Shbshabowamaryam21 | Status: [Free] | Refs: 0
ID: 8177548885 | Name: El-bet'el | Username: @Badhobore | Status: [Free] | Refs: 0
ID: 8181695806 | Name: Osman Ayalew | Username: @osman_maze | Status: [VIP/Premium] | Refs: 0
ID: 8181957184 | Name: Ab የሉርድ | Username: @None | Status: [Free] | Refs: 0
ID: 8210040588 | Name: Sime | Username: @None | Status: [Free] | Refs: 0
ID: 8214772486 | Name: Tina ... | Username: @None | Status: [Free] | Refs: 0
ID: 8219729407 | Name: ìs_Aßiyâ | Username: @None | Status: [Free] | Refs: 0
ID: 8220707598 | Name: Hina Mark | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8220781046 | Name: Selam # | Username: @None | Status: [Free] | Refs: 0
ID: 8227954373 | Name: Mujibo | Username: @MU6939 | Status: [Free] | Refs: 0
ID: 8233224872 | Name: Gabry | Username: @None | Status: [Free] | Refs: 0
ID: 8233462171 | Name: 𝓵𝓸𝓿𝓮𝓵𝔂 ....😘 | Username: @Sun9916 | Status: [Free] | Refs: 0
ID: 8238538581 | Name: Sarina🌸👸 | Username: @sara_girma42 | Status: [Free] | Refs: 0
ID: 8249507057 | Name: New Man | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8258852380 | Name: Leya | Username: @None | Status: [Free] | Refs: 0
ID: 8265870698 | Name: i...k✨️✨️ | Username: @india24478 | Status: [Free] | Refs: 0
ID: 8266588924 | Name: Dead pool 🔱🔱🔱 | Username: @Lbrghd | Status: [Free] | Refs: 0
ID: 8276752102 | Name: Marti Ye Mariyam lij | Username: @None | Status: [Free] | Refs: 0
ID: 8279477177 | Name: M Jemal M Kemal | Username: @Yoofedhasataee | Status: [Free] | Refs: 0
ID: 8282033596 | Name: Haymi | Username: @None | Status: [Free] | Refs: 0
ID: 8283671418 | Name: Ftsum🥀 | Username: @ftsum80 | Status: [Free] | Refs: 0
ID: 8285346026 | Name: Daisy 🌸 | Username: @Daisy_tmm | Status: [Free] | Refs: 0
ID: 8288873327 | Name: 🗯 | Username: @None | Status: [Free] | Refs: 0
ID: 8320672052 | Name: Aymen | Username: @Nurzemen123 | Status: [Free] | Refs: 0
ID: 8322389075 | Name: lนຖค | Username: @A_na101 | Status: [Free] | Refs: 0
ID: 8323040150 | Name: Super hero 💪 Super hero 💪 | Username: @None | Status: [Free] | Refs: 0
ID: 8325818035 | Name: Dagim | Username: @dagi142536 | Status: [Free] | Refs: 0
ID: 8334585520 | Name: Yalem | Username: @None | Status: [Free] | Refs: 0
ID: 8335730525 | Name: Na'ol Dambidollo University | Username: @None | Status: [Free] | Refs: 0
ID: 8337920798 | Name: Dagi | Username: @None | Status: [Free] | Refs: 0
ID: 8342866320 | Name: nxr | Username: @User_7052 | Status: [Free] | Refs: 0
ID: 8349497891 | Name: 🕸️🕷️🕷️ | Username: @None | Status: [Free] | Refs: 0
ID: 8352587840 | Name: Mafi | Username: @mafina0711 | Status: [Free] | Refs: 0
ID: 8352991427 | Name: Beletu Asnakew | Username: @None | Status: [Free] | Refs: 0
ID: 8354582042 | Name: Ela👌 Gobena | Username: @None | Status: [Free] | Refs: 0
ID: 8366049068 | Name: 𝐌𝐨𝐨𝐢 | Username: @gr_mooi | Status: [Free] | Refs: 0
ID: 8376253800 | Name: "አምላኬ ሆይ ኀይልከ ዬምጣልኝ":: | Username: @None | Status: [Free] | Refs: 0
ID: 8383395657 | Name: Amare Migbaru | Username: @None | Status: [Free] | Refs: 0
ID: 8398010196 | Name: Ss | Username: @Sita5262 | Status: [Free] | Refs: 0
ID: 8407295833 | Name: Sol | Username: @None | Status: [Free] | Refs: 0
ID: 8407813559 | Name: K | Username: @kidye_161 | Status: [Free] | Refs: 0
ID: 8414772292 | Name: 𝖓𝖎𝖌𝖍𝖙 𝖗𝖎𝖉𝖊𝖗 | Username: @None | Status: [Free] | Refs: 0
ID: 8417252878 | Name: Haimanot | Username: @None | Status: [Free] | Refs: 0
ID: 8422170234 | Name: 𝗧𝗢𝗠𝗢𝗥𝗥𝗢𝗪 IS AN OTHER DAY | Username: @Dani3710a | Status: [Free] | Refs: 0
ID: 8425043410 | Name: Neba D.r | Username: @None | Status: [Free] | Refs: 0
ID: 8430326103 | Name: M M | Username: @Mebuzg | Status: [Free] | Refs: 0
ID: 8443016054 | Name: Anmut Adugna | Username: @Animt2127 | Status: [Free] | Refs: 0
ID: 8458392623 | Name: Mitiku | Username: @None | Status: [Free] | Refs: 0
ID: 8458996403 | Name: Mercy | Username: @None | Status: [Free] | Refs: 0
ID: 8465146628 | Name: Betelihem | Username: @Beti8383 | Status: [Free] | Refs: 0
ID: 8465162652 | Name: 👉🏾Turisha ✍🏾 Official | Username: @Turishaa1 | Status: [Free] | Refs: 1
ID: 8470311272 | Name: Blen | Username: @None | Status: [Free] | Refs: 0
ID: 8477143998 | Name: Kuleni | Username: @MKS2205 | Status: [Free] | Refs: 0
ID: 8482612121 | Name: Lizana | Username: @None | Status: [Free] | Refs: 0
ID: 8482812379 | Name: Sifan | Username: @siif0412 | Status: [Free] | Refs: 0
ID: 8487962563 | Name: 𝓡𝓸𝓼𝔂 | Username: @rosyrosa1221 | Status: [Free] | Refs: 0
ID: 8502411734 | Name: Adane Teshome | Username: @None | Status: [Free] | Refs: 0
ID: 8506268783 | Name: Fiii🦋🦋 | Username: @Fiyory444 | Status: [Free] | Refs: 8
ID: 8509038624 | Name: S@m G# | Username: @None | Status: [Free] | Refs: 0
ID: 8516655195 | Name: Bemni 🦋 | Username: @Lun_a2116 | Status: [Free] | Refs: 0
ID: 8520362309 | Name: @ENDALE Ka | Username: @None | Status: [Free] | Refs: 0
ID: 8520939971 | Name: 𝓑𝓲𝓽𝓪𝓷𝓲𝔂𝓪 🦋 | Username: @None | Status: [Free] | Refs: 0
ID: 8521777158 | Name: حبيب | Username: @wershj09 | Status: [Free] | Refs: 0
ID: 8527938206 | Name: ∞ | Username: @None | Status: [Free] | Refs: 0
ID: 8531700901 | Name: 𝕓𝕠𝕠𝕞➼ 𝕓𝕠𝕠𝕞👀🇦🇷🇦🇷🇪🇹🇪🇹 | Username: @LijKhalids10 | Status: [Free] | Refs: 0
ID: 8536348885 | Name: yafeti | Username: @yafe73kgl | Status: [Free] | Refs: 0
ID: 8537162061 | Name: 𝓡𝓾𝓽𝓱 | Username: @Rnaz_rawit | Status: [Free] | Refs: 8
ID: 8548834723 | Name: Gunner | Username: @None | Status: [Free] | Refs: 0
ID: 8554835829 | Name: Muluken Werisa | Username: @muluken0621 | Status: [Free] | Refs: 0
ID: 8555581244 | Name: Smile ☺ | Username: @None | Status: [Free] | Refs: 0
ID: 8557009044 | Name: Silent | Username: @None | Status: [Free] | Refs: 0
ID: 8564246870 | Name: Abel Shumbeza | Username: @None | Status: [Free] | Refs: 0
ID: 8572366671 | Name: Elue | Username: @Elu1621 | Status: [Free] | Refs: 0
ID: 8579500020 | Name: Helen | Username: @None | Status: [Free] | Refs: 0
ID: 8596574530 | Name: Hiwot Abera | Username: @None | Status: [Free] | Refs: 0
ID: 8598785618 | Name: 🆕 | Username: @None | Status: [Free] | Refs: 0
ID: 8600868632 | Name: 🦋𝓔𝓵𝓵𝓪🤩👻👻☄️ | Username: @None | Status: [Free] | Refs: 0
ID: 8601412630 | Name: Daniel Itana | Username: @None | Status: [Free] | Refs: 0
ID: 8601803696 | Name: Meskerm Getachew | Username: @None | Status: [Free] | Refs: 0
ID: 8609847644 | Name: Betsegaw Mekonnin | Username: @None | Status: [Free] | Refs: 0
ID: 8618175744 | Name: Vino 🦋🦋 | Username: @Wine2704 | Status: [Free] | Refs: 0
ID: 8618762854 | Name: Senait | Username: @None | Status: [Free] | Refs: 0
ID: 8620848830 | Name: 🥀 | Username: @None | Status: [Free] | Refs: 0
ID: 8629206946 | Name: Behredin Ahmed | Username: @None | Status: [Free] | Refs: 0
ID: 8632325956 | Name: sida | Username: @Fasilove | Status: [Free] | Refs: 0
ID: 8635937662 | Name: EPHREM Tsehayu | Username: @None | Status: [Free] | Refs: 0
ID: 8636673406 | Name: Gizachew Tefera 👉MT👈 | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8685823725 | Name: Sevi...... | Username: @None | Status: [Free] | Refs: 0
ID: 8685977577 | Name: Châlâ is kîñg💊👌 | Username: @Dhufuuufjira | Status: [Free] | Refs: 0
ID: 8689057235 | Name: Roman | Username: @Mekidesroman | Status: [Free] | Refs: 0
ID: 8690395812 | Name: Kuka | Username: @Mekenehiwot | Status: [Free] | Refs: 0
ID: 8691702280 | Name: Beti | Username: @None | Status: [Free] | Refs: 0
ID: 8693099525 | Name: Emu | Username: @None | Status: [Free] | Refs: 0
ID: 8709337382 | Name: Wondu kassahun Dinato | Username: @None | Status: [Free] | Refs: 0
ID: 8726313320 | Name: 🌍 | Username: @None | Status: [Free] | Refs: 5
ID: 8727174836 | Name: 𝕜𝕚𝕪𝕒𝕣𝕒😍😍😍😍 😂😂😂 | Username: @None | Status: [Free] | Refs: 0
ID: 8730652357 | Name: @ | Username: @None | Status: [Free] | Refs: 0
ID: 8732933395 | Name: zed man | Username: @None | Status: [Free] | Refs: 0
ID: 8738495613 | Name: 𝖝𝖝𝖝 𝖆𝖇𝖎𝖙𝖆 | Username: @None | Status: [Free] | Refs: 0
ID: 8741331103 | Name: 𝓷𝓮𝓿𝓮𝓻 𝓰𝓲𝓿𝓮 𝓾𝓹🦋🦋🦋 | Username: @Betisha06 | Status: [Free] | Refs: 0
ID: 8741874318 | Name: 👸 | Username: @Rahe1216 | Status: [Free] | Refs: 0
ID: 8743936081 | Name: yanu $🍫 | Username: @None | Status: [Free] | Refs: 0
ID: 8745542555 | Name: 213 | Username: @None | Status: [VIP/Premium] | Refs: 31
ID: 8758305264 | Name: Solu al nebi | Username: @emutie124 | Status: [VIP/Premium] | Refs: 0
ID: 8764912036 | Name: yordi | Username: @None | Status: [Free] | Refs: 0
ID: 8770021219 | Name: Bacha Gemechis | Username: @None | Status: [Free] | Refs: 0
ID: 8777285774 | Name: Abdu 88 | Username: @None | Status: [Free] | Refs: 0
ID: 8783715776 | Name: hunyalew hune | Username: @None | Status: [Free] | Refs: 0
ID: 8796988285 | Name: Support | Username: @Rmedialmatrixsupport | Status: [VIP/Premium] | Refs: 0
ID: 8802571803 | Name: Melona 🤣😭 | Username: @None | Status: [Free] | Refs: 0
ID: 8813066709 | Name: Yordi 1916 | Username: @None | Status: [Free] | Refs: 0
ID: 8815258977 | Name: @R_b_k | Username: @ribkaA3451 | Status: [Free] | Refs: 0
ID: 8817781540 | Name: My Dream | Username: @Supermind21 | Status: [Free] | Refs: 0
ID: 8841895909 | Name: 𝕭𝖊𝖓𝖏𝖎 𝕱𝖑𝖔𝖜 | Username: @Benji_bst | Status: [Free] | Refs: 0
ID: 8842472030 | Name: •๋๋๋✟𝄞͡•๋๋𝚖𝚊𝚛𝚔🔱𝄞͡𓅃 | Username: @Mark_CJ_41 | Status: [Free] | Refs: 0
ID: 8850892137 | Name: Tizita | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8851466338 | Name: Adriano | Username: @Adriano2226 | Status: [Free] | Refs: 0
ID: 8855099966 | Name: Sisay Belete | Username: @None | Status: [Free] | Refs: 0
ID: 8859785603 | Name: Jack 💀 | Username: @None | Status: [Free] | Refs: 0
ID: 8874576780 | Name: .. | Username: @None | Status: [Free] | Refs: 0
ID: 8875957536 | Name: Kim | Username: @None | Status: [Free] | Refs: 0
ID: 8879540599 | Name: .... | Username: @Sava068 | Status: [Free] | Refs: 0
ID: 8885724020 | Name: Unko N | Username: @Tebakiye15 | Status: [VIP/Premium] | Refs: 0
ID: 8891332931 | Name: JOLLY | Username: @None | Status: [Free] | Refs: 0
ID: 8892992648 | Name: 𖣔ꠋ ᡃ⃝ᡃ⃝ᡃ⃝ 𝓲ᬼ⃝✞︎➠ˡ𝗫𝗹𝗹𝚙𝚊𝚙𝚢_𝗩𝗹𝗹✞︎𖣔ꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋꠋ 💀 | Username: @Yguvu | Status: [Free] | Refs: 0
ID: 8898981592 | Name: B.O.N.A | Username: @None | Status: [Free] | Refs: 0
ID: 8899715536 | Name: Geme | Username: @None | Status: [Free] | Refs: 0
ID: 8900229729 | Name: 🔗🔗🤖 💲 | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8900430577 | Name: Behrdin Belay | Username: @None | Status: [Free] | Refs: 27
ID: 8910804047 | Name: Black Max | Username: @None | Status: [Free] | Refs: 0
ID: 8911310477 | Name: Kemal Goat | Username: @None | Status: [Free] | Refs: 0
ID: 8912824684 | Name: Диана Максимова | Username: @None | Status: [Free] | Refs: 0
ID: 8914493817 | Name: Bro | Username: @None | Status: [Free] | Refs: 0
ID: 8920498554 | Name: ℛ𝓊𝓉𝒽 | Username: @Rarmy3 | Status: [VIP/Premium] | Refs: 34
ID: 8924583939 | Name: Eba | Username: @E_b_a123 | Status: [VIP/Premium] | Refs: 0
ID: 8925381921 | Name: unknown 09 51 61 73 !!!! | Username: @None | Status: [Free] | Refs: 0
ID: 8931852665 | Name: @H,,,,,,,, | Username: @None | Status: [Free] | Refs: 0
ID: 8932230946 | Name: Netsi | Username: @netsi12255 | Status: [Free] | Refs: 0
ID: 8937172663 | Name: Remedial matrix support 🎓 | Username: @Rmedial_matrix_support | Status: [VIP/Premium] | Refs: 0
ID: 8944145601 | Name: Vote | Username: @vote444 | Status: [Free] | Refs: 0
ID: 8946576728 | Name: ECHO | Username: @K_lyad | Status: [Free] | Refs: 0
ID: 8948521723 | Name: Cr7 👌💀 | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8950033465 | Name: ⋆:@🖤💥⎯⃝"Little princess👸 🖤💥 | Username: @Icy_heart678 | Status: [Free] | Refs: 0
ID: 8952625019 | Name: miracle 😎 | Username: @None | Status: [VIP/Premium] | Refs: 0
ID: 8960105868 | Name: Masfin | Username: @None | Status: [Free] | Refs: 0
ID: 8964733073 | Name: Abinet Adisu | Username: @None | Status: [Free] | Refs: 0
ID: 8976306255 | Name: M Jemal M Kemal | Username: @YaaRsitiiamaanaa | Status: [Free] | Refs: 0
ID: 8984385960 | Name: Diriba Tamiru | Username: @None | Status: [Free] | Refs: 0
ID: 8986727459 | Name: 🎧𝖘𝖔𝖑𝖆𝖓𝖐𝖎💦 | Username: @None | Status: [Free] | Refs: 0
ID: 8990145918 | Name: 𝓑𝓽𝓼 𝓛𝓸𝓿𝓮 | Username: @None | Status: [Free] | Refs: 0
"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    success_count = 0
    for line in raw_data.strip().split('\n'):
        if not line.strip(): continue
        try:
            parts = line.split(' | ')
            user_id = int(parts[0].replace('ID:', '').strip())
            name = parts[1].replace('Name:', '').strip()
            username = parts[2].replace('Username:', '').strip()
            if username in ['@None', 'None']: username = None
            elif username and username.startswith('@'): username = username[1:]
            status_str = parts[3].replace('Status:', '').strip()
            is_premium = 1 if 'VIP' in status_str else 0
            refs = int(parts[4].replace('Refs:', '').strip())
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, full_name, username, is_premium, referred_by, referral_count, total_score, total_quizzes, vip_expiry)
                VALUES (?, ?, ?, ?, NULL, ?, 0, 0, NULL)
            ''', (user_id, name, username, is_premium, refs))
            success_count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ {success_count} ተጠቃሚዎች ወደ ዳታቤዝ ገብተዋል!")

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

    # ይህ የተስተካከለው የ ጥያቄ ማንበቢያ ሎጂክ ነው
    if data.startswith("q|"):
        parts = data.split("|")
        category = parts[1]
        year = str(parts[2]) 
        subject = parts[3].lower()
        index = int(parts[4])

        questions_data = load_questions()
        cat_key = "model_exams" if category == "model" else "remedial_exams"
        exam_questions = []
        
        if cat_key in questions_data:
            year_data = {str(k): v for k, v in questions_data[cat_key].items()}
            if year in year_data:
                for k, v in year_data[year].items():
                    if k.lower() == subject or (subject in ["math", "maths"] and k.lower() in ["math", "maths", "mathematics"]):
                        exam_questions = v
                        break

        if not exam_questions:
            await query.message.reply_text(f"⚠️ የ {year} {parts[3]} ጥያቄዎች በፋይሉ ውስጥ ገና አልተሞሉም!")
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

            is_prot = False if user.id == ADMIN_ID else True
            await context.bot.send_poll(
                chat_id=query.message.chat_id,
                question=q_text,
                options=options,
                is_anonymous=False,
                type="quiz",
                correct_option_id=correct_id,
                explanation=explanation if explanation else None,
                protect_content=is_prot
            )

            nav_buttons = []
            row = []
            if index > 0:
                row.append(InlineKeyboardButton("⬅️ ተመለስ (Back)", callback_data=f"q|{category}|{year}|{parts[3]}|{index - 1}"))
            if index + 1 < total:
                row.append(InlineKeyboardButton(f"ቀጣይ ({index + 2}/{total}) ➡️", callback_data=f"q|{category}|{year}|{parts[3]}|{index + 1}"))
            
            if row:
                nav_buttons.append(row)
            nav_buttons.append([InlineKeyboardButton("🏠 ዋና ምናሌ (Main Menu)", callback_data="back_to_main")])

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="ለማስተካከል ወይም ለመቀጠል ከታች ያሉትን ቁልፎች ይጠቀሙ 👇",
                reply_markup=InlineKeyboardMarkup(nav_buttons),
                protect_content=is_prot
            )
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
            db_update_user_score(user_id, score)
            
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
    application.add_handler(CommandHandler("restore", restore_users_command)) # ዳታ ማስገቢያ ትዕዛዝ
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == '__main__':
    main()
