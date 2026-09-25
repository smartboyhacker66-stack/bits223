
import os
import random
import string
import logging
import tempfile
import datetime

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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "api77u7y")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", "10000"))

FILE_PREFIX = "BlindIndianTechSupport"
SUPPORT_EMAIL = "bits.headquarter505@gmail.com"
SUPPORT_IMAGE_PATH = "support.jpg"

SESSIONS = {}
ADMIN_STATE = {"admin_id": None, "failed_attempts": {}, "logs": {}}
SESSION_COUNTER = {"count": 0}

WELCOME_MESSAGES = {
    "en": (
        "Welcome to the Blind Indian Tech Support PDF Manipulation Toolbox. "
        "Our best tool of 2026. Specially designed for visually impaired individuals. "
        "Release date: September 22, 2026. All rights reserved (c) Blind Indian Tech Support Team, "
        "2026 and beyond. Developed and hosted by Blind Indian Tech Support. This bot has been online "
        "since September 22, 2026. A heartfelt thank you to all our testers and users who used this "
        "service and provided valuable feedback. We will continue to add more updates in the future, "
        "and we promise to never collect or store your files anywhere. Once again, a heartfelt thank "
        "you to everyone who used and tested this tool."
    ),
    "hi": (
        "ब्लाइंड इंडियन टेक सपोर्ट पीडीएफ मैनिपुलेशन टूलबॉक्स में आपका स्वागत है। यह 2026 का हमारा सबसे बेहतरीन टूल है, "
        "जो विशेष रूप से दृष्टिबाधित लोगों के लिए बनाया गया है। रिलीज़ की तारीख: 22 सितंबर, 2026। सर्वाधिकार सुरक्षित, "
        "ब्लाइंड इंडियन टेक सपोर्ट टीम, 2026 और आगे। इसे ब्लाइंड इंडियन टेक सपोर्ट द्वारा बनाया और होस्ट किया गया है। "
        "यह बॉट 22 सितंबर, 2026 से ऑनलाइन है। हमारे उन सभी परीक्षकों और उपयोगकर्ताओं का दिल से धन्यवाद, जिन्होंने इस सेवा "
        "का इस्तेमाल किया और महत्वपूर्ण प्रतिक्रिया दी। हम भविष्य में और भी अपडेट जोड़ते रहेंगे, और हम वादा करते हैं कि "
        "आपकी कोई भी फाइल कभी भी सुरक्षित या संग्रहीत नहीं की जाएगी। एक बार फिर, इस टूल का इस्तेमाल और परीक्षण करने वाले "
        "सभी लोगों का दिल से धन्यवाद।"
    ),
    "mr": (
        "ब्लाइंड इंडियन टेक सपोर्ट पीडीएफ मॅनिप्युलेशन टूलबॉक्समध्ये आपले स्वागत आहे. हे 2026 सालातील आमचे सर्वोत्तम टूल आहे, "
        "जे खास दृष्टिबाधित व्यक्तींसाठी तयार करण्यात आले आहे. प्रकाशन तारीख: 22 सप्टेंबर, 2026. सर्व हक्क राखीव, "
        "ब्लाइंड इंडियन टेक सपोर्ट टीम, 2026 आणि पुढे. हे ब्लाइंड इंडियन टेक सपोर्टने विकसित आणि होस्ट केले आहे. "
        "हा बॉट 22 सप्टेंबर, 2026 पासून ऑनलाइन आहे. या सेवेचा वापर करून मौल्यवान अभिप्राय देणाऱ्या आमच्या सर्व परीक्षकांचे "
        "आणि वापरकर्त्यांचे मनापासून आभार. आम्ही भविष्यातही अधिक अपडेट्स जोडत राहू, आणि आम्ही वचन देतो की तुमची कोणतीही "
        "फाइल आम्ही कधीही साठवणार किंवा जतन करणार नाही. पुन्हा एकदा, हे टूल वापरणाऱ्या आणि तपासणाऱ्या सर्वांचे मनापासून आभार."
    ),
}

def generate_session_id():
    SESSION_COUNTER["count"] += 1
    random_part = "".join(random.choices(string.ascii_letters + string.digits, k=18))
    return f"{random_part}C#{SESSION_COUNTER['count']}"


def get_session(user_id, username=None):
    if user_id not in SESSIONS:
        sid = generate_session_id()
        SESSIONS[user_id] = {
            "session_id": sid,
            "username": username,
            "language": "en",
            "mode": None,
            "files": [],
            "braille_buffer": [],
        }
        ADMIN_STATE["logs"][sid] = {
            "session_id": sid,
            "user_id": user_id,
            "username": username,
            "start_time": datetime.datetime.now().isoformat(),
            "last_time": datetime.datetime.now().isoformat(),
            "actions": [],
            "errors": [],
        }
    return SESSIONS[user_id]

def log_action(user_id, action):
    session = SESSIONS.get(user_id)
    if not session:
        return
    sid = session["session_id"]
    entry = ADMIN_STATE["logs"].get(sid)
    if entry:
        entry["actions"].append(action)
        entry["last_time"] = datetime.datetime.now().isoformat()


def log_error(user_id, error_text):
    session = SESSIONS.get(user_id)
    if not session:
        return
    sid = session["session_id"]
    entry = ADMIN_STATE["logs"].get(sid)
    if entry:
        entry["errors"].append(error_text)
        entry["last_time"] = datetime.datetime.now().isoformat()


async def notify_session_id(update, context, user_id):
    session = SESSIONS.get(user_id)
    if not session:
        return
    await context.bot.send_message(
        update.effective_chat.id,
        f"Your session ID: {session['session_id']}\n"
        "Please save this ID. If you face any error, share this ID with the admin using /feedback.",
    )

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
    await query.edit_message_text(
        "A full suite of PDF operations — select a category to get started.\n\n"
        "You can also directly send a PDF file to see available operations for it.",
        reply_markup=CATEGORY_MENU,
    )

async def category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    menus = {
        "cat_read": ("READ", READ_MENU),
        "cat_create": ("CREATE", CREATE_MENU),
        "cat_organise": ("ORGANISE", ORGANISE_MENU),
        "cat_transform": ("TRANSFORM", TRANSFORM_MENU),
        "cat_annotate": ("ANNOTATE & PROTECT", ANNOTATE_MENU),
        "cat_inspect": ("INSPECT & EXTRACT", INSPECT_MENU),
    }
    title, menu = menus[data]
    await query.edit_message_text(f"{title} — select a tool:", reply_markup=menu)


async def mode_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    session["mode"] = query.data.replace("mode_", "")
    session["files"] = []
    session["braille_buffer"] = []
    log_action(user_id, f"mode_selected:{session['mode']}")

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
    mode = session.get("mode")
    doc = update.message.document

    tmp_dir = tempfile.mkdtemp()
    local_path = os.path.join(tmp_dir, doc.file_name)
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(local_path)

    if not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Please send a PDF file.")
        return

    if mode == "merge":
        session["files"].append(local_path)
        await update.message.reply_text(f"'{doc.file_name}' received. Send more files or type /done.")
        return

    if not mode:
        session["files"] = [local_path]
        await update.message.reply_text("PDF received. What would you like to do with it?", reply_markup=SINGLE_FILE_OPS)
        await notify_session_id(update, context, user.id)
        return

    session["files"] = [local_path]
    await run_single_file_mode(update, context, mode, local_path)

async def op_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id, query.from_user.username)
    mode = query.data.replace("op_", "")
    session["mode"] = mode
    log_action(user_id, f"op_selected:{mode}")

    if not session["files"]:
        await query.edit_message_text("Please send the PDF file first.")
        return

    local_path = session["files"][0]
    await query.edit_message_text("Processing...")
    await run_single_file_mode(update, context, mode, local_path, query=query)


def extract_text_with_ocr_fallback(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    if text.strip():
        return text
    if OCR_AVAILABLE:
        images = convert_from_path(pdf_path)
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


async def run_single_file_mode(update, context, mode, local_path, query=None):
    user = update.effective_user
    session = get_session(user.id, user.username)
    out_dir = tempfile.mkdtemp()
    chat = update.effective_chat

    try:
        if mode in ("read_text", "text"):
            text = extract_text_with_ocr_fallback(local_path)
            if not text.strip():
                await context.bot.send_message(chat.id, "No readable text found in this PDF.")
                return
            txt_path = os.path.join(out_dir, f"{FILE_PREFIX}_extracted.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            await context.bot.send_document(chat.id, document=open(txt_path, "rb"))

        elif mode == "read_audio":
            text = extract_text_with_ocr_fallback(local_path)
            if not text.strip():
                await context.bot.send_message(chat.id, "No readable text found in this PDF.")
                return
            chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
            for idx, chunk in enumerate(chunks):
                mp3_path = os.path.join(out_dir, f"{FILE_PREFIX}_audio_{idx+1}.mp3")
                gTTS(text=chunk, lang="en").save(mp3_path)
                await context.bot.send_audio(chat.id, audio=open(mp3_path, "rb"))

        elif mode == "split":
            reader = PdfReader(local_path)
            for i, page in enumerate(reader.pages):
                writer = PdfWriter()
                writer.add_page(page)
                p = os.path.join(out_dir, f"{FILE_PREFIX}_page_{i+1}.pdf")
                with open(p, "wb") as f:
                    writer.write(f)
                await context.bot.send_document(chat.id, document=open(p, "rb"))

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

        elif mode == "compress":
            if not PIKEPDF_AVAILABLE:
                await context.bot.send_message(chat.id, "Compress PDF feature is currently unavailable on this server.")
                return
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_compressed.pdf")
            with pikepdf.open(local_path) as pdf:
                pdf.save(out_path, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
            await context.bot.send_document(chat.id, document=open(out_path, "rb"))

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

    await update.message.reply_text("Nothing to finish right now.")

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


async def handle_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)
    text = update.message.text.strip()

    if "admin_step" in session:
        await handle_admin_flow(update, context, text)
        return

    if "feedback_step" in session:
        await handle_feedback_flow(update, context, text)
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
        await update.message.reply_text("Please use /start to see the menu.")
        return

    path = session.pop("pending_path")
    session.pop("pending_action", None)
    out_dir = tempfile.mkdtemp()

    try:
        if pending == "extract":
            reader = PdfReader(path)
            pages = parse_page_ranges(text, len(reader.pages))
            writer = PdfWriter()
            for p in pages:
                writer.add_page(reader.pages[p - 1])
            out_path = os.path.join(out_dir, f"{FILE_PREFIX}_extracted.pdf")
            with open(out_path, "wb") as f:
                writer.write(f)
            await update.message.reply_document(document=open(out_path, "rb"))

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

        session["mode"] = None

    except Exception as e:
        logger.exception("Error in text reply handler")
        log_error(user.id, str(e))
        await update.message.reply_text(f"An error occurred: {e}")
        session["mode"] = None

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = f"For any queries you can reach out to us: {SUPPORT_EMAIL}"
    try:
        await update.message.reply_photo(photo=open(SUPPORT_IMAGE_PATH, "rb"), caption=caption)
    except Exception:
        await update.message.reply_text(caption)


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


async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_session(user.id, user.username)

    if ADMIN_STATE["failed_attempts"].get(user.id, 0) >= 3:
        await update.message.reply_text("Too many failed attempts. Access temporarily blocked.")
        return

    if ADMIN_STATE["admin_id"] is not None and user.id != ADMIN_STATE["admin_id"]:
        await update.message.reply_text("Access denied.")
        return

    session["admin_step"] = "awaiting_password"
    await update.message.reply_text("Enter admin password:")

ADMIN_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("View Recent Sessions", callback_data="admin_sessions")],
        [InlineKeyboardButton("Track a Session ID", callback_data="admin_track")],
        [InlineKeyboardButton("Broadcast Message", callback_data="admin_broadcast")],
    ]
)


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

        if user.id != ADMIN_STATE["admin_id"]:
            await update.message.reply_text("Access denied.")
            return

        ADMIN_STATE["failed_attempts"][user.id] = 0
        await update.message.reply_text("Admin Panel:", reply_markup=ADMIN_MENU)
        return

    if session.get("admin_step") == "awaiting_track_id":
        session.pop("admin_step", None)
        entry = ADMIN_STATE["logs"].get(text.strip())
        if not entry:
            await update.message.reply_text("No session found with that ID.")
            return
        start = entry["start_time"]
        last = entry["last_time"]
        info = (
            f"Session ID: {entry['session_id']}\n"
            f"Username: @{entry['username']}\n"
            f"Started: {start}\n"
            f"Last activity: {last}\n"
            f"Actions: {entry['actions']}\n"
            f"Errors: {entry['errors']}"
        )
        await update.message.reply_text(info)
        return

    if session.get("admin_step") == "awaiting_broadcast_text":
        session.pop("admin_step", None)
        sent = 0
        for uid in list(SESSIONS.keys()):
            try:
                await context.bot.send_message(uid, f"Announcement:\n\n{text}")
                sent += 1
            except Exception:
                pass
        await update.message.reply_text(f"Broadcast sent to {sent} users.")
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
        lines = ["Recent Sessions:\n"]
        entries = list(ADMIN_STATE["logs"].values())[-20:]
        for entry in entries:
            lines.append(
                f"ID: {entry['session_id']} | User: @{entry['username']} | "
                f"Started: {entry['start_time']}"
            )
        await query.edit_message_text("\n".join(lines) if len(lines) > 1 else "No sessions logged yet.")

    elif data == "admin_track":
        session["admin_step"] = "awaiting_track_id"
        await query.edit_message_text("Please type the session ID you want to track:")

    elif data == "admin_broadcast":
        session["admin_step"] = "awaiting_broadcast_text"
        await query.edit_message_text("Type the message you want to broadcast to all users:")

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done_merge))
    app.add_handler(CommandHandler("ok", done_braille))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("feedback", feedback_entry))
    app.add_handler(CommandHandler("admin", admin_entry))
    app.add_handler(CallbackQueryHandler(lang_choice, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(category_choice, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(admin_menu_choice, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(mode_choice, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(op_choice, pattern="^op_"))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_reply))

    if RENDER_EXTERNAL_URL:
        logger.info("Starting bot with webhook...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}",
        )
    else:
        logger.info("RENDER_EXTERNAL_URL not set, falling back to polling...")
        app.run_polling()

if __name__ == "__main__":
    main()
