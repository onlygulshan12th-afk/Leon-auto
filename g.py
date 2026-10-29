import asyncio
import logging
import html
import urllib.parse
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ChatMemberUpdated
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# ================= CONFIGURATION =================
BOT_TOKEN = "9108247343:AAFHKaVXxvyxziLEY5_MaL6vNM1KVjMCLE4"
ADMIN_ID = 8626080388
BOT_USERNAME = "Leongiveawaybot"
CHANNEL_USERNAME = "@sterniterspro"
CHANNEL_LINK = "https://t.me/sterniterspro"
DB_NAME = "leon_giveaway.db"
# =================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM STATES (ADMIN ONLY) ---
class CreateGiveaway(StatesGroup):
    title = State()
    prize = State()
    start_time = State()
    end_time = State()

class EditGiveaway(StatesGroup):
    new_value = State()

class BroadcastState(StatesGroup):
    message = State()

# --- DATABASE SETUP ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                referrer_id INTEGER,
                points INTEGER DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                is_member INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                prize TEXT,
                start_time TEXT,
                end_time TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.commit()

# --- HELPER FUNCTIONS ---
async def check_membership(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

async def get_active_giveaway():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, prize, start_time, end_time FROM giveaways WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ) as cursor:
            return await cursor.fetchone()

async def get_user_stats(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT points, referrals_count,
            (SELECT COUNT(*) + 1 FROM users u2 WHERE u2.is_member = 1 AND u2.points > u1.points) as rank
            FROM users u1 WHERE user_id = ?
            """,
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1], row[2]) if row else (0, 0, "N/A")

async def sync_and_reward_user(user_id: int, full_name: str, username: str):
    """Dono user aur uske dost ko +1 point deta hai jab channel join hota hai."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT referrer_id, is_member FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

        if user and user[1] == 0:
            referrer_id = user[0]
            await db.execute(
                "UPDATE users SET points = points + 1, is_member = 1, full_name = ?, username = ? WHERE user_id = ?",
                (full_name, username, user_id)
            )
            if referrer_id:
                await db.execute(
                    "UPDATE users SET points = points + 1, referrals_count = referrals_count + 1 WHERE user_id = ?",
                    (referrer_id,)
                )
                try:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 <b>NEW REFERRAL JOINED!</b>\n\n"
                        f"👤 <b>Friend:</b> {html.escape(full_name)}\n"
                        f"✅ Unhone <b>{CHANNEL_USERNAME}</b> join kar liya hai.\n"
                        f"➕ <b>Reward:</b> Aapko aur aapke dost dono ko <code>+1 Point</code> mil gaya hai!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            await db.commit()

async def handle_unsubscribed_user(user_id: int):
    """Channel leave karne par dono user aur referrer ka -1 point kat deta hai."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT referrer_id, is_member, full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if row and row[1] == 1:
            referrer_id, _, full_name = row
            await db.execute(
                "UPDATE users SET points = MAX(0, points - 1), is_member = 0 WHERE user_id = ?",
                (user_id,)
            )
            if referrer_id:
                await db.execute(
                    "UPDATE users SET points = MAX(0, points - 1), referrals_count = MAX(0, referrals_count - 1) WHERE user_id = ?",
                    (referrer_id,)
                )
                try:
                    await bot.send_message(
                        referrer_id,
                        f"⚠️ <b>REFERRAL UNSUBSCRIBED!</b>\n\n"
                        f"👤 <b>Friend:</b> {html.escape(full_name or str(user_id))}\n"
                        f"➖ Unhone <b>{CHANNEL_USERNAME}</b> leave kar diya hai, isliye aapka aur unka <code>-1 Point</code> kat gaya hai!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            await db.commit()

# --- KEYBOARDS (EASY & BOLD UI) ---
def force_join_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Join @sterniterspro Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Joined! Unlock Bot (+1 Point)", callback_data="verify_join")]
    ])

def user_home_kb(user_id: int):
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    share_text = urllib.parse.quote(
        f"🔥 Mega Giveaway chal raha hai {CHANNEL_USERNAME} par!\n\n"
        f"🎁 Mere link se bot start karke channel join karo, hum dono ko +1 Point milega:\n{ref_link}"
    )
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={share_text}"

    buttons = [
        [InlineKeyboardButton(text="🚀 Share Referral Link With Friends", url=share_url)],
        [InlineKeyboardButton(text="🏆 Check Leaderboard", callback_data="view_leaderboard"),
         InlineKeyboardButton(text="🔄 Refresh Status", callback_data="refresh_home")]
    ]
    # Sirf Admin ko Admin Panel button dikhega
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="🛠 Admin Control Panel (Admin Only)", callback_data="admin_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def leaderboard_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh Leaderboard", callback_data="view_leaderboard")],
        [InlineKeyboardButton(text="⬅️ Back to Giveaway & Referral", callback_data="refresh_home")]
    ])

def admin_panel_kb(has_active_gw: bool):
    buttons = [
        [InlineKeyboardButton(text="➕ Create New Giveaway", callback_data="admin_create")]
    ]
    if has_active_gw:
        buttons.extend([
            [InlineKeyboardButton(text="✏️ Edit Running Giveaway (Time / Prize)", callback_data="admin_edit_menu")],
            [InlineKeyboardButton(text="👑 Check Winner", callback_data="admin_winner"),
             InlineKeyboardButton(text="🗑 Delete Giveaway", callback_data="admin_delete")]
        ])
    buttons.extend([
        [InlineKeyboardButton(text="📊 Live Bot Stats", callback_data="admin_stats"),
         InlineKeyboardButton(text="🔄 Reset All Points", callback_data="admin_reset_pts")],
        [InlineKeyboardButton(text="📢 Broadcast Message", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⬅️ Back to User View", callback_data="refresh_home")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def edit_giveaway_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Edit End Time (Extend/Reduce)", callback_data="editfield_end_time")],
        [InlineKeyboardButton(text="🟢 Edit Start Time", callback_data="editfield_start_time")],
        [InlineKeyboardButton(text="💎 Edit Prize", callback_data="editfield_prize"),
         InlineKeyboardButton(text="🏷 Edit Title", callback_data="editfield_title")],
        [InlineKeyboardButton(text="⬅️ Back to Admin Panel", callback_data="admin_home")]
    ])

# --- HOME SCREEN BUILDER (SHOWS GIVEAWAY + REFERRAL DIRECTLY) ---
async def send_home_dashboard(target, user_id: int, full_name: str, is_edit: bool = True):
    gw = await get_active_giveaway()
    pts, refs, rank = await get_user_stats(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"

    if gw:
        gw_box = (
            f"🎁 <b>CURRENT RUNNING GIVEAWAY</b> 🎁\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷 <b>Giveaway:</b> <b>{html.escape(gw[1])}</b>\n"
            f"💎 <b>Winning Prize:</b> <b>{html.escape(gw[2])}</b>\n"
            f"🟢 <b>Start Time:</b> <code>{html.escape(gw[3])}</code>\n"
            f"🔴 <b>End Time:</b> <code>{html.escape(gw[4])}</code>\n"
            f"🏆 <b>Rule:</b> Sabse zyada referral karne wala <b>#1 Rank</b> user Winner banega!"
        )
    else:
        gw_box = (
            f"🎁 <b>GIVEAWAY STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Filhaal koi giveaway active nahi hai. Naye giveaway ke liye {CHANNEL_USERNAME} par jude rahein!</i>"
        )

    text = (
        f"👋 <b>Welcome, {html.escape(full_name)}!</b>\n\n"
        f"<blockquote>{gw_box}</blockquote>\n\n"
        f"📊 <b>YOUR LIVE STATS:</b>\n"
        f"⭐ <b>Your Points:</b> <code>{pts} Points</code>\n"
        f"👥 <b>Invited Friends:</b> <code>{refs} Referrals</code>\n"
        f"🏅 <b>Leaderboard Rank:</b> <code>#{rank}</code>\n\n"
        f"🔗 <b>YOUR REFERRAL LINK (Tap to Copy):</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"<blockquote>💡 <b>Kaise Kaam Karta Hai:</b>\n"
        f"• Apna link doston ko bhejein. Jab dost bot start karke <b>{CHANNEL_USERNAME}</b> join karega, to <b>aapko +1 Point</b> aur <b>dost ko bhi +1 Point</b> milega.\n"
        f"• Agar dost channel leave karega to dono ka <b>-1 Point</b> kat jayega!</blockquote>"
    )

    if is_edit:
        try:
            await target.edit_text(text, reply_markup=user_home_kb(user_id), parse_mode="HTML")
        except Exception:
            pass
    else:
        await target.answer(text, reply_markup=user_home_kb(user_id), parse_mode="HTML")

# --- /start COMMAND ---
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    full_name = message.from_user.full_name or "User"
    username = message.from_user.username or ""
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != user_id else None

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            exists = await cursor.fetchone()

        if not exists:
            await db.execute(
                "INSERT INTO users (user_id, full_name, username, referrer_id, points, referrals_count, is_member) VALUES (?, ?, ?, ?, 0, 0, 0)",
                (user_id, full_name, username, referrer_id)
            )
            await db.commit()
        else:
            await db.execute(
                "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
                (full_name, username, user_id)
            )
            await db.commit()

    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        await message.answer(
            f"🚫 <b>BOT LOCKED — JOIN CHANNEL FIRST!</b>\n\n"
            f"Giveaway me participate karne aur bot use karne ke liye aapko humara main channel <b>{CHANNEL_USERNAME}</b> join karna zaroori hai.\n\n"
            f"<blockquote>🎁 <b>Bonus:</b> Channel join karte hi aapko aur aapke referrer dost ko <b>+1 Point</b> turant mil jayega!</blockquote>",
            reply_markup=force_join_kb(),
            parse_mode="HTML"
        )
        return

    await sync_and_reward_user(user_id, full_name, username)
    await send_home_dashboard(message, user_id, full_name, is_edit=False)

# --- VERIFY MEMBERSHIP & REFRESH HOME ---
@dp.callback_query(F.data == "verify_join")
async def cb_verify_join(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_membership(user_id):
        await sync_and_reward_user(user_id, callback.from_user.full_name, callback.from_user.username or "")
        await callback.answer("✅ Channel Joined! +1 Point Activated.", show_alert=True)
        await send_home_dashboard(callback.message, user_id, callback.from_user.full_name, is_edit=True)
    else:
        await handle_unsubscribed_user(user_id)
        await callback.answer("❌ Aapne abhi tak @sterniterspro join nahi kiya hai! Pehle join karein.", show_alert=True)

@dp.callback_query(F.data == "refresh_home")
async def cb_refresh_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        await callback.answer("⚠️ Aapne channel leave kar diya hai! Points kat gaye hain.", show_alert=True)
        await callback.message.edit_text(
            f"🚫 <b>ACCESS BLOCKED!</b>\n\n"
            f"Aapne <b>{CHANNEL_USERNAME}</b> unsubscribe kar diya hai, isliye aapka aur aapke dost ka <code>-1 Point</code> kat gaya hai.\n\n"
            f"Bot use karne ke liye wapas channel join karein:",
            reply_markup=force_join_kb(),
            parse_mode="HTML"
        )
        return
    await callback.answer("🔄 Updated!")
    await send_home_dashboard(callback.message, user_id, callback.from_user.full_name, is_edit=True)

# --- LEADERBOARD FOR USERS ---
@dp.callback_query(F.data == "view_leaderboard")
async def cb_leaderboard(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        await callback.answer("⚠️ Pehle @sterniterspro channel join karein!", show_alert=True)
        await callback.message.edit_text(
            f"🚫 <b>CHANNEL UNSUBSCRIBED!</b>\n\nBot use karne ke liye <b>{CHANNEL_USERNAME}</b> join karein:",
            reply_markup=force_join_kb(),
            parse_mode="HTML"
        )
        return

    gw = await get_active_giveaway()
    gw_name = html.escape(gw[1]) if gw else "Giveaway"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, full_name, points, referrals_count FROM users WHERE is_member = 1 ORDER BY points DESC, referrals_count DESC LIMIT 10"
        ) as cursor:
            top_users = await cursor.fetchall()

    pts, refs, rank = await get_user_stats(user_id)

    if not top_users:
        board_text = "<i>Abhi tak koi participant nahi hai. Sabse pehle refer karke #1 par aayein!</i>"
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, (uid, name, u_pts, u_refs) in enumerate(top_users, start=1):
            badge = medals[idx - 1] if idx <= 3 else f"<b>#{idx}</b>"
            clean_name = html.escape((name or "User")[:18])
            you_tag = " <b>(YOU)</b>" if uid == user_id else ""
            lines.append(f"{badge} <b>{clean_name}</b>{you_tag} — <code>{u_pts} Pts</code> <i>({u_refs} Refs)</i>")
        board_text = "\n".join(lines)

    text = (
        f"🏆 <b>LIVE TOP 10 LEADERBOARD</b> 🏆\n"
        f"🎁 <b>Event:</b> <b>{gw_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{board_text}\n\n"
        f"<blockquote>👤 <b>Your Rank:</b> <code>#{rank}</code>  |  ⭐ <b>Points:</b> <code>{pts}</code>  |  👥 <b>Refs:</b> <code>{refs}</code></blockquote>"
    )
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=leaderboard_kb(), parse_mode="HTML")
    except Exception:
        pass

# --- AUTO POINT DEDUCTION ON CHANNEL LEAVE ---
@dp.chat_member()
async def on_channel_member_update(event: ChatMemberUpdated):
    if event.chat.username and f"@{event.chat.username.lower()}" == CHANNEL_USERNAME.lower():
        new_status = event.new_chat_member.status
        user = event.new_chat_member.user
        if new_status in ["left", "kicked"]:
            await handle_unsubscribed_user(user.id)
            try:
                await bot.send_message(
                    user.id,
                    f"⚠️ <b>CHANNEL UNSUBSCRIBED ALERT!</b>\n\n"
                    f"Aapne <b>{CHANNEL_USERNAME}</b> leave kar diya hai! Isliye aapka aur aapke referrer ka <code>-1 Point</code> kat gaya hai aur bot बंद ho gaya hai.\n\n"
                    f"Apna point wapas paane ke liye abhi rejoin karein:",
                    reply_markup=force_join_kb(),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        elif new_status in ["member", "administrator", "creator"]:
            await sync_and_reward_user(user.id, user.full_name, user.username or "")

# ==================== ADMIN PANEL (STRICTLY ADMIN ONLY) ====================
async def render_admin_panel(target, is_edit: bool = True):
    gw = await get_active_giveaway()
    if gw:
        gw_info = (
            f"🟢 <b>CURRENT RUNNING GIVEAWAY (ID #{gw[0]})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷 <b>Title:</b> <b>{html.escape(gw[1])}</b>\n"
            f"💎 <b>Prize:</b> <b>{html.escape(gw[2])}</b>\n"
            f"🟢 <b>Start:</b> <code>{html.escape(gw[3])}</code>\n"
            f"🔴 <b>End:</b> <code>{html.escape(gw[4])}</code>"
        )
    else:
        gw_info = "🔴 <b>STATUS:</b> <i>Koi Giveaway Active Nahi Hai</i>"

    text = (
        f"🛠 <b>ADMIN CONTROL PANEL (ONLY FOR LEON)</b>\n\n"
        f"<blockquote>{gw_info}</blockquote>\n\n"
        f"👇 <b>Yahan se Giveaway Add, Edit, ya Delete karein:</b>"
    )
    kb = admin_panel_kb(has_active_gw=bool(gw))
    if is_edit:
        try:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ <b>Access Denied!</b> Yeh panel sirf Admin ke liye hai.", parse_mode="HTML")
        return
    await render_admin_panel(message, is_edit=False)

@dp.callback_query(F.data == "admin_home")
async def cb_admin_home(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.clear()
    await render_admin_panel(callback.message, is_edit=True)

# --- EDIT RUNNING GIVEAWAY (TIME / PRIZE / TITLE) ---
@dp.callback_query(F.data == "admin_edit_menu")
async def cb_admin_edit_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)

    gw = await get_active_giveaway()
    if not gw:
        return await callback.answer("❌ Koi active giveaway nahi hai!", show_alert=True)

    text = (
        f"✏️ <b>EDIT RUNNING GIVEAWAY</b>\n\n"
        f"🏷 <b>Current Title:</b> {html.escape(gw[1])}\n"
        f"💎 <b>Current Prize:</b> {html.escape(gw[2])}\n"
        f"🟢 <b>Current Start Time:</b> <code>{html.escape(gw[3])}</code>\n"
        f"🔴 <b>Current End Time:</b> <code>{html.escape(gw[4])}</code>\n\n"
        f"👇 <b>Aap kya change karna chahte hain? Button select karein:</b>"
    )
    await callback.message.edit_text(text, reply_markup=edit_giveaway_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("editfield_"))
async def cb_select_edit_field(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)

    field = callback.data.replace("editfield_", "")
    field_labels = {
        "end_time": "🔴 Naya End Time & Date (e.g., 10 Nov 2026, 11:00 PM)",
        "start_time": "🟢 Naya Start Time & Date (e.g., 30 Oct 2026, 10:00 AM)",
        "prize": "💎 Naya Prize (e.g., ₹1000 Cash + OTT Subscription)",
        "title": "🏷 Naya Giveaway Title (e.g., Mega Referral Contest)"
    }

    await state.update_data(edit_field=field)
    await state.set_state(EditGiveaway.new_value)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Edit", callback_data="admin_edit_menu")]
    ])
    await callback.message.edit_text(
        f"✏️ <b>UPDATE GIVEAWAY</b>\n\n"
        f"Abhi type karke bhejein:\n<b>{field_labels.get(field, 'New Value')}</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(EditGiveaway.new_value)
async def process_edit_giveaway(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    field = data.get("edit_field")
    new_val = message.text

    allowed_columns = {"title": "title", "prize": "prize", "start_time": "start_time", "end_time": "end_time"}
    col = allowed_columns.get(field)

    if col:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(f"UPDATE giveaways SET {col} = ? WHERE is_active = 1", (new_val,))
            await db.commit()

    await state.clear()
    await message.answer(f"✅ <b>Giveaway successfully update ho gaya hai!</b>\nNayi value: <code>{html.escape(new_val)}</code>", parse_mode="HTML")
    await render_admin_panel(message, is_edit=False)

# --- STATS, DELETE, RESET & WINNER ---
@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1:
            total_users = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_member = 1") as c2:
            active_members = (await c2.fetchone())[0]
        async with db.execute("SELECT SUM(referrals_count) FROM users") as c3:
            total_refs = (await c3.fetchone())[0] or 0

    await callback.answer(
        f"📊 LIVE BOT STATS\n\n"
        f"👥 Total Bot Users: {total_users}\n"
        f"✅ Channel Members: {active_members}\n"
        f"🔗 Active Valid Referrals: {total_refs}",
        show_alert=True
    )

@dp.callback_query(F.data == "admin_delete")
async def cb_admin_delete(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE giveaways SET is_active = 0 WHERE is_active = 1")
        await db.commit()
    await callback.answer("🗑 Current Running Giveaway Delete Kar Diya Gaya Hai!", show_alert=True)
    await render_admin_panel(callback.message, is_edit=True)

@dp.callback_query(F.data == "admin_reset_pts")
async def cb_admin_reset(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET points = 0, referrals_count = 0")
        await db.commit()
    await callback.answer("🔄 Sabhi users ke Points aur Referrals 0 par reset ho gaye hain!", show_alert=True)
    await render_admin_panel(callback.message, is_edit=True)

@dp.callback_query(F.data == "admin_winner")
async def cb_admin_winner(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    gw = await get_active_giveaway()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, full_name, username, points, referrals_count FROM users WHERE is_member = 1 ORDER BY points DESC, referrals_count DESC LIMIT 1"
        ) as cursor:
            winner = await cursor.fetchone()

    if not winner or winner[3] == 0:
        await callback.answer("❌ Abhi tak koi valid winner nahi hai!", show_alert=True)
        return

    uid, name, uname, pts, refs = winner
    uname_str = f"@{uname}" if uname else f"<code>{uid}</code>"
    gw_title = gw[1] if gw else "Giveaway"
    gw_prize = gw[2] if gw else "Special Prize"

    win_text = (
        f"👑 <b>CURRENT #1 RANK WINNER</b> 👑\n\n"
        f"🎁 <b>Giveaway:</b> <b>{html.escape(gw_title)}</b>\n"
        f"💎 <b>Prize:</b> <b>{html.escape(gw_prize)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🥇 <b>Winner Name:</b> {html.escape(name)}\n"
        f"🆔 <b>Username / ID:</b> {uname_str} (<code>{uid}</code>)\n"
        f"⭐ <b>Total Points:</b> <code>{pts} Points</code>\n"
        f"👥 <b>Total Referrals:</b> <code>{refs} Friends</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Announce Winner to All Users", callback_data="admin_announce_win")],
        [InlineKeyboardButton(text="⬅️ Back to Admin Panel", callback_data="admin_home")]
    ])
    await callback.message.edit_text(win_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_announce_win")
async def cb_announce_winner_all(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    gw = await get_active_giveaway()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, full_name, points, referrals_count FROM users WHERE is_member = 1 ORDER BY points DESC, referrals_count DESC LIMIT 1"
        ) as cursor:
            winner = await cursor.fetchone()
        async with db.execute("SELECT user_id FROM users") as c_all:
            all_users = await c_all.fetchall()

    if not winner:
        return await callback.answer("❌ Winner nahi mila!", show_alert=True)

    uid, name, pts, refs = winner
    gw_title = gw[1] if gw else "Giveaway"
    gw_prize = gw[2] if gw else "Special Prize"

    announcement = (
        f"🎉 <b>GIVEAWAY WINNER ANNOUNCEMENT!</b> 🎉\n\n"
        f"🎁 <b>Giveaway:</b> <b>{html.escape(gw_title)}</b>\n"
        f"💎 <b>Prize:</b> <b>{html.escape(gw_prize)}</b>\n\n"
        f"👑 <b>WINNER:</b> <b>{html.escape(name)}</b>\n"
        f"⭐ <b>Winning Score:</b> <code>{pts} Points ({refs} Referrals)</code>\n\n"
        f"Congratulations! Agle giveaway ke liye <b>{CHANNEL_USERNAME}</b> par bane rahein!"
    )

    sent = 0
    for (u_id,) in all_users:
        try:
            await bot.send_message(u_id, announcement, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await callback.answer(f"✅ Winner Announcement {sent} users ko bhej diya gaya hai!", show_alert=True)

# --- CREATE GIVEAWAY FLOW (ADMIN ONLY) ---
@dp.callback_query(F.data == "admin_create")
async def cb_admin_create(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.set_state(CreateGiveaway.title)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_home")]])
    await callback.message.edit_text(
        "➕ <b>CREATE NEW GIVEAWAY (Step 1/4)</b>\n\nGiveaway ka <b>Title</b> bhejein (e.g., <i>Mega Referral Giveaway</i>):",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(CreateGiveaway.title)
async def step_gw_title(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(title=message.text)
    await state.set_state(CreateGiveaway.prize)
    await message.answer(
        "💎 <b>Step 2/4:</b> Giveaway ka <b>Prize</b> bhejein (e.g., <i>₹500 UPI Cash + Premium Pass</i>):",
        parse_mode="HTML"
    )

@dp.message(CreateGiveaway.prize)
async def step_gw_prize(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(prize=message.text)
    await state.set_state(CreateGiveaway.start_time)
    await message.answer(
        "🟢 <b>Step 3/4:</b> Giveaway ka <b>Start Time & Date</b> bhejein (e.g., <i>30 Oct 2026, 10:00 AM</i>):",
        parse_mode="HTML"
    )

@dp.message(CreateGiveaway.start_time)
async def step_gw_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(start_time=message.text)
    await state.set_state(CreateGiveaway.end_time)
    await message.answer(
        "🔴 <b>Step 4/4:</b> Giveaway ka <b>End Time & Date</b> bhejein (e.g., <i>05 Nov 2026, 10:00 PM</i>):",
        parse_mode="HTML"
    )

@dp.message(CreateGiveaway.end_time)
async def step_gw_end(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE giveaways SET is_active = 0 WHERE is_active = 1")
        await db.execute(
            "INSERT INTO giveaways (title, prize, start_time, end_time, is_active) VALUES (?, ?, ?, ?, 1)",
            (data["title"], data["prize"], data["start_time"], message.text)
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ <b>New Giveaway Successfully Created & Live!</b>", parse_mode="HTML")
    await render_admin_panel(message, is_edit=False)

# --- BROADCAST FLOW (ADMIN ONLY) ---
@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.set_state(BroadcastState.message)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_home")]])
    await callback.message.edit_text(
        "📢 <b>BROADCAST MESSAGE</b>\n\nJo message aap sabhi users ko bhejna chahte hain (Text, Photo, ya Video), wo abhi send karein:",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(BroadcastState.message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()

    sent, failed = 0, 0
    status_msg = await message.answer(f"⏳ <b>Broadcasting to {len(users)} users...</b>", parse_mode="HTML")
    for (uid,) in users:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>BROADCAST COMPLETED!</b>\n\n"
        f"🟢 <b>Delivered:</b> <code>{sent}</code>\n"
        f"🔴 <b>Failed/Blocked:</b> <code>{failed}</code>",
        parse_mode="HTML"
    )
    await render_admin_panel(message, is_edit=False)

# --- MAIN ENTRYPOINT ---
async def main():
    await init_db()
    print("🚀 @Leongiveawaybot is now LIVE and polling...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])

if __name__ == "__main__":
    asyncio.run(main())
