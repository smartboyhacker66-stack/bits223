import os
import random
import string
import logging
import tempfile
import datetime
import asyncio
import threading

import pytz
from flask import Flask, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from pypdf import PdfReader, PdfWriter
import pdfplumber
from gtts import gTTS
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except ImportError:
    PIKEPDF_AVAILABLE = False

try:
    import louis
    LOUIS_AVAILABLE = True
except ImportError:
    LOUIS_AVAILABLE = False

try:
    import pytesseract
    from pdf2image import convert_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_SDK_AVAILABLE = True
except ImportError:
    FIREBASE_SDK_AVAILABLE = False

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "api77u7y")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", "10000"))
FIREBASE_KEY_PATH = os.environ.get("FIREBASE_KEY_PATH", "/etc/secrets/firebase-key.json")

FILE_PREFIX = "BlindIndianTechSupport"
SUPPORT_EMAIL = "bits.headquarter505@gmail.com"
SUPPORT_IMAGE_PATH = "support.jpg"

VERSION_NAME = "Version 2.0 - Foundation Update"
VERSION_RELEASE_ISO = "2026-09-27T00:00:00"

SESSION_TIMEOUT_SECONDS = 120
IST = pytz.timezone("Asia/Kolkata")


def ist_now():
    return datetime.datetime.now(IST)


def ist_now_str():
    return ist_now().strftime("%d-%b-%Y %I:%M:%S %p IST")


# ---------------------------------------------------------------------------
# Firebase setup (falls back gracefully to memory-only mode if unavailable)
# ---------------------------------------------------------------------------
db = None
FIREBASE_AVAILABLE = False

if FIREBASE_SDK_AVAILABLE:
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_KEY_PATH)
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        FIREBASE_AVAILABLE = True
        logger.info("Firebase connected successfully.")
    except Exception as e:
        logger.warning(f"Firebase could not be initialized, running in memory-only mode: {e}")
        db = None
        FIREBASE_AVAILABLE = False


def fb_set(collection, doc_id, data, merge=True):
    if not FIREBASE_AVAILABLE:
        return
    try:
        db.collection(collection).document(doc_id).set(data, merge=merge)
    except Exception as e:
        logger.warning(f"Firebase write failed ({collection}/{doc_id}): {e}")


def fb_get(collection, doc_id):
    if not FIREBASE_AVAILABLE:
        return None
    try:
        doc = db.collection(collection).document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.warning(f"Firebase read failed ({collection}/{doc_id}): {e}")
        return None


def fb_delete(collection, doc_id):
    if not FIREBASE_AVAILABLE:
        return
    try:
        db.collection(collection).document(doc_id).delete()
    except Exception as e:
        logger.warning(f"Firebase delete failed ({collection}/{doc_id}): {e}")


# ---------------------------------------------------------------------------
# In-memory state (backed by Firebase where available)
# ---------------------------------------------------------------------------
SESSIONS = {}
PENDING_RATING = {}
ADMIN_STATE = {"admin_id": None, "failed_attempts": {}}

# Load admin_id from Firebase on startup, if it was set before a restart
_admin_doc = fb_get("admin", "state")
if _admin_doc and _admin_doc.get("admin_id"):
    ADMIN_STATE["admin_id"] = _admin_doc.get("admin_id")


WELCOME_MESSAGES = {
    "en": (
        "Welcome to the Blind Indian Tech Support PDF Manipulation Toolbox. "
        "Our best tool of 2026. Specially designed for visually impaired individuals. "
        "Release date: September 22, 2026. All rights reserved (c) Blind Indian Tech Support Team, "
        "2026 and beyond. Developed and hosted by Blind Indian Tech Support. This bot has been online "
        "since September 22, 2026. A heartfelt thank you to all our testers and users who used this "
        "service and provided valuable feedback. We will continue to add more updates in the future, "
        "and we promise to never collect or store your files anywhere. Once again, a heartfelt thank "
        "you to everyone who used and tested this tool.\n\n"
        "Please note: our server may sometimes take 30 to 60 seconds to respond to your very first "
        "message after a period of inactivity. After that, it will respond quickly."
    ),
    "hi": (
        "ब्लाइंड इंडियन टेक सपोर्ट पीडीएफ मैनिपुलेशन टूलबॉक्स में आपका स्वागत है। यह 2026 का हमारा सबसे बेहतरीन टूल है, "
        "जो विशेष रूप से दृष्टिबाधित लोगों के लिए बनाया गया है। रिलीज़ की तारीख: 22 सितंबर, 2026। सर्वाधिकार सुरक्षित, "
        "ब्लाइंड इंडियन टेक सपोर्ट टीम, 2026 और आगे। इसे ब्लाइंड इंडियन टेक सपोर्ट द्वारा बनाया और होस्ट किया गया है। "
        "यह बॉट 22 सितंबर, 2026 से ऑनलाइन है। हमारे उन सभी परीक्षकों और उपयोगकर्ताओं का दिल से धन्यवाद, जिन्होंने इस सेवा "
        "का इस्तेमाल किया और महत्वपूर्ण प्रतिक्रिया दी। हम भविष्य में और भी अपडेट जोड़ते रहेंगे, और हम वादा करते हैं कि "
        "आपकी कोई भी फाइल कभी भी सुरक्षित या संग्रहीत नहीं की जाएगी। एक बार फिर, इस टूल का इस्तेमाल और परीक्षण करने वाले "
        "सभी लोगों का दिल से धन्यवाद।\n\n"
        "कृपया ध्यान दें: कुछ समय तक इस्तेमाल न होने के बाद, आपके पहले मैसेज का जवाब आने में कभी-कभी 30 से 60 सेकंड का "
        "समय लग सकता है। उसके बाद बॉट तेज़ी से जवाब देगा।"
    ),
    "mr": (
        "ब्लाइंड इंडियन टेक सपोर्ट पीडीएफ मॅनिप्युलेशन टूलबॉक्समध्ये आपले स्वागत आहे. हे 2026 सालातील आमचे सर्वोत्तम टूल आहे, "
        "जे खास दृष्टिबाधित व्यक्तींसाठी तयार करण्यात आले आहे. प्रकाशन तारीख: 22 सप्टेंबर, 2026. सर्व हक्क राखीव, "
        "ब्लाइंड इंडियन टेक सपोर्ट टीम, 2026 आणि पुढे. हे ब्लाइंड इंडियन टेक सपोर्टने विकसित आणि होस्ट केले आहे. "
        "हा बॉट 22 सप्टेंबर, 2026 पासून ऑनलाइन आहे. या सेवेचा वापर करून मौल्यवान अभिप्राय देणाऱ्या आमच्या सर्व परीक्षकांचे "
        "आणि वापरकर्त्यांचे मनापासून आभार. आम्ही भविष्यातही अधिक अपडेट्स जोडत राहू, आणि आम्ही वचन देतो की तुमची कोणतीही "
        "फाइल आम्ही कधीही साठवणार किंवा जतन करणार नाही. पुन्हा एकदा, हे टूल वापरणाऱ्या आणि तपासणाऱ्या सर्वांचे मनापासून आभार.\n\n"
        "कृपया लक्षात घ्या: काही वेळ वापर न झाल्यास, तुमच्या पहिल्या मेसेजला उत्तर येण्यास कधीकधी 30 ते 60 सेकंद लागू "
        "शकतात. त्यानंतर बॉट लवकर उत्तर देईल."
    ),
}

MARATHI_DISCLAIMER = (
    "सूचना: मराठी भाषा सध्या चाचणी (testing) टप्प्यात आहे. उत्तरांमध्ये काही भाषांतर चुका असू शकतात. "
    "मराठी भाषांतर सुविधा पुरवठादार: Blind Indian Tech Support."
)

TXT = {
    "category_prompt": {
        "en": "A full suite of PDF operations — select a category to get started.\n\nYou can also directly send a PDF file to see available operations for it.",
        "hi": "पीडीएफ से जुड़े सारे काम यहां मिलेंगे — शुरू करने के लिए एक श्रेणी चुनिए।\n\nआप सीधे एक PDF फाइल भी भेज सकते हैं, उससे जुड़े विकल्प देखने के लिए।",
        "mr": "सर्व पीडीएफ ऑपरेशन्स इथे उपलब्ध आहेत — सुरू करण्यासाठी एक श्रेणी निवडा.\n\nतुम्ही थेट एक PDF फाइल देखील पाठवू शकता, त्यासाठीचे पर्याय पाहण्यासाठी.",
    },
    "select_tool": {
        "en": "select a tool:",
        "hi": "एक टूल चुनिए:",
        "mr": "एक टूल निवडा:",
    },
    "pdf_received_menu": {
        "en": "PDF received. What would you like to do with it?",
        "hi": "PDF मिल गई है। आप इस पर क्या करना चाहते हैं?",
        "mr": "PDF मिळाली आहे. तुम्ही यावर काय करायचे आहे?",
    },
    "send_pdf_first": {
        "en": "Please send the PDF file first.",
        "hi": "कृपया पहले PDF फाइल भेजिए।",
        "mr": "कृपया प्रथम PDF फाइल पाठवा.",
    },
    "processing": {
        "en": "Processing...",
        "hi": "काम हो रहा है...",
        "mr": "काम चालू आहे...",
    },
    "please_send_pdf": {
        "en": "Please send a PDF file.",
        "hi": "कृपया एक PDF फाइल भेजिए।",
        "mr": "कृपया एक PDF फाइल पाठवा.",
    },
    "use_menu_start": {
        "en": "Please use /start to see the menu.",
        "hi": "मेन्यू देखने के लिए कृपया /start टाइप करिए।",
        "mr": "मेनू पाहण्यासाठी कृपया /start टाइप करा.",
    },
    "no_text_found": {
        "en": "No readable text found in this PDF.",
        "hi": "इस PDF में कोई पढ़ने लायक टेक्स्ट नहीं मिला।",
        "mr": "या PDF मध्ये वाचण्यायोग्य मजकूर सापडला नाही.",
    },
    "text_output_choice": {
        "en": "How would you like to receive the text?",
        "hi": "आप टेक्स्ट किस तरीके से चाहते हैं?",
        "mr": "तुम्हाला मजकूर कसा हवा आहे?",
    },
    "ask_page_range": {
        "en": "Would you like the full document, or a specific page range? Type 'all' for the full document, or a range like 1-3,5",
        "hi": "आपको पूरा दस्तावेज़ चाहिए, या कोई खास page range? पूरा दस्तावेज़ के लिए 'all' टाइप करिए, या range जैसे 1-3,5",
        "mr": "तुम्हाला संपूर्ण दस्तऐवज हवा आहे, की एक विशिष्ट page range? संपूर्ण दस्तऐवजासाठी 'all' टाइप करा, किंवा range जसे 1-3,5",
    },
    "another_action_prompt": {
        "en": "Would you like to do anything else with this same PDF?",
        "hi": "क्या आप इस PDF पर कोई और काम करना चाहते हैं?",
        "mr": "तुम्हाला या PDF वर आणखी काही करायचे आहे का?",
    },
    "done_no_files": {
        "en": "Nothing to finish right now.",
        "hi": "अभी पूरा करने के लिए कुछ नहीं है।",
        "mr": "आत्ता पूर्ण करण्यासाठी काही नाही.",
    },
    "session_ended": {
        "en": "Your session has ended. You were active for {duration}.\n\nHow would you rate your experience?",
        "hi": "आपका सेशन समाप्त हो गया है। आपने {duration} तक इस्तेमाल किया।\n\nआप अपने अनुभव को कैसी रेटिंग देंगे?",
        "mr": "तुमचे सेशन समाप्त झाले आहे. तुम्ही {duration} वापरले.\n\nतुम्ही तुमच्या अनुभवाला कशी रेटिंग देईल?",
    },
    "rating_thanks_good": {
        "en": "Thank you for your feedback! 🙏",
        "hi": "आपकी प्रतिक्रिया के लिए धन्यवाद! 🙏",
        "mr": "तुमच्या अभिप्रायासाठी धन्यवाद! 🙏",
    },
    "rating_ask_reason": {
        "en": "We're sorry to hear that. Could you tell us what went wrong?",
        "hi": "हमें अफ़सोस है। क्या आप बता सकते हैं क्या गड़बड़ हुई?",
        "mr": "आम्हाला खेद आहे. काय चूक झाली ते तुम्ही सांगू शकाल का?",
    },
    "rating_reason_thanks": {
        "en": "Thank you for letting us know. We'll work on improving this.",
        "hi": "बताने के लिए धन्यवाद, हम इसे बेहतर बनाने पर काम करेंगे।",
        "mr": "सांगण्याबद्दल धन्यवाद, आम्ही हे सुधारण्यावर काम करू.",
    },
}


def t(key, lang):
    entry = TXT.get(key, {})
    return entry.get(lang, entry.get("en", ""))


def generate_session_id():
    random_part = "".join(random.choices(string.ascii_letters + string.digits, k=18))
    counter_doc = fb_get("counters", "sessions") or {"count": 0}
    new_count = counter_doc.get("count", 0) + 1
    fb_set("counters", "sessions", {"count": new_count})
    return f"{random_part}C#{new_count}"


def generate_auth_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=21))


def get_session(user_id, username=None):
    now = ist_now()
    s = SESSIONS.get(user_id)

    needs_new_session = (
        s is None
        or s.get("ended")
        or (now - s["last_active"]).total_seconds() > SESSION_TIMEOUT_SECONDS
    )

    if needs_new_session:
        sid = generate_session_id()
        prev_language = s["language"] if s else "en"
        s = {
            "session_id": sid,
            "username": username,
            "language": prev_language,
            "mode": None,
            "files": [],
            "braille_buffer": [],
            "actions": [],
            "errors": [],
            "start_time": now,
            "last_active": now,
            "ended": False,
        }
        SESSIONS[user_id] = s
        fb_set(
            "sessions",
            sid,
            {
                "session_id": sid,
                "user_id": user_id,
                "username": username,
                "start_time": now.isoformat(),
                "last_active": now.isoformat(),
                "actions": [],
                "errors": [],
                "ended": False,
            },
        )
    else:
        s["username"] = username
        s["last_active"] = now
        fb_set(
            "sessions",
            s["session_id"],
            {"last_active": now.isoformat(), "username": username},
        )

    return s


def log_action(user_id, action):
    s = SESSIONS.get(user_id)
    if not s:
        return
    s["actions"].append(action)
    fb_set("sessions", s["session_id"], {"actions": s["actions"]})


def log_error(user_id, error_text):
    s = SESSIONS.get(user_id)
    if not s:
        return
    s["errors"].append(error_text)
    fb_set("sessions", s["session_id"], {"errors": s["errors"]})
    if ADMIN_STATE["admin_id"] is not None:
        try:
            asyncio.ensure_future(
                telegram_app.bot.send_message(
                    ADMIN_STATE["admin_id"],
                    f"An error occurred.\nSession ID: {s['session_id']}\n"
                    f"User: @{s.get('username')}\nError: {error_text}",
                )
            )
        except Exception:
            pass


def format_duration(seconds):
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    if minutes > 0:
        return f"{minutes} min {sec} sec"
    return f"{sec} sec"


async def notify_session_id(update, context, user_id):
    session = SESSIONS.get(user_id)
    if not session:
        return
    lang = session["language"]
    await context.bot.send_message(
        update.effective_chat.id,
        f"Your session ID: {session['session_id']}\n"
        "Please save this ID. If you face any error, share this ID with the admin using /feedback.",
    )


RATING_MENU = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("⭐", callback_data="rate_1"),
            InlineKeyboardButton("⭐⭐", callback_data="rate_2"),
            InlineKeyboardButton("⭐⭐⭐", callback_data="rate_3"),
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data="rate_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="rate_5"),
        ]
    ]
)


async def session_watcher():
    while True:
        await asyncio.sleep(30)
        try:
            now = ist_now()
            for user_id, s in list(SESSIONS.items()):
                if s.get("ended"):
                    continue
                if (now - s["last_active"]).total_seconds() > SESSION_TIMEOUT_SECONDS:
                    await finalize_session(user_id, s)
        except Exception:
            logger.exception("Error in session watcher")


async def finalize_session(user_id, s):
    s["ended"] = True
    duration_seconds = (s["last_active"] - s["start_time"]).total_seconds()
    duration_text = format_duration(duration_seconds)
    lang = s["language"]

    fb_set(
        "sessions",
        s["session_id"],
        {
            "ended": True,
            "end_time": s["last_active"].isoformat(),
            "duration_seconds": duration_seconds,
        },
    )

    PENDING_RATING[user_id] = {"session_id": s["session_id"], "language": lang}

    try:
        await telegram_app.bot.send_message(
            user_id,
            t("session_ended", lang).format(duration=duration_text),
            reply_markup=RATING_MENU,
        )
    except Exception:
        pass


LANG_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("हिन्दी (भारत)", callback_data="lang_hi")],
        [InlineKeyboardButton("English (UK)", callback_data="lang_en")],
        [InlineKeyboardButton("मराठी (भारत)", callback_data="lang_mr")],
    ]
)

CATEGORY_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("READ", callback_data="cat_read")],
        [InlineKeyboardButton("CREATE", callback_data="cat_create")],
        [InlineKeyboardButton("ORGANISE", callback_data="cat_organise")],
        [InlineKeyboardButton("TRANSFORM", callback_data="cat_transform")],
        [InlineKeyboardButton("ANNOTATE & PROTECT", callback_data="cat_annotate")],
        [InlineKeyboardButton("INSPECT & EXTRACT", callback_data="cat_inspect")],
        [InlineKeyboardButton("MY ACCOUNT", callback_data="cat_account")],
    ]
)

READ_MENU = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Read PDF (Send file first)", callback_data="noop")]]
)

CREATE_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Images to PDF", callback_data="mode_images_to_pdf")],
        [InlineKeyboardButton("Text to PDF", callback_data="mode_text_to_pdf")],
        [InlineKeyboardButton("Text to Braille", callback_data="mode_text_to_braille")],
    ]
)

ORGANISE_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Merge PDFs", callback_data="mode_merge")],
        [InlineKeyboardButton("Split PDF", callback_data="mode_split")],
        [InlineKeyboardButton("Cut / Extract Pages", callback_data="mode_extract")],
        [InlineKeyboardButton("Reorder Pages", callback_data="mode_reorder")],
        [InlineKeyboardButton("Delete Pages", callback_data="mode_delete_pages")],
    ]
)

TRANSFORM_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("PDF to Images", callback_data="mode_pdf_to_images")],
        [InlineKeyboardButton("Compress PDF", callback_data="mode_compress")],
        [InlineKeyboardButton("Resize PDF", callback_data="mode_resize")],
        [InlineKeyboardButton("Rotate Pages", callback_data="mode_rotate")],
    ]
)

ANNOTATE_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Add Watermark", callback_data="mode_watermark")],
        [InlineKeyboardButton("Lock PDF", callback_data="mode_lock")],
        [InlineKeyboardButton("Unlock PDF", callback_data="mode_unlock")],
    ]
)

INSPECT_MENU = InlineKeyboardMarkup(
    [[InlineKeyboardButton("View PDF Metadata", callback_data="mode_metadata")]]
)

ACCOUNT_MENU = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Create Account", callback_data="mode_create_account")]]
)

SINGLE_FILE_OPS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Read (Text)", callback_data="op_read_text")],
        [InlineKeyboardButton("Read (Audio)", callback_data="op_read_audio")],
        [InlineKeyboardButton("Split", callback_data="op_split")],
        [InlineKeyboardButton("Cut / Extract Pages", callback_data="op_extract")],
        [InlineKeyboardButton("Reorder Pages", callback_data="op_reorder")],
        [InlineKeyboardButton("Delete Pages", callback_data="op_delete_pages")],
        [InlineKeyboardButton("PDF to Images", callback_data="op_pdf_to_images")],
        [InlineKeyboardButton("Compress", callback_data="op_compress")],
        [InlineKeyboardButton("Resize", callback_data="op_resize")],
        [InlineKeyboardButton("Rotate Pages", callback_data="op_rotate")],
        [InlineKeyboardButton("Add Watermark", callback_data="op_watermark")],
        [InlineKeyboardButton("Lock PDF", callback_data="op_lock")],
        [InlineKeyboardButton("Unlock PDF", callback_data="op_unlock")],
        [InlineKeyboardButton("View Metadata", callback_data="op_metadata")],
    ]
)

TEXT_OUTPUT_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Text File", callback_data="textout_file")],
        [InlineKeyboardButton("Chat Message", callback_data="textout_chat")],
    ]
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    SESSIONS.pop(user.id, None)
    get_session(user.id, user.username)
    await update.message.reply_text(WELCOME_MESSAGES["en"])
    await update.message.reply_text("Please select your preferred language:", reply_markup=LANG_MENU)


async def lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    lang_code = query.data.replace("lang_", "")
    session["language"] = lang_code
    log_action(user_id, f"language_set:{lang_code}")

    if lang_code == "mr":
        await context.bot.send_message(query.message.chat.id, MARATHI_DISCLAIMER)

    await query.edit_message_text(
        t("category_prompt", lang_code),
        reply_markup=CATEGORY_MENU,
    )


async def category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    lang = session["language"]
    data = query.data
    menus = {
        "cat_read": ("READ", READ_MENU),
        "cat_create": ("CREATE", CREATE_MENU),
        "cat_organise": ("ORGANISE", ORGANISE_MENU),
        "cat_transform": ("TRANSFORM", TRANSFORM_MENU),
        "cat_annotate": ("ANNOTATE & PROTECT", ANNOTATE_MENU),
        "cat_inspect": ("INSPECT & EXTRACT", INSPECT_MENU),
        "cat_account": ("MY ACCOUNT", ACCOUNT_MENU),
    }
    title, menu = menus[data]
    await query.edit_message_text(f"{title} — {t('select_tool', lang)}", reply_markup=menu)


async def mode_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    lang = session["language"]
    session["mode"] = query.data.replace("mode_", "")
    session["files"] = []
    session["braille_buffer"] = []
    log_action(user_id, f"mode_selected:{session['mode']}")

    if session["mode"] == "create_account":
        session["account_step"] = "name"
        await query.edit_message_text("Please type your Name:")
        return

    prompts = {
        "merge": "Send all the PDF files you want to merge, one by one. Type /done when finished.",
        "split": "Send the PDF you want to split into single pages.",
        "extract": "Send the PDF. Then tell me which pages to extract, example: 1-3,5",
        "reorder": "Send the PDF. Then tell me the new page order, example: 3,1,2",
        "delete_pages": "Send the PDF. Then tell me which pages to delete, example: 2,4",
        "pdf_to_images": "Send the PDF to convert its pages into images.",
        "compress": "Send the PDF you want to compress.",
        "resize": "Send the PDF. Then tell me the target page size: A4 or Letter.",
        "rotate": "Send the PDF. Then tell me the rotation: 90, 180 or 270.",
        "watermark": "Send the PDF. Then type the watermark text.",
        "lock": "Send the PDF. Then type the password you want to set.",
        "unlock": "Send the PDF. Then type its current password.",
        "metadata": "Send the PDF to view its metadata.",
        "images_to_pdf": "Send the images (one by one) you want to combine into a PDF. Type /done when finished.",
        "text_to_pdf": "Type or paste the text you want converted into a PDF.",
        "text_to_braille": "Send your text, one or more messages. When finished, type /ok and I will convert everything into Braille.",
    }
    await query.edit_message_text(prompts.get(session["mode"], "Send the file."))
    await notify_session_id(update, context, user_id)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)
    lang = session["language"]
    mode = session.get("mode")
    doc = update.message.document

    tmp_dir = tempfile.mkdtemp()
    local_path = os.path.join(tmp_dir, doc.file_name)
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(local_path)

    if not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(t("please_send_pdf", lang))
        return

    if mode == "merge":
        session["files"].append(local_path)
        await update.message.reply_text(f"'{doc.file_name}' received. Send more files or type /done.")
        return

    if not mode:
        session["files"] = [local_path]
        await update.message.reply_text(t("pdf_received_menu", lang), reply_markup=SINGLE_FILE_OPS)
        await notify_session_id(update, context, user.id)
        return

    session["files"] = [local_path]
    await run_single_file_mode(update, context, mode, local_path)


async def op_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    lang = session["language"]
    mode = query.data.replace("op_", "")
    session["mode"] = mode
    log_action(user_id, f"op_selected:{mode}")

    if not session["files"]:
        await query.edit_message_text(t("send_pdf_first", lang))
        return

    local_path = session["files"][0]
    await query.edit_message_text(t("processing", lang))
    await run_single_file_mode(update, context, mode, local_path, query=query)


def extract_text_with_ocr_fallback(pdf_path, page_numbers=None):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages
        if page_numbers:
            pages = [pdf.pages[i - 1] for i in page_numbers if 0 < i <= len(pdf.pages)]
        for page in pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    if text.strip():
        return text
    if OCR_AVAILABLE:
        images = convert_from_path(pdf_path)
        if page_numbers:
            images = [images[i - 1] for i in page_numbers if 0 < i <= len(images)]
        ocr_text = ""
        for img in images:
            ocr_text += pytesseract.image_to_string(img, lang="eng") + "\n"
        return ocr_text
    return ""


def parse_page_ranges(text, max_pages):
    pages = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            for p in range(int(start), int(end) + 1):
                if 1 <= p <= max_pages:
                    pages.add(p)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_pages:
                pages.add(p)
    return sorted(pages)


async def show_post_action_menu(update, context, chat_id, lang):
    await context.bot.send_message(chat_id, t("another_action_prompt", lang), reply_markup=SINGLE_FILE_OPS)


async def run_single_file_mode(update, context, mode, local_path, query=None):
    user = update.effective_user
    session = get_session(user.id, user.username)
    lang = session["language"]
    out_dir = tempfile.mkdtemp()
    chat = update.effective_chat

    try:
        if mode in ("read_text", "text"):
            session["pending_action"] = "extract_text_range"
            session["pending_path"] = local_path
            await context.bot.send_message(chat.id, t("ask_page_range", lang))
            return

        elif mode == "read_audio":
            text = extract_text_with_ocr_fallback(local_path)
            if not text.strip():
                await context.bot.send_message(chat.id, t("no_text_found", lang))
                return
            chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
            for idx, chunk in enumerate(chunks):
                mp3_path = os.path.join(out_dir, f"{FILE_PREFIX}_audio_{idx+1}.mp3")
                gTTS(text=chunk, lang="en").save(mp3_path)
                await context.bot.send_audio(chat.id, audio=open(mp3_path, "rb"))
            await show_post_action_menu(update, context, chat.id, lang)

        elif mode == "split":
            reader = PdfReader(local_path)
            for i, page in enumerate(reader.pages):
                writer = PdfWriter()
                writer.add_page(page)
                p = os.path.join(out_dir, f"{FILE_PREFIX}_page_{i+1}.pdf")
                with open(p, "wb") as f:
                    writer.write(f)
                await context.bot.send_document(chat.id, document=open(p, "rb"))
            await show_post_action_menu(update, context, chat.id, lang)

        elif mode == "extract":
            session["pending_path"] = local_path
            session["pending_action"] = "extract"
            await context.bot.send_message(chat.id, "Which pages? Example: 1-3,5")

        elif mode == "reorder":
            session["pending_path"] = local_path
            session["pending_action"] = "reorder"
            await context.bot.send_message(chat.id, "New page order? Example: 3,1,2")

        elif mode == "delete_pages":
            session["pending_path"] = local_path
            session["pending_action"] = "delete_pages"
            await context.bot.send_message(chat.id, "Which pages to delete? Example: 2,4")

        elif mode == "pdf_to_images":
            if not OCR_AVAILABLE:
                await context.bot.send_message(chat.id, "PDF to Images feature is currently unavailable on this server.")
                return
            images = convert_from_path(local_path)
            for i, img in enumerate(images):
                p = os.path.join(out_dir, f"{FILE_PREFIX}_page_{i+1}.jpg")
                img.save(p, "JPEG")
                await context.bot.send_document(chat.id, document=open(p, "rb"))
            await show_post_action_menu(update, context, chat.id, lang)

        elif mode == "compress":
            if not PIKEPDF_AVAILABLE:
                await context.bot.send_message(chat.id, "Compress PDF feature is currently unavailable on this server.")
                return
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_compressed.pdf")
            with pikepdf.open(local_path) as pdf:
                pdf.save(out_path, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
            await context.bot.send_document(chat.id, document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat.id, lang)

        elif mode == "resize":
            session["pending_path"] = local_path
            session["pending_action"] = "resize"
            await context.bot.send_message(chat.id, "Target page size? Type A4 or Letter")

        elif mode == "rotate":
            session["pending_path"] = local_path
            session["pending_action"] = "rotate"
            await context.bot.send_message(chat.id, "Rotation degrees? Type 90, 180 or 270")

        elif mode == "watermark":
            session["pending_path"] = local_path
            session["pending_action"] = "watermark"
            await context.bot.send_message(chat.id, "Type the watermark text")

        elif mode == "lock":
            session["pending_path"] = local_path
            session["pending_action"] = "lock"
            await context.bot.send_message(chat.id, "Type the password to set")

        elif mode == "unlock":
            session["pending_path"] = local_path
            session["pending_action"] = "unlock"
            await context.bot.send_message(chat.id, "Type the current password")

        elif mode == "metadata":
            reader = PdfReader(local_path)
            meta = reader.metadata
            info = (
                f"Title: {meta.title if meta else 'N/A'}\n"
                f"Author: {meta.author if meta else 'N/A'}\n"
                f"Creator: {meta.creator if meta else 'N/A'}\n"
                f"Pages: {len(reader.pages)}\n"
                f"Encrypted: {reader.is_encrypted}"
            )
            await context.bot.send_message(chat.id, info)
            await show_post_action_menu(update, context, chat.id, lang)

        if session.get("pending_action") is None:
            session["mode"] = None

    except Exception as e:
        logger.exception("Error processing file")
        log_error(user.id, str(e))
        await context.bot.send_message(chat.id, f"An error occurred: {e}")
        session["mode"] = None


async def done_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)

    if session.get("mode") == "merge":
        if len(session["files"]) < 2:
            await update.message.reply_text("Send at least 2 PDF files before /done.")
            return
        writer = PdfWriter()
        for path in session["files"]:
            reader = PdfReader(path)
            for page in reader.pages:
                writer.add_page(page)
        out_path = os.path.join(tempfile.mkdtemp(), f"{FILE_PREFIX}_merged.pdf")
        with open(out_path, "wb") as f:
            writer.write(f)
        await update.message.reply_document(document=open(out_path, "rb"))
        session["mode"] = None
        session["files"] = []
        return

    if session.get("mode") == "images_to_pdf":
        if not session["files"]:
            await update.message.reply_text("Send at least 1 image before /done.")
            return
        images = [Image.open(p).convert("RGB") for p in session["files"]]
        out_path = os.path.join(tempfile.mkdtemp(), f"{FILE_PREFIX}_images.pdf")
        images[0].save(out_path, save_all=True, append_images=images[1:])
        await update.message.reply_document(document=open(out_path, "rb"))
        session["mode"] = None
        session["files"] = []
        return

    await update.message.reply_text(t("done_no_files", session["language"]))


async def done_braille(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)

    if session.get("mode") != "text_to_braille":
        await update.message.reply_text("Nothing to convert right now.")
        return

    if not session["braille_buffer"]:
        await update.message.reply_text("You have not sent any text yet.")
        return

    if not LOUIS_AVAILABLE:
        await update.message.reply_text("Text to Braille feature is currently unavailable on this server.")
        session["mode"] = None
        session["braille_buffer"] = []
        return

    full_text = "\n".join(session["braille_buffer"])
    try:
        braille_text = louis.translateString(["en-us-g1.ctb"], full_text)
    except Exception as e:
        logger.exception("Braille conversion error")
        log_error(user.id, str(e))
        await update.message.reply_text(f"An error occurred during Braille conversion: {e}")
        session["mode"] = None
        session["braille_buffer"] = []
        return

    out_path = os.path.join(tempfile.mkdtemp(), f"{FILE_PREFIX}_braille.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(braille_text)
    await update.message.reply_document(document=open(out_path, "rb"))
    log_action(user.id, "text_to_braille_completed")
    session["mode"] = None
    session["braille_buffer"] = []


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)
    if session.get("mode") != "images_to_pdf":
        await update.message.reply_text("Please select 'Images to PDF' from the menu first.")
        return
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    tmp_dir = tempfile.mkdtemp()
    local_path = os.path.join(tmp_dir, f"{len(session['files'])+1}.jpg")
    await tg_file.download_to_drive(local_path)
    session["files"].append(local_path)
    await update.message.reply_text("Image received. Send more or type /done.")


async def handle_account_flow(update, context, text):
    user = update.effective_user
    session = get_session(user.id, user.username)
    step = session.get("account_step")

    if step == "name":
        session["account_name"] = text
        session["account_step"] = "country"
        await update.message.reply_text("Please type your Country:")
        return

    if step == "country":
        session["account_country"] = text
        session["account_step"] = "gender"
        await update.message.reply_text("Please type your Gender:")
        return

    if step == "gender":
        session["account_gender"] = text
        session["account_step"] = "password"
        await update.message.reply_text("Please choose a password for your account:")
        return

    if step == "password":
        token = generate_auth_token()
        account_data = {
            "user_id": user.id,
            "username": user.username,
            "name": session.get("account_name"),
            "country": session.get("account_country"),
            "gender": session.get("account_gender"),
            "password": text,
            "auth_token": token,
            "created_at": ist_now().isoformat(),
        }
        fb_set("users", str(user.id), account_data)
        session.pop("account_step", None)
        session["mode"] = None

        await update.message.reply_text(
            "Your account has been created!\n"
            f"Your Authorization Token: {token}\n"
            "Please save this token safely."
        )

        if ADMIN_STATE["admin_id"] is not None:
            try:
                await context.bot.send_message(
                    ADMIN_STATE["admin_id"],
                    f"New account created.\nName: {account_data['name']}\n"
                    f"Country: {account_data['country']}\nGender: {account_data['gender']}\n"
                    f"Telegram: @{user.username} (ID: {user.id})\nToken: {token}",
                )
            except Exception:
                pass
        return


async def handle_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)
    lang = session["language"]
    text = update.message.text.strip()

    if "admin_step" in session:
        await handle_admin_flow(update, context, text)
        return

    if "feedback_step" in session:
        await handle_feedback_flow(update, context, text)
        return

    if "account_step" in session:
        await handle_account_flow(update, context, text)
        return

    if user.id in PENDING_RATING and session.get("awaiting_rating_reason"):
        session["awaiting_rating_reason"] = False
        pending = PENDING_RATING.pop(user.id, None)
        if pending and ADMIN_STATE["admin_id"] is not None:
            try:
                await context.bot.send_message(
                    ADMIN_STATE["admin_id"],
                    f"Low rating feedback.\nSession ID: {pending['session_id']}\n"
                    f"User: @{user.username}\nReason: {text}",
                )
            except Exception:
                pass
        await update.message.reply_text(t("rating_reason_thanks", lang))
        return

    if session.get("mode") == "text_to_braille":
        session["braille_buffer"].append(text)
        await update.message.reply_text("Text received. Send more, or type /ok to convert to Braille.")
        return

    if session.get("mode") == "text_to_pdf":
        out_path = os.path.join(tempfile.mkdtemp(), f"{FILE_PREFIX}_text.pdf")
        c = canvas.Canvas(out_path, pagesize=letter)
        width, height = letter
        y = height - 50
        for line in text.split("\n"):
            c.drawString(50, y, line[:100])
            y -= 15
            if y < 50:
                c.showPage()
                y = height - 50
        c.save()
        await update.message.reply_document(document=open(out_path, "rb"))
        session["mode"] = None
        return

    pending = session.get("pending_action")
    if not pending:
        await update.message.reply_text(t("use_menu_start", lang))
        return

    path = session.get("pending_path")
    session.pop("pending_action", None)
    session.pop("pending_path", None)
    out_dir = tempfile.mkdtemp()
    chat_id = update.effective_chat.id

    try:
        if pending == "extract_text_range":
            reader = PdfReader(path)
            max_pages = len(reader.pages)
            if text.strip().lower() == "all":
                page_numbers = None
            else:
                page_numbers = parse_page_ranges(text, max_pages)
            extracted = extract_text_with_ocr_fallback(path, page_numbers)
            if not extracted.strip():
                await update.message.reply_text(t("no_text_found", lang))
                session["mode"] = None
                return
            session["pending_text_result"] = extracted
            session["pending_action"] = "choose_text_output"
            await update.message.reply_text(t("text_output_choice", lang), reply_markup=TEXT_OUTPUT_MENU)
            return

        elif pending == "extract":
            reader = PdfReader(path)
            pages = parse_page_ranges(text, len(reader.pages))
            writer = PdfWriter()
            for p in pages:
                writer.add_page(reader.pages[p - 1])
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_extracted.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "reorder":
            reader = PdfReader(path)
            order = [int(x.strip()) for x in text.split(",")]
            writer = PdfWriter()
            for p in order:
                writer.add_page(reader.pages[p - 1])
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_reordered.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "delete_pages":
            reader = PdfReader(path)
            to_delete = set(int(x.strip()) for x in text.split(","))
            writer = PdfWriter()
            for i, page in enumerate(reader.pages):
                if (i + 1) not in to_delete:
                    writer.add_page(page)
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_deleted_pages.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "resize":
            from reportlab.lib.pagesizes import A4, LETTER
            target = A4 if text.upper() == "A4" else LETTER
            reader = PdfReader(path)
            writer = PdfWriter()
            for page in reader.pages:
                page.scale_to(target[0], target[1])
                writer.add_page(page)
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_resized.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "rotate":
            reader = PdfReader(path)
            writer = PdfWriter()
            for page in reader.pages:
                page.rotate(int(text))
                writer.add_page(page)
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_rotated.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "watermark":
            wm_path = os.path.join(out_dir, "wm.pdf")
            c = canvas.Canvas(wm_path, pagesize=letter)
            c.setFont("Helvetica", 40)
            c.setFillGray(0.5, 0.3)
            c.saveState()
            c.translate(300, 400)
            c.rotate(45)
            c.drawCentredString(0, 0, text)
            c.restoreState()
            c.save()
            wm_page = PdfReader(wm_path).pages[0]
            reader = PdfReader(path)
            writer = PdfWriter()
            for page in reader.pages:
                page.merge_page(wm_page)
                writer.add_page(page)
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_watermarked.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "lock":
            reader = PdfReader(path)
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.encrypt(text)
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_locked.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        elif pending == "unlock":
            reader = PdfReader(path)
            if reader.is_encrypted:
                reader.decrypt(text)
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_unlocked.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))
            await show_post_action_menu(update, context, chat_id, lang)

        session["mode"] = None

    except Exception as e:
        logger.exception("Error in text reply handler")
        log_error(user.id, str(e))
        await update.message.reply_text(f"An error occurred: {e}")
        session["mode"] = None


async def text_output_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    lang = session["language"]
    extracted = session.pop("pending_text_result", "")
    session.pop("pending_action", None)
    session["mode"] = None

    if not extracted:
        await query.edit_message_text(t("no_text_found", lang))
        return

    if query.data == "textout_file":
        out_dir = tempfile.mkdtemp()
        txt_path = os.path.join(out_dir, f"{FILE_PREFIX}_extracted.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(extracted)
        await query.edit_message_text(t("processing", lang))
        await context.bot.send_document(query.message.chat.id, document=open(txt_path, "rb"))
    else:
        await query.edit_message_text(t("processing", lang))
        chunks = [extracted[i:i + 4000] for i in range(0, len(extracted), 4000)]
        for chunk in chunks:
            await context.bot.send_message(query.message.chat.id, chunk)

    await show_post_action_menu(update, context, query.message.chat.id, lang)


async def rating_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    stars = int(query.data.replace("rate_", ""))
    pending = PENDING_RATING.get(user_id)
    lang = pending["language"] if pending else "en"

    if pending:
        fb_set(
            "ratings",
            f"{pending['session_id']}",
            {
                "session_id": pending["session_id"],
                "user_id": user_id,
                "stars": stars,
                "timestamp": ist_now().isoformat(),
            },
        )

    if stars >= 3:
        PENDING_RATING.pop(user_id, None)
        await query.edit_message_text(t("rating_thanks_good", lang))
    else:
        session = get_session(user_id, query.from_user.username)
        session["awaiting_rating_reason"] = True
        await query.edit_message_text(t("rating_ask_reason", lang))


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = f"For any queries you can reach out to us: {SUPPORT_EMAIL}"
    try:
        await update.message.reply_photo(photo=open(SUPPORT_IMAGE_PATH, "rb"), caption=caption)
    except Exception:
        await update.message.reply_text(caption)


async def whatsnew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"Current version: {VERSION_NAME}\n"
        f"Released: {VERSION_RELEASE_ISO}\n\n"
        "What's new in this version:\n"
        "- Full multi-language support (English, Hindi, Marathi)\n"
        "- User Accounts with Authorization Token\n"
        "- Improved, more reliable session tracking\n"
        "- Rate your experience after each session\n"
        "- Choice of text file or chat message for extracted text\n"
        "- Page-range selection for text extraction\n"
        "- Continue using the same PDF for multiple actions without re-uploading\n"
    )
    await update.message.reply_text(text)


async def feedback_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)
    session["feedback_step"] = True
    await update.message.reply_text(
        "Please type your feedback. Also include your Telegram username or other contact "
        "details, so we can reach out to you if needed."
    )


async def handle_feedback_flow(update, context, text):
    user = update.effective_user
    session = get_session(user.id, user.username)
    session.pop("feedback_step", None)

    if ADMIN_STATE["admin_id"] is not None:
        try:
            await context.bot.send_message(
                ADMIN_STATE["admin_id"],
                f"New feedback received.\nSession ID: {session['session_id']}\n"
                f"Username: @{user.username}\nUser ID: {user.id}\n\nMessage:\n{text}",
            )
        except Exception:
            pass

    log_action(user.id, "feedback_submitted")
    await update.message.reply_text("Your feedback has been sent. Thank you!")


ADMIN_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("View Recent Sessions", callback_data="admin_sessions")],
        [InlineKeyboardButton("Track a Session ID", callback_data="admin_track")],
        [InlineKeyboardButton("Total Users", callback_data="admin_totalusers")],
        [InlineKeyboardButton("Search User", callback_data="admin_searchuser")],
        [InlineKeyboardButton("Recent Errors", callback_data="admin_errors")],
        [InlineKeyboardButton("Delete User Account", callback_data="admin_deleteuser")],
        [InlineKeyboardButton("Message a Specific User", callback_data="admin_msguser")],
        [InlineKeyboardButton("Most Used Feature", callback_data="admin_mostused")],
    ]
)


async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)

    if ADMIN_STATE["failed_attempts"].get(user.id, 0) >= 3:
        await update.message.reply_text("Too many failed attempts. Access temporarily blocked.")
        return

    if ADMIN_STATE["admin_id"] is not None and user.id != ADMIN_STATE["admin_id"]:
        await update.message.reply_text("Access denied.")
        return

    if ADMIN_STATE["admin_id"] == user.id:
        await update.message.reply_text("Admin Panel:", reply_markup=ADMIN_MENU)
        return

    session["admin_step"] = "awaiting_password"
    await update.message.reply_text("Enter admin password:")


async def handle_admin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user
    session = get_session(user.id, user.username)

    if session.get("admin_step") == "awaiting_password":
        session.pop("admin_step", None)

        if text != ADMIN_PASSWORD:
            ADMIN_STATE["failed_attempts"][user.id] = ADMIN_STATE["failed_attempts"].get(user.id, 0) + 1
            if ADMIN_STATE["admin_id"] is not None:
                try:
                    await context.bot.send_message(
                        ADMIN_STATE["admin_id"],
                        f"Warning: someone attempted to access the admin panel with a wrong password. "
                        f"User ID: {user.id}",
                    )
                except Exception:
                    pass
            await update.message.reply_text("Incorrect password.")
            return

        if ADMIN_STATE["admin_id"] is None:
            ADMIN_STATE["admin_id"] = user.id
            fb_set("admin", "state", {"admin_id": user.id})

        if user.id != ADMIN_STATE["admin_id"]:
            await update.message.reply_text("Access denied.")
            return

        ADMIN_STATE["failed_attempts"][user.id] = 0
        await update.message.reply_text("Admin Panel:", reply_markup=ADMIN_MENU)
        return

    if session.get("admin_step") == "awaiting_track_id":
        session.pop("admin_step", None)
        entry = fb_get("sessions", text.strip())
        if not entry:
            await update.message.reply_text("No session found with that ID.", reply_markup=ADMIN_MENU)
            return
        info = (
            f"Session ID: {entry.get('session_id')}\n"
            f"Username: @{entry.get('username')}\n"
            f"Started: {entry.get('start_time')}\n"
            f"Last activity: {entry.get('last_active')}\n"
            f"Ended: {entry.get('ended')}\n"
            f"Duration (seconds): {entry.get('duration_seconds', 'N/A')}\n"
            f"Actions: {entry.get('actions')}\n"
            f"Errors: {entry.get('errors')}"
        )
        await update.message.reply_text(info, reply_markup=ADMIN_MENU)
        return

    if session.get("admin_step") == "awaiting_search_user":
        session.pop("admin_step", None)
        if not FIREBASE_AVAILABLE:
            await update.message.reply_text("Database unavailable.", reply_markup=ADMIN_MENU)
            return
        try:
            found = []
            docs = db.collection("users").stream()
            for d in docs:
                data = d.to_dict()
                if (
                    text.strip().lower() in str(data.get("name", "")).lower()
                    or text.strip() == str(data.get("auth_token", ""))
                    or text.strip() == str(data.get("user_id", ""))
                ):
                    found.append(data)
            if not found:
                await update.message.reply_text("No matching user found.", reply_markup=ADMIN_MENU)
            else:
                for data in found[:5]:
                    info = (
                        f"Name: {data.get('name')}\nCountry: {data.get('country')}\n"
                        f"Gender: {data.get('gender')}\nUsername: @{data.get('username')}\n"
                        f"Telegram ID: {data.get('user_id')}\nToken: {data.get('auth_token')}\n"
                        f"Created: {data.get('created_at')}"
                    )
                    await update.message.reply_text(info)
                await update.message.reply_text("Search complete.", reply_markup=ADMIN_MENU)
        except Exception as e:
            await update.message.reply_text(f"Search failed: {e}", reply_markup=ADMIN_MENU)
        return

    if session.get("admin_step") == "awaiting_delete_user":
        session.pop("admin_step", None)
        fb_delete("users", text.strip())
        await update.message.reply_text("If that account existed, it has been deleted.", reply_markup=ADMIN_MENU)
        return

    if session.get("admin_step") == "awaiting_msguser_id":
        session["admin_step"] = "awaiting_msguser_text"
        session["admin_msg_target"] = text.strip()
        await update.message.reply_text("Now type the message to send to that user:")
        return

    if session.get("admin_step") == "awaiting_msguser_text":
        session.pop("admin_step", None)
        target_id = session.pop("admin_msg_target", None)
        try:
            await context.bot.send_message(int(target_id), f"Message from Admin:\n\n{text}")
            await update.message.reply_text("Message sent.", reply_markup=ADMIN_MENU)
        except Exception as e:
            await update.message.reply_text(f"Could not send message: {e}", reply_markup=ADMIN_MENU)
        return


async def admin_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    session = get_session(user.id, user.username)

    if user.id != ADMIN_STATE["admin_id"]:
        await query.edit_message_text("Access denied.")
        return

    data = query.data

    if data == "admin_sessions":
        if not FIREBASE_AVAILABLE:
            await query.edit_message_text("Database unavailable.", reply_markup=ADMIN_MENU)
            return
        try:
            docs = (
                db.collection("sessions")
                .order_by("start_time", direction=firestore.Query.DESCENDING)
                .limit(15)
                .stream()
            )
            lines = ["Recent Sessions:\n"]
            for d in docs:
                e = d.to_dict()
                lines.append(
                    f"ID: {e.get('session_id')} | User: @{e.get('username')} | "
                    f"Started: {e.get('start_time')}"
                )
            await query.edit_message_text("\n".join(lines), reply_markup=ADMIN_MENU)
        except Exception as e:
            await query.edit_message_text(f"Could not load sessions: {e}", reply_markup=ADMIN_MENU)

    elif data == "admin_track":
        session["admin_step"] = "awaiting_track_id"
        await query.edit_message_text("Please type the session ID you want to track:")

    elif data == "admin_totalusers":
        if not FIREBASE_AVAILABLE:
            await query.edit_message_text("Database unavailable.", reply_markup=ADMIN_MENU)
            return
        try:
            agg = db.collection("users").count().get()
            total = agg[0][0].value
            await query.edit_message_text(f"Total registered users: {total}", reply_markup=ADMIN_MENU)
        except Exception as e:
            await query.edit_message_text(f"Could not count users: {e}", reply_markup=ADMIN_MENU)

    elif data == "admin_searchuser":
        session["admin_step"] = "awaiting_search_user"
        await query.edit_message_text("Type the name, Telegram ID, or Authorization Token to search:")

    elif data == "admin_errors":
        if not FIREBASE_AVAILABLE:
            await query.edit_message_text("Database unavailable.", reply_markup=ADMIN_MENU)
            return
        try:
            docs = (
                db.collection("sessions")
                .order_by("start_time", direction=firestore.Query.DESCENDING)
                .limit(50)
                .stream()
            )
            lines = ["Recent Errors:\n"]
            count = 0
            for d in docs:
                e = d.to_dict()
                errors = e.get("errors") or []
                if errors:
                    count += 1
                    lines.append(f"Session: {e.get('session_id')} | User: @{e.get('username')} | Errors: {errors}")
                if count >= 10:
                    break
            if count == 0:
                lines.append("No recent errors found.")
            await query.edit_message_text("\n".join(lines), reply_markup=ADMIN_MENU)
        except Exception as e:
            await query.edit_message_text(f"Could not load errors: {e}", reply_markup=ADMIN_MENU)

    elif data == "admin_deleteuser":
        session["admin_step"] = "awaiting_delete_user"
        await query.edit_message_text("Type the Telegram ID of the account to delete:")

    elif data == "admin_msguser":
        session["admin_step"] = "awaiting_msguser_id"
        await query.edit_message_text("Type the Telegram ID of the user you want to message:")

    elif data == "admin_mostused":
        if not FIREBASE_AVAILABLE:
            await query.edit_message_text("Database unavailable.", reply_markup=ADMIN_MENU)
            return
        try:
            docs = (
                db.collection("sessions")
                .order_by("start_time", direction=firestore.Query.DESCENDING)
                .limit(200)
                .stream()
            )
            counts = {}
            for d in docs:
                e = d.to_dict()
                for a in e.get("actions") or []:
                    if a.startswith("op_selected:") or a.startswith("mode_selected:"):
                        feature = a.split(":", 1)[1]
                        counts[feature] = counts.get(feature, 0) + 1
            if not counts:
                await query.edit_message_text("Not enough data yet.", reply_markup=ADMIN_MENU)
                return
            sorted_features = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            lines = ["Most Used Features:\n"]
            for feature, cnt in sorted_features[:10]:
                lines.append(f"{feature}: {cnt} times")
            await query.edit_message_text("\n".join(lines), reply_markup=ADMIN_MENU)
        except Exception as e:
            await query.edit_message_text(f"Could not compute stats: {e}", reply_markup=ADMIN_MENU)


def main():
    global telegram_app

    app = Application.builder().token(BOT_TOKEN).build()
    telegram_app = app

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done_merge))
    app.add_handler(CommandHandler("ok", done_braille))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("feedback", feedback_entry))
    app.add_handler(CommandHandler("admin", admin_entry))
    app.add_handler(CommandHandler("whatsnew", whatsnew))
    app.add_handler(CallbackQueryHandler(lang_choice, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(category_choice, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(admin_menu_choice, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(rating_choice, pattern="^rate_"))
    app.add_handler(CallbackQueryHandler(text_output_choice, pattern="^textout_"))
    app.add_handler(CallbackQueryHandler(mode_choice, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(op_choice, pattern="^op_"))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_reply))

    global flask_app, bot_loop

    flask_app = Flask(__name__)
    bot_loop = asyncio.new_event_loop()

    def run_event_loop():
        asyncio.set_event_loop(bot_loop)
        bot_loop.run_until_complete(app.initialize())
        if RENDER_EXTERNAL_URL:
            bot_loop.run_until_complete(
                app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}")
            )
        bot_loop.create_task(session_watcher())
        bot_loop.run_forever()

    threading.Thread(target=run_event_loop, daemon=True).start()

    @flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
    def webhook():
        update = Update.de_json(request.get_json(force=True), app.bot)
        asyncio.run_coroutine_threadsafe(app.process_update(update), bot_loop)
        return "ok"

    @flask_app.route("/", methods=["GET"])
    def index():
        return "Bot is running."

    flask_app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
