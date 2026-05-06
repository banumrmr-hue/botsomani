import sqlite3
import random
import string
import html
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
API_TOKEN = '8628992445:AAGBmsTfZXNslbB7yViEdBS_TpfA5jdOYO4' # ⚠️ Revoke and change this later for security!
ADMIN_IDS = [7616065999, 7672413819] # Both Admins supported!
SUPPORT_LINK = 'https://t.me/somani_07x'

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
conn = sqlite3.connect('userid.db', check_same_thread=False)
c = conn.cursor()

# Notice the new 'year' column added to the store table!
c.executescript('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 2,
    last_bonus TIMESTAMP
);
CREATE TABLE IF NOT EXISTS store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    gmail TEXT,
    year TEXT,
    price INTEGER
);
CREATE TABLE IF NOT EXISTS channels (
    chat_id TEXT PRIMARY KEY,
    url TEXT
);
CREATE TABLE IF NOT EXISTS redeem_codes (
    code TEXT PRIMARY KEY,
    points INTEGER,
    uses_left INTEGER
);
CREATE TABLE IF NOT EXISTS claimed_codes (
    user_id INTEGER,
    code TEXT,
    PRIMARY KEY (user_id, code)
);
''')
conn.commit()

# ==========================================
# 🧠 STATE MACHINES (FSM)
# ==========================================
class AdminAddProduct(StatesGroup):
    waiting_for_user = State()
    waiting_for_gmail = State()
    waiting_for_year = State()  # New state for creation year
    waiting_for_price = State()

class AdminAddChannel(StatesGroup):
    waiting_for_chat_id = State()
    waiting_for_url = State()

class AdminDelChannel(StatesGroup):
    waiting_for_chat_id = State()

class AdminGenCode(StatesGroup):
    waiting_for_points = State()
    waiting_for_uses = State()

class AdminBroadcast(StatesGroup):
    waiting_for_msg = State()

class UserRedeem(StatesGroup):
    waiting_for_code = State()

# ==========================================
# 🛡️ GATEKEEPER & DYNAMIC KEYBOARDS
# ==========================================
async def check_joined(user_id: int):
    """Returns (is_joined_all: bool, not_joined_list: list)"""
    c.execute("SELECT chat_id, url FROM channels")
    channels = c.fetchall()
    
    if not channels:
        return True, [] # If admin hasn't added any channels, let everyone in

    not_joined = []
    for chat_id, url in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                not_joined.append((chat_id, url))
        except Exception:
            # If bot isn't admin in the channel, it throws an error. Assume not joined.
            not_joined.append((chat_id, url))
            
    return len(not_joined) == 0, not_joined

def main_menu_kb(user_id: int):
    # Base layout for every standard user
    kb_rows = [
        [InlineKeyboardButton(text="🛍️ 𝙎𝙏𝙊𝙍𝙀", callback_data="menu_store"),
         InlineKeyboardButton(text="🎁 𝘿𝘼𝙄𝙇𝙔 𝘽𝙊𝙉𝙐𝙎", callback_data="menu_daily")],
        [InlineKeyboardButton(text="🎟️ 𝙍𝙀𝘿𝙀𝙀𝙈", callback_data="menu_redeem"),
         InlineKeyboardButton(text="💳 𝙈𝙔 𝙋𝙊𝙄𝙉𝙏𝙎", callback_data="menu_points")],
        [InlineKeyboardButton(text="🔗 𝙍𝙀𝙁𝙀𝙍", callback_data="menu_refer"),
         InlineKeyboardButton(text="📞 𝙎𝙐𝙋𝙋𝙊𝙍𝙏", url=SUPPORT_LINK)]
    ]
    
    # 👑 Auto-inject Admin Panel if the user is an Admin
    if user_id in ADMIN_IDS:
        kb_rows.append([InlineKeyboardButton(text="👑 ——— 𝘼𝘿𝙈𝙄𝙉 𝘾𝙊𝙉𝙏𝙍𝙊𝙇𝙎 ——— 👑", callback_data="ignore_click")])
        kb_rows.append([InlineKeyboardButton(text="➕ 𝘼𝘿𝘿 𝘼𝘾𝘾𝙊𝙐𝙉𝙏", callback_data="admin_add"),
                        InlineKeyboardButton(text="🎟️ 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀 𝘾𝙊𝘿𝙀", callback_data="admin_gen")])
        kb_rows.append([InlineKeyboardButton(text="➕ 𝘼𝘿𝘿 𝘾𝙃𝙉𝙇", callback_data="admin_addch"),
                        InlineKeyboardButton(text="➖ 𝘿𝙀𝙇 𝘾𝙃𝙉𝙇", callback_data="admin_delch")])
        kb_rows.append([InlineKeyboardButton(text="📢 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏", callback_data="admin_cast"),
                        InlineKeyboardButton(text="📊 𝙎𝙏𝘼𝙏𝙎", callback_data="admin_stats")])
                        
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

# ==========================================
# 🚀 CORE COMMANDS & REFERRAL LOGIC
# ==========================================
async def process_new_user_and_welcome(user_id: int, message_obj: Message, args: str, is_callback=False):
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()

    # If brand new user
    if not user:
        c.execute("INSERT INTO users (user_id, points) VALUES (?, 2)", (user_id,))
        conn.commit()
        
        if args and args != "0" and args.isdigit() and int(args) != user_id:
            referrer = int(args)
            c.execute("UPDATE users SET points = points + 5 WHERE user_id=?", (referrer,))
            conn.commit()
            try:
                await bot.send_message(referrer, "🎉 <b>Arey wah! Someone joined using your link. You earned 5 points!</b> 💕")
            except:
                pass

    c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
    bal = c.fetchone()[0]

    text = (f"<b>𝙐𝙉𝘾 𝙄𝙂 𝘽𝙊𝙏✨❣️</b>\n\n"
            f"Welcome to the ultimate IG store! You currently have <b>{bal} 🪙</b>.\n"
            f"Use the menu below to explore:")
    
    if is_callback:
        await message_obj.answer(text, reply_markup=main_menu_kb(user_id))
    else:
        await message_obj.reply(text, reply_markup=main_menu_kb(user_id))


@dp.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject):
    user_id = message.from_user.id
    args = command.args

    is_joined, not_joined = await check_joined(user_id)

    if not is_joined:
        ref_id = args if (args and args.isdigit()) else "0"
        join_kb = InlineKeyboardMarkup(inline_keyboard=[])
        
        for idx, (cid, url) in enumerate(not_joined):
            join_kb.inline_keyboard.append([InlineKeyboardButton(text=f"Join Channel {idx+1} 🚀", url=url)])
            
        join_kb.inline_keyboard.append([InlineKeyboardButton(text="🔄 Check Membership", callback_data=f"check_join_{ref_id}")])

        await message.reply("🔒 <b>Arey yaar, you must join our channels to use the bot!</b> 🥺", reply_markup=join_kb)
        return

    await process_new_user_and_welcome(user_id, message, args)

@dp.callback_query(F.data.startswith('check_join_'))
async def verify_join_callback(call: CallbackQuery):
    user_id = call.from_user.id
    ref_id = call.data.split('_')[2]

    is_joined, not_joined = await check_joined(user_id)
    if not is_joined:
        await call.answer("You still need to join all channels! 🥺", show_alert=True)
        return

    await call.message.delete()
    await process_new_user_and_welcome(user_id, call.message, ref_id, is_callback=True)

# ==========================================
# 👤 USER CALLBACKS
# ==========================================
@dp.callback_query(F.data.startswith('menu_'))
async def user_menu(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    
    is_joined, not_joined = await check_joined(user_id)
    if not is_joined:
        await call.answer("You left a channel! Please send /start again to rejoin.", show_alert=True)
        return

    action = call.data.split('_')[1]

    if action == "daily":
        c.execute("SELECT points, last_bonus FROM users WHERE user_id=?", (user_id,))
        pts, last_b = c.fetchone()
        now = datetime.now()
        
        if last_b:
            last_time = datetime.fromisoformat(last_b)
            if now < last_time + timedelta(hours=24):
                left = (last_time + timedelta(hours=24)) - now
                hours, remainder = divmod(left.seconds, 3600)
                minutes = remainder // 60
                await call.answer(f"⏳ Come back in {hours}h {minutes}m!", show_alert=True)
                return
        
        bonus = 2
        c.execute("UPDATE users SET points=?, last_bonus=? WHERE user_id=?", (pts + bonus, now.isoformat(), user_id))
        conn.commit()
        await call.message.edit_text(f"🎁 <b>Daily Bonus Claimed!</b>\nYou got {bonus} 🪙.\nTotal: {pts + bonus} 🪙", reply_markup=main_menu_kb(user_id))

    elif action == "points":
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        bal = c.fetchone()[0]
        await call.answer(f"💳 Your current balance is {bal} 🪙!", show_alert=True)

    elif action == "refer":
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user_id}"
        text = f"🔗 <b>Your Unique Referral Link:</b>\n\n<code>{link}</code>\n\nShare this to earn 5 points per valid join!"
        await call.message.edit_text(text, reply_markup=main_menu_kb(user_id))

    elif action == "redeem":
        await state.set_state(UserRedeem.waiting_for_code)
        await call.message.edit_text("🎟️ Send the redeem code in the chat now:")

    elif action == "store":
        # Fetching year as well now to display on the buttons
        c.execute("SELECT id, username, year, price FROM store")
        items = c.fetchall()
        if not items:
            await call.answer("Store is empty right now!", show_alert=True)
            return
            
        kb_rows = []
        for i in items:
            # Displays: 👤 demo [Yr: 2018] - 100 🪙
            safe_yr = html.escape(str(i[2]))
            kb_rows.append([InlineKeyboardButton(text=f"👤 {i[1]} [Yr: {safe_yr}] - {i[3]} 🪙", callback_data=f"buy_{i[0]}")])
            
        kb_rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="back_main")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        await call.message.edit_text("🛍️ <b>Select an account to buy:</b>", reply_markup=kb)

@dp.callback_query(F.data == 'back_main')
async def back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
    bal = c.fetchone()[0]
    await call.message.edit_text(f"<b>𝙐𝙉𝘾 𝙄𝙂 𝘽𝙊𝙏✨❣️</b>\nBalance: <b>{bal} 🪙</b>", reply_markup=main_menu_kb(user_id))

@dp.callback_query(F.data.startswith('buy_'))
async def buy_item(call: CallbackQuery):
    item_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    
    c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
    bal = c.fetchone()[0]
    
    # Fetching the year from the database upon purchase
    c.execute("SELECT username, gmail, year, price FROM store WHERE id=?", (item_id,))
    item = c.fetchone()
    
    if not item:
        await call.answer("Someone just bought this! It's gone.", show_alert=True)
        return
        
    username, gmail, year, price = item
    
    if bal < price:
        await call.answer(f"Not enough points! You need {price} 🪙", show_alert=True)
        return
        
    c.execute("UPDATE users SET points = points - ? WHERE user_id=?", (price, user_id))
    c.execute("DELETE FROM store WHERE id=?", (item_id,))
    conn.commit()
    
    safe_user = html.escape(username)
    safe_gmail = html.escape(gmail)
    safe_year = html.escape(str(year))
    
    details = (f"🎉 <b>Purchase Successful!</b>\n\n"
               f"👤 Username: <code>{safe_user}</code>\n"
               f"📧 Gmail: <code>{safe_gmail}</code>\n"
               f"📅 Creation Year: <b>{safe_year}</b>\n\n"
               f"Need help? Contact support.")
    
    await call.message.edit_text(details, reply_markup=main_menu_kb(user_id))

@dp.message(UserRedeem.waiting_for_code)
async def process_redeem(message: Message, state: FSMContext):
    code = message.text.strip()
    user_id = message.from_user.id
    
    c.execute("SELECT points, uses_left FROM redeem_codes WHERE code=?", (code,))
    res = c.fetchone()
    
    if not res or res[1] <= 0:
        await message.reply("❌ Invalid or expired code.", reply_markup=main_menu_kb(user_id))
        await state.clear()
        return
        
    c.execute("SELECT * FROM claimed_codes WHERE user_id=? AND code=?", (user_id, code))
    if c.fetchone():
        await message.reply("❌ You already claimed this code!", reply_markup=main_menu_kb(user_id))
        await state.clear()
        return
        
    pts, uses = res
    c.execute("UPDATE redeem_codes SET uses_left = uses_left - 1 WHERE code=?", (code,))
    c.execute("INSERT INTO claimed_codes (user_id, code) VALUES (?, ?)", (user_id, code))
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, user_id))
    conn.commit()
    
    await message.reply(f"✅ <b>Redeemed!</b> You got {pts} 🪙", reply_markup=main_menu_kb(user_id))
    await state.clear()

# ==========================================
# 👑 ADMIN CALLBACKS & STATES
# ==========================================
@dp.callback_query(F.data == 'ignore_click')
async def ignore_click(call: CallbackQuery):
    await call.answer("This is just a divider! 👑", show_alert=False)

@dp.callback_query(F.data.startswith('admin_'))
async def admin_menu(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
        
    action = call.data.split('_')[1]
    user_id = call.from_user.id
    
    if action == "stats":
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM store")
        items = c.fetchone()[0]
        c.execute("SELECT SUM(points) FROM users")
        total_pts = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM channels")
        ch_count = c.fetchone()[0]
        
        text = f"📊 <b>Bot Stats</b>\n👥 Users: {users}\n🛍️ Items: {items}\n🪙 Total Points: {total_pts}\n📢 Active Channels: {ch_count}"
        await call.message.edit_text(text, reply_markup=main_menu_kb(user_id))
        
    elif action == "add":
        await state.set_state(AdminAddProduct.waiting_for_user)
        await call.message.edit_text("Send the IG Username:")
        
    elif action == "gen":
        await state.set_state(AdminGenCode.waiting_for_points)
        await call.message.edit_text("Send point value for the code:")
        
    elif action == "cast":
        await state.set_state(AdminBroadcast.waiting_for_msg)
        await call.message.edit_text("Send the message/file you want to broadcast:")

    elif action == "addch":
        await state.set_state(AdminAddChannel.waiting_for_chat_id)
        await call.message.edit_text("Send the Chat ID or Username of the channel (e.g., -1001234567 or @channel):")
        
    elif action == "delch":
        c.execute("SELECT chat_id, url FROM channels")
        chs = c.fetchall()
        if not chs:
            await call.answer("No channels are currently linked!", show_alert=True)
            return
            
        text = "➖ <b>Send the exact Chat ID to remove it:</b>\n\n"
        for cid, url in chs:
            text += f"ID: <code>{cid}</code> | Link: {url}\n"
            
        await state.set_state(AdminDelChannel.waiting_for_chat_id)
        await call.message.edit_text(text)

# --- Admin Store FSM ---
@dp.message(AdminAddProduct.waiting_for_user)
async def admin_add_user(message: Message, state: FSMContext):
    await state.update_data(username=message.text)
    await state.set_state(AdminAddProduct.waiting_for_gmail)
    await message.reply("Send the Fresh Gmail associated with this account:")

@dp.message(AdminAddProduct.waiting_for_gmail)
async def admin_add_gmail(message: Message, state: FSMContext):
    await state.update_data(gmail=message.text)
    await state.set_state(AdminAddProduct.waiting_for_year)
    await message.reply("Send the Creation Year of the account (e.g., 2018):")

@dp.message(AdminAddProduct.waiting_for_year)
async def admin_add_year(message: Message, state: FSMContext):
    await state.update_data(year=message.text)
    await state.set_state(AdminAddProduct.waiting_for_price)
    await message.reply("Send the Price in points (Numbers only):")

@dp.message(AdminAddProduct.waiting_for_price)
async def admin_add_price(message: Message, state: FSMContext):
    # This crashed previously because the old database schema didn't match!
    # With a deleted/fresh userid.db, this will run perfectly.
    data = await state.get_data()
    c.execute("INSERT INTO store (username, gmail, year, price) VALUES (?, ?, ?, ?)", 
              (data['username'], data['gmail'], data['year'], int(message.text)))
    conn.commit()
    await message.reply("✅ Item added to store! Users will now see the Creation Year.", reply_markup=main_menu_kb(message.from_user.id))
    await state.clear()

# --- Admin Channel Manage FSM ---
@dp.message(AdminAddChannel.waiting_for_chat_id)
async def admin_add_ch_id(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.text)
    await state.set_state(AdminAddChannel.waiting_for_url)
    await message.reply("Now send the Invite Link for this channel (e.g., https://t.me/...):")

@dp.message(AdminAddChannel.waiting_for_url)
async def admin_add_ch_url(message: Message, state: FSMContext):
    data = await state.get_data()
    c.execute("INSERT OR REPLACE INTO channels (chat_id, url) VALUES (?, ?)", (data['chat_id'], message.text))
    conn.commit()
    await message.reply("✅ Channel added to Force Join list! Make sure I am an admin in that channel.", reply_markup=main_menu_kb(message.from_user.id))
    await state.clear()

@dp.message(AdminDelChannel.waiting_for_chat_id)
async def admin_del_ch_id(message: Message, state: FSMContext):
    c.execute("DELETE FROM channels WHERE chat_id=?", (message.text.strip(),))
    conn.commit()
    await message.reply("✅ Channel removed if it existed!", reply_markup=main_menu_kb(message.from_user.id))
    await state.clear()

# --- Admin Code & Broadcast FSM ---
@dp.message(AdminGenCode.waiting_for_points)
async def admin_gen_pts(message: Message, state: FSMContext):
    await state.update_data(pts=int(message.text))
    await state.set_state(AdminGenCode.waiting_for_uses)
    await message.reply("How many users can claim this? (Numbers only):")

@dp.message(AdminGenCode.waiting_for_uses)
async def admin_gen_uses(message: Message, state: FSMContext):
    data = await state.get_data()
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    c.execute("INSERT INTO redeem_codes (code, points, uses_left) VALUES (?, ?, ?)", 
              (code, data['pts'], int(message.text)))
    conn.commit()
    
    await message.reply(f"✅ Code created: <code>{code}</code>\nValue: {data['pts']} 🪙 | Uses: {message.text}", 
                        reply_markup=main_menu_kb(message.from_user.id))
    await state.clear()

@dp.message(AdminBroadcast.waiting_for_msg)
async def admin_broadcast(message: Message, state: FSMContext):
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    sent = 0
    for u in users:
        try:
            await bot.copy_message(chat_id=u[0], from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except Exception:
            pass
    await message.reply(f"✅ Broadcast sent to {sent} users.", reply_markup=main_menu_kb(message.from_user.id))
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
