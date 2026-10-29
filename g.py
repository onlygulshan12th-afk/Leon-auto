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
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

# ================= CONFIGURATION =================
BOT_TOKEN = "9108247343:AAFHKaVXxvyxziLEY5_MaL6vNM1KVjMCLE4"
ADMIN_ID = 8626080388
BOT_USERNAME = "Leongiveawaybot"
CHANNEL_USERNAME = "@sterniterspro"
CHANNEL_LINK = "https://t.me/sterniterspro"
DB_NAME = "leon_giveaway_v2.db"
# =================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM STATES (ADMIN ONLY) ---
class CreateGW(StatesGroup):
    title = State()
    prize = State()
    points_per_ref = State()
    start_time = State()
    end_time = State()

class EditGW(StatesGroup):
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
                is_member INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                prize TEXT,
                points_per_ref INTEGER DEFAULT 1,
                start_time TEXT,
                end_time TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                giveaway_id INTEGER,
                user_id INTEGER,
                referrer_id INTEGER,
                points INTEGER DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                rewarded INTEGER DEFAULT 0,
                PRIMARY KEY (giveaway_id, user_id)
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

async def safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass

async def get_active_giveaways():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, prize, points_per_ref, start_time, end_time FROM giveaways WHERE is_active = 1 ORDER BY id DESC"
        ) as cursor:
            return await cursor.fetchall()

async def get_giveaway(gw_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, prize, points_per_ref, start_time, end_time, is_active FROM giveaways WHERE id = ?",
            (gw_id,)
        ) as cursor:
            return await cursor.fetchone()

async def ensure_participant(gw_id: int, user_id: int, referrer_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM participants WHERE giveaway_id = ? AND user_id = ?",
            (gw_id, user_id)
        ) as cursor:
            exists = await cursor.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO participants (giveaway_id, user_id, referrer_id, points, referrals_count, rewarded) VALUES (?, ?, ?, 0, 0, 0)",
                (gw_id, user_id, referrer_id)
            )
            await db.commit()

async def get_participant_stats(gw_id: int, user_id: int):
    await ensure_participant(gw_id, user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT p1.points, p1.referrals_count,
            (SELECT COUNT(*) + 1 FROM participants p2 
             JOIN users u ON p2.user_id = u.user_id
             WHERE p2.giveaway_id = p1.giveaway_id AND u.is_member = 1 AND p2.points > p1.points) as rank
            FROM participants p1 WHERE p1.giveaway_id = ? AND p1.user_id = ?
            """,
            (gw_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1], row[2]) if row else (0, 0, 1)

async def process_verified_rewards(user_id: int, full_name: str, username: str):
    """Jab user channel join kar leta hai, to uske aur uske referrer ke points add karta hai."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET is_member = 1, full_name = ?, username = ? WHERE user_id = ?",
            (full_name, username, user_id)
        )
        # Check all active giveaways where this user was referred and not yet rewarded
        async with db.execute(
            """
            SELECT p.giveaway_id, p.referrer_id, g.title, g.points_per_ref
            FROM participants p
            JOIN giveaways g ON p.giveaway_id = g.id
            WHERE p.user_id = ? AND p.rewarded = 0 AND g.is_active = 1
            """,
            (user_id,)
        ) as cursor:
            pending_rows = await cursor.fetchall()

        for gw_id, ref_id, gw_title, pts_per_ref in pending_rows:
            if ref_id:
                await ensure_participant(gw_id, ref_id)
                # Dono user aur dost ko points milenge
                await db.execute(
                    "UPDATE participants SET points = points + ?, rewarded = 1 WHERE giveaway_id = ? AND user_id = ?",
                    (pts_per_ref, gw_id, user_id)
                )
                await db.execute(
                    "UPDATE participants SET points = points + ?, referrals_count = referrals_count + 1 WHERE giveaway_id = ? AND user_id = ?",
                    (pts_per_ref, gw_id, ref_id)
                )
                try:
                    await bot.send_message(
                        ref_id,
                        f"🎉 <b>NEW REFERRAL VERIFIED!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎁 <b>Giveaway:</b> {html.escape(gw_title)}\n"
                        f"👤 <b>Friend:</b> {html.escape(full_name)}\n"
                        f"✨ <b>Bonus Added:</b> <code>+{pts_per_ref} Points</code>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            else:
                await db.execute(
                    "UPDATE participants SET rewarded = 1 WHERE giveaway_id = ? AND user_id = ?",
                    (gw_id, user_id)
                )
        await db.commit()

async def handle_unsubscribed_user(user_id: int):
    """Channel leave karne par user aur uske referrer dono ke points deduct karta hai."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_member, full_name FROM users WHERE user_id = ?", (user_id,)) as c_u:
            u_row = await c_u.fetchone()
        if not u_row or u_row[0] == 0:
            return

        full_name = u_row[1] or str(user_id)
        await db.execute("UPDATE users SET is_member = 0 WHERE user_id = ?", (user_id,))

        async with db.execute(
            """
            SELECT p.giveaway_id, p.referrer_id, g.title, g.points_per_ref
            FROM participants p
            JOIN giveaways g ON p.giveaway_id = g.id
            WHERE p.user_id = ? AND p.rewarded = 1 AND g.is_active = 1
            """,
            (user_id,)
        ) as cursor:
            rewarded_rows = await cursor.fetchall()

        for gw_id, ref_id, gw_title, pts_per_ref in rewarded_rows:
            if ref_id:
                await db.execute(
                    "UPDATE participants SET points = MAX(0, points - ?), rewarded = 0 WHERE giveaway_id = ? AND user_id = ?",
                    (pts_per_ref, gw_id, user_id)
                )
                await db.execute(
                    "UPDATE participants SET points = MAX(0, points - ?), referrals_count = MAX(0, referrals_count - 1) WHERE giveaway_id = ? AND user_id = ?",
                    (pts_per_ref, gw_id, ref_id)
                )
                try:
                    await bot.send_message(
                        ref_id,
                        f"⚠️ <b>REFERRAL LEFT CHANNEL!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎁 <b>Giveaway:</b> {html.escape(gw_title)}\n"
                        f"👤 <b>Friend:</b> {html.escape(full_name)}\n"
                        f"➖ <b>Penalty:</b> Unhone <b>{CHANNEL_USERNAME}</b> leave kar diya, isliye aap dono ke <code>-{pts_per_ref} Points</code> kat gaye hain!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            else:
                await db.execute(
                    "UPDATE participants SET rewarded = 0 WHERE giveaway_id = ? AND user_id = ?",
                    (gw_id, user_id)
                )
        await db.commit()

# ================= UI KEYBOARDS =================
def force_join_kb(target_gw_id: int = 0):
    cb_data = f"verify_join_{target_gw_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Join @sterniterspro Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Joined! Unlock Bot", callback_data=cb_data)]
    ])

def home_giveaways_kb(giveaways, user_id: int):
    buttons = []
    # Har running giveaway ek clean button ke roop me dikhega
    for gw in giveaways:
        gw_id, title, prize, pts_per_ref, _, _ = gw
        btn_text = f"🎁 {title}  •  🏆 {prize}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"opengw_{gw_id}")])

    buttons.append([InlineKeyboardButton(text="🔄 Refresh Running Giveaways", callback_data="home_menu")])
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="🛠 Admin Control Panel", callback_data="admin_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def single_giveaway_kb(gw_id: int, gw_title: str, prize: str, pts_per_ref: int, user_id: int):
    ref_link = f"https://t.me/{BOT_USERNAME}?start=gw{gw_id}_{user_id}"
    share_text = urllib.parse.quote(
        f"🔥 {gw_title} is LIVE on {CHANNEL_USERNAME}!\n"
        f"🏆 Winning Prize: {prize}\n\n"
        f"🎁 Mere link se join karo, hum dono ko +{pts_per_ref} Points milenge:\n{ref_link}"
    )
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={share_text}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Share Referral Link With Friends", url=share_url)],
        [InlineKeyboardButton(text="🏆 Leaderboard", callback_data=f"gwlead_{gw_id}"),
         InlineKeyboardButton(text="🔄 Refresh Stats", callback_data=f"opengw_{gw_id}")],
        [InlineKeyboardButton(text="🔙 Back to All Giveaways", callback_data="home_menu")]
    ])

def gw_leaderboard_kb(gw_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh Leaderboard", callback_data=f"gwlead_{gw_id}")],
        [InlineKeyboardButton(text="🔙 Back to Giveaway Details", callback_data=f"opengw_{gw_id}")]
    ])

# ================= USER SCREENS =================
async def render_home_screen(target, user_id: int, full_name: str, is_edit: bool = True):
    giveaways = await get_active_giveaways()
    gw_count = len(giveaways)

    if gw_count > 0:
        guide_box = (
            f"🔥 <b>RUNNING GIVEAWAYS ({gw_count} ACTIVE)</b>\n"
            f"<i>Neeche diye gaye Giveaway button par click karke uski details, apna Referral Link aur Leaderboard dekhein 👇</i>"
        )
    else:
        guide_box = (
            f"💤 <b>NO RUNNING GIVEAWAY</b>\n"
            f"<i>Filhaal koi giveaway active nahi hai. Naye updates ke liye {CHANNEL_USERNAME} par jude rahein!</i>"
        )

    text = (
        f"✨ <b>WELCOME TO GIVEAWAY HUB</b> ✨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"╭ 👤 <b>User:</b> <b>{html.escape(full_name)}</b>\n"
        f"├ 📢 <b>Channel:</b> {CHANNEL_USERNAME}\n"
        f"╰ ✅ <b>Status:</b> <code>Verified Member</code>\n\n"
        f"<blockquote>{guide_box}</blockquote>"
    )
    kb = home_giveaways_kb(giveaways, user_id)
    if is_edit:
        await safe_edit(target, text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")

async def render_single_giveaway(target, gw_id: int, user_id: int, is_edit: bool = True):
    gw = await get_giveaway(gw_id)
    if not gw or gw[6] == 0:
        text = "❌ <b>Yeh giveaway ab khatam ya बंद ho chuka hai!</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back to Home", callback_data="home_menu")]])
        if is_edit:
            await safe_edit(target, text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    _, title, prize, pts_per_ref, start_t, end_t, _ = gw
    pts, refs, rank = await get_participant_stats(gw_id, user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=gw{gw_id}_{user_id}"

    text = (
        f"🎁 <b>{html.escape(title.upper())}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"╭ 🏆 <b>Winning Prize:</b> <b>{html.escape(prize)}</b>\n"
        f"├ ⭐ <b>Per Referral:</b> <code>+{pts_per_ref} Points</code>\n"
        f"├ 🟢 <b>Start Time:</b> <code>{html.escape(start_t)}</code>\n"
        f"╰ 🔴 <b>End Time:</b> <code>{html.escape(end_t)}</code>\n\n"
        f"<blockquote>📊 <b>YOUR STATS IN THIS GIVEAWAY</b>\n"
        f"╭ 🏅 <b>Your Rank:</b> <code>#{rank}</code>\n"
        f"├ 💎 <b>Your Points:</b> <code>{pts} Points</code>\n"
        f"╰ 👥 <b>Active Referrals:</b> <code>{refs} Friends</code></blockquote>\n\n"
        f"🔗 <b>YOUR GIVEAWAY REFERRAL LINK:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"<i>💡 Tap link to copy! Jab aapka dost is link se bot start karke <b>{CHANNEL_USERNAME}</b> join karega, to aap dono ko <b>+{pts_per_ref} Points</b> milenge.</i>"
    )
    kb = single_giveaway_kb(gw_id, title, prize, pts_per_ref, user_id)
    if is_edit:
        await safe_edit(target, text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= /start & REFERRAL HANDLER =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    full_name = message.from_user.full_name or "User"
    username = message.from_user.username or ""
    args = message.text.split()

    target_gw_id = 0
    referrer_id = None

    # Parse clean giveaway referral link: ?start=gw1_8626080388
    if len(args) > 1 and args[1].startswith("gw"):
        try:
            parts = args[1][2:].split("_")
            parsed_gw = int(parts[0])
            parsed_ref = int(parts[1])
            if parsed_ref != user_id:
                target_gw_id = parsed_gw
                referrer_id = parsed_ref
            else:
                target_gw_id = parsed_gw
        except Exception:
            pass

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            exists = await cursor.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO users (user_id, full_name, username, is_member) VALUES (?, ?, ?, 0)",
                (user_id, full_name, username)
            )
        else:
            await db.execute(
                "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
                (full_name, username, user_id)
            )
        await db.commit()

    if target_gw_id > 0:
        gw = await get_giveaway(target_gw_id)
        if gw and gw[6] == 1:
            await ensure_participant(target_gw_id, user_id, referrer_id)

    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        await message.answer(
            f"🔒 <b>ACCESS LOCKED — JOIN CHANNEL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Bot aur Giveaway me participate karne ke liye aapko humara official channel <b>{CHANNEL_USERNAME}</b> join karna zaroori hai.\n\n"
            f"<blockquote>✨ <b>Instant Bonus:</b> Channel join karke Verify dabayein, aapko aur aapke dost dono ko turant Referral Points mil jayenge!</blockquote>",
            reply_markup=force_join_kb(target_gw_id),
            parse_mode="HTML"
        )
        return

    await process_verified_rewards(user_id, full_name, username)
    if target_gw_id > 0:
        await render_single_giveaway(message, target_gw_id, user_id, is_edit=False)
    else:
        await render_home_screen(message, user_id, full_name, is_edit=False)

# --- VERIFY & NAVIGATION CALLBACKS ---
@dp.callback_query(F.data.startswith("verify_join_"))
async def cb_verify_join(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_gw_id = int(callback.data.split("_")[-1])

    if await check_membership(user_id):
        await process_verified_rewards(user_id, callback.from_user.full_name, callback.from_user.username or "")
        await callback.answer("✅ Verified! Welcome to the Giveaway.", show_alert=True)
        if target_gw_id > 0:
            await render_single_giveaway(callback.message, target_gw_id, user_id, is_edit=True)
        else:
            await render_home_screen(callback.message, user_id, callback.from_user.full_name, is_edit=True)
    else:
        await handle_unsubscribed_user(user_id)
        await callback.answer("❌ Aapne abhi tak @sterniterspro join nahi kiya hai!", show_alert=True)

@dp.callback_query(F.data == "home_menu")
async def cb_home_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        await callback.answer("⚠️ Pehle @sterniterspro join karein!", show_alert=True)
        await safe_edit(
            callback.message,
            f"🚫 <b>CHANNEL UNSUBSCRIBED!</b>\n\nBot use karne ke liye wapas <b>{CHANNEL_USERNAME}</b> join karein:",
            reply_markup=force_join_kb(0)
        )
        return
    await callback.answer()
    await render_home_screen(callback.message, user_id, callback.from_user.full_name, is_edit=True)

@dp.callback_query(F.data.startswith("opengw_"))
async def cb_open_giveaway(callback: CallbackQuery):
    user_id = callback.from_user.id
    gw_id = int(callback.data.split("_")[1])

    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        await callback.answer("⚠️ Aapne channel leave kar diya hai! Points deduct ho gaye hain.", show_alert=True)
        await safe_edit(
            callback.message,
            f"🚫 <b>ACCESS LOCKED!</b>\n\nAapne <b>{CHANNEL_USERNAME}</b> leave kar diya hai. Points wapas paane ke liye channel join karein:",
            reply_markup=force_join_kb(gw_id)
        )
        return

    await callback.answer()
    await render_single_giveaway(callback.message, gw_id, user_id, is_edit=True)

@dp.callback_query(F.data.startswith("gwlead_"))
async def cb_gw_leaderboard(callback: CallbackQuery):
    user_id = callback.from_user.id
    gw_id = int(callback.data.split("_")[1])

    if not await check_membership(user_id):
        await handle_unsubscribed_user(user_id)
        return await callback.answer("⚠️ Pehle @sterniterspro channel join karein!", show_alert=True)

    gw = await get_giveaway(gw_id)
    if not gw:
        return await callback.answer("❌ Giveaway nahi mila!", show_alert=True)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT p.user_id, u.full_name, p.points, p.referrals_count
            FROM participants p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.giveaway_id = ? AND u.is_member = 1 AND p.points > 0
            ORDER BY p.points DESC, p.referrals_count DESC LIMIT 10
            """,
            (gw_id,)
        ) as cursor:
            top_list = await cursor.fetchall()

    pts, refs, rank = await get_participant_stats(gw_id, user_id)

    if not top_list:
        board_str = "<i>Abhi tak kisi user ke points nahi hain. Sabse pehle refer karke #1 Rank par aayein!</i>"
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, (uid, name, u_pts, u_refs) in enumerate(top_list, start=1):
            badge = medals[idx - 1] if idx <= 3 else f"<b>#{idx}</b>"
            clean_name = html.escape((name or "User")[:16])
            you_tag = " <b>(YOU)</b>" if uid == user_id else ""
            lines.append(f"{badge} <b>{clean_name}</b>{you_tag} — <code>{u_pts} Pts</code> <i>({u_refs} Refs)</i>")
        board_str = "\n".join(lines)

    text = (
        f"🏆 <b>GIVEAWAY TOP 10 LEADERBOARD</b>\n"
        f"🎁 <b>{html.escape(gw[1])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{board_str}\n\n"
        f"<blockquote>👤 <b>Your Position:</b> Rank <code>#{rank}</code>  |  💎 <b>{pts} Pts</b> ({refs} Refs)</blockquote>"
    )
    await callback.answer()
    await safe_edit(callback.message, text, reply_markup=gw_leaderboard_kb(gw_id))

# --- REAL-TIME AUTO POINT DEDUCTION ON CHANNEL LEAVE ---
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
                    f"⚠️ <b>CHANNEL UNSUBSCRIBED ALERT!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Aapne <b>{CHANNEL_USERNAME}</b> unsubscribe kar diya hai! Isliye aapke aur aapke dost ke Referral Points kat gaye hain.\n\n"
                    f"👇 <b>Points wapas paane ke liye turant rejoin karein:</b>",
                    reply_markup=force_join_kb(0),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        elif new_status in ["member", "administrator", "creator"]:
            await process_verified_rewards(user.id, user.full_name, user.username or "")

# ==================== ADMIN CONTROL PANEL ====================
async def render_admin_home(target, is_edit: bool = True):
    giveaways = await get_active_giveaways()
    buttons = [
        [InlineKeyboardButton(text="➕ Create New Giveaway", callback_data="admin_create")]
    ]
    # Har running giveaway admin panel me manage karne ke liye dikhega
    for gw in giveaways:
        gw_id, title, prize, pts_ref, _, _ = gw
        buttons.append([
            InlineKeyboardButton(
                text=f"⚙️ Manage: {title} (+{pts_ref} Pts/Ref)",
                callback_data=f"admin_manage_{gw_id}"
            )
        ])

    buttons.extend([
        [InlineKeyboardButton(text="📊 Live Bot Stats", callback_data="admin_stats"),
         InlineKeyboardButton(text="📢 Broadcast Message", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Back to User View", callback_data="home_menu")]
    ])

    text = (
        f"🛠 <b>ADMIN CONTROL PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>Active Giveaways:</b> <code>{len(giveaways)} Running</code>\n\n"
        f"<blockquote>💡 <b>Admin Guide:</b>\n"
        f"• Naya giveaway banane ke liye <b>➕ Create New Giveaway</b> dabayein.\n"
        f"• Kisi running giveaway ka <b>Time, Prize, Referral Point</b> badalne ya <b>Winner/Delete</b> karne ke liye neeche us giveaway par click karein:</blockquote>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_edit:
        await safe_edit(target, text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await render_admin_home(message, is_edit=False)

@dp.callback_query(F.data == "admin_home")
async def cb_admin_home(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.clear()
    await callback.answer()
    await render_admin_home(callback.message, is_edit=True)

# --- MANAGE SPECIFIC RUNNING GIVEAWAY (EDIT / WINNER / DELETE) ---
async def render_admin_manage_gw(target, gw_id: int, is_edit: bool = True):
    gw = await get_giveaway(gw_id)
    if not gw or gw[6] == 0:
        return await render_admin_home(target, is_edit=is_edit)

    _, title, prize, pts_per_ref, start_t, end_t, _ = gw
    text = (
        f"⚙️ <b>MANAGE RUNNING GIVEAWAY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"╭ 🏷 <b>Title:</b> <b>{html.escape(title)}</b>\n"
        f"├ 🏆 <b>Prize:</b> <b>{html.escape(prize)}</b>\n"
        f"├ ⭐ <b>Referral Point:</b> <code>+{pts_per_ref} Points / Invite</code>\n"
        f"├ 🟢 <b>Start Time:</b> <code>{html.escape(start_t)}</code>\n"
        f"╰ 🔴 <b>End Time:</b> <code>{html.escape(end_t)}</code>\n\n"
        f"👇 <b>Is giveaway me kya edit ya action lena hai?</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Edit Referral Points", callback_data=f"editgw_{gw_id}_points_per_ref"),
         InlineKeyboardButton(text="🔴 Edit End Time", callback_data=f"editgw_{gw_id}_end_time")],
        [InlineKeyboardButton(text="🟢 Edit Start Time", callback_data=f"editgw_{gw_id}_start_time"),
         InlineKeyboardButton(text="🏆 Edit Prize", callback_data=f"editgw_{gw_id}_prize")],
        [InlineKeyboardButton(text="🏷 Edit Title", callback_data=f"editgw_{gw_id}_title"),
         InlineKeyboardButton(text="🔄 Reset Points (This GW)", callback_data=f"resetgw_{gw_id}")],
        [InlineKeyboardButton(text="👑 Check & Announce Winner", callback_data=f"wingw_{gw_id}")],
        [InlineKeyboardButton(text="🗑 Delete This Giveaway", callback_data=f"delgw_{gw_id}")],
        [InlineKeyboardButton(text="🔙 Back to Admin Panel", callback_data="admin_home")]
    ])
    if is_edit:
        await safe_edit(target, text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("admin_manage_"))
async def cb_admin_manage_gw(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.clear()
    gw_id = int(callback.data.split("_")[-1])
    await callback.answer()
    await render_admin_manage_gw(callback.message, gw_id, is_edit=True)

# --- EDIT GIVEAWAY FIELDS (INCLUDING REFERRAL POINTS) ---
@dp.callback_query(F.data.startswith("editgw_"))
async def cb_edit_gw_field(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)

    parts = callback.data.split("_", 2)
    gw_id = int(parts[1])
    field = parts[2]

    labels = {
        "points_per_ref": "⭐ <b>Naya Referral Point</b> enter karein (Sirf Number likhein, jaise: <code>1</code>, <code>2</code>, <code>5</code>, <code>10</code>):",
        "end_time": "🔴 <b>Naya End Time & Date</b> bhejein (e.g., <code>10 Nov 2026, 10:00 PM</code>):",
        "start_time": "🟢 <b>Naya Start Time & Date</b> bhejein (e.g., <code>30 Oct 2026, 10:00 AM</code>):",
        "prize": "🏆 <b>Naya Winning Prize</b> bhejein (e.g., <code>₹500 UPI Cash</code>):",
        "title": "🏷 <b>Naya Giveaway Title</b> bhejein (e.g., <code>Mega Special Giveaway</code>):"
    }

    await state.update_data(gw_id=gw_id, field=field)
    await state.set_state(EditGW.new_value)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Edit", callback_data=f"admin_manage_{gw_id}")]
    ])
    await callback.answer()
    await safe_edit(
        callback.message,
        f"✏️ <b>EDIT GIVEAWAY SETTING</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{labels.get(field, 'Nayi value bhejein:')}",
        reply_markup=kb
    )

@dp.message(EditGW.new_value)
async def step_save_edit_gw(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    gw_id = data["gw_id"]
    field = data["field"]
    val = message.text.strip()

    if field == "points_per_ref":
        if not val.isdigit() or int(val) <= 0:
            return await message.answer("❌ <b>Invalid Number!</b> Kripya 1 ya usse bada number bhejein (e.g., <code>2</code>, <code>5</code>):", parse_mode="HTML")
        val = int(val)

    allowed = {"title": "title", "prize": "prize", "points_per_ref": "points_per_ref", "start_time": "start_time", "end_time": "end_time"}
    col = allowed.get(field)
    if col:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(f"UPDATE giveaways SET {col} = ? WHERE id = ?", (val, gw_id))
            await db.commit()

    await state.clear()
    await message.answer(f"✅ <b>Updated Successfully!</b>", parse_mode="HTML")
    await render_admin_manage_gw(message, gw_id, is_edit=False)

# --- DELETE, RESET, & WINNER FOR SPECIFIC GIVEAWAY ---
@dp.callback_query(F.data.startswith("delgw_"))
async def cb_delete_gw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    gw_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE giveaways SET is_active = 0 WHERE id = ?", (gw_id,))
        await db.commit()
    await callback.answer("🗑 Giveaway Deleted Successfully!", show_alert=True)
    await render_admin_home(callback.message, is_edit=True)

@dp.callback_query(F.data.startswith("resetgw_"))
async def cb_reset_gw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    gw_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE participants SET points = 0, referrals_count = 0, rewarded = 0 WHERE giveaway_id = ?", (gw_id,))
        await db.commit()
    await callback.answer("🔄 Is giveaway ke sabhi points 0 par reset ho gaye hain!", show_alert=True)
    await render_admin_manage_gw(callback.message, gw_id, is_edit=True)

@dp.callback_query(F.data.startswith("wingw_"))
async def cb_winner_gw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    gw_id = int(callback.data.split("_")[1])
    gw = await get_giveaway(gw_id)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT p.user_id, u.full_name, u.username, p.points, p.referrals_count
            FROM participants p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.giveaway_id = ? AND u.is_member = 1 AND p.points > 0
            ORDER BY p.points DESC, p.referrals_count DESC LIMIT 1
            """,
            (gw_id,)
        ) as cursor:
            winner = await cursor.fetchone()

    if not winner:
        return await callback.answer("❌ Is giveaway me abhi tak koi valid winner nahi hai!", show_alert=True)

    uid, name, uname, pts, refs = winner
    uname_str = f"@{uname}" if uname else f"<code>{uid}</code>"

    text = (
        f"👑 <b>#1 RANK WINNER DETAILS</b> 👑\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 <b>Giveaway:</b> <b>{html.escape(gw[1])}</b>\n"
        f"🏆 <b>Prize:</b> <b>{html.escape(gw[2])}</b>\n\n"
        f"╭ 🥇 <b>Winner:</b> <b>{html.escape(name)}</b>\n"
        f"├ 🆔 <b>User:</b> {uname_str} (<code>{uid}</code>)\n"
        f"├ 💎 <b>Total Points:</b> <code>{pts} Points</code>\n"
        f"╰ 👥 <b>Total Referrals:</b> <code>{refs} Friends</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Broadcast Winner to All Users", callback_data=f"annwin_{gw_id}")],
        [InlineKeyboardButton(text="🔙 Back to Manage Giveaway", callback_data=f"admin_manage_{gw_id}")]
    ])
    await callback.answer()
    await safe_edit(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data.startswith("annwin_"))
async def cb_announce_winner(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    gw_id = int(callback.data.split("_")[1])
    gw = await get_giveaway(gw_id)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT p.user_id, u.full_name, p.points, p.referrals_count
            FROM participants p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.giveaway_id = ? AND u.is_member = 1 AND p.points > 0
            ORDER BY p.points DESC, p.referrals_count DESC LIMIT 1
            """,
            (gw_id,)
        ) as cursor:
            winner = await cursor.fetchone()
        async with db.execute("SELECT user_id FROM users") as c_all:
            all_users = await c_all.fetchall()

    if not winner:
        return await callback.answer("❌ Winner nahi mila!", show_alert=True)

    uid, name, pts, refs = winner
    msg_text = (
        f"🎊 <b>OFFICIAL GIVEAWAY WINNER!</b> 🎊\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 <b>Giveaway:</b> <b>{html.escape(gw[1])}</b>\n"
        f"🏆 <b>Prize:</b> <b>{html.escape(gw[2])}</b>\n\n"
        f"👑 <b>Winner:</b> <b>{html.escape(name)}</b>\n"
        f"💎 <b>Score:</b> <code>{pts} Points ({refs} Referrals)</code>\n\n"
        f"🔥 Congratulations! Agle giveaway me participate karne ke liye bot start karein!"
    )
    sent = 0
    for (u_id,) in all_users:
        try:
            await bot.send_message(u_id, msg_text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await callback.answer(f"✅ Winner Announcement {sent} users ko bhej diya gaya hai!", show_alert=True)

# --- CREATE NEW GIVEAWAY FLOW (WITH CUSTOM REFERRAL POINTS) ---
@dp.callback_query(F.data == "admin_create")
async def cb_admin_create(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.set_state(CreateGW.title)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_home")]])
    await callback.answer()
    await safe_edit(
        callback.message,
        "➕ <b>CREATE NEW GIVEAWAY (Step 1/5)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏷 Giveaway ka <b>Title (Naam)</b> bhejein:\n"
        "<i>(Example: Netflix 4K Giveaway)</i>",
        reply_markup=kb
    )

@dp.message(CreateGW.title)
async def step_gw_title(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(CreateGW.prize)
    await message.answer(
        "🏆 <b>Step 2/5: Winning Prize</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Giveaway ka <b>Prize</b> bhejein:\n"
        "<i>(Example: ₹500 UPI Cash / 1 Month Premium)</i>",
        parse_mode="HTML"
    )

@dp.message(CreateGW.prize)
async def step_gw_prize(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(prize=message.text.strip())
    await state.set_state(CreateGW.points_per_ref)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Point", callback_data="setpts_1"),
         InlineKeyboardButton(text="⭐ 2 Points", callback_data="setpts_2")],
        [InlineKeyboardButton(text="⭐ 5 Points", callback_data="setpts_5"),
         InlineKeyboardButton(text="⭐ 10 Points", callback_data="setpts_10")]
    ])
    await message.answer(
        "⭐ <b>Step 3/5: Set Referral Points</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1 Friend ko refer karne par <b>kitne Points</b> milne chahiye?\n\n"
        "👇 <i>Neeche button select karein ya koi bhi number (jaise 3, 15, 50) type karke bhejein:</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(CreateGW.points_per_ref, F.data.startswith("setpts_"))
async def cb_set_ref_pts(callback: CallbackQuery, state: FSMContext):
    pts = int(callback.data.split("_")[1])
    await state.update_data(points_per_ref=pts)
    await state.set_state(CreateGW.start_time)
    await callback.answer(f"✅ +{pts} Points Per Referral Set!")
    await safe_edit(
        callback.message,
        f"🟢 <b>Step 4/5: Start Time & Date</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <b>Selected Referral Points:</b> <code>+{pts} Points</code>\n\n"
        f"Ab Giveaway ka <b>Start Time</b> bhejein:\n"
        f"<i>(Example: 30 Oct 2026, 10:00 AM)</i>"
    )

@dp.message(CreateGW.points_per_ref)
async def step_gw_pts_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        return await message.answer("❌ <b>Sirf number bhejein!</b> (Jaise: <code>1</code>, <code>2</code>, <code>5</code>):", parse_mode="HTML")
    pts = int(message.text.strip())
    await state.update_data(points_per_ref=pts)
    await state.set_state(CreateGW.start_time)
    await message.answer(
        f"🟢 <b>Step 4/5: Start Time & Date</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <b>Selected Referral Points:</b> <code>+{pts} Points</code>\n\n"
        f"Ab Giveaway ka <b>Start Time</b> bhejein:\n"
        f"<i>(Example: 30 Oct 2026, 10:00 AM)</i>",
        parse_mode="HTML"
    )

@dp.message(CreateGW.start_time)
async def step_gw_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(start_time=message.text.strip())
    await state.set_state(CreateGW.end_time)
    await message.answer(
        "🔴 <b>Step 5/5: End Time & Date</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Giveaway kab khatam hoga? <b>End Time</b> bhejein:\n"
        "<i>(Example: 05 Nov 2026, 10:00 PM)</i>",
        parse_mode="HTML"
    )

@dp.message(CreateGW.end_time)
async def step_gw_end(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO giveaways (title, prize, points_per_ref, start_time, end_time, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (data["title"], data["prize"], data["points_per_ref"], data["start_time"], message.text.strip())
        )
        await db.commit()
    await state.clear()
    await message.answer("🎉 <b>New Giveaway Created & Added to Home Screen Buttons!</b>", parse_mode="HTML")
    await render_admin_home(message, is_edit=False)

# --- BOT STATS & BROADCAST ---
@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1:
            total_u = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_member = 1") as c2:
            active_u = (await c2.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM giveaways WHERE is_active = 1") as c3:
            active_gw = (await c3.fetchone())[0]

    await callback.answer(
        f"📊 LIVE BOT STATISTICS\n\n"
        f"👥 Total Users: {total_u}\n"
        f"✅ Verified Members: {active_u}\n"
        f"🎁 Active Giveaways: {active_gw}",
        show_alert=True
    )

@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌ Access Denied!", show_alert=True)
    await state.set_state(BroadcastState.message)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_home")]])
    await callback.answer()
    await safe_edit(
        callback.message,
        "📢 <b>BROADCAST MESSAGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Jo message, photo, ya video sabhi users ko bhejna hai wo abhi send karein:",
        reply_markup=kb
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
    status_msg = await message.answer(f"⏳ <b>Sending to {len(users)} users...</b>", parse_mode="HTML")
    for (uid,) in users:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>BROADCAST COMPLETED!</b>\n"
        f"🟢 <b>Sent:</b> <code>{sent}</code>  |  🔴 <b>Failed:</b> <code>{failed}</code>",
        parse_mode="HTML"
    )
    await render_admin_home(message, is_edit=False)

# --- MAIN ENTRYPOINT ---
async def main():
    await init_db()
    print("🚀 @Leongiveawaybot V2 is LIVE and polling...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])

if __name__ == "__main__":
    asyncio.run(main())
