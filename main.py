import asyncio, os, random, string
from datetime import datetime, timedelta
import psycopg2

from aiogram import Bot, Dispatcher, F
from aiogram.types import *
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [7418454273,7672413819]

bot = Bot(API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ===== DB =====
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = True
c = conn.cursor()

c.execute("CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY,points INT DEFAULT 2,ref_by BIGINT,last_bonus TIMESTAMP)")
c.execute("CREATE TABLE IF NOT EXISTS channels(chat_id TEXT PRIMARY KEY)")
c.execute("""
CREATE TABLE IF NOT EXISTS store(
id SERIAL PRIMARY KEY,
username TEXT,
gmail TEXT,
year TEXT,
price INT
)
""")
c.execute("CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY,points INT,uses INT)")
c.execute("CREATE TABLE IF NOT EXISTS claimed(user_id BIGINT,code TEXT,PRIMARY KEY(user_id,code))")

# ===== FORCE SUB =====
async def check_sub(uid):
async def check_sub(uid):
    c.execute("SELECT chat_id FROM channels")
    channels = c.fetchall()

    for ch in channels:
        chat = ch[0]

        try:
            member = await bot.get_chat_member(chat, uid)

            if member.status in ["left", "kicked"]:
                return False

        except Exception as e:
            print("JOIN CHECK ERROR:", e)
            return False

    return True

# ===== MENU =====
def menu(uid):
    kb = [
        [InlineKeyboardButton(text="💰 Points", callback_data="points"),
         InlineKeyboardButton(text="🎁 Bonus", callback_data="bonus")],
        [InlineKeyboardButton(text="🔗 Refer", callback_data="ref"),
         InlineKeyboardButton(text="🛍 Store", callback_data="store")],
        [InlineKeyboardButton(text="🎟 Redeem", callback_data="redeem")]
    ]
    if uid in ADMIN_IDS:
        kb.append([InlineKeyboardButton(text="👑 Admin", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ===== START =====
@dp.message(CommandStart())
async def start(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    ref = command.args

    if not await check_sub(uid):
        c.execute("SELECT chat_id FROM channels")
        ch = c.fetchall()

        kb = []

        for i in ch:
            try:
                chat = await bot.get_chat(i[0])
                invite = await bot.create_chat_invite_link(chat.id)

                kb.append([
                    InlineKeyboardButton(
                        text=f"📢 {chat.title}",
                        url=invite.invite_link
                    )
                ])
            except:
                pass

        kb.append([InlineKeyboardButton(text="🔄 Check Again", callback_data="start_again")])

        await msg.answer(
            "❌ Join all channels first",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
        return

    # user add
    c.execute("INSERT INTO users(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,))

    # referral
    if ref and ref.isdigit():
        ref_id = int(ref)
        if ref_id != uid:
            c.execute("UPDATE users SET points=points+5 WHERE user_id=%s",(ref_id,))

    await msg.answer("✅ Bot Started", reply_markup=menu(uid))

# ===== POINTS =====
@dp.callback_query(F.data=="points")
async def pts(call: CallbackQuery):
    c.execute("SELECT points FROM users WHERE user_id=%s",(call.from_user.id,))
    await call.answer(f"{c.fetchone()[0]} 🪙", show_alert=True)

# ===== BONUS =====
@dp.callback_query(F.data=="bonus")
async def bonus(call: CallbackQuery):
    uid = call.from_user.id
    now = datetime.now()

    c.execute("SELECT last_bonus FROM users WHERE user_id=%s",(uid,))
    d = c.fetchone()

    if d and d[0] and now < d[0] + timedelta(hours=24):
        await call.answer("⏳ Wait 24h", show_alert=True)
        return

    c.execute("UPDATE users SET points=points+2,last_bonus=%s WHERE user_id=%s",(now,uid))
    await call.answer("+2 bonus", show_alert=True)

# ===== REF =====
@dp.callback_query(F.data=="ref")
async def ref(call: CallbackQuery):
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={call.from_user.id}"
    await call.message.answer(f"🔗 Your link:\n{link}")

# ===== STORE =====
@dp.callback_query(F.data=="store")
async def store(call: CallbackQuery):
    c.execute("SELECT * FROM store")
    data = c.fetchall()

    if not data:
        await call.message.edit_text("Store empty")
        return

    text = "🛍 STORE\n\n"
    kb = []

    for i in data:
        text += f"{i[0]}. Account - {i[4]} 🪙\n"
        kb.append([InlineKeyboardButton(text=f"Buy #{i[0]}", callback_data=f"buy_{i[0]}")])

    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ===== BUY + DELIVERY =====
@dp.callback_query(F.data.startswith("buy_"))
async def buy(call: CallbackQuery):
    item_id = int(call.data.split("_")[1])
    uid = call.from_user.id

    c.execute("SELECT username,gmail,year,price FROM store WHERE id=%s",(item_id,))
    item = c.fetchone()

    if not item:
        await call.answer("❌ Item not found", show_alert=True)
        return

    username, gmail, year, price = item

    c.execute("SELECT points FROM users WHERE user_id=%s",(uid,))
    bal = c.fetchone()[0]

    if bal < price:
        await call.answer("❌ Not enough points", show_alert=True)
        return

    c.execute("UPDATE users SET points=points-%s WHERE user_id=%s",(price,uid))
    c.execute("DELETE FROM store WHERE id=%s",(item_id,))

    await call.message.answer(
        f"✅ Purchased!\n\n"
        f"👤 Username: {username}\n"
        f"📧 Gmail: {gmail}\n"
        f"📅 Year: {year}"
    )

# ===== REDEEM =====
class Redeem(StatesGroup): code = State()

@dp.callback_query(F.data=="redeem")
async def redeem(call: CallbackQuery, state: FSMContext):
    await state.set_state(Redeem.code)
    await call.message.answer("Send code")

@dp.message(Redeem.code)
async def redeem_code(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    code = msg.text

    c.execute("SELECT points,uses FROM codes WHERE code=%s",(code,))
    data = c.fetchone()

    if not data:
        await msg.answer("Invalid code")
        return

    pts, uses = data

    if uses <= 0:
        await msg.answer("Code expired")
        return

    c.execute("SELECT 1 FROM claimed WHERE user_id=%s AND code=%s",(uid,code))
    if c.fetchone():
        await msg.answer("Already used")
        return

    c.execute("UPDATE users SET points=points+%s WHERE user_id=%s",(pts,uid))
    c.execute("UPDATE codes SET uses=uses-1 WHERE code=%s",(code,))
    c.execute("INSERT INTO claimed VALUES(%s,%s)",(uid,code))

    await msg.answer(f"+{pts} points added")
    await state.clear()

# ===== ADMIN =====
@dp.callback_query(F.data=="admin")
async def admin(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    kb = [
        [InlineKeyboardButton(text="Add Channel", callback_data="add_ch")],
        [InlineKeyboardButton(text="Add Item", callback_data="add_item")],
        [InlineKeyboardButton(text="Gen Code", callback_data="gen_code")],
        [InlineKeyboardButton(text="Broadcast", callback_data="bc")],
        [InlineKeyboardButton(text="Stats", callback_data="stats")]
    ]
    await call.message.edit_text("👑 ADMIN PANEL", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ===== ADD CHANNEL =====
class AddChannel(StatesGroup):
    chat_id = State()

@dp.callback_query(F.data=="add_ch")
async def add_ch(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddChannel.chat_id)
    await call.message.answer("Send @channel or @group username")

@dp.message(AddChannel.chat_id)
async def save_ch(msg: Message, state: FSMContext):
    try:
        chat = await bot.get_chat(msg.text.strip())

        chat_id = str(chat.id)   # real chat_id (-100xxxx)

        c.execute("INSERT INTO channels(chat_id) VALUES(%s)", (chat_id,))
        await msg.reply(f"✅ Added: {chat.title}")

    except Exception as e:
        await msg.reply("❌ Invalid / bot not admin")

    await state.clear()

# ===== ADD ITEM =====
class AddItem(StatesGroup):
    username=State()
    gmail=State()
    year=State()
    price=State()

@dp.callback_query(F.data=="add_item")
async def add_item(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddItem.username)
    await call.message.answer("Username?")

@dp.message(AddItem.username)
async def i1(msg: Message, state: FSMContext):
    await state.update_data(username=msg.text)
    await state.set_state(AddItem.gmail)
    await msg.answer("Gmail?")

@dp.message(AddItem.gmail)
async def i2(msg: Message, state: FSMContext):
    await state.update_data(gmail=msg.text)
    await state.set_state(AddItem.year)
    await msg.answer("Year?")

@dp.message(AddItem.year)
async def i3(msg: Message, state: FSMContext):
    await state.update_data(year=msg.text)
    await state.set_state(AddItem.price)
    await msg.answer("Price?")

@dp.message(AddItem.price)
async def i4(msg: Message, state: FSMContext):
    d = await state.get_data()
    c.execute("INSERT INTO store(username,gmail,year,price) VALUES(%s,%s,%s,%s)",
              (d['username'],d['gmail'],d['year'],int(msg.text)))
    await msg.answer("Item added")
    await state.clear()

# ===== GEN CODE =====
@dp.callback_query(F.data=="gen_code")
async def gen(call: CallbackQuery):
    code = ''.join(random.choices(string.ascii_uppercase+string.digits,k=6))
    c.execute("INSERT INTO codes VALUES(%s,%s,%s)",(code,10,5))
    await call.message.answer(f"Code: {code}")

# ===== BROADCAST =====
class BC(StatesGroup): msg = State()

@dp.callback_query(F.data=="bc")
async def bc(call: CallbackQuery, state: FSMContext):
    await state.set_state(BC.msg)
    await call.message.answer("Send message")

@dp.message(BC.msg)
async def send_all(msg: Message, state: FSMContext):
    c.execute("SELECT user_id FROM users")
    for u in c.fetchall():
        try:
            await bot.send_message(u[0], msg.text)
        except:
            pass
    await msg.answer("Broadcast done")
    await state.clear()

# ===== STATS =====
@dp.callback_query(F.data=="stats")
async def stats(call: CallbackQuery):
    c.execute("SELECT COUNT(*) FROM users")
    await call.answer(f"Users: {c.fetchone()[0]}", show_alert=True)

# ===== RUN =====

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    server = HTTPServer(("0.0.0.0", 10000), Handler)
    server.serve_forever()

threading.Thread(target=run_server).start()

# ===== CLEAR CHANNELS (ADMIN ONLY) =====
@dp.message(F.text == "/clearchannels")
async def clear_channels(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return

    c.execute("DELETE FROM channels")
    await msg.answer("✅ All channels cleared")
    
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
