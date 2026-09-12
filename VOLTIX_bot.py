import asyncio
import html
import logging
import sqlite3
from datetime import datetime
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = "ВСТАВЬ_СЮДА_НОВЫЙ_ТОКЕН"

ADMIN_IDS = [
    8617256826,
    5300942141,
]

# Username менеджера БЕЗ @
MANAGER_USERNAME = "reivoxi"

SHOP_NAME = "VOLTIX"

DB_NAME = "shop.db"


# =========================================================
# ТОВАРЫ
# =========================================================

PRODUCTS = {
    "battery": {
        "name": "🔋 MagSafe Battery Pack 5000 mAh",
        "price": 899,
        "stock": 15,
        "description": (
            "Компактный внешний аккумулятор для повседневного использования.\n\n"
            "🔋 Ёмкость: 5000 mAh\n"
            "🧲 Магнитное крепление\n"
            "📱 Для совместимых устройств"
        ),
    },

    "cardholder": {
        "name": "💳 MagSafe Cardholder",
        "price": 449,
        "stock": 10,
        "description": (
            "Компактный магнитный кардхолдер для повседневного использования.\n\n"
            "💳 Для карт\n"
            "🧲 Магнитное крепление\n"
            "🎒 Удобный компактный формат"
        ),
    },

    "charger": {
        "name": "🔌 Зарядный блок 20W",
        "price": 499,
        "stock": 10,
        "description": (
            "Компактный зарядный блок для совместимых устройств.\n\n"
            "⚡ Мощность: 20W\n"
            "🔌 USB-C\n"
            "🎒 Удобный формат"
        ),
    },

    "case": {
        "name": "📱 Чехлы iPhone 14–17",
        "price": 399,
        "stock": 30,
        "description": (
            "Защитный чехол для iPhone с аккуратной посадкой.\n\n"
            "🛡 Защита корпуса\n"
            "✨ Аккуратный дизайн\n"
            "🎨 По поводу цвета — уточняйте у менеджера.\n"
            "Подскажем доступные варианты перед оформлением заказа."
        ),
    },
}


CASE_MODELS = [
    "iPhone 14",
    "iPhone 14 Pro",
    "iPhone 14 Pro Max",
    "iPhone 15",
    "iPhone 15 Pro",
    "iPhone 15 Pro Max",
    "iPhone 16",
    "iPhone 16 Pro",
    "iPhone 16 Pro Max",
    "iPhone 17",
    "iPhone 17 Pro",
    "iPhone 17 Pro Max",
]


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_NAME)
db.row_factory = sqlite3.Row


def init_db():
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            product_id TEXT,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id TEXT,
            variant TEXT,
            quantity INTEGER
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            total INTEGER,
            status TEXT,
            created_at TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            product_id TEXT,
            product_name TEXT,
            variant TEXT,
            quantity INTEGER,
            price INTEGER
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            category TEXT,
            message TEXT,
            created_at TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            rating INTEGER,
            text TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    # Реальные остатки товаров.
    db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            product_id TEXT PRIMARY KEY,
            stock INTEGER NOT NULL,
            initial_stock INTEGER NOT NULL
        )
    """)

    # Позволяет старой базе работать с новой логикой остатков.
    try:
        db.execute("ALTER TABLE orders ADD COLUMN stock_applied INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    for product_id, product in PRODUCTS.items():
        db.execute("""
            INSERT OR IGNORE INTO inventory
            (product_id, stock, initial_stock)
            VALUES (?, ?, ?)
        """, (
            product_id,
            product["stock"],
            product["stock"],
        ))

    db.commit()


# =========================================================
# ОБЩИЕ ФУНКЦИИ
# =========================================================

def money(value):
    return f"{value:,}".replace(",", " ") + " ₽"


def is_admin(user_id):
    return user_id in ADMIN_IDS


def register_user(user):
    db.execute("""
        INSERT INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
    ))
    db.commit()


def get_product(product_id):
    return PRODUCTS[product_id]


def get_stock(product_id):
    row = db.execute("""
        SELECT stock
        FROM inventory
        WHERE product_id = ?
    """, (product_id,)).fetchone()
    if row is None:
        return PRODUCTS[product_id]["stock"]
    return row["stock"]


def set_stock(product_id, stock):
    stock = max(0, int(stock))
    db.execute("""
        UPDATE inventory
        SET stock = ?
        WHERE product_id = ?
    """, (stock, product_id))
    db.commit()


def change_stock(product_id, delta):
    current = get_stock(product_id)
    new_stock = max(0, current + int(delta))
    set_stock(product_id, new_stock)
    return new_stock


def get_cart(user_id):
    return db.execute("""
        SELECT *
        FROM cart
        WHERE user_id = ?
        ORDER BY id
    """, (user_id,)).fetchall()


def get_cart_item(user_id, item_id):
    return db.execute("""
        SELECT *
        FROM cart
        WHERE user_id = ?
        AND id = ?
    """, (user_id, item_id)).fetchone()


def cart_total(user_id):
    total = 0

    for item in get_cart(user_id):
        p = get_product(item["product_id"])
        total += p["price"] * item["quantity"]

    return total


def cart_product_quantity(user_id, product_id):
    row = db.execute("""
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM cart
        WHERE user_id = ?
        AND product_id = ?
    """, (
        user_id,
        product_id,
    )).fetchone()

    return row["total"]


def is_favorite(user_id, product_id):
    row = db.execute("""
        SELECT 1
        FROM favorites
        WHERE user_id = ?
        AND product_id = ?
    """, (
        user_id,
        product_id,
    )).fetchone()

    return row is not None


def toggle_favorite(user_id, product_id):
    if is_favorite(user_id, product_id):
        db.execute("""
            DELETE FROM favorites
            WHERE user_id = ?
            AND product_id = ?
        """, (
            user_id,
            product_id,
        ))
        db.commit()
        return False

    db.execute("""
        INSERT OR IGNORE INTO favorites
        (user_id, product_id)
        VALUES (?, ?)
    """, (
        user_id,
        product_id,
    ))
    db.commit()
    return True


def add_to_cart(user_id, product_id, quantity, variant=""):
    current = cart_product_quantity(
        user_id,
        product_id
    )

    stock = get_stock(product_id)

    if current + quantity > stock:
        return False

    existing = db.execute("""
        SELECT *
        FROM cart
        WHERE user_id = ?
        AND product_id = ?
        AND variant = ?
    """, (
        user_id,
        product_id,
        variant,
    )).fetchone()

    if existing:
        db.execute("""
            UPDATE cart
            SET quantity = quantity + ?
            WHERE id = ?
        """, (
            quantity,
            existing["id"],
        ))
    else:
        db.execute("""
            INSERT INTO cart
            (user_id, product_id, variant, quantity)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            product_id,
            variant,
            quantity,
        ))

    db.commit()
    return True


def clear_cart(user_id):
    db.execute("""
        DELETE FROM cart
        WHERE user_id = ?
    """, (user_id,))
    db.commit()


# =========================================================
# ЗАКАЗЫ
# =========================================================

def create_order(user):
    items = get_cart(user.id)

    if not items:
        return None

    quantities = {}
    for item in items:
        pid = item["product_id"]
        quantities[pid] = quantities.get(pid, 0) + item["quantity"]

    for pid, quantity in quantities.items():
        if quantity > get_stock(pid):
            return "NO_STOCK"

    total = cart_total(user.id)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    cursor = db.cursor()

    try:
        db.execute("BEGIN")

        # Списываем реальные остатки в момент подтверждения заказа.
        for pid, quantity in quantities.items():
            db.execute("""
                UPDATE inventory
                SET stock = stock - ?
                WHERE product_id = ? AND stock >= ?
            """, (quantity, pid, quantity))
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                db.rollback()
                return "NO_STOCK"

        cursor.execute("""
            INSERT INTO orders
            (user_id, username, first_name,
             total, status, created_at, stock_applied)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            total,
            "Новый",
            now,
        ))

        order_id = cursor.lastrowid

        for item in items:
            p = get_product(item["product_id"])
            cursor.execute("""
                INSERT INTO order_items
                (order_id, product_id, product_name,
                 variant, quantity, price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                order_id,
                item["product_id"],
                p["name"],
                item["variant"],
                item["quantity"],
                p["price"],
            ))

        db.commit()
        clear_cart(user.id)
        return order_id

    except Exception:
        db.rollback()
        logging.exception("Ошибка создания заказа")
        return "ERROR"


def get_order(order_id):
    return db.execute("""
        SELECT *
        FROM orders
        WHERE id = ?
    """, (order_id,)).fetchone()


def get_order_items(order_id):
    return db.execute("""
        SELECT *
        FROM order_items
        WHERE order_id = ?
        ORDER BY id
    """, (order_id,)).fetchall()


def get_user_orders(user_id):
    return db.execute("""
        SELECT *
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,)).fetchall()


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def main_menu(user_id=None):
    keyboard = [
        [
            KeyboardButton(text="🛍 Каталог"),
            KeyboardButton(text="🛒 Корзина"),
        ],
        [
            KeyboardButton(text="📦 Мои заказы"),
            KeyboardButton(text="⭐ Избранное"),
        ],
        [
            KeyboardButton(text="⭐ Отзывы"),
            KeyboardButton(text="💬 Поддержка"),
        ],
    ]

    if user_id is not None and is_admin(user_id):
        keyboard.append([
            KeyboardButton(text="👑 Админ-панель")
        ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )


def catalog_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔋 Battery Pack — 899 ₽",
                    callback_data="product:battery"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Cardholder — 449 ₽",
                    callback_data="product:cardholder"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔌 Зарядный блок — 499 ₽",
                    callback_data="product:charger"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📱 Чехлы — 399 ₽",
                    callback_data="product:case"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Избранное",
                    callback_data="favorites"
                )
            ],
        ]
    )


def product_keyboard(user_id, product_id, quantity):
    favorite = is_favorite(
        user_id,
        product_id
    )

    favorite_text = (
        "💛 В избранном"
        if favorite
        else "⭐ Добавить в избранное"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➖",
                    callback_data=f"minus:{product_id}:{quantity}"
                ),
                InlineKeyboardButton(
                    text=str(quantity),
                    callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="➕",
                    callback_data=f"plus:{product_id}:{quantity}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=favorite_text,
                    callback_data=f"fav:{product_id}:{quantity}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛒 Добавить в корзину",
                    callback_data=f"add:{product_id}:{quantity}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="catalog"
                )
            ],
        ]
    )


def case_models_keyboard():
    buttons = []

    for i, model in enumerate(CASE_MODELS):
        buttons.append([
            InlineKeyboardButton(
                text=model,
                callback_data=f"case:{i}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="catalog"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def case_keyboard(index, quantity):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➖",
                    callback_data=f"cminus:{index}:{quantity}"
                ),
                InlineKeyboardButton(
                    text=str(quantity),
                    callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="➕",
                    callback_data=f"cplus:{index}:{quantity}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⭐ В избранное",
                    callback_data=f"cfav:{index}:{quantity}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛒 Добавить в корзину",
                    callback_data=f"cadd:{index}:{quantity}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Другая модель",
                    callback_data="product:case"
                )
            ],
        ]
    )


def cart_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data="cart_edit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Оформить заказ",
                    callback_data="checkout"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Очистить корзину",
                    callback_data="cart_clear"
                )
            ],
        ]
    )


# =========================================================
# FSM
# =========================================================

class SupportState(StatesGroup):
    waiting_message = State()


class ReviewState(StatesGroup):
    waiting_rating = State()
    waiting_text = State()


# =========================================================
# BOT
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    register_user(message.from_user)

    await message.answer(
        f"⚡ <b>Добро пожаловать в {SHOP_NAME}!</b>\n\n"
        "Здесь ты можешь выбрать нужные товары,\n"
        "добавить их в корзину и оформить заказ.\n\n"
        "👇 Выбирай, что тебе нужно:",
        reply_markup=main_menu(message.from_user.id)
    )


@dp.message(Command("id"))
async def user_id(message: Message):
    await message.answer(
        "🆔 Твой Telegram ID:\n\n"
        f"<code>{message.from_user.id}</code>"
    )


# =========================================================
# КАТАЛОГ
# =========================================================

@dp.message(F.text == "🛍 Каталог")
async def catalog_message(message: Message):
    register_user(message.from_user)

    await message.answer(
        "🛍 <b>КАТАЛОГ</b>\n\n"
        "⚡ Аксессуары для твоих устройств\n"
        "📦 Все товары в наличии\n\n"
        "👇 Выбери нужный товар:",
        reply_markup=catalog_keyboard()
    )


@dp.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍 <b>КАТАЛОГ</b>\n\n"
        "⚡ Аксессуары для твоих устройств\n"
        "📦 Все товары в наличии\n\n"
        "👇 Выбери нужный товар:",
        reply_markup=catalog_keyboard()
    )
    await callback.answer()


# =========================================================
# ТОВАР
# =========================================================

async def show_product(callback, product_id, quantity=1):
    p = get_product(product_id)

    total = p["price"] * quantity

    await callback.message.edit_text(
        f"<b>{p['name']}</b>\n\n"
        f"{p['description']}\n\n"
        f"📦 В наличии: <b>{get_stock(product_id)} шт.</b>\n"
        f"💰 Цена: <b>{money(p['price'])}</b>\n\n"
        f"Количество:\n\n"
        f"💰 Итого: <b>{money(total)}</b>",
        reply_markup=product_keyboard(
            callback.from_user.id,
            product_id,
            quantity
        )
    )


@dp.callback_query(F.data.startswith("product:"))
async def product_callback(callback: CallbackQuery):
    product_id = callback.data.split(":")[1]

    if product_id == "case":
        await callback.message.edit_text(
            "📱 <b>Чехлы iPhone 14–17</b>\n\n"
            "🛡 Защитный чехол с аккуратной посадкой.\n"
            "🎨 По поводу цвета — уточняйте у менеджера.\n"
            "Подскажем доступные варианты перед оформлением заказа.\n\n"
            "Выбери модель:",
            reply_markup=case_models_keyboard()
        )
        await callback.answer()
        return

    await show_product(
        callback,
        product_id
    )

    await callback.answer()


# =========================================================
# +/- ТОВАРОВ
# =========================================================

@dp.callback_query(F.data.startswith("plus:"))
async def plus(callback: CallbackQuery):
    _, product_id, quantity = callback.data.split(":")
    quantity = int(quantity)

    p = get_product(product_id)

    if quantity >= get_stock(product_id):
        await callback.answer(
            "Больше товара нет.",
            show_alert=True
        )
        return

    await show_product(
        callback,
        product_id,
        quantity + 1
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("minus:"))
async def minus(callback: CallbackQuery):
    _, product_id, quantity = callback.data.split(":")
    quantity = int(quantity)

    if quantity <= 1:
        await callback.answer(
            "Минимальное количество — 1."
        )
        return

    await show_product(
        callback,
        product_id,
        quantity - 1
    )

    await callback.answer()


# =========================================================
# ЧЕХЛИ
# =========================================================

@dp.callback_query(F.data.startswith("case:"))
async def case_select(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])

    model = CASE_MODELS[index]
    p = get_product("case")

    await callback.message.edit_text(
        f"📱 <b>Чехол для {model}</b>\n\n"
        f"{p['description']}\n\n"
        f"📦 В наличии: <b>{get_stock('case')} шт.</b>\n"
        f"💰 Цена: <b>{money(p['price'])}</b>\n\n"
        f"Количество:\n\n"
        f"💰 Итого: <b>{money(p['price'])}</b>",
        reply_markup=case_keyboard(
            index,
            1
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("cplus:"))
async def case_plus(callback: CallbackQuery):
    _, index, quantity = callback.data.split(":")

    index = int(index)
    quantity = int(quantity)

    p = get_product("case")

    if quantity >= get_stock("case"):
        await callback.answer(
            "Больше товара нет."
        )
        return

    quantity += 1
    model = CASE_MODELS[index]

    await callback.message.edit_text(
        f"📱 <b>Чехол для {model}</b>\n\n"
        f"{p['description']}\n\n"
        f"📦 В наличии: <b>{get_stock('case')} шт.</b>\n"
        f"💰 Цена: <b>{money(p['price'])}</b>\n\n"
        f"Количество:\n\n"
        f"💰 Итого: <b>{money(p['price'] * quantity)}</b>",
        reply_markup=case_keyboard(
            index,
            quantity
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("cminus:"))
async def case_minus(callback: CallbackQuery):
    _, index, quantity = callback.data.split(":")

    index = int(index)
    quantity = int(quantity)

    if quantity <= 1:
        await callback.answer(
            "Минимальное количество — 1."
        )
        return

    quantity -= 1

    model = CASE_MODELS[index]
    p = get_product("case")

    await callback.message.edit_text(
        f"📱 <b>Чехол для {model}</b>\n\n"
        f"{p['description']}\n\n"
        f"📦 В наличии: <b>{get_stock('case')} шт.</b>\n"
        f"💰 Цена: <b>{money(p['price'])}</b>\n\n"
        f"Количество:\n\n"
        f"💰 Итого: <b>{money(p['price'] * quantity)}</b>",
        reply_markup=case_keyboard(
            index,
            quantity
        )
    )

    await callback.answer()


# =========================================================
# ИЗБРАННОЕ
# =========================================================

@dp.callback_query(F.data.startswith("fav:"))
async def favorite(callback: CallbackQuery):
    _, product_id, quantity = callback.data.split(":")
    quantity = int(quantity)

    added = toggle_favorite(
        callback.from_user.id,
        product_id
    )

    await callback.answer(
        "⭐ Добавлено в избранное!"
        if added
        else "Убрано из избранного."
    )

    await show_product(
        callback,
        product_id,
        quantity
    )


@dp.callback_query(F.data.startswith("cfav:"))
async def case_favorite(callback: CallbackQuery):
    _, index, quantity = callback.data.split(":")

    index = int(index)
    quantity = int(quantity)

    added = toggle_favorite(
        callback.from_user.id,
        "case"
    )

    await callback.answer(
        "⭐ Чехлы добавлены в избранное!"
        if added
        else "Чехлы убраны из избранного."
    )

    model = CASE_MODELS[index]
    p = get_product("case")

    await callback.message.edit_text(
        f"📱 <b>Чехол для {model}</b>\n\n"
        f"{p['description']}\n\n"
        f"💰 Цена: <b>{money(p['price'])}</b>\n\n"
        f"Количество:\n\n"
        f"💰 Итого: <b>{money(p['price'] * quantity)}</b>",
        reply_markup=case_keyboard(
            index,
            quantity
        )
    )


@dp.message(F.text == "⭐ Избранное")
async def favorites_message(message: Message):
    rows = db.execute("""
        SELECT product_id
        FROM favorites
        WHERE user_id = ?
    """, (message.from_user.id,)).fetchall()

    if not rows:
        await message.answer(
            "⭐ <b>ИЗБРАННОЕ</b>\n\n"
            "Здесь пока ничего нет.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛍 В каталог",
                            callback_data="catalog"
                        )
                    ]
                ]
            )
        )
        return

    buttons = []

    for row in rows:
        pid = row["product_id"]

        buttons.append([
            InlineKeyboardButton(
                text=PRODUCTS[pid]["name"],
                callback_data=f"product:{pid}"
            )
        ])

    await message.answer(
        "⭐ <b>ИЗБРАННОЕ</b>\n\n"
        "Твои сохранённые товары:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data == "favorites")
async def favorites_callback(callback: CallbackQuery):
    rows = db.execute("""
        SELECT product_id
        FROM favorites
        WHERE user_id = ?
    """, (callback.from_user.id,)).fetchall()

    if not rows:
        await callback.message.edit_text(
            "⭐ <b>ИЗБРАННОЕ</b>\n\n"
            "Здесь пока ничего нет.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛍 В каталог",
                            callback_data="catalog"
                        )
                    ]
                ]
            )
        )
        await callback.answer()
        return

    buttons = []

    for row in rows:
        pid = row["product_id"]

        buttons.append([
            InlineKeyboardButton(
                text=PRODUCTS[pid]["name"],
                callback_data=f"product:{pid}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="catalog"
        )
    ])

    await callback.message.edit_text(
        "⭐ <b>ИЗБРАННОЕ</b>\n\n"
        "Твои сохранённые товары:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =========================================================
# ДОБАВЛЕНИЕ В КОРЗИНУ
# =========================================================

@dp.callback_query(F.data.startswith("add:"))
async def add_product(callback: CallbackQuery):
    _, product_id, quantity = callback.data.split(":")
    quantity = int(quantity)

    success = add_to_cart(
        callback.from_user.id,
        product_id,
        quantity
    )

    if success:
        await callback.answer(
            f"🛒 Добавлено ×{quantity}!",
            show_alert=True
        )
    else:
        await callback.answer(
            "Недостаточно товара на складе.",
            show_alert=True
        )


@dp.callback_query(F.data.startswith("cadd:"))
async def add_case(callback: CallbackQuery):
    _, index, quantity = callback.data.split(":")

    index = int(index)
    quantity = int(quantity)

    model = CASE_MODELS[index]

    success = add_to_cart(
        callback.from_user.id,
        "case",
        quantity,
        model
    )

    if success:
        await callback.answer(
            f"🛒 {model} ×{quantity} добавлен!",
            show_alert=True
        )
    else:
        await callback.answer(
            "Недостаточно чехлов на складе.",
            show_alert=True
        )


# =========================================================
# КОРЗИНА
# =========================================================

async def send_cart(message):
    items = get_cart(message.chat.id)

    if not items:
        await message.answer(
            "🛒 <b>КОРЗИНА</b>\n\n"
            "Корзина пока пустая.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛍 В каталог",
                            callback_data="catalog"
                        )
                    ]
                ]
            )
        )
        return

    text = "🛒 <b>ВАША КОРЗИНА</b>\n\n"

    for item in items:
        p = get_product(item["product_id"])

        variant = ""

        if item["variant"]:
            variant = f"\n📱 {item['variant']}"

        total = p["price"] * item["quantity"]

        text += (
            f"{p['name']}{variant}\n"
            f"Количество: {item['quantity']}\n"
            f"Сумма: {money(total)}\n\n"
        )

    text += (
        "━━━━━━━━━━━━\n"
        f"💰 <b>Итого: {money(cart_total(message.chat.id))}</b>"
    )

    await message.answer(
        text,
        reply_markup=cart_keyboard()
    )


@dp.message(F.text == "🛒 Корзина")
async def cart_message(message: Message):
    await send_cart(message)


@dp.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    await send_cart(callback.message)
    await callback.answer()


# =========================================================
# РЕДАКТИРОВАНИЕ КОРЗИНЫ
# =========================================================

@dp.callback_query(F.data == "cart_edit")
async def cart_edit(callback: CallbackQuery):
    items = get_cart(callback.from_user.id)

    if not items:
        await callback.answer(
            "Корзина пустая."
        )
        return

    buttons = []

    for item in items:
        p = get_product(item["product_id"])

        name = p["name"]

        if item["variant"]:
            name += f" — {item['variant']}"

        buttons.append([
            InlineKeyboardButton(
                text=f"{name} ×{item['quantity']}",
                callback_data=f"edit:{item['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="cart"
        )
    ])

    await callback.message.edit_text(
        "✏️ <b>ИЗМЕНИТЬ КОРЗИНУ</b>\n\n"
        "Выбери товар:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


async def render_cart_item(callback, item):
    p = get_product(item["product_id"])

    variant = ""

    if item["variant"]:
        variant = f"\n📱 Модель: {item['variant']}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➖",
                    callback_data=f"em:{item['id']}:minus"
                ),
                InlineKeyboardButton(
                    text=str(item["quantity"]),
                    callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="➕",
                    callback_data=f"em:{item['id']}:plus"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"del:{item['id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="cart_edit"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        f"✏️ <b>{p['name']}</b>"
        f"{variant}\n\n"
        f"💰 Цена: {money(p['price'])}\n"
        f"Количество: {item['quantity']}\n"
        f"💰 Сумма: "
        f"{money(p['price'] * item['quantity'])}",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("edit:"))
async def edit_item(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[1])

    item = get_cart_item(
        callback.from_user.id,
        item_id
    )

    if not item:
        await callback.answer(
            "Товар не найден."
        )
        return

    await render_cart_item(
        callback,
        item
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("em:"))
async def edit_quantity(callback: CallbackQuery):
    _, item_id, action = callback.data.split(":")

    item_id = int(item_id)

    item = get_cart_item(
        callback.from_user.id,
        item_id
    )

    if not item:
        await callback.answer(
            "Товар не найден."
        )
        return

    quantity = item["quantity"]
    p = get_product(item["product_id"])

    if action == "plus":
        if quantity >= get_stock(item["product_id"]):
            await callback.answer(
                "Больше товара нет."
            )
            return

        quantity += 1

    else:
        if quantity <= 1:
            await callback.answer(
                "Минимальное количество — 1."
            )
            return

        quantity -= 1

    update_quantity = db.execute("""
        UPDATE cart
        SET quantity = ?
        WHERE id = ?
    """, (
        quantity,
        item_id,
    ))

    db.commit()

    item = get_cart_item(
        callback.from_user.id,
        item_id
    )

    await render_cart_item(
        callback,
        item
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("del:"))
async def delete_item(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[1])

    db.execute("""
        DELETE FROM cart
        WHERE id = ?
        AND user_id = ?
    """, (
        item_id,
        callback.from_user.id,
    ))

    db.commit()

    await callback.message.edit_text(
        "🗑 <b>Товар удалён из корзины.</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🛒 Открыть корзину",
                        callback_data="cart"
                    )
                ]
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "cart_clear")
async def cart_clear(callback: CallbackQuery):
    clear_cart(callback.from_user.id)

    await callback.message.edit_text(
        "🗑 <b>Корзина очищена.</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🛍 В каталог",
                        callback_data="catalog"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# ПРОВЕРКА ЗАКАЗА
# =========================================================

@dp.callback_query(F.data == "checkout")
async def checkout(callback: CallbackQuery):
    items = get_cart(callback.from_user.id)

    if not items:
        await callback.answer(
            "Корзина пустая."
        )
        return

    text = "🛒 <b>ПРОВЕРКА ЗАКАЗА</b>\n\n"

    for item in items:
        p = get_product(item["product_id"])

        variant = ""

        if item["variant"]:
            variant = f" ({item['variant']})"

        total = p["price"] * item["quantity"]

        text += (
            f"{p['name']}{variant} ×"
            f"{item['quantity']} — "
            f"{money(total)}\n"
        )

    text += (
        "\n━━━━━━━━━━━━\n"
        f"💰 <b>Итого: {money(cart_total(callback.from_user.id))}</b>\n\n"
        "Всё верно?"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить заказ",
                    callback_data="confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить корзину",
                    callback_data="cart_edit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data="cart"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# =========================================================
# СОЗДАНИЕ ЗАКАЗА
# =========================================================

def make_order_text(order_id):
    order = get_order(order_id)
    items = get_order_items(order_id)

    text = (
        f"📦 <b>Заказ #{order_id}</b>\n\n"
    )

    for item in items:
        variant = ""

        if item["variant"]:
            variant = f" ({item['variant']})"

        text += (
            f"{item['product_name']}{variant} ×"
            f"{item['quantity']} — "
            f"{money(item['price'] * item['quantity'])}\n"
        )

    text += (
        "\n━━━━━━━━━━━━\n"
        f"💰 <b>Итого: {money(order['total'])}</b>"
    )

    return text


def manager_order_url(order_id):
    order = get_order(order_id)
    items = get_order_items(order_id)

    message = f"Здравствуйте! Хочу оформить заказ #{order_id}.\n\n"

    for item in items:
        variant = ""

        if item["variant"]:
            variant = f" ({item['variant']})"

        message += (
            f"{item['product_name']}{variant} ×"
            f"{item['quantity']} — "
            f"{item['price'] * item['quantity']} ₽\n"
        )

    message += f"\nИтого: {order['total']} ₽"

    return (
        f"https://t.me/{MANAGER_USERNAME}"
        f"?text={quote(message)}"
    )


@dp.callback_query(F.data == "confirm")
async def confirm(callback: CallbackQuery):
    order_id = create_order(
        callback.from_user
    )

    if order_id is None:
        await callback.answer(
            "Корзина пустая."
        )
        return

    if order_id == "NO_STOCK":
        await callback.answer(
            "К сожалению, товара уже не хватает.",
            show_alert=True
        )
        return

    if order_id == "ERROR":
        await callback.answer(
            "Не удалось создать заказ. Попробуйте ещё раз.",
            show_alert=True
        )
        return

    order = get_order(order_id)

    user_text = (
        "🎉 <b>ЗАКАЗ ОФОРМЛЕН!</b>\n\n"
        f"{make_order_text(order_id)}\n\n"
        "👇 Для дальнейшей обработки:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 Скинуть заказ менеджеру",
                    url=manager_order_url(order_id)
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Мой заказ",
                    callback_data=f"order:{order_id}"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        user_text,
        reply_markup=keyboard
    )

    # Отправляем обоим админам
    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else "нет username"
    )

    admin_text = (
        "🔔 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"{make_order_text(order_id)}\n\n"
        f"👤 Клиент: {username}\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"🕐 {order['created_at']}"
    )

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"status:{order_id}:В обработке"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Собирается",
                    callback_data=f"status:{order_id}:Собирается"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚚 Отправлен",
                    callback_data=f"status:{order_id}:Отправлен"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"status:{order_id}:Отменён"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Открыть клиента",
                    url=f"tg://user?id={callback.from_user.id}"
                )
            ],
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                reply_markup=admin_keyboard
            )
        except Exception as e:
            logging.error(
                f"Ошибка отправки админу {admin_id}: {e}"
            )

    await callback.answer(
        "Заказ создан!"
    )


# =========================================================
# МОИ ЗАКАЗЫ
# =========================================================

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: Message):
    orders = get_user_orders(
        message.from_user.id
    )

    if not orders:
        await message.answer(
            "📦 <b>МОИ ЗАКАЗЫ</b>\n\n"
            "У тебя пока нет заказов."
        )
        return

    buttons = []

    for order in orders:
        buttons.append([
            InlineKeyboardButton(
                text=(
                    f"📦 #{order['id']} — "
                    f"{money(order['total'])}"
                ),
                callback_data=f"order:{order['id']}"
            )
        ])

    await message.answer(
        "📦 <b>МОИ ЗАКАЗЫ</b>\n\n"
        "Выбери заказ:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("order:"))
async def order_detail(callback: CallbackQuery):
    order_id = int(
        callback.data.split(":")[1]
    )

    order = get_order(order_id)

    if not order:
        await callback.answer(
            "Заказ не найден."
        )
        return

    if order["user_id"] != callback.from_user.id:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    text = (
        make_order_text(order_id)
        + "\n\n"
        + f"📊 Статус: <b>{order['status']}</b>\n"
        + f"🕐 {order['created_at']}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="orders_back"
                    )
                ]
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "orders_back")
async def orders_back(callback: CallbackQuery):
    orders = get_user_orders(
        callback.from_user.id
    )

    if not orders:
        await callback.message.edit_text(
            "📦 <b>Мои заказы</b>\n\n"
            "Заказов пока нет."
        )
        await callback.answer()
        return

    buttons = []

    for order in orders:
        buttons.append([
            InlineKeyboardButton(
                text=(
                    f"📦 #{order['id']} — "
                    f"{money(order['total'])}"
                ),
                callback_data=f"order:{order['id']}"
            )
        ])

    await callback.message.edit_text(
        "📦 <b>МОИ ЗАКАЗЫ</b>\n\n"
        "Выбери заказ:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =========================================================
# СТАТУСЫ ЗАКАЗОВ
# =========================================================

@dp.callback_query(F.data.startswith("status:"))
async def status_change(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    _, order_id, status = callback.data.split(":", 2)

    order_id = int(order_id)

    order = get_order(order_id)

    if not order:
        await callback.answer(
            "Заказ не найден."
        )
        return

    old_status = order["status"]

    if old_status == "Отменён" and status != "Отменён":
        await callback.answer(
            "Отменённый заказ нельзя вернуть в обработку.",
            show_alert=True
        )
        return

    # Если заказ отменяют впервые — возвращаем списанный товар на склад.
    if status == "Отменён" and old_status != "Отменён" and order["stock_applied"]:
        for item in get_order_items(order_id):
            db.execute("""
                UPDATE inventory
                SET stock = stock + ?
                WHERE product_id = ?
            """, (item["quantity"], item["product_id"]))

        db.execute("""
            UPDATE orders
            SET status = ?, stock_applied = 0
            WHERE id = ?
        """, (status, order_id))
    else:
        db.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (status, order_id))

    db.commit()

    try:
        await bot.send_message(
            order["user_id"],
            f"📦 <b>Заказ #{order_id}</b>\n\n"
            f"Новый статус:\n"
            f"<b>{status}</b>"
        )
    except Exception as e:
        logging.error(
            f"Ошибка уведомления клиента: {e}"
        )

    await callback.answer(
        f"Статус изменён: {status}"
    )


# =========================================================
# ПОДДЕРЖКА
# =========================================================

@dp.message(F.text == "💬 Поддержка")
async def support(message: Message):
    await message.answer(
        "💬 <b>ПОДДЕРЖКА</b>\n\n"
        "Выберите категорию обращения:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📦 Вопрос по заказу",
                        callback_data="support:order"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🛍 Вопрос о товаре",
                        callback_data="support:product"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❓ Другое",
                        callback_data="support:other"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back_menu"
                    )
                ],
            ]
        )
    )


@dp.callback_query(F.data.startswith("support:"))
async def support_category(
    callback: CallbackQuery,
    state: FSMContext
):
    code = callback.data.split(":")[1]

    categories = {
        "order": "📦 Вопрос по заказу",
        "product": "🛍 Вопрос о товаре",
        "other": "❓ Другое",
    }

    await state.update_data(
        category=categories[code]
    )

    await state.set_state(
        SupportState.waiting_message
    )

    await callback.message.edit_text(
        f"<b>{categories[code]}</b>\n\n"
        "✍️ Напиши сообщение для поддержки."
    )

    await callback.answer()


@dp.message(SupportState.waiting_message)
async def support_message(
    message: Message,
    state: FSMContext
):
    data = await state.get_data()

    category = data["category"]

    text = message.text or ""

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "нет username"
    )

    now = datetime.now().strftime(
        "%d.%m.%Y %H:%M"
    )

    db.execute("""
        INSERT INTO support_messages
        (user_id, username, category,
         message, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        message.from_user.username or "",
        category,
        text,
        now,
    ))

    db.commit()

    await state.clear()

    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Мы получили ваше обращение.",
        reply_markup=main_menu(message.from_user.id)
    )

    admin_text = (
        "📩 <b>НОВОЕ ОБРАЩЕНИЕ</b>\n\n"
        f"👤 {username}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"📌 {category}\n\n"
        f"💬 <b>Сообщение:</b>\n"
        f"{html.escape(text)}"
    )

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Открыть пользователя",
                    url=f"tg://user?id={message.from_user.id}"
                )
            ]
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                reply_markup=admin_keyboard
            )
        except Exception as e:
            logging.error(
                f"Ошибка поддержки: {e}"
            )


# =========================================================
# АДМИН-ПАНЕЛЬ / СТАТИСТИКА
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
                InlineKeyboardButton(text="📦 Остатки", callback_data="admin:stock"),
            ],
            [
                InlineKeyboardButton(text="📈 Продажи", callback_data="admin:sales"),
                InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_menu")
            ],
        ]
    )


def parse_order_date(value):
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return None


def sales_snapshot():
    orders = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    now = datetime.now()
    today_revenue = 0
    week_revenue = 0
    month_revenue = 0
    all_revenue = 0
    active_orders = 0

    for order in orders:
        if order["status"] == "Отменён":
            continue
        dt = parse_order_date(order["created_at"])
        if not dt:
            continue
        all_revenue += order["total"]
        active_orders += 1
        if dt.date() == now.date():
            today_revenue += order["total"]
        if dt >= now.replace(hour=0, minute=0, second=0, microsecond=0) - __import__("datetime").timedelta(days=6):
            week_revenue += order["total"]
        if dt.year == now.year and dt.month == now.month:
            month_revenue += order["total"]

    sold_rows = db.execute("""
        SELECT oi.product_id, oi.product_name, SUM(oi.quantity) AS qty
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status != 'Отменён'
        GROUP BY oi.product_id, oi.product_name
        ORDER BY qty DESC
    """).fetchall()
    total_units = sum(row["qty"] for row in sold_rows)
    return today_revenue, week_revenue, month_revenue, all_revenue, active_orders, total_units, sold_rows


def admin_stats_text():
    today, week, month, total, orders_count, units, sold_rows = sales_snapshot()
    text = (
        "📊 <b>СТАТИСТИКА VOLTIX</b>\n\n"
        f"💰 Сегодня: <b>{money(today)}</b>\n"
        f"📅 За 7 дней: <b>{money(week)}</b>\n"
        f"🗓 За месяц: <b>{money(month)}</b>\n"
        f"💵 За всё время: <b>{money(total)}</b>\n\n"
        f"📦 Заказов: <b>{orders_count}</b>\n"
        f"🛍 Товаров продано: <b>{units}</b>\n\n"
        "🔥 <b>ТОП ПРОДАЖ</b>\n"
    )
    if not sold_rows:
        text += "Пока продаж нет.\n"
    else:
        for i, row in enumerate(sold_rows[:5], 1):
            text += f"{i}. {row['product_name']} — <b>{row['qty']} шт.</b>\n"
    return text


def admin_stock_text():
    text = "📦 <b>ОСТАТКИ ТОВАРОВ</b>\n\n"
    for pid, product in PRODUCTS.items():
        row = db.execute("""
            SELECT stock, initial_stock
            FROM inventory
            WHERE product_id = ?
        """, (pid,)).fetchone()
        stock = row["stock"] if row else product["stock"]
        sold_row = db.execute("""
            SELECT COALESCE(SUM(oi.quantity), 0) AS qty
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.product_id = ? AND o.status != 'Отменён'
        """, (pid,)).fetchone()
        sold = sold_row["qty"] if sold_row else 0
        if stock == 0:
            marker = "❌"
        elif stock <= 3:
            marker = "⚠️"
        else:
            marker = "📦"
        text += (
            f"{marker} <b>{product['name']}</b>\n"
            f"Осталось: <b>{stock} шт.</b> | Продано: <b>{sold} шт.</b>\n"
        )
    text += "\n👇 Нажми на товар, чтобы вручную изменить остаток."
    return text


def admin_stock_keyboard():
    buttons = []
    for pid, product in PRODUCTS.items():
        buttons.append([
            InlineKeyboardButton(
                text=product["name"],
                callback_data=f"stock_item:{pid}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stock_item_keyboard(product_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➖ 1", callback_data=f"stock:{product_id}:-1"),
                InlineKeyboardButton(text="➕ 1", callback_data=f"stock:{product_id}:1"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Остатки", callback_data="admin:stock")
            ],
        ]
    )


@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Здесь можно посмотреть выручку, продажи и реальные остатки товаров.",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data.startswith("admin:"))
async def admin_section(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    section = callback.data.split(":")[1]
    if section == "stock":
        await callback.message.edit_text(
            admin_stock_text(),
            reply_markup=admin_stock_keyboard()
        )
    elif section == "sales":
        today, week, month, total, orders_count, units, sold_rows = sales_snapshot()
        text = (
            "📈 <b>ПРОДАЖИ</b>\n\n"
            f"🧾 Заказов: <b>{orders_count}</b>\n"
            f"🛍 Товаров продано: <b>{units}</b>\n"
            f"💰 Выручка: <b>{money(total)}</b>\n\n"
            "🔥 <b>По товарам:</b>\n"
        )
        if sold_rows:
            for row in sold_rows:
                text += f"• {row['product_name']} — {row['qty']} шт.\n"
        else:
            text += "Пока продаж нет."
        await callback.message.edit_text(text, reply_markup=admin_keyboard())
    else:
        await callback.message.edit_text(
            admin_stats_text(),
            reply_markup=admin_keyboard()
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("stock_item:"))
async def stock_item(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    pid = callback.data.split(":", 1)[1]
    if pid not in PRODUCTS:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    p = PRODUCTS[pid]
    await callback.message.edit_text(
        f"📦 <b>{p['name']}</b>\n\n"
        f"Текущий остаток: <b>{get_stock(pid)} шт.</b>\n\n"
        "Изменить остаток:",
        reply_markup=stock_item_keyboard(pid)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("stock:"))
async def stock_change(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    _, pid, delta = callback.data.split(":")
    if pid not in PRODUCTS:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    new_stock = change_stock(pid, int(delta))
    await callback.message.edit_text(
        f"📦 <b>{PRODUCTS[pid]['name']}</b>\n\n"
        f"Текущий остаток: <b>{new_stock} шт.</b>\n\n"
        "Изменить остаток:",
        reply_markup=stock_item_keyboard(pid)
    )
    await callback.answer(f"Остаток: {new_stock} шт.")


# =========================================================
# ОТЗЫВЫ
# =========================================================

def stars(rating):
    return "⭐" * rating


@dp.message(F.text == "⭐ Отзывы")
async def reviews(message: Message):
    rows = db.execute("""
        SELECT *
        FROM reviews
        WHERE status = 'published'
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()

    text = "⭐ <b>ОТЗЫВЫ</b>\n\n"

    if not rows:
        text += (
            "Пока отзывов нет.\n"
            "Будь первым! 👇"
        )
    else:
        for review in rows:
            name = (
                f"@{review['username']}"
                if review["username"]
                else review["first_name"]
            )

            text += (
                f"{stars(review['rating'])}\n"
                f"<b>{html.escape(name)}</b>\n"
                f"{html.escape(review['text'])}\n\n"
                "━━━━━━━━━━━━\n\n"
            )

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✍️ Оставить отзыв",
                        callback_data="review_start"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back_menu"
                    )
                ]
            ]
        )
    )


@dp.callback_query(F.data == "review_start")
async def review_start(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        ReviewState.waiting_rating
    )

    await callback.message.edit_text(
        "⭐ <b>ОСТАВИТЬ ОТЗЫВ</b>\n\n"
        "Поставь оценку от 1 до 5:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⭐",
                        callback_data="rating:1"
                    ),
                    InlineKeyboardButton(
                        text="⭐⭐",
                        callback_data="rating:2"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⭐⭐⭐",
                        callback_data="rating:3"
                    ),
                    InlineKeyboardButton(
                        text="⭐⭐⭐⭐",
                        callback_data="rating:4"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⭐⭐⭐⭐⭐",
                        callback_data="rating:5"
                    ),
                ],
            ]
        )
    )

    await callback.answer()


@dp.callback_query(
    ReviewState.waiting_rating,
    F.data.startswith("rating:")
)
async def review_rating(
    callback: CallbackQuery,
    state: FSMContext
):
    rating = int(
        callback.data.split(":")[1]
    )

    await state.update_data(
        rating=rating
    )

    await state.set_state(
        ReviewState.waiting_text
    )

    await callback.message.edit_text(
        f"{stars(rating)}\n\n"
        "✍️ Теперь напиши свой отзыв:"
    )

    await callback.answer()


@dp.message(ReviewState.waiting_text)
async def review_text(
    message: Message,
    state: FSMContext
):
    data = await state.get_data()

    rating = data["rating"]

    text = message.text or ""

    if len(text.strip()) < 3:
        await message.answer(
            "✍️ Напиши отзыв чуть подробнее."
        )
        return

    username = message.from_user.username or ""

    first_name = message.from_user.first_name or ""

    now = datetime.now().strftime(
        "%d.%m.%Y %H:%M"
    )

    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO reviews
        (user_id, username, first_name,
         rating, text, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        username,
        first_name,
        rating,
        text,
        "pending",
        now,
    ))

    review_id = cursor.lastrowid

    db.commit()

    await state.clear()

    await message.answer(
        "✅ <b>Спасибо за отзыв!</b>\n\n"
        "Он отправлен на проверку и появится "
        "в разделе отзывов после публикации.",
        reply_markup=main_menu(message.from_user.id)
    )

    name = (
        f"@{username}"
        if username
        else first_name
    )

    admin_text = (
        "⭐ <b>НОВЫЙ ОТЗЫВ</b>\n\n"
        f"👤 {html.escape(name)}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"Оценка: {stars(rating)}\n\n"
        f"💬 {html.escape(text)}"
    )

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать",
                    callback_data=f"review:publish:{review_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"review:reject:{review_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Открыть пользователя",
                    url=f"tg://user?id={message.from_user.id}"
                )
            ],
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                reply_markup=admin_keyboard
            )
        except Exception as e:
            logging.error(
                f"Ошибка отправки отзыва: {e}"
            )


# =========================================================
# МОДЕРАЦИЯ ОТЗЫВОВ
# =========================================================

@dp.callback_query(F.data.startswith("review:"))
async def moderate_review(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    _, action, review_id = callback.data.split(":")

    review_id = int(review_id)

    review = db.execute("""
        SELECT *
        FROM reviews
        WHERE id = ?
    """, (review_id,)).fetchone()

    if not review:
        await callback.answer(
            "Отзыв не найден."
        )
        return

    if review["status"] != "pending":
        await callback.answer(
            "Этот отзыв уже обработан."
        )
        return

    if action == "publish":
        status = "published"
        result = "✅ Отзыв опубликован!"

    else:
        status = "rejected"
        result = "❌ Отзыв отклонён."

    db.execute("""
        UPDATE reviews
        SET status = ?
        WHERE id = ?
    """, (
        status,
        review_id,
    ))

    db.commit()

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.answer(
        result,
        show_alert=True
    )


@dp.callback_query(F.data == "back_menu")
async def back_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# =========================================================
# НАЗАД / NOOP
# =========================================================

@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# =========================================================
# ЗАПУСК
# =========================================================

async def main():
    logging.basicConfig(
        level=logging.INFO
    )

    init_db()

    if not BOT_TOKEN or BOT_TOKEN.startswith("ВСТАВЬ"):
        print("❌ Вставь токен бота в BOT_TOKEN")
        return

    print("==============================")
    print(f"   {SHOP_NAME} BOT ЗАПУЩЕН")
    print("==============================")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")