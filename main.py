import logging
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
)

# --- CONFIGURATION ---
BOT_TOKEN = "8756205223:AAH3BHjz-wPYoJkt6Gk19pu4cjokUS6QQj4"
MONGO_URI = "mongodb://127.0.0.1:27017/"
ADMIN_ID = 7128167678
DEPOSIT_WALLET = "TUtGRkicz5Zn5DiUhLSH3B1MUoPCfErWAa"
REFER_BONUS = 3.0

# --- DATABASE SETUP ---
client = MongoClient(MONGO_URI)
db = client['telegram_bot']
users_col = db['users']
deposits_col = db['deposits']
withdraws_col = db['withdraws']
tasks_col = db['tasks']

logging.basicConfig(level=logging.INFO)

# --- KEYBOARD ---
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Account", callback_data='account'),
         InlineKeyboardButton("💰 Deposit", callback_data='deposit')],
        [InlineKeyboardButton("👥 Refer", callback_data='refer'),
         InlineKeyboardButton("📝 Tasks", callback_data='tasks')],
        [InlineKeyboardButton("💳 Withdraw", callback_data='withdraw')]
    ])

# --- START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    existing_user = users_col.find_one({"user_id": user.id})

    if not existing_user:
        referrer_id = None
        if args:
            try:
                ref_id = int(args[0])
                if ref_id != user.id:
                    referrer_id = ref_id

                    users_col.update_one(
                        {"user_id": referrer_id},
                        {"$push": {"referrals": user.id}}
                    )
            except:
                pass

        users_col.insert_one({
            "user_id": user.id,
            "username": user.username,
            "balance": 0.0,
            "referrer_id": referrer_id,
            "referrals": [],
            "referral_paid": False,
            "total_referrals": 0,
            "completed_tasks": [],
            "is_active": False
        })

        text = "✅ Account created!\n\n💰 আগে deposit করুন"
    else:
        text = "💰 আগে deposit করুন (Admin approve না হওয়া পর্যন্ত bot locked থাকবে)"

    await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# --- BUTTON ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = users_col.find_one({"user_id": user_id})

    if not user.get("is_active", False):
        if query.data != 'deposit':
            await query.answer("❌ আগে deposit করুন!", show_alert=True)
            return

    await query.answer()

    if query.data == 'account':
        text = f"👤 Account Info\n\nID: {user_id}\nBalance: {user.get('balance', 0)} USD\nReferrals: {user.get('total_referrals', 0)}"
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())

    elif query.data == 'deposit':
        context.user_data['step'] = 'awaiting_deposit'
        await query.edit_message_text(
            f"Send USDT (BEP20) here:\n{DEPOSIT_WALLET}\n\nThen send TXID.",
            reply_markup=main_menu_keyboard()
        )

    elif query.data == 'withdraw':
        if user.get('balance', 0) < 1:
            await query.edit_message_text("❌ আপনার ব্যালেন্স ১ ডলারের কম।", reply_markup=main_menu_keyboard())
            return
        
        context.user_data['step'] = 'awaiting_withdraw_address'
        await query.edit_message_text(
            "💳 আপনার Trust Wallet (USDT BEP20) অ্যাড্রেস দিন:",
            reply_markup=main_menu_keyboard()
        )

    elif query.data == 'refer':
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user_id}"
        await query.edit_message_text(
            f"👥 Referral Program\n\nপ্রতি রেফারে পাবেন: {REFER_BONUS} USD\n\nYour referral link:\n{link}",
            reply_markup=main_menu_keyboard()
        )

    elif query.data == 'tasks':
        tasks = list(tasks_col.find())
        if not tasks:
            await query.edit_message_text("❌ No tasks available", reply_markup=main_menu_keyboard())
            return

        buttons = []
        for t in tasks:
            buttons.append([InlineKeyboardButton(
                f"{t['title']} (+{t['reward']}$)",
                callback_data=f"do_task_{t['_id']}"
            )])

        await query.edit_message_text(
            "📝 Available Tasks:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif query.data.startswith("do_task_"):
        task_id = query.data.replace("do_task_", "")
        task = tasks_col.find_one({"_id": task_id})

        if not task:
            await query.answer("Task not found", show_alert=True)
            return

        if task_id in user.get("completed_tasks", []):
            await query.answer("❌ Already completed", show_alert=True)
            return

        users_col.update_one(
            {"user_id": user_id},
            {
                "$inc": {"balance": task["reward"]},
                "$push": {"completed_tasks": task_id}
            }
        )

        await query.edit_message_text(
            f"✅ Task Completed!\nReward: {task['reward']} USD",
            reply_markup=main_menu_keyboard()
        )

# --- ADMIN: ALL USERS VIEW ---
async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    users = list(users_col.find())
    text = f"👥 Total Users: {len(users)}\n\n"

    for user in users:
        uid = user["user_id"]
        refs = user.get("referrals", [])
        ref_by = user.get("referrer_id")

        text += f"🆔 User: {uid}\n"
        text += f"👤 Referred By: {ref_by}\n"
        text += f"🔗 Total Referrals: {len(refs)}\n"
        text += f"📌 Referrals: {refs}\n\n"

    await update.message.reply_text(text[:4000])

# --- HANDLE TEXT ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})

    step = context.user_data.get('step')

    if not user.get("is_active", False):
        if step != 'awaiting_deposit':
            await update.message.reply_text("❌ আগে deposit করুন")
            return

    text = update.message.text

    if step == 'awaiting_deposit':
        deposits_col.insert_one({
            "user_id": user_id,
            "txid": text,
            "status": "pending"
        })
        context.user_data['step'] = None

        await context.bot.send_message(
            ADMIN_ID,
            f"New Deposit\nUser: {user_id}\nTXID: {text}\n\n/approve {user_id} 10"
        )

        await update.message.reply_text("✅ TXID sent for approval.")

    elif step == 'awaiting_withdraw_address':
        context.user_data['withdraw_address'] = text
        context.user_data['step'] = 'awaiting_withdraw_amount'
        await update.message.reply_text("💰 কত ডলার তুলবেন?")

    elif step == 'awaiting_withdraw_amount':
        try:
            amount = float(text)
            balance = user.get("balance", 0)

            if amount <= 0:
                await update.message.reply_text("❌ সঠিক amount দিন")
                return

            if balance - amount < 10:
                await update.message.reply_text("❌ Withdraw করার পরে কমপক্ষে 10$ account এ থাকতে হবে")
                return

            address = context.user_data.get('withdraw_address')

            withdraws_col.insert_one({
                "user_id": user_id,
                "address": address,
                "amount": amount,
                "status": "pending"
            })

            context.user_data['step'] = None

            await context.bot.send_message(
                ADMIN_ID,
                f"Withdraw Request\nUser: {user_id}\nAmount: {amount}\nAddress: {address}\n\n/deduct {user_id} {amount}"
            )

            await update.message.reply_text("✅ Withdraw request sent")

        except:
            await update.message.reply_text("❌ সংখ্যা লিখুন")

# --- ADMIN COMMANDS ---
async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])

        users_col.update_one(
            {"user_id": target_id},
            {
                "$inc": {"balance": amount},
                "$set": {"is_active": True}
            }
        )

        user = users_col.find_one({"user_id": target_id})

        if amount >= 10 and user.get("referrer_id") and not user.get("referral_paid", False):
            referrer_id = user["referrer_id"]

            users_col.update_one(
                {"user_id": referrer_id},
                {"$inc": {"balance": REFER_BONUS, "total_referrals": 1}}
            )

            users_col.update_one(
                {"user_id": target_id},
                {"$set": {"referral_paid": True}}
            )

            try:
                await context.bot.send_message(
                    referrer_id,
                    f"🎉 Referral Bonus Added!\nYou earned {REFER_BONUS}$"
                )
            except:
                pass

        await context.bot.send_message(target_id, f"✅ Deposit Approved: {amount} USD")
        await update.message.reply_text("Done ✅")

    except:
        await update.message.reply_text("Use: /approve ID AMOUNT")

# ✅ NEW DEDUCT COMMAND
async def deduct_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])

        users_col.update_one(
            {"user_id": target_id},
            {"$inc": {"balance": -amount}}
        )

        await context.bot.send_message(
            target_id,
            f"✅ Withdrawal Done! {amount} USD sent"
        )

        await update.message.reply_text("Done ✅")

    except:
        await update.message.reply_text("Use: /deduct ID AMOUNT")

# --- RUN ---
updater = Updater(BOT_TOKEN, use_context=True)
dp = updater.dispatcher

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("approve", approve_deposit))
app.add_handler(CommandHandler("allusers", all_users))
app.add_handler(CommandHandler("deduct", deduct_balance))  # ✅ added

app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("Bot running...")
app.run_polling()
updater.start_polling()
updater.idle()
