"""
Professional Expense Manager Bot - Render Webhook Ready
Uses python-telegram-bot v20 custom webhook pattern
"""

import logging
import os
import sqlite3
import asyncio
from datetime import datetime
from typing import List, Tuple
from http import HTTPStatus

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters
)

from flask import Flask, request, Response
from asgiref.wsgi import WsgiToAsgi
import uvicorn

# ─── Configuration ───────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
PORT = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
DB_PATH = "expenses.db"

# Conversation states
MENU, AMOUNT_INPUT, CATEGORY_INPUT = range(3)
MASTER_MESSAGE_KEY = "master_message_id"

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Database ────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('in', 'out')),
            category TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_transaction(user_id: int, amount: float, t_type: str, category: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO transactions (user_id, amount, type, category) VALUES (?, ?, ?, ?)",
        (user_id, amount, t_type, category)
    )
    tx_id = c.lastrowid
    conn.commit()
    conn.close()
    return tx_id

def get_transactions(user_id: int, limit: int = 5) -> List[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, amount, type, category, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def get_balance(user_id: int) -> Tuple[float, float, float]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT type, SUM(amount) FROM transactions WHERE user_id = ? GROUP BY type",
        (user_id,)
    )
    rows = {r[0]: r[1] for r in c.fetchall()}
    conn.close()
    income = rows.get('in', 0.0)
    expense = rows.get('out', 0.0)
    return income, expense, income - expense

def delete_transaction(tx_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

# ─── UI Builders ─────────────────────────────────────────────────────────────
def build_master_text(user_id: int) -> str:
    income, expense, balance = get_balance(user_id)
    transactions = get_transactions(user_id, limit=5)
    separator = "-" * 28

    text = f"📊 <b>Balance Overview</b>\n"
    text += separator + "\n"
    text += f"💵 Income:    <code>+{income:,.2f}</code>\n"
    text += f"💸 Expenses:  <code>-{expense:,.2f}</code>\n"
    text += separator + "\n"

    if balance >= 0:
        text += f"📈 Net:       <code>+{balance:,.2f}</code> ✅\n\n"
    else:
        text += f"📉 Net:       <code>{balance:,.2f}</code> ⚠️\n\n"

    text += "📝 <b>Last 5 Transactions</b>\n"
    text += separator + "\n"

    if not transactions:
        text += "<i>No transactions yet.</i>\n"
    else:
        for tx_id, amount, t_type, category, created_at in transactions:
            sign = "-" if t_type == 'out' else "+"
            emoji = "💸" if t_type == 'out' else "💵"
            date_str = datetime.fromisoformat(created_at).strftime("%m/%d")
            text += f"{emoji} <code>{sign}{amount:,.2f}</code> · {category} · {date_str}\n"

    return text

def build_master_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("💰 Expense", callback_data="add_out"),
            InlineKeyboardButton("💵 Income", callback_data="add_in"),
        ],
        [
            InlineKeyboardButton("🗑️ Delete Record", callback_data="delete_mode"),
            InlineKeyboardButton("📤 Export", callback_data="export"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_delete_keyboard(user_id: int) -> InlineKeyboardMarkup:
    transactions = get_transactions(user_id, limit=10)
    keyboard = []

    for tx_id, amount, t_type, category, created_at in transactions:
        sign = "-" if t_type == 'out' else "+"
        emoji = "💸" if t_type == 'out' else "💵"
        date_str = datetime.fromisoformat(created_at).strftime("%m/%d")
        label = f"{emoji} {sign}{amount:,.0f} · {category} · {date_str}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"del_{tx_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_input_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_input")]]
    return InlineKeyboardMarkup(keyboard)

# ─── Master Message Manager ──────────────────────────────────────────────────
async def update_master_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    bot = context.bot

    text = build_master_text(user_id)
    keyboard = build_master_keyboard()

    master_msg_id = context.user_data.get(MASTER_MESSAGE_KEY)

    try:
        if master_msg_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=master_msg_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            context.user_data[MASTER_MESSAGE_KEY] = msg.message_id
    except Exception:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        context.user_data[MASTER_MESSAGE_KEY] = msg.message_id

async def delete_user_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

# ─── Command Handlers ────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_messages(update, context)
    await update_master_message(update, context)
    return MENU

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await update_master_message(update, context)
    return MENU

# ─── Transaction Flow (Auto-Confirm) ─────────────────────────────────────────
async def start_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    t_type = query.data.split("_")[1]
    context.user_data["transaction_type"] = t_type
    context.user_data["step"] = "amount"

    action = "expense" if t_type == 'out' else "income"
    chat_id = update.effective_chat.id
    master_msg_id = context.user_data.get(MASTER_MESSAGE_KEY)

    prompt_text = (
        f"✏️ <b>Add {action.title()}</b>\n\n"
        f"Please type the amount:\n"
        f"<i>(e.g., 25.50 or 100)</i>"
    )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=master_msg_id,
            text=prompt_text,
            reply_markup=build_input_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        pass

    return AMOUNT_INPUT

async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip().replace(",", ".")

    await delete_user_messages(update, context)

    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
        context.user_data["amount"] = amount
    except ValueError:
        error_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Invalid amount. Please enter a valid number.",
            parse_mode="HTML"
        )
        await asyncio.sleep(2)
        try:
            await error_msg.delete()
        except Exception:
            pass
        return AMOUNT_INPUT

    context.user_data["step"] = "category"
    t_type = context.user_data["transaction_type"]
    action = "expense" if t_type == 'out' else "income"

    master_msg_id = context.user_data.get(MASTER_MESSAGE_KEY)
    prompt_text = (
        f"✏️ <b>Add {action.title()}</b>\n\n"
        f"Amount: <code>{amount:,.2f}</code>\n\n"
        f"Please type the category:\n"
        f"<i>(e.g., Food, Transport, Salary)</i>"
    )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=master_msg_id,
            text=prompt_text,
            reply_markup=build_input_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        pass

    return CATEGORY_INPUT

async def handle_category_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    category = update.message.text.strip()

    await delete_user_messages(update, context)

    if len(category) > 30:
        error_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Category too long (max 30 chars). Try again:",
            parse_mode="HTML"
        )
        await asyncio.sleep(2)
        try:
            await error_msg.delete()
        except Exception:
            pass
        return CATEGORY_INPUT

    amount = context.user_data["amount"]
    t_type = context.user_data["transaction_type"]

    tx_id = add_transaction(user_id, amount, t_type, category)

    sign = "-" if t_type == 'out' else "+"
    emoji = "💸" if t_type == 'out' else "💵"

    success_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"{emoji} Saved: <code>{sign}{amount:,.2f}</code> · {category}",
        parse_mode="HTML"
    )

    await asyncio.sleep(1.5)
    try:
        await success_msg.delete()
    except Exception:
        pass

    await update_master_message(update, context)

    context.user_data.pop("transaction_type", None)
    context.user_data.pop("amount", None)
    context.user_data.pop("step", None)

    return MENU

async def cancel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Cancelled")

    context.user_data.pop("transaction_type", None)
    context.user_data.pop("amount", None)
    context.user_data.pop("step", None)

    await update_master_message(update, context)
    return MENU

# ─── Delete Records ──────────────────────────────────────────────────────────
async def enter_delete_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    master_msg_id = context.user_data.get(MASTER_MESSAGE_KEY)

    transactions = get_transactions(user_id, limit=10)

    if not transactions:
        await query.edit_message_text(
            "🗑️ <b>Delete Records</b>\n\n"
            "No transactions to delete.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
            parse_mode="HTML"
        )
        return MENU

    text = "🗑️ <b>Tap to Delete</b>\n\nSelect a transaction to remove:\n"

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=master_msg_id,
            text=text,
            reply_markup=build_delete_keyboard(user_id),
            parse_mode="HTML"
        )
    except Exception:
        pass

    return MENU

async def delete_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    tx_id = int(query.data.split("_")[1])

    if delete_transaction(tx_id, user_id):
        await query.answer("Deleted", show_alert=False)
    else:
        await query.answer("Not found", show_alert=False)

    transactions = get_transactions(user_id, limit=10)
    chat_id = update.effective_chat.id
    master_msg_id = context.user_data.get(MASTER_MESSAGE_KEY)

    if not transactions:
        text = "🗑️ <b>Delete Records</b>\n\nNo more transactions to delete."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]])
    else:
        text = "🗑️ <b>Tap to Delete</b>\n\nSelect a transaction to remove:\n"
        keyboard = build_delete_keyboard(user_id)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=master_msg_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        pass

    return MENU

# ─── Export ──────────────────────────────────────────────────────────────────
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT amount, type, category, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await query.edit_message_text(
            "📤 <b>Export</b>\n\nNo data to export.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
            parse_mode="HTML"
        )
        return MENU

    lines = ["Date,Type,Amount,Category"]
    for amount, t_type, category, created_at in rows:
        date_str = datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M")
        lines.append(f"{date_str},{t_type},{amount},{category}")

    export_text = "\n".join(lines)

    if len(export_text) > 3500:
        filename = f"expenses_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv"
        with open(filename, "w") as f:
            f.write(export_text)

        await query.edit_message_text(
            "📤 <b>Export Ready</b>\nSending file...",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
            parse_mode="HTML"
        )

        await context.bot.send_document(
            chat_id=chat_id,
            document=open(filename, "rb"),
            caption="📊 Your expense data"
        )
        os.remove(filename)
    else:
        await query.edit_message_text(
            f"📤 <b>Your Data</b>\n\n<pre>{export_text}</pre>\n\nCopy the text above.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
            parse_mode="HTML"
        )

    return MENU

# ─── Build PTB Application (NO Updater - webhook only) ──────────────────────
def build_ptb_application():
    init_db()

    # CRITICAL: .updater(None) disables the internal Updater
    # We handle updates via Flask webhook instead
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
        ],
        states={
            MENU: [
                CallbackQueryHandler(start_transaction, pattern=r"^add_(in|out)$"),
                CallbackQueryHandler(enter_delete_mode, pattern=r"^delete_mode$"),
                CallbackQueryHandler(export_data, pattern=r"^export$"),
                CallbackQueryHandler(delete_record, pattern=r"^del_\d+$"),
                CallbackQueryHandler(back_to_menu, pattern=r"^back_menu$"),
            ],
            AMOUNT_INPUT: [
                CallbackQueryHandler(cancel_input, pattern=r"^cancel_input$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount_input),
            ],
            CATEGORY_INPUT: [
                CallbackQueryHandler(cancel_input, pattern=r"^cancel_input$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_category_input),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(back_to_menu, pattern=r"^back_menu$"),
        ],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)

    return application

# ─── Flask Web App ───────────────────────────────────────────────────────────
flask_app = Flask(__name__)
ptb_app = build_ptb_application()

@flask_app.route('/')
def health_check():
    return "✅ Bot is running!", 200

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    """Receive updates from Telegram"""
    if request.method == 'POST':
        update = Update.de_json(request.get_json(force=True), ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return Response('ok', status=200)
    return Response('ok', status=200)

@flask_app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    """Set webhook URL (call once after deploy)"""
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await ptb_app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
        return f"Webhook set to: {webhook_url}", 200
    return "RENDER_EXTERNAL_URL not set", 400

# ─── Main ────────────────────────────────────────────────────────────────────
async def main():
    """Run PTB application and webserver together"""

    # Set webhook on startup if URL is available
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await ptb_app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook set to: {webhook_url}")

    # Wrap Flask with ASGI adapter for uvicorn
    asgi_app = WsgiToAsgi(flask_app)

    # Configure uvicorn server
    config = uvicorn.Config(
        app=asgi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)

    # Run PTB and webserver together
    async with ptb_app:
        await ptb_app.start()
        await server.serve()
        await ptb_app.stop()

if __name__ == "__main__":
    asyncio.run(main())
