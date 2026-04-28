from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv
import asyncio
import calendar
import os
import aiosqlite
from datetime import datetime, timedelta

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # Ваш user_id

TELEGRAM_PROXY_URL = os.getenv(
    "TELEGRAM_PROXY_URL",
    "http://DcNVAT:32DeAo@170.83.233.92:8000"
)

# Инициализация бота с использованием DefaultBotProperties
session = AiohttpSession(proxy=TELEGRAM_PROXY_URL)
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)  # Устанавливаем parse_mode по умолчанию
)
dp = Dispatcher()



async def init_db():
    # Инициализация соединения с базой данных
    async with aiosqlite.connect('events.db') as db:
        # Создание таблицы для хранения пользователей
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            registered_at TEXT,
            is_active BOOLEAN DEFAULT 1
        )
        ''')

        # Создание таблицы для хранения категорий
        await db.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category_name TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')

        # Создание таблицы для хранения событий
        await db.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_name TEXT,
            remind_datetime TEXT,
            repeat_interval TEXT,
            category TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')

        # Добавление категории "Дни рождения" по умолчанию для всех пользователей
        await db.execute('''
        INSERT OR IGNORE INTO categories (user_id, category_name)
        SELECT 0, 'Дни рождения'
        WHERE NOT EXISTS (
            SELECT 1 FROM categories WHERE user_id = 0 AND category_name = 'Дни рождения'
        )
        ''')

        await db.commit()


def get_user_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """
    Возвращает клавиатуру в зависимости от роли пользователя.
    """
    keyboard = [
        [KeyboardButton(text="Добавить событие")],
        [KeyboardButton(text="Мои события")],
        [KeyboardButton(text="События по категориям")],
        [KeyboardButton(text="Удалить событие")],
        [KeyboardButton(text="Отключить бота")]
    ]

    # Если пользователь — админ, добавляем кнопку "Вернуться в админку"
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton(text="Вернуться в админку")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

from datetime import datetime

def format_datetime(dt_str: str) -> str:
    """
    Приводит строку даты и времени к формату "YYYY-MM-DD HH:MM".
    """
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")

# Клавиатура для удобства
# keyboard = ReplyKeyboardMarkup(
#     keyboard=[
#         [KeyboardButton(text="Добавить событие")],
#         [KeyboardButton(text="Мои события")],
#         [KeyboardButton(text="События по категориям")],
#         [KeyboardButton(text="Удалить событие")],
#         [KeyboardButton(text="Отключить бота")]
#     ],
#     resize_keyboard=True
# )

# Клавиатура для админки
admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Статистика по пользователям")],
        [KeyboardButton(text="Статистика по событиям")],
        [KeyboardButton(text="Статистика по категориям")],
        [KeyboardButton(text="Выйти из админки")]
    ],
    resize_keyboard=True
)

# Состояния для FSM (Finite State Machine)
class Form(StatesGroup):
    event_name = State()
    remind_date = State()
    remind_time = State()
    repeat_interval = State()
    category = State()
    delete_event = State()
    add_category = State()

# Функция для создания inline-календаря
def create_calendar(year: int, month: int):
    builder = InlineKeyboardBuilder()
    # Заголовок с месяцем и годом
    builder.button(text=f"{calendar.month_name[month]} {year}", callback_data="ignore")
    # Дни недели
    for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
        builder.button(text=day, callback_data="ignore")
    builder.adjust(7)
    # Дни месяца
    for week in calendar.monthcalendar(year, month):
        for day in week:
            if day == 0:
                builder.button(text=" ", callback_data="ignore")
            else:
                builder.button(text=str(day), callback_data=f"date_{year}_{month}_{day}")
    builder.adjust(7)
    # Кнопки для переключения месяцев
    builder.row(
        InlineKeyboardButton(text="<", callback_data=f"prev_{year}_{month}"),
        InlineKeyboardButton(text=">", callback_data=f"next_{year}_{month}")
    )
    return builder.as_markup()

# Функция для создания inline-клавиатуры с выбором времени
def create_time_keyboard():
    builder = InlineKeyboardBuilder()
    # Время с шагом 30 минут
    for hour in range(0, 24):
        for minute in ["00", "30"]:
            builder.button(text=f"{hour}:{minute}", callback_data=f"time_{hour}:{minute}")
    builder.adjust(4)
    return builder.as_markup()

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    try:
        # Регистрация пользователя
        await register_user(message.from_user)

        # Активируем пользователя (устанавливаем is_active = 1)
        async with aiosqlite.connect('events.db') as db:
            await db.execute('''
                    UPDATE users SET is_active = 1 WHERE user_id = ?
                    ''', (message.from_user.id,))
            await db.commit()

        # Проверка, является ли пользователь админом
        if message.from_user.id == ADMIN_ID:
            await message.answer("Привет, админ! Выберите действие:", reply_markup=admin_keyboard)
        else:
            await message.answer(
                "Привет! Я бот для напоминаний о важных событиях. Используй кнопки ниже.",
                reply_markup=get_user_keyboard(message.from_user.id)  # Используем функцию для получения клавиатуры
            )
    except Exception as e:
        await message.answer("Произошла ошибка при запуске бота. Попробуйте позже.")
        print(f"Ошибка в команде /start: {e}")

@dp.message(F.text == "Вернуться в админку")
async def return_to_admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:  # Проверяем, что пользователь — админ
        await message.answer("Вы вернулись в админку.", reply_markup=admin_keyboard)
    else:
        await message.answer("У вас нет доступа к админке.")

# Обработка callback-запросов для календаря
@dp.callback_query(F.data.startswith("date_"))
async def process_calendar_select(callback_query: CallbackQuery, state: FSMContext):
    _, year, month, day = callback_query.data.split("_")
    await state.update_data(remind_date=f"{year}-{month}-{day}")
    await state.set_state(Form.remind_time)
    await callback_query.message.answer("Выберите время напоминания:", reply_markup=create_time_keyboard())
    await callback_query.answer()

@dp.callback_query(F.data.startswith("prev_"))
async def process_calendar_prev(callback_query: CallbackQuery):
    _, year, month = callback_query.data.split("_")
    year = int(year)
    month = int(month)
    if month == 1:
        month = 12
        year -= 1
    else:
        month -= 1
    await callback_query.message.edit_reply_markup(reply_markup=create_calendar(year, month))  # Добавлено reply_markup=
    await callback_query.answer()

@dp.callback_query(F.data.startswith("next_"))
async def process_calendar_next(callback_query: CallbackQuery):
    _, year, month = callback_query.data.split("_")
    year = int(year)
    month = int(month)
    if month == 12:
        month = 1
        year += 1
    else:
        month += 1
    await callback_query.message.edit_reply_markup(reply_markup=create_calendar(year, month))  # Добавлено reply_markup=
    await callback_query.answer()

# Обработка callback-запросов для выбора времени
@dp.callback_query(F.data.startswith("time_"), Form.remind_time)
async def process_time_select(callback_query: CallbackQuery, state: FSMContext):
    time = callback_query.data.split("_")[1]
    data = await state.get_data()
    remind_date = data['remind_date']
    remind_datetime = f"{remind_date} {time}"
    await state.update_data(remind_datetime=remind_datetime)
    await state.set_state(Form.repeat_interval)
    await callback_query.message.answer("Выберите тип повторения:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Без повторения")],
            [KeyboardButton(text="Ежедневно")],
            [KeyboardButton(text="Еженедельно")],
            [KeyboardButton(text="Раз в две недели")],  # Новая кнопка
            [KeyboardButton(text="Ежемесячно")],
            [KeyboardButton(text="Ежегодно")]
        ],
        resize_keyboard=True
    ))
    await callback_query.answer()

# # # Константы для пагинации
EVENTS_PER_PAGE = 5  # Количество событий на одной странице

# Функция для регистрации пользователя
async def register_user(user: types.User):
    async with aiosqlite.connect('events.db') as db:
        await db.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, registered_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, user.last_name, datetime.now().strftime("%Y-%m-%d %H:%M"), 1))
        await db.commit()

# Функция для получения категорий пользователя
async def get_user_categories(user_id: int):
    async with aiosqlite.connect('events.db') as db:
        cursor = await db.execute('''
        SELECT category_name FROM categories WHERE user_id = ? OR user_id = 0
        ''', (user_id,))
        return [row[0] for row in await cursor.fetchall()]

# Обработка кнопки "Добавить событие"
@dp.message(F.text == "Добавить событие")
async def add_event_step_1(message: types.Message, state: FSMContext):
    await state.set_state(Form.event_name)
    await message.answer("Введите название события:")

# Шаг 1: Получение названия события
@dp.message(Form.event_name)
async def process_event_name(message: types.Message, state: FSMContext):
    await state.update_data(event_name=message.text)
    await state.set_state(Form.remind_date)
    await message.answer("Выберите дату напоминания:", reply_markup=create_calendar(datetime.now().year, datetime.now().month))

# Шаг 2: Получение времени напоминания
@dp.callback_query(F.data.startswith("time_"), Form.remind_time)
async def process_time_select(callback_query: CallbackQuery, state: FSMContext):
    time = callback_query.data.split("_")[1]
    data = await state.get_data()
    remind_date = data['remind_date']
    remind_datetime = f"{remind_date} {time}"
    await state.update_data(remind_datetime=remind_datetime)
    await state.set_state(Form.repeat_interval)
    await callback_query.message.answer("Выберите тип повторения:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Без повторения")],
            [KeyboardButton(text="Ежедневно")],
            [KeyboardButton(text="Еженедельно")],
            [KeyboardButton(text="Раз в две недели")],
            [KeyboardButton(text="Ежемесячно")],
            [KeyboardButton(text="Ежегодно")]
        ],
        resize_keyboard=True
    ))
    await callback_query.answer()

# Шаг 3: Получение типа повторения
@dp.message(Form.repeat_interval)
async def process_repeat_interval(message: types.Message, state: FSMContext):
    repeat_intervals = {
        "Без повторения": "none",
        "Ежедневно": "daily",
        "Еженедельно": "weekly",
        "Раз в две недели": "biweekly",  # Новый интервал
        "Ежемесячно": "monthly",
        "Ежегодно": "yearly",
    }

    if message.text not in repeat_intervals:
        await message.answer("Пожалуйста, выберите тип повторения из предложенных вариантов.")
        return

    await state.update_data(repeat_interval=repeat_intervals[message.text])
    await state.set_state(Form.category)
    categories = await get_user_categories(message.from_user.id)
    categories_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=category)] for category in categories
        ] + [
            [KeyboardButton(text="Добавить новую категорию")],
            [KeyboardButton(text="Без категории")]
        ],
        resize_keyboard=True
    )
    await message.answer("Выберите категорию:", reply_markup=categories_keyboard)

# Шаг 4: Получение категории
@dp.message(Form.category)
async def process_category(message: types.Message, state: FSMContext):
    if message.text == "Добавить новую категорию":
        await state.set_state(Form.add_category)
        await message.answer("Введите название новой категории:")
        return

    data = await state.get_data()
    category = None if message.text == "Без категории" else message.text

    # Форматируем дату и время
    remind_datetime = format_datetime(data['remind_datetime'])

    # Сохранение события в базу данных
    try:
        async with aiosqlite.connect('events.db') as db:
            await db.execute('''
                INSERT INTO events (user_id, event_name, remind_datetime, repeat_interval, category)
                VALUES (?, ?, ?, ?, ?)
                ''', (message.from_user.id, data['event_name'], remind_datetime, data['repeat_interval'], category))
            await db.commit()

        # Формируем сообщение с информацией о событии
        repeat_interval_text = {
            "none": "Без повторения",
            "daily": "Ежедневно",
            "weekly": "Еженедельно",
            "biweekly": "Раз в две недели",
            "monthly": "Ежемесячно",
            "yearly": "Ежегодно",
        }.get(data['repeat_interval'], "Неизвестно")

        response = (
            f"✅ Событие успешно создано!\n\n"
            f"📌 Название: {data['event_name']}\n"
            f"📅 Дата и время: {remind_datetime}\n"
            f"🔄 Повторение: {repeat_interval_text}\n"
            f"📁 Категория: {category if category else 'Без категории'}"
        )

        await message.answer(response, reply_markup=get_user_keyboard(message.from_user.id))
    except Exception as e:
        await message.answer("Произошла ошибка при сохранении события. Попробуйте позже.")
        print(f"Ошибка при сохранении события: {e}")
        return

    await state.clear()

# Шаг 5: Добавление новой категории
@dp.message(Form.add_category)
async def process_add_category(message: types.Message, state: FSMContext):
    category_name = message.text
    try:
        async with aiosqlite.connect('events.db') as db:
            # Добавляем новую категорию
            await db.execute('''
            INSERT INTO categories (user_id, category_name)
            VALUES (?, ?)
            ''', (message.from_user.id, category_name))
            await db.commit()

        # Получаем данные о событии из состояния
        data = await state.get_data()

        # Форматируем дату и время
        remind_datetime = format_datetime(data['remind_datetime'])

        # Сохраняем событие с новой категорией
        async with aiosqlite.connect('events.db') as db:
            await db.execute('''
            INSERT INTO events (user_id, event_name, remind_datetime, repeat_interval, category)
            VALUES (?, ?, ?, ?, ?)
            ''', (message.from_user.id, data['event_name'], remind_datetime, data['repeat_interval'], category_name))
            await db.commit()

        # Формируем сообщение с информацией о событии
        repeat_interval_text = {
            "none": "Без повторения",
            "daily": "Ежедневно",
            "weekly": "Еженедельно",
            "biweekly": "Раз в две недели",
            "monthly": "Ежемесячно",
            "yearly": "Ежегодно",
        }.get(data['repeat_interval'], "Неизвестно")

        response = (
            f"✅ Событие успешно создано!\n\n"
            f"📌 Название: {data['event_name']}\n"
            f"📅 Дата и время: {remind_datetime}\n"
            f"🔄 Повторение: {repeat_interval_text}\n"
            f"📁 Категория: {category_name}"
        )

        await message.answer(response, reply_markup=get_user_keyboard(message.from_user.id))
    except Exception as e:
        await message.answer("Произошла ошибка при добавлении категории или сохранении события. Попробуйте позже.")
        print(f"Ошибка в process_add_category: {e}")
        return

    await state.clear()

# Константы для пагинации
EVENTS_PER_PAGE = 5  # Количество событий на одной странице

@dp.message(F.text == "Мои события")
async def handle_my_events(message: types.Message):
    await show_events(message, message.from_user.id, page=0)


async def show_events(message: types.Message, user_id: int, page: int = 0):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")  # Текущее время в формате "YYYY-MM-DD HH:MM"
        async with aiosqlite.connect('events.db') as db:
            # Получаем события для текущей страницы
            cursor = await db.execute('''
            SELECT id, event_name, remind_datetime, repeat_interval, category
            FROM events WHERE user_id = ? and remind_datetime >= ?
            ORDER BY remind_datetime ASC
            LIMIT ? OFFSET ?
            ''', (user_id, now, EVENTS_PER_PAGE, page * EVENTS_PER_PAGE))
            events = await cursor.fetchall()

            # Получаем общее количество событий
            cursor = await db.execute('SELECT COUNT(*) FROM events WHERE user_id = ?', (user_id,))
            total_events = (await cursor.fetchone())[0]

        if not events:
            await message.answer("У вас пока нет сохраненных событий.")
            return

        response = f"Ваши события (страница {page + 1}):\n"
        for event in events:
            repeat_interval = {
                "none": "Без повторения",
                "daily": "Ежедневно",
                "weekly": "Еженедельно",
                "biweekly": "Раз в две недели",
                "monthly": "Ежемесячно",
                "yearly": "Ежегодно",
            }.get(event[3], "Неизвестно")
            category = event[4] if event[4] else "Без категории"
            response += f"🆔 {event[0]} — {event[1]} (напомнить: {event[2]}, повтор: {repeat_interval}, категория: {category})\n"

        total_pages = (total_events + EVENTS_PER_PAGE - 1) // EVENTS_PER_PAGE

        # Добавляем кнопки пагинации
        builder = InlineKeyboardBuilder()
        if page > 0:
            builder.button(text="⬅️ Назад", callback_data=f"page_{page - 1}")
        if page < total_pages - 1:
            builder.button(text="Вперед ➡️", callback_data=f"page_{page + 1}")
        builder.adjust(2)

        await message.answer(response, reply_markup=builder.as_markup())
    except Exception as e:
        await message.answer("Произошла ошибка при получении событий. Попробуйте позже.")
        print(f"Ошибка в show_events: {e}")

# Функция для получения общего количества событий
async def get_total_events(user_id: int):
    async with aiosqlite.connect('events.db') as db:
        cursor = await db.execute('''
        SELECT COUNT(*) FROM events WHERE user_id = ?
        ''', (user_id,))
        return (await cursor.fetchone())[0]

# Обработка callback-запросов для пагинации
@dp.callback_query(F.data.startswith("page_"))
async def paginate_events(callback_query: CallbackQuery):
    page = int(callback_query.data.split("_")[1])  # Получаем номер страницы из callback_data
    await show_events(callback_query.message, callback_query.from_user.id, page)  # Передаем user_id
    await callback_query.answer()

# Обработка кнопки "События по категориям"
@dp.message(F.text == "События по категориям")
async def show_events_by_category(message: types.Message):
    try:
        categories = await get_user_categories(message.from_user.id)
        if not categories:
            await message.answer("У вас пока нет категорий.")
            return

        # Создаем клавиатуру с категориями
        builder = InlineKeyboardBuilder()
        for category in categories:
            if len(category) > 30:
                category = category[0:29]
            builder.button(text=category, callback_data=f"category_{category}")
        builder.adjust(2)
        await message.answer("Выберите категорию:", reply_markup=builder.as_markup())
    except Exception as e:
        await message.answer("Произошла ошибка при получении категорий. Попробуйте позже.")
        print(e)

# Обработка callback-запросов для выбора категории
@dp.callback_query(F.data.startswith("category_"))
async def process_category_events(callback_query: CallbackQuery):
    category = callback_query.data.split("_")[1:]
    category_like = f"{category[0]}%"
    try:
        async with aiosqlite.connect('events.db') as db:
            cursor = await db.execute('''
            SELECT id, event_name, remind_datetime, repeat_interval, category
            FROM events WHERE user_id = ? AND category LIKE ?
            ORDER BY remind_datetime ASC
            ''', (callback_query.from_user.id, category_like))
            events = await cursor.fetchall()

        if not events:
            await callback_query.message.answer(f"В категории '{category}' пока нет событий.")
            return
        response = f"События в категории '{events[0][4]}':\n"
        for event in events:
            repeat_interval = {
                "none": "Без повторения",
                "daily": "Ежедневно",
                "weekly": "Еженедельно",
                "biweekly": "Раз в две недели",
                "monthly": "Ежемесячно",
                "yearly": "Ежегодно",
            }.get(event[3], "Неизвестно")
            response += f"🆔 {event[0]} — {event[1]} (напомнить: {event[2]}, повтор: {repeat_interval})\n"

        await callback_query.message.answer(response)
    except Exception as e:
        await callback_query.message.answer("Произошла ошибка при получении событий. Попробуйте позже.")
    await callback_query.answer()

# Обработка кнопки "Удалить событие"
@dp.message(F.text == "Удалить событие")
async def delete_event_step_1(message: types.Message, state: FSMContext):
    await state.set_state(Form.delete_event)
    await message.answer("Введите ID события, которое хотите удалить:")

# Шаг 1: Получение ID события для удаления
@dp.message(Form.delete_event)
async def process_delete_event(message: types.Message, state: FSMContext):
    event_id = message.text
    try:
        async with aiosqlite.connect('events.db') as db:
            cursor = await db.execute('SELECT id FROM events WHERE id = ? AND user_id = ?', (event_id, message.from_user.id))
            event = await cursor.fetchone()

        if not event:
            await message.answer("Событие с таким ID не найдено.")
        else:
            async with aiosqlite.connect('events.db') as db:
                await db.execute('DELETE FROM events WHERE id = ?', (event_id,))
                await db.commit()
            await message.answer("Событие успешно удалено!")
    except Exception as e:
        await message.answer("Произошла ошибка при удалении события. Попробуйте позже.")

    await state.clear()

# Обработка кнопки "Отключить бота"
@dp.message(F.text == "Отключить бота")
async def disable_bot(message: types.Message):
    disable_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отключить на время")],
            [KeyboardButton(text="Отключить навсегда")],
            [KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True
    )
    await message.answer("Выберите тип отключения:", reply_markup=disable_keyboard)

# Обработка выбора "Отключить на время"
@dp.message(F.text == "Отключить на время")
async def disable_temporarily(message: types.Message):
    try:
        async with aiosqlite.connect('events.db') as db:
            await db.execute('UPDATE users SET is_active = 0 WHERE user_id = ?', (message.from_user.id,))
            await db.commit()
        await message.answer("Бот отключен на время. Чтобы снова включить, используйте команду /start.", reply_markup=types.ReplyKeyboardRemove())
    except Exception as e:
        await message.answer("Произошла ошибка при отключении бота. Попробуйте позже.")

# Обработка выбора "Отключить навсегда"
@dp.message(F.text == "Отключить навсегда")
async def disable_permanently(message: types.Message):
    try:
        async with aiosqlite.connect('events.db') as db:
            await db.execute('UPDATE users SET is_active = 0 WHERE user_id = ?', (message.from_user.id,))
            await db.commit()
        await message.answer("Бот отключен навсегда. Спасибо за использование!", reply_markup=types.ReplyKeyboardRemove())
    except Exception as e:
        await message.answer("Произошла ошибка при отключении бота. Попробуйте позже.")

# Обработка выбора "Отмена"
@dp.message(F.text == "Отмена")
async def cancel_disable(message: types.Message):
    await message.answer("Отключение отменено.", reply_markup=get_user_keyboard(message.from_user.id))

# Функция для проверки напоминаний
async def check_reminders():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            async with aiosqlite.connect('events.db') as db:
                cursor = await db.execute('SELECT id, user_id, event_name, remind_datetime, repeat_interval FROM events WHERE remind_datetime = ?', (now,))
                reminders = await cursor.fetchall()

            for reminder in reminders:
                event_id, user_id, event_name, remind_datetime, repeat_interval = reminder

                # Проверяем, активен ли пользователь
                async with aiosqlite.connect('events.db') as db:
                    cursor = await db.execute('SELECT is_active FROM users WHERE user_id = ?', (user_id,))
                    user = await cursor.fetchone()
                if user and user[0]:  # Если пользователь активен
                    await bot.send_message(user_id, f"⏰ Напоминание: {event_name}!")

                    # Обновляем дату напоминания для повторяющихся событий
                    if repeat_interval != "none":
                        new_remind_datetime = calculate_next_reminder(remind_datetime, repeat_interval)
                        if new_remind_datetime:
                            async with aiosqlite.connect('events.db') as db:
                                await db.execute('''
                                UPDATE events SET remind_datetime = ? WHERE id = ?
                                ''', (new_remind_datetime.strftime("%Y-%m-%d %H:%M"), event_id))
                                await db.commit()
        except Exception as e:
            print(f"Ошибка при проверке напоминаний: {e}")

        await asyncio.sleep(60)  # Проверка каждую минуту

# Функция для расчета следующей даты напоминания
def calculate_next_reminder(remind_datetime: str, repeat_interval: str) -> datetime | None:
    """
    Вычисляет следующую дату напоминания на основе интервала повторения.
    """
    remind_datetime = datetime.strptime(remind_datetime, "%Y-%m-%d %H:%M")
    if repeat_interval == "daily":
        return remind_datetime + timedelta(days=1)
    elif repeat_interval == "weekly":
        return remind_datetime + timedelta(weeks=1)
    elif repeat_interval == "biweekly":  # Новый интервал
        return remind_datetime + timedelta(weeks=2)
    elif repeat_interval == "monthly":
        # Добавляем 1 месяц с учетом количества дней в месяце
        year = remind_datetime.year
        month = remind_datetime.month + 1
        if month > 12:
            month = 1
            year += 1
        day = remind_datetime.day
        try:
            return remind_datetime.replace(year=year, month=month, day=day)
        except ValueError:
            # Если дня нет (например, 31 февраля), берем последний день месяца
            last_day = calendar.monthrange(year, month)[1]
            return remind_datetime.replace(year=year, month=month, day=last_day)
    elif repeat_interval == "yearly":
        return remind_datetime.replace(year=remind_datetime.year + 1)
    else:
        return None

# Админка: Статистика по пользователям
@dp.message(F.text == "Статистика по пользователям", F.from_user.id == ADMIN_ID)
async def show_user_stats(message: types.Message):
    try:
        async with aiosqlite.connect('events.db') as db:
            # Общее количество пользователей
            cursor = await db.execute('SELECT COUNT(*) FROM users')
            total_users = (await cursor.fetchone())[0]

            # Количество активных пользователей
            cursor = await db.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
            active_users = (await cursor.fetchone())[0]

            # Получение списка пользователей
            cursor = await db.execute('SELECT user_id, username, first_name, last_name, registered_at FROM users')
            users = await cursor.fetchall()

        response = f"📊 Статистика по пользователям:\n"
        response += f"Всего пользователей: {total_users}\n"
        response += f"Активных пользователей: {active_users}\n\n"
        for user in users:
            response += f"🆔 {user[0]}\n"
            response += f"👤 Имя: {user[2]} {user[3]}\n"
            response += f"📧 Username: @{user[1]}\n"
            response += f"📅 Дата регистрации: {user[4]}\n\n"

        await message.answer(response)
    except Exception as e:
        await message.answer("Произошла ошибка при получении статистики по пользователям. Попробуйте позже.")
        print(f"Ошибка в show_user_stats: {e}")

# Админка: Статистика по событиям
@dp.message(F.text == "Статистика по событиям", F.from_user.id == ADMIN_ID)
async def show_event_stats(message: types.Message):
    try:
        async with aiosqlite.connect('events.db') as db:
            # Общее количество событий
            cursor = await db.execute('SELECT COUNT(*) FROM events')
            total_events = (await cursor.fetchone())[0]

            # Получение списка событий
            cursor = await db.execute('''
            SELECT events.id, events.event_name, events.remind_datetime, events.category, users.username
            FROM events
            JOIN users ON events.user_id = users.user_id
            ORDER BY events.remind_datetime ASC
            ''')
            events = await cursor.fetchall()

        response = f"📊 Статистика по событиям:\n"
        response += f"Всего событий: {total_events}\n\n"
        # for event in events:
        #     response += f"🆔 {event[0]}\n"
        #     response += f"📅 Событие: {event[1]}\n"
        #     response += f"📅 Напомнить: {event[2]}\n"
        #     response += f"📁 Категория: {event[3] if event[3] else 'Без категории'}\n"
        #     response += f"👤 Пользователь: @{event[4]}\n\n"

        await message.answer(response)
    except Exception as e:
        await message.answer("Произошла ошибка при получении статистики по событиям. Попробуйте позже.")
        print(f"Ошибка в show_event_stats: {e}")

# Админка: Статистика по категориям
@dp.message(F.text == "Статистика по категориям", F.from_user.id == ADMIN_ID)
async def show_category_stats(message: types.Message):
    try:
        async with aiosqlite.connect('events.db') as db:
            # Общее количество категорий
            cursor = await db.execute('SELECT COUNT(*) FROM categories')
            total_categories = (await cursor.fetchone())[0]

            # Получение списка категорий с количеством событий
            cursor = await db.execute('''
            SELECT categories.category_name, COUNT(events.id) as event_count
            FROM categories
            LEFT JOIN events ON categories.category_name = events.category
            GROUP BY categories.category_name
            ''')
            categories = await cursor.fetchall()

        response = f"📊 Статистика по категориям:\n"
        response += f"Всего категорий: {total_categories}\n\n"
        for category in categories:
            response += f"📁 Категория: {category[0]}\n"
            response += f"📅 Количество событий: {category[1]}\n\n"

        await message.answer(response)
    except Exception as e:
        await message.answer("Произошла ошибка при получении статистики по категориям. Попробуйте позже.")
        print(f"Ошибка в show_category_stats: {e}")

# Выход из админки
@dp.message(F.text == "Выйти из админки", F.from_user.id == ADMIN_ID)
async def exit_admin_panel(message: types.Message):
    await message.answer("Вы вышли из админки.", reply_markup=get_user_keyboard(message.from_user.id))

# Запуск бота
async def main():
    await init_db()
    loop = asyncio.get_event_loop()
    loop.create_task(check_reminders())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
