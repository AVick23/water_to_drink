import sqlite3
import re
import logging
from datetime import time
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    ConversationHandler,
    MessageHandler, 
    filters, 
    CallbackQueryHandler
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ЧЁТКИЕ СОСТОЯНИЯ ДЛЯ КАЖДОГО ШАГА
(
    ASKING_WEIGHT,
    ASKING_HEIGHT,
    ASKING_GENDER,
    ASKING_ACTIVITY,
    ASKING_NOTIFICATION_TIME,
    ASKING_CITY,
    AWAITING_WEIGHT_INPUT,
    AWAITING_HEIGHT_INPUT,
    AWAITING_START_TIME_INPUT,
    AWAITING_END_TIME_INPUT,
    AWAITING_CITY_INPUT
) = range(11)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('water_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        weight REAL NOT NULL,
        height REAL NOT NULL,
        gender TEXT NOT NULL,
        activity_level TEXT NOT NULL,
        start_time TEXT NOT NULL DEFAULT '08:00',
        end_time TEXT NOT NULL DEFAULT '22:00',
        city TEXT
    )
    ''')
    conn.commit()
    conn.close()

# Получение данных пользователя
def get_user(chat_id):
    conn = sqlite3.connect('water_tracker.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Сохранение данных пользователя
def save_user(chat_id, first_name, weight, height, gender, activity, start_time='08:00', end_time='22:00', city=None):
    conn = sqlite3.connect('water_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO users 
    (chat_id, first_name, weight, height, gender, activity_level, start_time, end_time, city)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (chat_id, first_name, weight, height, gender, activity, start_time, end_time, city))
    conn.commit()
    conn.close()

# Создание инлайн-клавиатуры для пола
def get_gender_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🙋‍♂️ Мужской", callback_data='gender_male'),
            InlineKeyboardButton("🙋‍♀️ Женский", callback_data='gender_female')
        ],
        [InlineKeyboardButton("🔙 Вернуться к весу", callback_data='back_to_weight')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Создание инлайн-клавиатуры для активности
def get_activity_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🚶‍♂️ Низкий", callback_data='activity_low'),
            InlineKeyboardButton("🏃‍♀️ Средний", callback_data='activity_medium'),
            InlineKeyboardButton("🏋️‍♂️ Высокий", callback_data='activity_high')
        ],
        [InlineKeyboardButton("🔙 Вернуться к полу", callback_data='back_to_gender')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Создание инлайн-клавиатуры для времени уведомлений
def get_notification_time_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🕗 Стандартное время (08:00-22:00)", callback_data='time_standard'),
            InlineKeyboardButton("⏰ Указать своё время", callback_data='time_custom')
        ],
        [InlineKeyboardButton("🔙 Вернуться к активности", callback_data='back_to_activity')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Создание инлайн-клавиатуры для города
def get_city_keyboard():
    keyboard = [
        [InlineKeyboardButton("⏭️ Пропустить этот шаг", callback_data='skip_city')],
        [InlineKeyboardButton("🔙 Вернуться к времени уведомлений", callback_data='back_to_time')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Валидация времени
def validate_time(time_str):
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
        return False
    
    try:
        hours, minutes = map(int, time_str.split(':'))
        return 0 <= hours <= 23 and 0 <= minutes <= 59
    except ValueError:
        return False

# Команда /start - ТОЧКА ВХОДА
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    
    if db_user:
        await update.message.reply_text(
            f"👋 Здравствуйте, {user.first_name}! Рад вас видеть! 💧\n\n"
            f"Надеюсь, вы не забываете пить водичку! 😊\n"
            f"Ваша норма на сегодня: *{calculate_water_norm(db_user)}* литров 💦\n"
            f"⏰ Уведомления: с {db_user[6]} до {db_user[7]}",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    # СБРОС ДАННЫХ ПРИ НОВОМ СТАРТЕ
    context.user_data.clear()
    
    # Переключение на первый шаг - запрос веса
    return await ask_weight(update, context)

# Расчёт нормы воды
def calculate_water_norm(user_data):
    weight = user_data[2]  # вес из БД
    activity_level = user_data[5]  # уровень активности
    
    # Базовый расчёт: 30 мл на 1 кг веса
    base_norm = weight * 0.03
    
    # Коэффициенты для активности
    activity_coefficients = {
        'низкий': 1.0,
        'средний': 1.2,
        'высокий': 1.5
    }
    
    final_norm = base_norm * activity_coefficients.get(activity_level.lower(), 1.0)
    return f"{final_norm:.1f}"

# ШАГ 1: ЗАПРОС ВЕСА
async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение на состояние запроса веса"""
    if update.message:
        await update.message.reply_text(
            f"👋 Привет! Я - ваш персональный помощник по питью воды! 💧\n\n"
            f"Чтобы правильно рассчитать вашу дневную норму воды, мне нужна немного информации.\n"
            f"Все данные защищены и используются только для расчётов! 🔒",
            reply_markup=ReplyKeyboardRemove()
        )
    
    message_text = (
        "⚖️ *ШАГ 1 ИЗ 6: ВЕС*\n\n"
        "Пожалуйста, введите ваш вес в килограммах (примеры: 65 или 72.5)\n\n"
        "💡 *Зачем это нужно?*\n"
        "От веса напрямую зависит количество воды, которое вам нужно пить. "
        "Чем больше вес - тем больше воды требуется вашему организму! 💪"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            message_text,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text(
            message_text,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
    
    return AWAITING_WEIGHT_INPUT

# ОБРАБОТКА ВВОДА ВЕСА
async def handle_weight_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Валидация и обработка ввода веса"""
    text = update.message.text.strip()
    
    # Валидация веса
    if not re.match(r'^\d+(\.\d{1,2})?$', text):
        await update.message.reply_text(
            "❌ *ОШИБКА ВВОДА!*\n\n"
            "Пожалуйста, введите вес в правильном формате:\n"
            "• Целое число: `65`\n"
            "• Десятичная дробь: `65.5`\n\n"
            "⚖️ *Примеры правильного ввода:*\n"
            "✅ 50\n"
            "✅ 55.5\n"
            "✅ 120\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_WEIGHT_INPUT
    
    weight_value = float(text)
    
    if weight_value < 30 or weight_value > 300:
        await update.message.reply_text(
            "⚠️ *НЕРЕАЛИСТИЧНЫЙ ВЕС!*\n\n"
            "Диапазон допустимых значений:\n"
            "• Минимум: 30 кг\n"
            "• Максимум: 300 кг\n\n"
            "⚖️ *Примеры правильного ввода:*\n"
            "✅ 65\n"
            "✅ 72.5\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_WEIGHT_INPUT
    
    context.user_data['weight'] = weight_value
    
    # Переход к следующему шагу
    return await ask_height(update, context)

# ШАГ 2: ЗАПРОС РОСТА
async def ask_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение на состояние запроса роста"""
    message_text = (
        "✅ *Вес успешно сохранён!*\n\n"
        "📏 *ШАГ 2 ИЗ 6: РОСТ*\n\n"
        "Введите ваш рост в сантиметрах (примеры: 175 или 168.5)\n\n"
        "💡 *Зачем это нужно?*\n"
        "Рост помогает точнее рассчитать вашу норму воды, "
        "особенно в сочетании с весом и уровнем активности! 📐"
    )
    
    await update.message.reply_text(
        message_text,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return AWAITING_HEIGHT_INPUT

# ОБРАБОТКА ВВОДА РОСТА
async def handle_height_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Валидация и обработка ввода роста"""
    text = update.message.text.strip()
    
    # Валидация роста
    if not re.match(r'^\d+(\.\d{1,2})?$', text):
        await update.message.reply_text(
            "❌ *ОШИБКА ВВОДА!*\n\n"
            "Пожалуйста, введите рост в правильном формате:\n"
            "• Целое число: `175`\n"
            "• Десятичная дробь: `168.5`\n\n"
            "📏 *Примеры правильного ввода:*\n"
            "✅ 160\n"
            "✅ 175.5\n"
            "✅ 200\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_HEIGHT_INPUT
    
    height_value = float(text)
    
    if height_value < 100 or height_value > 250:
        await update.message.reply_text(
            "⚠️ *НЕРЕАЛИСТИЧНЫЙ РОСТ!*\n\n"
            "Диапазон допустимых значений:\n"
            "• Минимум: 100 см\n"
            "• Максимум: 250 см\n\n"
            "📏 *Примеры правильного ввода:*\n"
            "✅ 165\n"
            "✅ 180.5\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_HEIGHT_INPUT
    
    context.user_data['height'] = height_value
    
    # Переход к следующему шагу
    return await ask_gender(update, context)

# ШАГ 3: ЗАПРОС ПОЛА
async def ask_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение на состояние запроса пола"""
    message_text = (
        "✅ *Рост успешно сохранён!*\n\n"
        "👤 *ШАГ 3 ИЗ 6: ПОЛ*\n\n"
        "Выберите ваш пол, нажав на кнопку ниже 👇\n\n"
        "💡 *Зачем это нужно?*\n"
        "Пол влияет на расчёт базовой нормы воды из-за различий в физиологии. "
        "Это поможет мне дать вам более точные рекомендации! 🔍"
    )
    
    await update.message.reply_text(
        message_text,
        parse_mode='Markdown',
        reply_markup=get_gender_keyboard()
    )
    
    return ASKING_GENDER

# ОБРАБОТКА ВЫБОРА ПОЛА
async def handle_gender_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора пола с валидацией"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    # Обработка возврата к предыдущему шагу
    if callback_data == 'back_to_weight':
        return await ask_weight(update, context)
    
    if callback_data not in ['gender_male', 'gender_female']:
        await query.edit_message_text(
            "❌ *НЕВЕРНЫЙ ВЫБОР!*\n\n"
            "Пожалуйста, выберите пол, нажав на одну из кнопок ниже:",
            parse_mode='Markdown',
            reply_markup=get_gender_keyboard()
        )
        return ASKING_GENDER
    
    gender_map = {
        'gender_male': 'мужской',
        'gender_female': 'женский'
    }
    
    context.user_data['gender'] = gender_map[callback_data]
    
    # Подтверждение выбора и переход к следующему шагу
    await query.edit_message_text(
        f"✅ *Пол успешно выбран: {context.user_data['gender'].capitalize()}*\n\n"
        "🏋️‍♂️ *ШАГ 4 ИЗ 6: УРОВЕНЬ АКТИВНОСТИ*\n\n"
        "Выберите ваш уровень физической активности 👇\n\n"
        "💡 *Зачем это нужно?*\n"
        "Чем активнее вы занимаетесь спортом или работаете, тем больше воды "
        "вам нужно пить для восполнения потерь! 💦",
        parse_mode='Markdown',
        reply_markup=get_activity_keyboard()
    )
    
    return ASKING_ACTIVITY

async def handle_activity_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора уровня активности с валидацией"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    # Обработка возврата к предыдущим шагам
    if callback_data == 'back_to_gender':
        return await ask_gender(update, context)
    
    if callback_data not in ['activity_low', 'activity_medium', 'activity_high']:
        await query.edit_message_text(
            "❌ *НЕВЕРНЫЙ ВЫБОР!*\n\n"
            "Пожалуйста, выберите уровень активности, нажав на одну из кнопок ниже:",
            parse_mode='Markdown',
            reply_markup=get_activity_keyboard()
        )
        return ASKING_ACTIVITY
    
    activity_map = {
        'activity_low': 'низкий',
        'activity_medium': 'средний',
        'activity_high': 'высокий'
    }
    
    context.user_data['activity'] = activity_map[callback_data]
    
    # Подтверждение выбора и переход к следующему шагу
    await query.edit_message_text(
        f"✅ *Уровень активности успешно выбран: {context.user_data['activity'].capitalize()}*\n\n"
        "⏰ *ШАГ 5 ИЗ 6: ВРЕМЯ УВЕДОМЛЕНИЙ*\n\n"
        "Когда вам удобно получать напоминания о питье воды? 💧\n\n"
        "💡 *Зачем это нужно?*\n"
        "Я рассчитаю оптимальное количество напоминаний в течение дня, "
        "учитывая вашу норму воды и выбранный временной диапазон. "
        "Каждое напоминание будет предлагать выпить примерно стакан воды (250 мл)! 🥤",
        parse_mode='Markdown',
        reply_markup=get_notification_time_keyboard()
    )
    
    return ASKING_NOTIFICATION_TIME

# ШАГ 5: ЗАПРОС ВРЕМЕНИ УВЕДОМЛЕНИЙ (обработка выбора)
async def handle_notification_time_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора времени уведомлений"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    # Обработка возврата к предыдущему шагу
    if callback_data == 'back_to_activity':
        return await handle_activity_choice(update, context)
    
    if callback_data == 'time_standard':
        # Установка стандартного времени
        context.user_data['start_time'] = '08:00'
        context.user_data['end_time'] = '22:00'
        
        await query.edit_message_text(
            "✅ *Стандартное время выбрано!*\n\n"
            "🕗 Уведомления будут приходить с 08:00 до 22:00\n\n"
            "🏙️ *ШАГ 6 ИЗ 6: ГОРОД*\n\n"
            "Теперь укажите ваш город (примеры: Москва или New York)\n\n"
            "💡 *Зачем это нужно?* (необязательно)\n"
            "Если вы укажете город, каждое утро я буду присылать вам:\n"
            "• Прогноз погоды на день ☀️🌧️\n"
            "• Персонализированную рекомендацию по потреблению воды\n"
            "• Напоминания с учётом погодных условий\n\n"
            "👉 Если хотите пропустить этот шаг, нажмите кнопку ниже:",
            parse_mode='Markdown',
            reply_markup=get_city_keyboard()
        )
        return ASKING_CITY
    
    elif callback_data == 'time_custom':
        # Переход к состоянию ожидания времени начала
        # ВАЖНО: сохраняем состояние в user_data для правильной работы
        context.user_data['current_state'] = AWAITING_START_TIME_INPUT
        
        # Отправляем сообщение о вводе времени начала
        await query.message.reply_text(
            "⏰ *УКАЖИТЕ СВОЁ ВРЕМЯ*\n\n"
            "🕗 С какого времени начинать присылать уведомления?\n"
            "Введите время в формате ЧЧ:ММ (пример: 09:30)\n\n"
            "💡 Минимальное время: 06:00\n"
            "Диапазон для уведомлений должен быть не менее 4 часов!",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Удаляем предыдущее сообщение с кнопками
        await query.message.delete()
        
        return AWAITING_START_TIME_INPUT
    
    else:
        await query.edit_message_text(
            "❌ *НЕВЕРНЫЙ ВЫБОР!*\n\n"
            "Пожалуйста, выберите вариант времени из кнопок ниже:",
            parse_mode='Markdown',
            reply_markup=get_notification_time_keyboard()
        )
        return ASKING_NOTIFICATION_TIME

# ОБРАБОТКА ВВОДА ВРЕМЕНИ НАЧАЛА
async def handle_start_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Валидация и обработка ввода времени начала"""
    time_str = update.message.text.strip()
    
    if not validate_time(time_str):
        await update.message.reply_text(
            "❌ *НЕВЕРНЫЙ ФОРМАТ ВРЕМЕНИ!*\n\n"
            "Пожалуйста, введите время в формате ЧЧ:ММ\n\n"
            "🕗 *Примеры правильного ввода:*\n"
            "✅ 08:00\n"
            "✅ 09:30\n"
            "✅ 12:45\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_START_TIME_INPUT
    
    try:
        hours, minutes = map(int, time_str.split(':'))
        start_time = time(hours, minutes)
        
        # Минимальное время - 06:00
        if start_time < time(6, 0):
            raise ValueError("Слишком раннее время (минимум 06:00)")
        
        context.user_data['start_time'] = time_str
        
        # Переход к состоянию ожидания времени окончания
        context.user_data['current_state'] = AWAITING_END_TIME_INPUT
        
        # Запрос времени окончания
        await update.message.reply_text(
            f"✅ *Время начала: {time_str}*\n\n"
            "🕕 До какого времени присылать уведомления?\n"
            "Введите время в формате ЧЧ:ММ (пример: 21:00)\n\n"
            "💡 Максимальное время: 23:59\n"
            "Разница между началом и окончанием должна быть не менее 4 часов!",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_END_TIME_INPUT
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ *ОШИБКА: {str(e)}*\n\n"
            "🕗 Пожалуйста, введите корректное время начала:\n"
            "• Минимум: 06:00\n"
            "• Формат: ЧЧ:ММ\n\n"
            "🕗 *Примеры правильного ввода:*\n"
            "✅ 08:00\n"
            "✅ 09:30\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_START_TIME_INPUT

# ОБРАБОТКА ВВОДА ВРЕМЕНИ ОКОНЧАНИЯ
async def handle_end_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Валидация и обработка ввода времени окончания"""
    time_str = update.message.text.strip()
    
    if not validate_time(time_str):
        await update.message.reply_text(
            "❌ *НЕВЕРНЫЙ ФОРМАТ ВРЕМЕНИ!*\n\n"
            "Пожалуйста, введите время в формате ЧЧ:ММ\n\n"
            "🕕 *Примеры правильного ввода:*\n"
            "✅ 21:00\n"
            "✅ 22:30\n"
            "✅ 23:45\n\n"
            "Попробуйте ещё раз:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_END_TIME_INPUT
    
    try:
        hours, minutes = map(int, time_str.split(':'))
        end_time = time(hours, minutes)
        start_time_str = context.user_data['start_time']
        start_hours, start_minutes = map(int, start_time_str.split(':'))
        start_time = time(start_hours, start_minutes)
        
        # Максимальное время - 23:59
        if end_time > time(23, 59):
            raise ValueError("Слишком позднее время (максимум 23:59)")
        
        # Проверка минимального диапазона (4 часа)
        time_diff = (end_time.hour * 60 + end_time.minute) - (start_time.hour * 60 + start_time.minute)
        if time_diff < 240:  # 4 часа = 240 минут
            raise ValueError("Диапазон времени должен быть не менее 4 часов")
        
        # Проверка, что время окончания позже начала
        if end_time <= start_time:
            raise ValueError("Время окончания должно быть позже времени начала")
        
        context.user_data['end_time'] = time_str
        
        # Переход к следующему шагу
        await update.message.reply_text(
            f"✅ *Время уведомлений установлено!*\n\n"
            f"🕗 С {context.user_data['start_time']} до {context.user_data['end_time']}\n\n"
            f"🏙️ *ШАГ 6 ИЗ 6: ГОРОД*\n\n"
            f"Теперь укажите ваш город (примеры: Москва или New York)\n\n"
            f"💡 *Зачем это нужно?* (необязательно)\n"
            f"Если вы укажете город, каждое утро я буду присылать вам:\n"
            f"• Прогноз погоды на день ☀️🌧️\n"
            f"• Персонализированную рекомендацию по потреблению воды\n"
            f"• Напоминания с учётом погодных условий\n\n"
            f"👉 Если хотите пропустить этот шаг, нажмите кнопку ниже:",
            parse_mode='Markdown',
            reply_markup=get_city_keyboard()
        )
        return ASKING_CITY
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ *ОШИБКА: {str(e)}*\n\n"
            "🕕 Пожалуйста, введите корректное время окончания:\n"
            "• Максимум: 23:59\n"
            "• Должно быть позже времени начала\n"
            "• Диапазон не менее 4 часов\n\n"
            "🕕 *Примеры правильного ввода:*\n"
            "✅ 21:00\n"
            "✅ 22:30\n\n"
            "Попробуйте ещё раз или вернитесь к началу:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Вернуться к началу", callback_data='back_to_start_time')]
            ])
        )
        return AWAITING_END_TIME_INPUT

# Обработка возврата к времени начала
async def back_to_start_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Возврат к состоянию ввода времени начала
    context.user_data['current_state'] = AWAITING_START_TIME_INPUT
    
    await query.message.reply_text(
        "🕗 С какого времени начинать присылать уведомления?\n"
        "Введите время в формате ЧЧ:ММ (пример: 09:30)\n\n"
        "💡 Минимальное время: 06:00\n"
        "Диапазон для уведомлений должен быть не менее 4 часов!",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Удаляем предыдущее сообщение
    await query.message.delete()
    
    return AWAITING_START_TIME_INPUT

# ШАГ 6: ЗАПРОС ГОРОДА
async def handle_city_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода города с валидацией"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        # Обработка пропуска города
        if query.data == 'skip_city':
            context.user_data['city'] = None
            await query.edit_message_text("⏭️ *Город пропущен!*\n\nПодготавливаю ваш профиль...", parse_mode='Markdown')
            return await final_save(update, context)
        
        # Обработка возврата к предыдущему шагу
        if query.data == 'back_to_time':
            # Возврат к шагу времени уведомлений
            await query.edit_message_text(
                "⏰ *ВРЕМЯ УВЕДОМЛЕНИЙ*\n\n"
                "Когда вам удобно получать напоминания о питье воды? 💧\n\n"
                "💡 *Зачем это нужно?*\n"
                "Я рассчитаю оптимальное количество напоминаний в течение дня, "
                "учитывая вашу норму воды и выбранный временной диапазон. "
                "Каждое напоминание будет предлагать выпить примерно стакан воды (250 мл)! 🥤",
                parse_mode='Markdown',
                reply_markup=get_notification_time_keyboard()
            )
            return ASKING_NOTIFICATION_TIME
    
    # Обработка текстового ввода города
    if update.message:
        city_name = update.message.text.strip()
        
        # Валидация названия города
        if len(city_name) < 2 or len(city_name) > 50 or not re.match(r'^[а-яА-Яa-zA-ZёЁ\s\-]+$', city_name):
            await update.message.reply_text(
                "❌ *ОШИБКА ВВОДА!*\n\n"
                "Название города должно:\n"
                "• Содержать только буквы и пробелы\n"
                "• Быть от 2 до 50 символов\n\n"
                "🏙️ *Примеры правильного ввода:*\n"
                "✅ Москва\n"
                "✅ Санкт-Петербург\n"
                "✅ New York\n"
                "✅ Los Angeles\n\n"
                "Попробуйте ещё раз или нажмите 'Пропустить':",
                parse_mode='Markdown',
                reply_markup=get_city_keyboard()
            )
            return ASKING_CITY
        
        context.user_data['city'] = city_name
    
    return await final_save(update, context)

# ФИНАЛЬНОЕ СОХРАНЕНИЕ ДАННЫХ
async def final_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение всех данных и завершение регистрации"""
    user = update.effective_user if update.message else update.callback_query.from_user
    chat_id = user.id
    
    # Получение времени (стандартные значения, если не заданы)
    start_time = context.user_data.get('start_time', '08:00')
    end_time = context.user_data.get('end_time', '22:00')
    
    save_user(
        chat_id=chat_id,
        first_name=user.first_name,
        weight=context.user_data['weight'],
        height=context.user_data['height'],
        gender=context.user_data['gender'],
        activity=context.user_data['activity'],
        start_time=start_time,
        end_time=end_time,
        city=context.user_data.get('city')
    )
    
    city_msg = f"🏙️ Город: {context.user_data['city']}\n" if context.user_data.get('city') else ""
    water_norm = calculate_water_norm((
        None, None,
        context.user_data['weight'],
        context.user_data['height'],
        context.user_data['gender'],
        context.user_data['activity'],
        None
    ))
    
    # Расчёт количества напоминаний
    start_h, start_m = map(int, start_time.split(':'))
    end_h, end_m = map(int, end_time.split(':'))
    total_minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
    glass_size = 250  # мл
    total_ml = float(water_norm) * 1000  # переводим литры в мл
    num_reminders = max(1, int(total_ml / glass_size))
    
    # Финальное сообщение
    final_message = (
        f"🎉 *ПОЗДРАВЛЯЮ, {user.first_name}!*\n\n"
        f"✅ *Все данные успешно сохранены!*\n\n"
        f"📋 *Ваш профиль:*\n"
        f"⚖️ Вес: {context.user_data['weight']} кг\n"
        f"📏 Рост: {context.user_data['height']} см\n"
        f"👤 Пол: {context.user_data['gender']}\n"
        f"🏃‍♂️ Активность: {context.user_data['activity']}\n"
        f"⏰ Уведомления: с {start_time} до {end_time}\n"
        f"{city_msg}\n"
        f"💧 *Ваша дневная норма воды: {water_norm} литров*\n"
        f"🛎️ *Количество напоминаний: ~{num_reminders} раз в день*\n\n"
        f"✨ *Что дальше?*\n"
        f"• Я буду автоматически напоминать вам пить водичку! 💦\n"
        f"• Каждое напоминание - примерно стакан воды (250 мл) 🥤\n"
        f"• Если указан город - каждое утро получите прогноз погоды ☀️🌧️\n\n"
        f"Спасибо, что заботитесь о своём здоровье! ❤️"
    )
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            final_message,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text(
            final_message,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
    
    # Очистка данных в контексте
    context.user_data.clear()
    
    return ConversationHandler.END

# Обработка команды /cancel - но мы НЕ даём отменить регистрацию!
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Блокировка отмены регистрации"""
    user = update.effective_user
    
    await update.message.reply_text(
        "🚫 *РЕГИСТРАЦИЮ НЕЛЬЗЯ ОТМЕНИТЬ!*\n\n"
        "❗️ Для корректной работы бота необходимо заполнить все данные.\n"
        f"Вы на шаге: {get_current_step(context)}\n\n"
        "💧 Помните: правильное потребление воды - это важно для вашего здоровья! ❤️\n"
        "Пожалуйста, продолжите регистрацию.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Возврат на текущий шаг
    current_state = context.user_data.get('current_state', ASKING_WEIGHT)
    
    if current_state == ASKING_WEIGHT or current_state == AWAITING_WEIGHT_INPUT:
        return await ask_weight(update, context)
    elif current_state == ASKING_HEIGHT or current_state == AWAITING_HEIGHT_INPUT:
        return await ask_height(update, context)
    elif current_state == ASKING_GENDER:
        return await ask_gender(update, context)
    elif current_state == ASKING_ACTIVITY:
        return await handle_activity_choice(update, context)
    elif current_state == ASKING_NOTIFICATION_TIME or current_state in [AWAITING_START_TIME_INPUT, AWAITING_END_TIME_INPUT]:
        # Возврат к шагу времени уведомлений
        await update.message.reply_text(
            "⏰ *ВРЕМЯ УВЕДОМЛЕНИЙ*\n\n"
            "Когда вам удобно получать напоминания о питье воды? 💧\n\n"
            "💡 *Зачем это нужно?*\n"
            "Я рассчитаю оптимальное количество напоминаний в течение дня, "
            "учитывая вашу норму воды и выбранный временной диапазон. "
            "Каждое напоминание будет предлагать выпить примерно стакан воды (250 мл)! 🥤",
            parse_mode='Markdown',
            reply_markup=get_notification_time_keyboard()
        )
        return ASKING_NOTIFICATION_TIME
    elif current_state == ASKING_CITY:
        return await handle_city_input(update, context)
    
    return await ask_weight(update, context)

def get_current_step(context):
    """Возвращает название текущего шага для сообщения"""
    state_map = {
        ASKING_WEIGHT: "Запрос веса",
        AWAITING_WEIGHT_INPUT: "Ввод веса",
        ASKING_HEIGHT: "Запрос роста",
        AWAITING_HEIGHT_INPUT: "Ввод роста",
        ASKING_GENDER: "Выбор пола",
        ASKING_ACTIVITY: "Выбор активности",
        ASKING_NOTIFICATION_TIME: "Настройка времени уведомлений",
        AWAITING_START_TIME_INPUT: "Ввод времени начала",
        AWAITING_END_TIME_INPUT: "Ввод времени окончания",
        ASKING_CITY: "Ввод города"
    }
    return state_map.get(context.user_data.get('current_state', ASKING_WEIGHT), "Начало регистрации")

# Основная функция
def main():
    init_db()
    
    application = Application.builder().token("7502354287:AAGW-s-unwW_pOVrhvdpN0NBTq8-IDsIOvM").build()
    
    # ЕДИНСТВЕННЫЙ ConversationHandler для ВСЕХ состояний
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # ШАГ 1: ВЕС
            AWAITING_WEIGHT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_input)
            ],
            
            # ШАГ 2: РОСТ
            AWAITING_HEIGHT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_height_input)
            ],
            
            # ШАГ 3: ПОЛ
            ASKING_GENDER: [
                CallbackQueryHandler(handle_gender_choice, pattern='^gender_'),
                CallbackQueryHandler(ask_weight, pattern='^back_to_weight$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_invalid_text_during_choice(u, c, ASKING_GENDER))
            ],
            
            # ШАГ 4: АКТИВНОСТЬ
            ASKING_ACTIVITY: [
                CallbackQueryHandler(handle_activity_choice, pattern='^activity_'),
                CallbackQueryHandler(ask_gender, pattern='^back_to_gender$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_invalid_text_during_choice(u, c, ASKING_ACTIVITY))
            ],
            
            # ШАГ 5: ВРЕМЯ УВЕДОМЛЕНИЙ
            ASKING_NOTIFICATION_TIME: [
                CallbackQueryHandler(handle_notification_time_choice, pattern='^time_'),
                CallbackQueryHandler(handle_activity_choice, pattern='^back_to_activity$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_invalid_text_during_choice(u, c, ASKING_NOTIFICATION_TIME))
            ],
            
            AWAITING_START_TIME_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_start_time_input),
                CallbackQueryHandler(back_to_start_time, pattern='^back_to_start_time$')
            ],
            
            AWAITING_END_TIME_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_end_time_input),
                CallbackQueryHandler(back_to_start_time, pattern='^back_to_start_time$')
            ],
            
            # ШАГ 6: ГОРОД
            ASKING_CITY: [
                CallbackQueryHandler(handle_city_input, pattern='^skip_city$'),
                CallbackQueryHandler(handle_city_input, pattern='^back_to_time$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city_input)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    
    application.add_handler(conv_handler)
    
    # Добавляем обработчик для всех остальных сообщений (игнорируем после завершения)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown_command))
    application.add_handler(CallbackQueryHandler(handle_unknown_callback))
    
    application.run_polling()

# Обработка неизвестных команд после завершения регистрации
async def handle_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игнорирование текстовых сообщений после завершения диалога"""
    if not get_user(update.effective_user.id):
        # Если пользователь не зарегистрирован, перенаправляем на старт
        return await start(update, context)
    
    await update.message.reply_text(
        "💧 Я понимаю только команды! Используйте:\n"
        "/drink - записать выпитую воду\n"
        "/stats - посмотреть статистику\n"
        "/update - обновить данные профиля",
        reply_markup=ReplyKeyboardRemove()
    )

# Обработка неизвестных callback после завершения регистрации
async def handle_unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игнорирование старых кнопок после завершения диалога"""
    query = update.callback_query
    await query.answer()
    
    if not get_user(update.effective_user.id):
        # Если пользователь не зарегистрирован
        await query.edit_message_text(
            "❌ Эта кнопка больше не активна. Пожалуйста, начните регистрацию командой /start"
        )
        return
    
    await query.edit_message_text(
        "💧 Эта кнопка больше не активна. Используйте команды:\n"
        "/drink - записать выпитую воду\n"
        "/stats - посмотреть статистику"
    )

# Обработка текстового ввода во время выбора с кнопками
async def handle_invalid_text_during_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, state):
    """Обработка текстового ввода когда ожидается выбор кнопок"""
    messages = {
        ASKING_GENDER: (
            "❌ *НЕПРАВИЛЬНЫЙ ВВОД!*\n\n"
            "На этом шаге нужно выбрать пол, нажав на кнопку ниже.\n"
            "Пожалуйста, используйте инлайн-кнопки для выбора."
        ),
        ASKING_ACTIVITY: (
            "❌ *НЕПРАВИЛЬНЫЙ ВВОД!*\n\n"
            "На этом шаге нужно выбрать уровень активности, нажав на кнопку ниже.\n"
            "Пожалуйста, используйте инлайн-кнопки для выбора."
        ),
        ASKING_NOTIFICATION_TIME: (
            "❌ *НЕПРАВИЛЬНЫЙ ВВОД!*\n\n"
            "На этом шаге нужно выбрать вариант времени, нажав на кнопку ниже.\n"
            "Пожалуйста, используйте инлайн-кнопки для выбора."
        )
    }
    
    keyboards = {
        ASKING_GENDER: get_gender_keyboard(),
        ASKING_ACTIVITY: get_activity_keyboard(),
        ASKING_NOTIFICATION_TIME: get_notification_time_keyboard()
    }
    
    await update.message.reply_text(
        messages.get(state, "❌ Неправильный ввод! Пожалуйста, используйте кнопки ниже."),
        parse_mode='Markdown',
        reply_markup=keyboards.get(state, ReplyKeyboardRemove())
    )
    
    return state

if __name__ == "__main__":
    main()