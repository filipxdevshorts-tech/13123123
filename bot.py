import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import requests
from datetime import datetime, timedelta
import json
import os
import hashlib

# Konfiguracja
ADMIN_ID = 7797765900
ADMIN_GROUP_ID = -5053109401
BOT_TOKEN = "8244892496:AAF_ZI44_6DJhF-yWzm743Xv9Vy7_sbgLSo"
BLOCKCYPHER_TOKEN = "bffa1a32807845a78b6ea3dfe846afdfN"
LTC_ADDRESS = "LLQtaBnSAFpCFUw5cXRRka7Nvtrs4Up9bH"
PAYPAL_EMAIL = "playcraftalt@int.pl"
COMMISSION = 0.10  # 10%
DEPOSIT_LIMIT = 5000

# Stany konwersacji
(AWAITING_LTC_AMOUNT, AWAITING_TXID, AWAITING_BLIK_AMOUNT, AWAITING_BLIK_CODE,
 AWAITING_PAYPAL_AMOUNT, AWAITING_LTC_WITHDRAW_ADDRESS, AWAITING_LTC_WITHDRAW_AMOUNT,
 AWAITING_ANNOUNCEMENT, AWAITING_ADD_BALANCE_ID, AWAITING_ADD_BALANCE_AMOUNT,
 AWAITING_REMOVE_BALANCE_ID, AWAITING_REMOVE_BALANCE_AMOUNT,
 AWAITING_BLACKLIST_ID, AWAITING_BLACKLIST_REASON, AWAITING_UNBLACKLIST_ID,
 AWAITING_ADMIN_CHAT_MESSAGE) = range(16)

# Baza danych
users_db = {}
transactions_db = []
bot_status = {"online": True, "admin_available": False}
blacklist = {}
pending_operations = {}  # Przechowuje dane dla długich callback_data

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def load_data():
    global users_db, transactions_db, blacklist
    try:
        if os.path.exists('users.json'):
            with open('users.json', 'r') as f:
                users_db = json.load(f)
        if os.path.exists('transactions.json'):
            with open('transactions.json', 'r') as f:
                transactions_db = json.load(f)
        if os.path.exists('blacklist.json'):
            with open('blacklist.json', 'r') as f:
                blacklist = json.load(f)
    except Exception as e:
        logger.error(f"Błąd ładowania danych: {e}")

def save_data():
    try:
        with open('users.json', 'w') as f:
            json.dump(users_db, f, indent=2)
        with open('transactions.json', 'w') as f:
            json.dump(transactions_db, f, indent=2)
        with open('blacklist.json', 'w') as f:
            json.dump(blacklist, f, indent=2)
    except Exception as e:
        logger.error(f"Błąd zapisywania danych: {e}")

def is_admin(user_id):
    return user_id == ADMIN_ID

def get_user_balance(user_id):
    return users_db.get(str(user_id), {}).get('balance', 0)

def add_balance(user_id, amount):
    user_id = str(user_id)
    if user_id not in users_db:
        users_db[user_id] = {'balance': 0}
    users_db[user_id]['balance'] += amount
    save_data()

def remove_balance(user_id, amount):
    user_id = str(user_id)
    if user_id in users_db:
        users_db[user_id]['balance'] = max(0, users_db[user_id]['balance'] - amount)
        save_data()

def log_transaction(user_id, type, amount, details):
    transaction = {
        'user_id': user_id,
        'type': type,
        'amount': amount,
        'details': details,
        'timestamp': datetime.now().isoformat(),
        'commission': amount * COMMISSION if type == 'deposit' else 0
    }
    transactions_db.append(transaction)
    save_data()

def get_ltc_price():
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd', timeout=10)
        return response.json()['litecoin']['usd']
    except Exception as e:
        logger.error(f"Nie udało się pobrać ceny LTC: {e}")
        return 100.0

def usd_to_ltc(usd_amount):
    ltc_price = get_ltc_price()
    return usd_amount / ltc_price

def check_ltc_transaction(txid):
    try:
        url = f"https://api.blockcypher.com/v1/ltc/main/txs/{txid}?token={BLOCKCYPHER_TOKEN}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        confirmations = data.get('confirmations', 0)
        outputs = data.get('outputs', [])
        
        for output in outputs:
            if output.get('addresses', [None])[0] == LTC_ADDRESS:
                amount_ltc = output.get('value', 0) / 100000000
                return {
                    'found': True,
                    'confirmations': confirmations,
                    'amount_ltc': amount_ltc,
                    'amount_usd': amount_ltc * get_ltc_price()
                }
        return {'found': False}
    except Exception as e:
        logger.error(f"Błąd sprawdzania transakcji: {e}")
        return {'found': False}

def create_operation_id(data):
    """Tworzy krótki ID dla operacji zamiast długiego callback_data"""
    op_id = hashlib.md5(str(data).encode()).hexdigest()[:8]
    pending_operations[op_id] = data
    return op_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if user_id not in users_db:
        users_db[user_id] = {'balance': 0}
        save_data()
    
    status = "🟢 ONLINE" if bot_status["online"] else "🔴 OFFLINE"
    balance = get_user_balance(user.id)
    
    keyboard = [
        [InlineKeyboardButton("💰 Wpłać", callback_data="deposit")],
        [InlineKeyboardButton("💸 Wypłać", callback_data="withdraw")],
        [InlineKeyboardButton("💬 Czat z adminem", callback_data="admin_chat")]
    ]
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Panel administratora", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"""Witaj {user.first_name}!

📊 Status bota: {status}
💵 Twoje saldo: ${balance:.2f}
📈 Pobierana prowizja: {int(COMMISSION * 100)}%
💳 Limit wpłaty: ${DEPOSIT_LIMIT}"""
    
    # Jeśli wywołane przez komendę /start mamy update.message
    if update.message:
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        # jeżeli wywołane z callback_query (np. powrót)
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        except:
            pass

async def start_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = str(user.id)
    if user_id not in users_db:
        users_db[user_id] = {'balance': 0}
        save_data()
    status = "🟢 ONLINE" if bot_status["online"] else "🔴 OFFLINE"
    balance = get_user_balance(user.id)
    keyboard = [
        [InlineKeyboardButton("💰 Wpłać", callback_data="deposit")],
        [InlineKeyboardButton("💸 Wypłać", callback_data="withdraw")],
        [InlineKeyboardButton("💬 Czat z adminem", callback_data="admin_chat")]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Panel administratora", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = f"""Witaj {user.first_name}!

📊 Status bota: {status}
💵 Twoje saldo: ${balance:.2f}
📈 Pobierana prowizja: {int(COMMISSION * 100)}%
💳 Limit wpłaty: ${DEPOSIT_LIMIT}"""
    try:
        await query.edit_message_text(message, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"start_from_callback error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    data = query.data
    
    # Sprawdzanie blacklisty
    if user_id in blacklist and not data.startswith("admin_"):
        await query.edit_message_text(f"❌ Jesteś zablokowany!\nPowód: {blacklist[user_id]}")
        return ConversationHandler.END
    
    # Obsługa operacji z krótkimi ID
    if data.startswith("op_"):
        op_id = data.split("_")[1]
        if op_id in pending_operations:
            operation = pending_operations[op_id]
            data = operation['action']
            context.user_data.update(operation)
    
    # Obsługa przycisków BLIK admin
    if data.startswith("blik_approve"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            amount = op_data['amount']
            amount_usd = amount / 4.0
            amount_with_commission = amount_usd * (1 - COMMISSION)
            add_balance(target_user, amount_with_commission)
            log_transaction(target_user, 'deposit', amount_usd, f'BLIK {amount} PLN')
            
            await query.edit_message_text(f"✅ Dodano balance użytkownikowi {target_user}!\nKwota: ${amount_with_commission:.2f}")
            try:
                await context.bot.send_message(chat_id=int(target_user), text=f"✅ Dodano balance!\nTwoje saldo: ${get_user_balance(int(target_user)):.2f}\nUżyj /start!")
            except:
                pass
            del pending_operations[op_id]
        return ConversationHandler.END
    
    elif data.startswith("blik_reject"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            await query.edit_message_text("❌ Kod został odrzucony!")
            try:
                await context.bot.send_message(chat_id=int(target_user), text="❌ Podałeś zły kod!")
            except:
                pass
            del pending_operations[op_id]
        return ConversationHandler.END
    
    # Obsługa PayPal
    elif data.startswith("paypal_sent"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            amount = op_data['amount']
            
            new_op_id = create_operation_id({'action': 'paypal_approve', 'user_id': target_user, 'amount': amount})
            
            keyboard = [
                [InlineKeyboardButton("✅ Akceptuj", callback_data=f"paypal_approve_{new_op_id}")],
                [InlineKeyboardButton("❌ Odrzuć", callback_data=f"paypal_reject_{new_op_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=f"💰 Nowa wpłata PayPal\n\n👤 User ID: {target_user}\n💵 Kwota: ${amount:.2f} USD\n📧 Email PayPal: {PAYPAL_EMAIL}",
                reply_markup=reply_markup
            )
            
            await query.edit_message_text("⏳ Czekam na potwierdzenie administratora...")
        return ConversationHandler.END
    
    elif data.startswith("paypal_approve"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            amount = op_data['amount']
            amount_with_commission = amount * (1 - COMMISSION)
            add_balance(target_user, amount_with_commission)
            log_transaction(target_user, 'deposit', amount, 'PayPal')
            
            await query.edit_message_text(f"✅ Wpłata zatwierdzona!\nUser: {target_user}\nDodano: ${amount_with_commission:.2f}")
            try:
                await context.bot.send_message(chat_id=int(target_user), text=f"✅ Twój balance został dodany!\nSaldo: ${get_user_balance(int(target_user)):.2f}\nUżyj /start!")
            except:
                pass
            del pending_operations[op_id]
        return ConversationHandler.END
    
    elif data.startswith("paypal_reject"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            await query.edit_message_text("❌ Wpłata odrzucona!")
            try:
                await context.bot.send_message(chat_id=int(target_user), text="❌ Twoja transakcja została odrzucona!")
            except:
                pass
            del pending_operations[op_id]
        return ConversationHandler.END
    
    # Obsługa wypłat
    elif data.startswith("withdraw_approve"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            amount = op_data['amount']
            address = op_data['address']
            
            remove_balance(target_user, amount)
            log_transaction(target_user, 'withdraw', amount, f'LTC to {address}')
            
            await query.edit_message_text(f"✅ Wypłata wysłana!\n👤 User: {target_user}\n💵 Kwota: ${amount:.2f}\n📍 Adres: {address}")
            try:
                await context.bot.send_message(chat_id=int(target_user), text=f"✅ Wypłata wysłana!\nKwota: ${amount:.2f}")
            except:
                pass
            del pending_operations[op_id]
        return ConversationHandler.END
    
    elif data.startswith("withdraw_reject"):
        op_id = query.data.split("_")[2]
        if op_id in pending_operations:
            op_data = pending_operations[op_id]
            target_user = op_data['user_id']
            await query.edit_message_text("❌ Wypłata odrzucona!")
            try:
                await context.bot.send_message(chat_id=int(target_user), text="❌ Twoja wypłata została odrzucona!")
            except:
                pass
            del pending_operations[op_id]
        return ConversationHandler.END
    
    # Menu główne
    if data == "deposit":
        if not bot_status["online"]:
            await query.edit_message_text("❌ Bot jest offline - wpłaty wyłączone!")
            return ConversationHandler.END
        
        keyboard = [
            [InlineKeyboardButton("₿ Litecoin", callback_data="deposit_ltc")],
            [InlineKeyboardButton("💳 Kod BLIK", callback_data="deposit_blik")],
            [InlineKeyboardButton("💰 PayPal", callback_data="deposit_paypal")],
            [InlineKeyboardButton("« Powrót", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Wybierz metodę płatności:", reply_markup=reply_markup)
        return ConversationHandler.END
    
    elif data == "deposit_ltc":
        await query.edit_message_text("💵 Podaj kwotę do wpłaty w USD:")
        return AWAITING_LTC_AMOUNT
    
    elif data == "deposit_blik":
        if not bot_status.get("admin_available", False):
            keyboard = [[InlineKeyboardButton("« Powrót", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ Admin nie jest dostępny :( spróbuj kiedy indziej", reply_markup=reply_markup)
            return ConversationHandler.END
        await query.edit_message_text("💵 Podaj kwotę wpłaty w PLN:")
        return AWAITING_BLIK_AMOUNT
    
    elif data == "deposit_paypal":
        await query.edit_message_text("💵 Podaj kwotę wpłaty w USD:")
        return AWAITING_PAYPAL_AMOUNT
    
    elif data == "withdraw":
        if not bot_status["online"]:
            await query.edit_message_text("❌ Bot jest offline - wypłaty wyłączone!")
            return ConversationHandler.END
        await query.edit_message_text("📤 Podaj adres portfela Litecoin:")
        return AWAITING_LTC_WITHDRAW_ADDRESS
    
    elif data == "admin_chat":
        keyboard = [[InlineKeyboardButton("❌ Anuluj", callback_data="back_to_start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("💬 Napisz swoją wiadomość do administratora:", reply_markup=reply_markup)
        return AWAITING_ADMIN_CHAT_MESSAGE
    
    elif data == "have_txid":
        await query.edit_message_text("🔍 Podaj TXID transakcji:")
        return AWAITING_TXID
    
    elif data == "admin_panel" and is_admin(query.from_user.id):
        admin_status = "🟢 Zameldowany" if bot_status.get("admin_available", False) else "🔴 Odmeldowany"
        
        keyboard = [
            [InlineKeyboardButton("📢 Wyślij ogłoszenie", callback_data="admin_announce")],
            [InlineKeyboardButton("🟢 Zamelduj się" if not bot_status.get("admin_available") else "🔴 Odmelduj się", 
                                callback_data="admin_toggle_avail")],
            [InlineKeyboardButton("🔴 Wyłącz bota" if bot_status["online"] else "🟢 Włącz bota", 
                                callback_data="admin_toggle_bot")],
            [InlineKeyboardButton("➕ Dodaj balance", callback_data="admin_add_bal")],
            [InlineKeyboardButton("➖ Usuń balance", callback_data="admin_rem_bal")],
            [InlineKeyboardButton("🚫 Zblacklistuj", callback_data="admin_blacklist")],
            [InlineKeyboardButton("✅ Unblacklistuj", callback_data="admin_unblacklist")],
            [InlineKeyboardButton("📋 Sprawdź logi", callback_data="admin_logs")],
            [InlineKeyboardButton("💰 Zarobki dziś", callback_data="admin_earn_day")],
            [InlineKeyboardButton("📊 Zarobki tydzień", callback_data="admin_earn_week")],
            [InlineKeyboardButton("📈 Zarobki miesiąc", callback_data="admin_earn_month")],
            [InlineKeyboardButton("« Powrót", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"⚙️ Panel Administratora\n\nStatus: {admin_status}", reply_markup=reply_markup)
        return ConversationHandler.END
    
    elif data.startswith("admin_") and is_admin(query.from_user.id):
        return await handle_admin_actions(update, context)
    
    elif data == "back_to_start":
        await start_from_callback(update, context)
        return ConversationHandler.END
    
    return ConversationHandler.END

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "admin_announce":
        await query.edit_message_text("📢 Podaj treść ogłoszenia:")
        return AWAITING_ANNOUNCEMENT
    
    elif data == "admin_toggle_avail":
        bot_status["admin_available"] = not bot_status.get("admin_available", False)
        status = "🟢 zameldowany" if bot_status["admin_available"] else "🔴 odmeldowany"
        keyboard = [[InlineKeyboardButton("« Powrót do panelu", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"✅ Status zmieniony!\nJesteś teraz {status}", reply_markup=reply_markup)
        return ConversationHandler.END
    
    elif data == "admin_toggle_bot":
        bot_status["online"] = not bot_status["online"]
        msg = "✅BOT JEST ONLINE - Wpłaty i wypłaty włączone!" if bot_status["online"] else "❗BOT JEST OFFLINE - Wpłaty i wypłaty wyłączone"
        
        keyboard = [[InlineKeyboardButton("« Powrót do panelu", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"✅ Bot {'włączony' if bot_status['online'] else 'wyłączony'}!", reply_markup=reply_markup)
        
        for uid in users_db.keys():
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg)
            except:
                pass
        return ConversationHandler.END
    
    elif data == "admin_add_bal":
        await query.edit_message_text("👤 Podaj ID użytkownika:")
        return AWAITING_ADD_BALANCE_ID
    
    elif data == "admin_rem_bal":
        await query.edit_message_text("👤 Podaj ID użytkownika:")
        return AWAITING_REMOVE_BALANCE_ID
    
    elif data == "admin_blacklist":
        await query.edit_message_text("👤 Podaj ID użytkownika do zablokowania:")
        return AWAITING_BLACKLIST_ID
    
    elif data == "admin_unblacklist":
        await query.edit_message_text("👤 Podaj ID użytkownika do odblokowania:")
        return AWAITING_UNBLACKLIST_ID
    
    elif data == "admin_logs":
        if not transactions_db:
            logs_text = "📋 Brak transakcji"
        else:
            logs_text = "📋 Ostatnie 10 transakcji:\n\n"
            for t in transactions_db[-10:]:
                logs_text += f"• {t['timestamp'][:16]} | {t['type'].upper()} | ${t['amount']:.2f} | User: {t['user_id']}\n"
        
        keyboard = [[InlineKeyboardButton("« Powrót do panelu", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(logs_text, reply_markup=reply_markup)
        return ConversationHandler.END
    
    elif data == "admin_earn_day":
        today = datetime.now().date()
        earnings = sum(t['commission'] for t in transactions_db if datetime.fromisoformat(t['timestamp']).date() == today)
        keyboard = [[InlineKeyboardButton("« Powrót do panelu", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"💰 Zarobki z dzisiaj: ${earnings:.2f}", reply_markup=reply_markup)
        return ConversationHandler.END
    
    elif data == "admin_earn_week":
        week_ago = datetime.now() - timedelta(days=7)
        earnings = sum(t['commission'] for t in transactions_db if datetime.fromisoformat(t['timestamp']) >= week_ago)
        keyboard = [[InlineKeyboardButton("« Powrót do panelu", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"📊 Zarobki z tego tygodnia: ${earnings:.2f}", reply_markup=reply_markup)
        return ConversationHandler.END
    
    elif data == "admin_earn_month":
        month_ago = datetime.now() - timedelta(days=30)
        earnings = sum(t['commission'] for t in transactions_db if datetime.fromisoformat(t['timestamp']) >= month_ago)
        keyboard = [[InlineKeyboardButton("« Powrót do panelu", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"📈 Zarobki z tego miesiąca: ${earnings:.2f}", reply_markup=reply_markup)
        return ConversationHandler.END
    
    return ConversationHandler.END

# Handlery wiadomości tekstowych
async def handle_ltc_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount_usd = float(update.message.text)
        if amount_usd > DEPOSIT_LIMIT:
            await update.message.reply_text(f"❌ Limit wpłaty to ${DEPOSIT_LIMIT}!")
            return ConversationHandler.END
        
        amount_ltc = usd_to_ltc(amount_usd)
        context.user_data['deposit_amount_usd'] = amount_usd
        context.user_data['deposit_amount_ltc'] = amount_ltc
        
        keyboard = [
            [InlineKeyboardButton("❌ Anuluj", callback_data="back_to_start")],
            [InlineKeyboardButton("✅ Mam TXID", callback_data="have_txid")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"""💳 Wpłata zainicjowana!

Wyślij {amount_ltc:.8f} LTC na adres:
`{LTC_ADDRESS}`

Kliknij "Mam TXID" gdy wyślesz środki."""
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Nieprawidłowa kwota! Użyj /start aby wrócić.")
        return ConversationHandler.END

async def handle_txid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txid = update.message.text.strip()
    await update.message.reply_text("🔍 Sprawdzam transakcję...")
    
    result = check_ltc_transaction(txid)
    
    if not result['found']:
        await update.message.reply_text("❌ Txid nie istnieje lub wysłałeś na zły adres lub inną ilość ltc :(\n\nUżyj /start aby wrócić.")
        return ConversationHandler.END
    
    if result['confirmations'] < 2:
        await update.message.reply_text("⏳ Transakcja znaleziona!\nSaldo zostanie przyznane od razu gdy transakcja osiągnie 2 potwierdzenia!\n\nUżyj /start aby wrócić.")
        return ConversationHandler.END
    
    amount_with_commission = result['amount_usd'] * (1 - COMMISSION)
    add_balance(update.effective_user.id, amount_with_commission)
    log_transaction(update.effective_user.id, 'deposit', result['amount_usd'], f'LTC TXID: {txid}')
    
    await update.message.reply_text(f"✅ Transakcja znaleziona!\nTwoje saldo zostało przyznane: ${amount_with_commission:.2f}\n\nUżyj /start!")
    return ConversationHandler.END

async def handle_blik_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount > DEPOSIT_LIMIT * 4:
            await update.message.reply_text(f"❌ Limit wpłaty to {DEPOSIT_LIMIT * 4} PLN!")
            return ConversationHandler.END
        context.user_data['blik_amount'] = amount
        await update.message.reply_text("🔢 Podaj kod BLIK (6 cyfr):")
        return AWAITING_BLIK_CODE
    except ValueError:
        await update.message.reply_text("❌ Nieprawidłowa kwota! Użyj /start aby wrócić.")
        return ConversationHandler.END

async def handle_blik_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    amount = context.user_data.get('blik_amount', 0)
    user_id = update.effective_user.id
    username = update.effective_user.first_name
    
    op_id = create_operation_id({'action': 'blik_approve', 'user_id': user_id, 'amount': amount})
    
    keyboard = [
        [InlineKeyboardButton("✅ Dodaj balance", callback_data=f"blik_approve_{op_id}")],
        [InlineKeyboardButton("❌ Zły kod", callback_data=f"blik_reject_{op_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=f"💳 Nowa wpłata BLIK\n\n👤 User: {username} ({user_id})\n💵 Kwota: {amount} PLN\n🔢 Kod: {code}",
        reply_markup=reply_markup
    )
    
    await update.message.reply_text("⏳ Wysłano do administratora! Czekaj na potwierdzenie...\n\nUżyj /start aby wrócić.")
    return ConversationHandler.END

async def handle_paypal_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount > DEPOSIT_LIMIT:
            await update.message.reply_text(f"❌ Limit wpłaty to ${DEPOSIT_LIMIT}!")
            return ConversationHandler.END
        user_id = update.effective_user.id
        op_id = create_operation_id({'action': 'paypal_sent', 'user_id': user_id, 'amount': amount})
        
        keyboard = [
            [InlineKeyboardButton("✅ Zgłoszę płatność", callback_data=f"paypal_sent_{op_id}")],
            [InlineKeyboardButton("« Powrót", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(f"🔔 Zgłosiłem wpłatę PayPal do administracji. Kwota: ${amount:.2f}\nUżyj /start aby wrócić.", reply_markup=reply_markup)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Nieprawidłowa kwota! Użyj /start aby wrócić.")
        return ConversationHandler.END

async def handle_ltc_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    # Prosta walidacja adresu (można rozszerzyć)
    if len(address) < 20:
        await update.message.reply_text("❌ Nieprawidłowy adres! Użyj /start aby wrócić.")
        return ConversationHandler.END
    context.user_data['withdraw_address'] = address
    await update.message.reply_text("📤 Podaj kwotę do wypłaty w USD:")
    return AWAITING_LTC_WITHDRAW_AMOUNT

async def handle_ltc_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        user_id = update.effective_user.id
        balance = get_user_balance(user_id)
        if amount > balance:
            await update.message.reply_text("❌ Nie masz wystarczającego salda! Użyj /start aby wrócić.")
            return ConversationHandler.END
        address = context.user_data.get('withdraw_address')
        # Tworzymy operację do zatwierdzenia przez admina
        op_id = create_operation_id({'action': 'withdraw', 'user_id': user_id, 'amount': amount, 'address': address})
        keyboard = [
            [InlineKeyboardButton("✅ Akceptuj wypłatę", callback_data=f"withdraw_approve_{op_id}")],
            [InlineKeyboardButton("❌ Odrzuć", callback_data=f"withdraw_reject_{op_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"📤 Prośba o wypłatę\nUser: {user_id}\nKwota: ${amount:.2f}\nAdres: {address}", reply_markup=reply_markup)
        await update.message.reply_text("⏳ Twoja prośba została wysłana do administratora. Poczekaj na decyzję.\nUżyj /start aby wrócić.")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Nieprawidłowa kwota! Użyj /start aby wrócić.")
        return ConversationHandler.END

# Admin: dodaj/usun balance
async def handle_add_balance_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['admin_target'] = text
    await update.message.reply_text("💵 Podaj kwotę do dodania (USD):")
    return AWAITING_ADD_BALANCE_AMOUNT

async def handle_add_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        target = context.user_data.get('admin_target')
        if not target:
            await update.message.reply_text("❌ Brak ID użytkownika. Użyj /start aby wrócić.")
            return ConversationHandler.END
        add_balance(target, amount)
        log_transaction(target, 'deposit', amount, 'Admin add')
        await update.message.reply_text(f"✅ Dodano ${amount:.2f} do konta {target}.")
        try:
            await context.bot.send_message(chat_id=int(target), text=f"✅ Administrator dodał ${amount:.2f} do Twojego konta.\nSaldo: ${get_user_balance(int(target)):.2f}")
        except:
            pass
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Nieprawidłowa kwota.")
        return ConversationHandler.END

async def handle_remove_balance_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['admin_target'] = text
    await update.message.reply_text("💸 Podaj kwotę do usunięcia (USD):")
    return AWAITING_REMOVE_BALANCE_AMOUNT

async def handle_remove_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        target = context.user_data.get('admin_target')
        if not target:
            await update.message.reply_text("❌ Brak ID użytkownika. Użyj /start aby wrócić.")
            return ConversationHandler.END
        remove_balance(target, amount)
        log_transaction(target, 'admin_remove', amount, 'Admin remove')
        await update.message.reply_text(f"✅ Usunięto ${amount:.2f} z konta {target}.")
        try:
            await context.bot.send_message(chat_id=int(target), text=f"❗ Administrator usunął ${amount:.2f} z Twojego konta.\nSaldo: ${get_user_balance(int(target)):.2f}")
        except:
            pass
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Nieprawidłowa kwota.")
        return ConversationHandler.END

# Blacklist
async def handle_blacklist_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['blacklist_target'] = update.message.text.strip()
    await update.message.reply_text("📝 Podaj powód zablokowania:")
    return AWAITING_BLACKLIST_REASON

async def handle_blacklist_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = context.user_data.get('blacklist_target')
    reason = update.message.text.strip()
    if not target:
        await update.message.reply_text("❌ Brak ID użytkownika.")
        return ConversationHandler.END
    blacklist[str(target)] = reason
    save_data()
    await update.message.reply_text(f"🚫 Użytkownik {target} został zablokowany. Powód: {reason}")
    try:
        await context.bot.send_message(chat_id=int(target), text=f"🚫 Zostałeś zablokowany przez administratora. Powód: {reason}")
    except:
        pass
    return ConversationHandler.END

async def handle_unblacklist_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.text.strip()
    if str(target) in blacklist:
        del blacklist[str(target)]
        save_data()
        await update.message.reply_text(f"✅ Użytkownik {target} został odblokowany.")
        try:
            await context.bot.send_message(chat_id=int(target), text="✅ Zostałeś odblokowany przez administratora.")
        except:
            pass
    else:
        await update.message.reply_text("❗ Ten użytkownik nie jest na blacklist.")
    return ConversationHandler.END

# Ogłoszenie
async def handle_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    count = 0
    for uid in list(users_db.keys()):
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 OGŁOSZENIE:\n\n{text}")
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Wysłano ogłoszenie do {count} użytkowników.")
    return ConversationHandler.END

# Czat z adminem (użytkownik -> admin group)
async def handle_admin_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"💬 Wiadomość od {user.first_name} ({user.id}):\n\n{text}")
    await update.message.reply_text("✅ Twoja wiadomość została wysłana do administratora. Odpowiedź może zająć chwilę.")
    return ConversationHandler.END

def build_conv_handler():
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start), CallbackQueryHandler(button_handler)],
        states={
            AWAITING_LTC_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ltc_amount)],
            AWAITING_TXID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_txid)],
            AWAITING_BLIK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_blik_amount)],
            AWAITING_BLIK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_blik_code)],
            AWAITING_PAYPAL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_paypal_amount)],
            AWAITING_LTC_WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ltc_withdraw_address)],
            AWAITING_LTC_WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ltc_withdraw_amount)],
            AWAITING_ANNOUNCEMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_announcement)],
            AWAITING_ADD_BALANCE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_balance_id)],
            AWAITING_ADD_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_balance_amount)],
            AWAITING_REMOVE_BALANCE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_balance_id)],
            AWAITING_REMOVE_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_balance_amount)],
            AWAITING_BLACKLIST_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_blacklist_id)],
            AWAITING_BLACKLIST_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_blacklist_reason)],
            AWAITING_UNBLACKLIST_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unblacklist_id)],
            AWAITING_ADMIN_CHAT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_chat_message)],
        },
        fallbacks=[],
        allow_reentry=True,
        persistent=False,
    )
    return conv

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Nie rozumiem komendy. Użyj /start aby rozpocząć.")

def main():
    load_data()
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv = build_conv_handler()
    application.add_handler(conv)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    logger.info("Bot uruchomiony.")
    application.run_polling()

if __name__ == '__main__':
    main()
