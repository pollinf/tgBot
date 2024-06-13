import telebot, uuid, itertools, sqlite3
from telebot import TeleBot, types
from telebot.handler_backends import StatesGroup, State
from collections import defaultdict

bot = TeleBot("token") 
# Определение состояний для машины состояний
class TaskState(StatesGroup):
    waiting_for_task_text = State()  # Ожидание текста задачи
    waiting_for_task_number = State()  # Ожидание номера задачи для удаления
    waiting_for_task_deletion_confirmation = State() # Ожидание подтверждения удаления задачи
    waiting_for_new_task_name = State()  # Ожидание нового названия задачи
    waiting_for_menu_return = State()  # Возврат в меню
    waiting_for_search_query = State()  # Ожидание запроса для поиска задачи

# Словарь для хранения состояний пользователей
user_states = {}

def set_user_state(user_id, state):
    user_states[user_id] = state

def get_user_state(user_id):
    return user_states.get(user_id, None)

def reset_user_state(user_id):
    if user_id in user_states:
        del user_states[user_id]

# Функция для создания таблицы задач, если она еще не существует
def create_tasks_table():
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                task_name TEXT
            )
        ''')
        conn.commit()
create_tasks_table()

def create_users_table():
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
        ''')
        conn.commit()
create_users_table()

# Создание таблицы для связи задач с пользователями
def create_task_users_table():
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_users (
                task_id INTEGER,
                user_id INTEGER,
                FOREIGN KEY (task_id) REFERENCES tasks (id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        conn.commit()
create_task_users_table()

# Функция для добавления пользователя в базу данных (если еще не добавлен)
def add_user_to_db(user_id, username):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        # Проверяем, есть ли уже пользователь в базе
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        if cursor.fetchone() is None:
            # Если никнейм отсутствует, используем user_id в качестве username
            username_to_insert = username if username else str(user_id)
            # Если пользователя нет, добавляем его с проверкой на никнейм
            cursor.execute('INSERT INTO users (user_id, username) VALUES (?, ?)', (user_id, username_to_insert))
            conn.commit()
            
# Функция для добавления задачи в базу данных
def add_task_to_db(chat_id, user_id, username, task_name):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        # Сначала добавляем пользователя в базу данных, если он ещё не добавлен
        add_user_to_db(user_id, username)
        # Затем добавляем задачу
        cursor.execute('INSERT INTO tasks (chat_id, user_id, task_name) VALUES (?, ?, ?)',
                       (chat_id, user_id, task_name))
        conn.commit()
 
# Функция для получения списка всех задач из базы данных с никнеймами пользователей или без них
def list_all_tasks_from_db():
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.id, COALESCE(u.username, 'Никто'), t.task_name
            FROM tasks t
            LEFT JOIN users u ON t.user_id = u.user_id
            ORDER BY t.id ASC
        ''')
        all_tasks = cursor.fetchall()
    return all_tasks

# Функция для удаления задачи из базы данных
def delete_task_from_db(task_number):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tasks WHERE id = ?', (task_number,))
        conn.commit()

# Функция для получения имени пользователя по идентификатору задачи
def get_username_by_task_number(task_number):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.username
            FROM tasks t
            JOIN users u ON t.user_id = u.user_id
            WHERE t.id = ?
        ''', (task_number,))
        username = cursor.fetchone()
        return username[0] if username else 'Никто'

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    add_task_btn = types.KeyboardButton("Добавить")
    delete_task_btn = types.KeyboardButton("Удалить")
    view_tasks_btn = types.KeyboardButton("Список")
    view_my_tasks_btn = types.KeyboardButton("Мои\x20Задачи") 
    search_task_btn = types.KeyboardButton("Поиск") 
    take_task_btn = types.KeyboardButton("Взять")
    markup.add(add_task_btn, delete_task_btn, view_tasks_btn, view_my_tasks_btn, search_task_btn, take_task_btn)
    bot.send_message(message.chat.id, "Здравствуйте, {}. Я бот для управления задачами. Выберите нужное: ".format(message.from_user.first_name), reply_markup=markup)
    
# Функция для получения общего количества задач
def get_total_tasks_count():
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM tasks')
        count = cursor.fetchone()[0]
    return count

# Функция для получения количества задач конкретного пользователя
def get_user_tasks_count(user_id):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ?', (user_id,))
        count = cursor.fetchone()[0]
    return count

# Обработчик команды /view_tasks
@bot.message_handler(func=lambda message: message.text.lower() == "Список".lower()) 
def list_handler(message): 
    with sqlite3.connect('tasks.db') as conn: 
        cursor = conn.cursor() 
        # Выбираем только те задачи, которые кто-то взял 
        cursor.execute(''' 
            SELECT t.id, t.task_name, GROUP_CONCAT(u.username) AS user_names 
            FROM tasks t 
            JOIN task_users tu ON t.id = tu.task_id 
            JOIN users u ON tu.user_id = u.user_id 
            GROUP BY t.id 
            HAVING COUNT(tu.user_id) > 0 
            ORDER BY t.id ASC
        ''') 
        tasks = cursor.fetchall() 
 
    chat_id = message.chat.id 
    tasks_info = "Список всех задач:\n" 
    for task_number, (id, task_name, user_names) in enumerate(tasks, start=1): 
        task_users = [username.strip() for username in user_names.split(',')] if user_names else [] 
        user_names_formatted = ', '.join([f"@{username}" for username in task_users]) 
        tasks_info += f"{task_number}: {task_name} (Взяли: {user_names_formatted})\n" 
 
    if tasks: 
        bot.send_message(chat_id, tasks_info) 
    else: 
        bot.send_message(chat_id, 'Список задач пуст')

# функция добавлялет задачу
def add_task_to_db(chat_id, user_id, username, task_name):
    # Добавляем пользователя в базу данных, если его там нет
    add_user_to_db(user_id, username)
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO tasks (chat_id, user_id, task_name) VALUES (?, ?, ?)',
                       (chat_id, user_id, task_name))
        conn.commit()
        
# Обработчик команды /add_task 
@bot.message_handler(func=lambda message: message.text.lower() == "Добавить".lower())
def handle_add_task(message):
    set_user_state(message.from_user.id, TaskState.waiting_for_task_text)
    bot.send_message(message.chat.id, 'Введите текст задачи:')
    bot.register_next_step_handler(message, receive_task)

# Функция для проверки существования задачи в базе данных
def task_exists(chat_id, task_name):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tasks WHERE chat_id = ? AND task_name = ?', (chat_id, task_name))
        return cursor.fetchone() is not None

# функция для приёма текста задачи от пользователя
def receive_task(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username
    task_text = message.text
    if task_exists(chat_id, task_text):
        markup = types.InlineKeyboardMarkup()
        new_task_btn = types.InlineKeyboardButton('Ввести новое название', callback_data='new_task_name')
        return_menu_btn = types.InlineKeyboardButton('Вернуться в меню', callback_data='return_menu')
        markup.add(new_task_btn, return_menu_btn)
        bot.send_message(chat_id, f'Задача с названием "{task_text}" уже существует.', reply_markup=markup)
    else:
        add_task_to_db(chat_id, user_id, username, task_text)
        bot.send_message(chat_id, f'Задача "{task_text}" успешно добавлена!')

# Обработчик callback_query для новых кнопок
@bot.callback_query_handler(func=lambda call: call.data in ['new_task_name', 'return_menu'])
def handle_callback_query(call):
    if call.data == 'new_task_name':
        set_user_state(call.from_user.id, TaskState.waiting_for_new_task_name)
        bot.send_message(call.message.chat.id, 'Введите новое название задачи:')
    elif call.data == 'return_menu':
        reset_user_state(call.from_user.id)
        send_welcome(call.message)

# Функция для приёма нового названия задачи от пользователя
def receive_new_task_name(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username
    task_name = message.text

    if task_exists(chat_id, task_name):
        markup = types.InlineKeyboardMarkup()
        new_task_btn = types.InlineKeyboardButton('Ввести новое название', callback_data='new_task_name')
        return_menu_btn = types.InlineKeyboardButton('Вернуться в меню', callback_data='return_menu')
        markup.add(new_task_btn, return_menu_btn)
        bot.send_message(chat_id, 'Задача с таким названием уже существует. Попробуйте другое название.', reply_markup=markup)
    else:
        add_task_to_db(chat_id, user_id, username, task_name)
        bot.send_message(chat_id, f'Новая задача "{task_name}" успешно добавлена!')
        reset_user_state(user_id)

# Регистрируем новую функцию для состояния waiting_for_new_task_name
@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == TaskState.waiting_for_new_task_name)
def handle_new_task_name(message):
    receive_new_task_name(message)
       
# Обработчик команды /delete_task
@bot.message_handler(func=lambda message: message.text.lower() == "Удалить".lower())
def handle_delete_task(message):
    user_id = message.from_user.id  # Получаем user_id из сообщения
    # Получаем задачи, взятые пользователем
    user_tasks = list_users_tasks_from_db(user_id)

    if user_tasks:
        markup = types.InlineKeyboardMarkup()
        # Создаём кнопки для каждой взятой задачи
        for task_id, task_name in user_tasks:
            markup.add(types.InlineKeyboardButton(task_name, callback_data=f"delete:{task_id}"))
        bot.send_message(message.chat.id, "Выберите задачу, которую хотите отменить:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет взятых задач.")

# Функция для обработки callback_query от InlineKeyboardButton
@bot.callback_query_handler(func=lambda call: call.data.startswith('delete:'))
def handle_task_deletion(call):
    task_id = int(call.data.split(':')[1])
    user_id = call.from_user.id
    # Удаляем задачу из списка взятых пользователем
    delete_user_task_from_db(task_id, user_id)
    bot.answer_callback_query(call.id, "Ваша задача отменена.")
    bot.edit_message_text("Вы отменили задачу.", call.message.chat.id, call.message.message_id)

# Функция для удаления взятой задачи пользователем из базы данных
def delete_user_task_from_db(task_id, user_id):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        # Удаляем запись о взятой задаче пользователем
        cursor.execute('DELETE FROM task_users WHERE task_id = ? AND user_id = ?', (task_id, user_id))
        conn.commit()

# Функция для получения списка всех взятых задач конкретного пользователя из базы данных
def list_users_tasks_from_db(user_id):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        # Выбираем все взятые задачи для пользователя
        cursor.execute('''
            SELECT t.id, t.task_name
            FROM task_users tu
            JOIN tasks t ON tu.task_id = t.id
            WHERE tu.user_id = ?
            ORDER BY t.task_name ASC
        ''', (user_id,))
        # Получаем все взятые задачи пользователя
        tasks_for_user = cursor.fetchall()
    return tasks_for_user

@bot.message_handler(func=lambda message: message.text.lower() == "Мои\x20Задачи".lower()) 
def handle_view_my_tasks(message): 
    user_id = message.from_user.id 
    tasks = list_users_tasks_from_db(user_id) 
    chat_id = message.chat.id 
    
    # Проверка наличия задач у пользователя
    if tasks:
        tasks_info = "Ваши задачи:\n" 
        for task_number, (task_id, task_name) in enumerate(tasks, start=1): 
            tasks_info += f"{task_number}: {task_name}\n" 
        bot.send_message(chat_id, tasks_info) 
    else: 
        bot.send_message(chat_id, 'Список Ваших задач пуст')

# Обработчик команды /search_task
@bot.message_handler(func=lambda message: message.text.lower() == "поиск".lower())
def handle_search_task_command(message):
    # Устанавливаем состояние пользователя на ожидание текста для поиска
    set_user_state(message.from_user.id, TaskState.waiting_for_search_query)
    bot.send_message(message.chat.id, "Введите текст задачи для поиска:")

# Обработчик текстовых сообщений для поиска задач, когда пользователь в состоянии ожидания текста задачи
@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == TaskState.waiting_for_search_query)
def handle_task_search_text(message):
    # Получаем текст для поиска от пользователя
    search_text = message.text.strip().lower()
    # Выполняем поиск задач
    found_tasks = search_tasks(search_text)
    # Формируем ответное сообщение
    response_message = "Найденные задачи:\n" + "\n".join(f"{task[0]} - {task[1]}" for task in found_tasks) if found_tasks else "Задачи не найдены."
    # Отправляем ответное сообщение
    bot.send_message(message.chat.id, response_message)
    # Сброс состояния пользователя должен происходить после отправки сообщения
    reset_user_state(message.from_user.id)

def search_tasks(search_text):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.task_name, GROUP_CONCAT('@' || u.username) AS user_nicknames
            FROM tasks AS t
            LEFT JOIN task_users AS tu ON t.id = tu.task_id
            LEFT JOIN users AS u ON tu.user_id = u.user_id
            WHERE LOWER(t.task_name) LIKE ?
            GROUP BY t.task_name
            ORDER BY t.task_name ASC;
        ''', ('%' + search_text.lower() + '%',))
        found_tasks = cursor.fetchall()
        return found_tasks

def reset_user_state(user_id):
    user_states.pop(user_id, None) # Удаляем состояние пользователя, если оно есть
    pass

# Обработчик команды /take_task
@bot.message_handler(func=lambda message: message.text.lower() == "Взять".lower())
def handle_take_task(message):
    user_id = message.from_user.id
    tasks = list_all_tasks_from_db()  # Получаем список всех задач
    markup = types.InlineKeyboardMarkup()
    for task_id, username, task_name in tasks:
        # Создаем кнопку для каждой задачи
        markup.add(types.InlineKeyboardButton(task_name, callback_data=f"take:{task_id}"))
    bot.send_message(message.chat.id, "Выберите задачу для взятия:", reply_markup=markup)

# Функция для обработки callback_query от InlineKeyboardButton
@bot.callback_query_handler(func=lambda call: call.data.startswith('take:'))
def handle_task_taking(call):
    task_id = int(call.data.split(':')[1])
    user_id = call.from_user.id
    if not is_task_taken(task_id, user_id):
        take_task(user_id, task_id)
        bot.answer_callback_query(call.id, "Задача взята.")
        bot.edit_message_text("Вы взяли задачу.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Эту задачу уже взяли.", show_alert=True)

# Функция для проверки, взял ли уже пользователь задачу
def is_task_taken(task_id, user_id):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM task_users WHERE task_id = ? AND user_id = ?', (task_id, user_id))
        return cursor.fetchone() is not None

# Функция для "взятия" задачи пользователем
def take_task(user_id, task_id):
    with sqlite3.connect('tasks.db') as conn:
        cursor = conn.cursor()
        # Добавляем запись о том, что пользователь взял задачу
        cursor.execute('INSERT INTO task_users (task_id, user_id) VALUES (?, ?)', (task_id, user_id))
        conn.commit()

# ID вашего личного чата с ботом
MY_CHAT_ID = 'id'

# Обработчик для текстовых сообщений, стикеров и документов
@bot.message_handler(content_types=['text', 'sticker', 'document'])
def handle_unknown_messages(message):
    # Уведомляем пользователя о неизвестной команде или контенте
    bot.send_message(message.chat.id, "Я не совсем Вас понял. Пожалуйста, используйте доступные кнопки.") 
    # Пересылаем сообщение в ваш личный чат
    bot.forward_message(MY_CHAT_ID, message.chat.id, message.message_id)
            
bot.polling()