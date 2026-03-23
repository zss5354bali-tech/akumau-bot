import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8604636539:AAGa_fCesF29a5ZEueK52Wuc3iPfkYsKy5U")

# States
CHOOSE_ROLE, CHOOSE_CATEGORY, WRITE_REQUEST, SELLER_REGISTER, SELLER_CATEGORY, SELLER_AREA = range(6)

CATEGORIES = {
    "scooter": "🛵 Аренда скутеров",
    "realty": "🏠 Аренда жилья",
    "farm": "🌿 Продукты / Фермеры"
}

AREAS = {
    "kuta": "Kuta / Legian",
    "seminyak": "Seminyak / Canggu",
    "ubud": "Ubud",
    "sanur": "Sanur",
    "nusa_dua": "Nusa Dua / Jimbaran",
    "other": "Другой район"
}

# In-memory storage (replace with DB later)
sellers = {}      # chat_id -> {name, category, area, active, phone}
requests = {}     # request_id -> {buyer_id, category, text, photo_id, responses}
req_counter = [0]

def main_keyboard(is_seller=False):
    kb = [
        [InlineKeyboardButton("🔍 Найти товар/услугу", callback_data="buyer")],
        [InlineKeyboardButton("🏪 Я продавец / регистрация", callback_data="seller")],
    ]
    if is_seller:
        kb.append([InlineKeyboardButton("📋 Мои входящие заявки", callback_data="my_requests")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_seller = user_id in sellers
    name = update.effective_user.first_name
    
    text = (
        f"🌴 *Добро пожаловать в AkuMau, {name}!*\n\n"
        f"_«Aku Mau» — по-индонезийски «Я хочу»_\n\n"
        f"Платформа для быстрого поиска товаров и услуг на Бали.\n\n"
        f"*Как это работает:*\n"
        f"• Покупатель пишет запрос с фото\n"
        f"• Продавцы видят запрос и отвечают\n"
        f"• Покупатель выбирает лучшее предложение\n\n"
        f"Выбери свою роль 👇"
    )
    
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(is_seller))
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_keyboard(is_seller))

# ── BUYER FLOW ──────────────────────────────────────────────

async def buyer_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = [[InlineKeyboardButton(label, callback_data=f"cat_{key}")] for key, label in CATEGORIES.items()]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    
    await query.edit_message_text(
        "🔍 *Что ищешь?*\n\nВыбери категорию:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CHOOSE_CATEGORY

async def category_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_key = query.data.replace("cat_", "")
    ctx.user_data["category"] = cat_key
    cat_label = CATEGORIES[cat_key]
    
    await query.edit_message_text(
        f"*{cat_label}*\n\n"
        f"Опиши что именно тебе нужно.\n"
        f"Можешь прикрепить фото 📸\n\n"
        f"_Например: «Нужен скутер Honda Beat на 3 дня в районе Canggu»_",
        parse_mode="Markdown"
    )
    return WRITE_REQUEST

async def handle_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cat_key = ctx.user_data.get("category")
    
    text = update.message.text or update.message.caption or ""
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    
    req_counter[0] += 1
    req_id = req_counter[0]
    
    requests[req_id] = {
        "buyer_id": user.id,
        "buyer_name": user.first_name,
        "category": cat_key,
        "text": text,
        "photo_id": photo_id,
        "responses": []
    }
    
    # Notify matching sellers
    notified = 0
    for seller_id, seller in sellers.items():
        if seller.get("category") == cat_key and seller.get("active"):
            try:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Ответить на заявку", callback_data=f"respond_{req_id}")
                ]])
                msg = (
                    f"🔔 *Новая заявка #{req_id}*\n\n"
                    f"📦 Категория: {CATEGORIES[cat_key]}\n"
                    f"📝 Запрос: {text or '_(только фото)_'}\n\n"
                    f"Нажми кнопку чтобы ответить покупателю:"
                )
                if photo_id:
                    await ctx.bot.send_photo(seller_id, photo_id, caption=msg, parse_mode="Markdown", reply_markup=kb)
                else:
                    await ctx.bot.send_message(seller_id, msg, parse_mode="Markdown", reply_markup=kb)
                notified += 1
            except Exception as e:
                logger.error(f"Failed to notify seller {seller_id}: {e}")
    
    await update.message.reply_text(
        f"✅ *Заявка #{req_id} отправлена!*\n\n"
        f"Уведомлено продавцов: *{notified}*\n\n"
        f"Как только продавцы ответят — ты получишь уведомление.\n"
        f"Контакты продавца откроются когда выберешь понравившееся предложение.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")
        ]])
    )
    return ConversationHandler.END

# ── SELLER FLOW ─────────────────────────────────────────────

async def seller_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id in sellers:
        s = sellers[user_id]
        status = "✅ Активен" if s.get("active") else "⏸ Приостановлен"
        await query.edit_message_text(
            f"🏪 *Твой профиль продавца*\n\n"
            f"Категория: {CATEGORIES.get(s['category'], '—')}\n"
            f"Район: {AREAS.get(s['area'], '—')}\n"
            f"Статус: {status}\n\n"
            f"_Бесплатный период: 6 месяцев_ 🎉",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏸ Пауза / ▶️ Возобновить", callback_data="toggle_seller")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
            ])
        )
        return ConversationHandler.END
    
    await query.edit_message_text(
        "🏪 *Регистрация продавца*\n\n"
        "Это бесплатно на первые 6 месяцев!\n\n"
        "Как тебя зовут? Напиши своё имя или название бизнеса:",
        parse_mode="Markdown"
    )
    return SELLER_REGISTER

async def seller_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["seller_name"] = update.message.text
    
    kb = [[InlineKeyboardButton(label, callback_data=f"scat_{key}")] for key, label in CATEGORIES.items()]
    await update.message.reply_text(
        "Отлично! Выбери свою категорию:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return SELLER_CATEGORY

async def seller_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["seller_category"] = query.data.replace("scat_", "")
    
    kb = [[InlineKeyboardButton(label, callback_data=f"area_{key}")] for key, label in AREAS.items()]
    await query.edit_message_text(
        "В каком районе Бали работаешь?",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return SELLER_AREA

async def seller_area(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    area_key = query.data.replace("area_", "")
    
    sellers[user_id] = {
        "name": ctx.user_data.get("seller_name", "—"),
        "category": ctx.user_data.get("seller_category"),
        "area": area_key,
        "active": True,
        "phone": None
    }
    
    await query.edit_message_text(
        f"🎉 *Готово! Ты зарегистрирован как продавец!*\n\n"
        f"Имя: {sellers[user_id]['name']}\n"
        f"Категория: {CATEGORIES[sellers[user_id]['category']]}\n"
        f"Район: {AREAS[area_key]}\n\n"
        f"Теперь ты будешь получать уведомления о новых заявках в своей категории.\n\n"
        f"_Бесплатный период: 6 месяцев_ 🌴",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")
        ]])
    )
    return ConversationHandler.END

async def toggle_seller(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in sellers:
        sellers[user_id]["active"] = not sellers[user_id]["active"]
        status = "✅ Активен" if sellers[user_id]["active"] else "⏸ Приостановлен"
        await query.answer(f"Статус изменён: {status}", show_alert=True)
    await start(update, ctx)

async def respond_to_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.replace("respond_", ""))
    ctx.user_data["responding_to"] = req_id
    
    req = requests.get(req_id)
    if not req:
        await query.answer("Заявка не найдена", show_alert=True)
        return
    
    await query.edit_message_caption(
        caption=query.message.caption + "\n\n✏️ *Напиши своё предложение:*",
        parse_mode="Markdown"
    ) if query.message.caption else await query.edit_message_text(
        query.message.text + "\n\n✏️ *Напиши своё предложение:*",
        parse_mode="Markdown"
    )

async def seller_response(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    req_id = ctx.user_data.get("responding_to")
    if not req_id:
        return
    
    seller_id = update.effective_user.id
    seller = sellers.get(seller_id, {})
    req = requests.get(req_id)
    if not req:
        return
    
    response_text = update.message.text
    req["responses"].append({
        "seller_id": seller_id,
        "seller_name": seller.get("name", "Продавец"),
        "text": response_text
    })
    
    # Notify buyer
    resp_idx = len(req["responses"])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Выбрать этого продавца", callback_data=f"choose_{req_id}_{seller_id}")
    ]])
    
    await ctx.bot.send_message(
        req["buyer_id"],
        f"💬 *Ответ на заявку #{req_id}*\n\n"
        f"От: {seller.get('name', 'Продавец')}\n"
        f"Район: {AREAS.get(seller.get('area', ''), '—')}\n\n"
        f"_{response_text}_\n\n"
        f"Если понравилось — нажми кнопку и получишь контакт продавца:",
        parse_mode="Markdown",
        reply_markup=kb
    )
    
    await update.message.reply_text(
        "✅ Твой ответ отправлен покупателю! Ждём его решения.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")
        ]])
    )
    ctx.user_data.pop("responding_to", None)

async def choose_seller(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    req_id = int(parts[1])
    seller_id = int(parts[2])
    
    seller = sellers.get(seller_id, {})
    
    # Show seller contact to buyer
    await query.edit_message_text(
        f"🎉 *Отличный выбор!*\n\n"
        f"Контакт продавца:\n"
        f"Имя: *{seller.get('name', '—')}*\n"
        f"Район: {AREAS.get(seller.get('area', ''), '—')}\n"
        f"Telegram: @{(await ctx.bot.get_chat(seller_id)).username or 'нет username'}\n\n"
        f"Напиши продавцу напрямую и договаривайтесь! 🤝",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")
        ]])
    )
    
    # Notify seller
    await ctx.bot.send_message(
        seller_id,
        f"🎉 *Покупатель выбрал тебя!*\n\n"
        f"По заявке #{req_id}.\n"
        f"Ожидай сообщения в Telegram. Удачной сделки! 🤝",
        parse_mode="Markdown"
    )

async def back_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    buyer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(buyer_start, pattern="^buyer$")],
        states={
            CHOOSE_CATEGORY: [CallbackQueryHandler(category_chosen, pattern="^cat_")],
            WRITE_REQUEST: [MessageHandler(filters.TEXT | filters.PHOTO, handle_request)],
        },
        fallbacks=[CallbackQueryHandler(back_main, pattern="^back_main$")],
        per_message=False
    )
    
    seller_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(seller_start, pattern="^seller$")],
        states={
            SELLER_REGISTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_name)],
            SELLER_CATEGORY: [CallbackQueryHandler(seller_category, pattern="^scat_")],
            SELLER_AREA: [CallbackQueryHandler(seller_area, pattern="^area_")],
        },
        fallbacks=[CallbackQueryHandler(back_main, pattern="^back_main$")],
        per_message=False
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(CallbackQueryHandler(toggle_seller, pattern="^toggle_seller$"))
    app.add_handler(CallbackQueryHandler(respond_to_request, pattern="^respond_\\d+$"))
    app.add_handler(CallbackQueryHandler(choose_seller, pattern="^choose_\\d+_\\d+$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, seller_response))
    
    print("🤖 AkuMau бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
