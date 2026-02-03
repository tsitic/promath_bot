import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta
import random
import string

# ==========================================
# 1. КОНФИГУРАЦИЯ
# ==========================================
API_TOKEN = '8473555914:AAEX3DSna4HKkdLiClyFiAd9B835Owos8Mc'
ADMIN_ACCESS_CODE = "1488"

bot = telebot.TeleBot(API_TOKEN)

# Кэш ролей: {chat_id: {'role': 'admin'|'tutor'|'parent', 'id': db_id}}
user_sessions = {}

# ==========================================
# 2. БАЗА ДАННЫХ
# ==========================================
class SchoolDB:
    def __init__(self, db_name="school_platinum.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate_tables() # Обновление структуры для старых БД

    def create_tables(self):
        # Добавлены поля phone, access_code, telegram_chat_id
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS tutors (
            id INTEGER PRIMARY KEY, full_name TEXT, specialty TEXT, hourly_rate REAL, 
            phone TEXT, access_code TEXT, telegram_chat_id INTEGER)''')
        
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS parents (
            id INTEGER PRIMARY KEY, full_name TEXT, phone TEXT, 
            access_code TEXT, telegram_chat_id INTEGER)''')
        
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY, parent_id INTEGER, full_name TEXT, notes TEXT)''')
        
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY, tutor_id INTEGER, student_id INTEGER, 
            day_of_week INTEGER, time_start TEXT, duration_min INTEGER, price REAL)''')
        
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY, schedule_id INTEGER, tutor_id INTEGER, student_id INTEGER, 
            lesson_date TEXT, duration_min INTEGER, price REAL, status TEXT DEFAULT 'scheduled', is_paid INTEGER DEFAULT 0)''')
        self.conn.commit()

    def migrate_tables(self):
        # Безопасное добавление колонок, если их нет (для обновления старой версии)
        try: self.cursor.execute("ALTER TABLE tutors ADD COLUMN access_code TEXT")
        except: pass
        try: self.cursor.execute("ALTER TABLE tutors ADD COLUMN telegram_chat_id INTEGER")
        except: pass
        try: self.cursor.execute("ALTER TABLE tutors ADD COLUMN phone TEXT")
        except: pass
        try: self.cursor.execute("ALTER TABLE parents ADD COLUMN access_code TEXT")
        except: pass
        try: self.cursor.execute("ALTER TABLE parents ADD COLUMN telegram_chat_id INTEGER")
        except: pass
        self.conn.commit()

    def generate_code(self):
        return ''.join(random.choices(string.digits, k=6))

    # --- АВТОРИЗАЦИЯ ---
    def get_user_role(self, chat_id):
        # Проверяем кэш
        if chat_id in user_sessions: return user_sessions[chat_id]
        
        # Проверяем БД (Репетиторы)
        self.cursor.execute("SELECT id FROM tutors WHERE telegram_chat_id=?", (chat_id,))
        res = self.cursor.fetchone()
        if res:
            user_sessions[chat_id] = {'role': 'tutor', 'id': res[0]}
            return user_sessions[chat_id]

        # Проверяем БД (Родители)
        self.cursor.execute("SELECT id FROM parents WHERE telegram_chat_id=?", (chat_id,))
        res = self.cursor.fetchone()
        if res:
            user_sessions[chat_id] = {'role': 'parent', 'id': res[0]}
            return user_sessions[chat_id]
        
        return None

    def authorize_by_code(self, chat_id, code):
        if code == ADMIN_ACCESS_CODE:
            user_sessions[chat_id] = {'role': 'admin', 'id': 0}
            return "admin"
        
        # Ищем в репетиторах
        self.cursor.execute("SELECT id FROM tutors WHERE access_code=?", (code,))
        res = self.cursor.fetchone()
        if res:
            self.cursor.execute("UPDATE tutors SET telegram_chat_id=? WHERE id=?", (chat_id, res[0]))
            self.conn.commit()
            user_sessions[chat_id] = {'role': 'tutor', 'id': res[0]}
            return "tutor"

        # Ищем в родителях
        self.cursor.execute("SELECT id FROM parents WHERE access_code=?", (code,))
        res = self.cursor.fetchone()
        if res:
            self.cursor.execute("UPDATE parents SET telegram_chat_id=? WHERE id=?", (chat_id, res[0]))
            self.conn.commit()
            user_sessions[chat_id] = {'role': 'parent', 'id': res[0]}
            return "parent"
            
        return None

    # --- Добавление ---
    def add_tutor(self, name, spec, rate, phone):
        code = self.generate_code()
        self.cursor.execute("INSERT INTO tutors (full_name, specialty, hourly_rate, phone, access_code) VALUES (?, ?, ?, ?, ?)", 
                            (name, spec, rate, phone, code))
        self.conn.commit()
        return code

    def add_parent(self, name, phone):
        code = self.generate_code()
        self.cursor.execute("INSERT INTO parents (full_name, phone, access_code) VALUES (?, ?, ?)", (name, phone, code))
        self.conn.commit()
        return self.cursor.lastrowid, code

    def add_student(self, pid, name, notes):
        self.cursor.execute("INSERT INTO students (parent_id, full_name, notes) VALUES (?, ?, ?)", (pid, name, notes))
        self.conn.commit()

    def add_schedule(self, tid, sid, day, time, dur, price):
        self.cursor.execute("INSERT INTO schedules (tutor_id, student_id, day_of_week, time_start, duration_min, price) VALUES (?, ?, ?, ?, ?, ?)", 
                            (tid, sid, day, time, dur, price))
        self.conn.commit()

    def add_one_off_lesson(self, tid, sid, date_str, dur, price):
        self.cursor.execute("INSERT INTO lessons (tutor_id, student_id, lesson_date, duration_min, price) VALUES (?, ?, ?, ?, ?)", 
                            (tid, sid, date_str, dur, price))
        self.conn.commit()

    # --- Удаление ---
    def delete_tutor(self, tid):
        self.cursor.execute("DELETE FROM tutors WHERE id=?", (tid,))
        self.conn.commit()

    def delete_student(self, sid):
        self.cursor.execute("DELETE FROM students WHERE id=?", (sid,))
        self.conn.commit()

    # --- Генерация ---
    def generate_lessons(self, weeks=2):
        self.cursor.execute("SELECT * FROM schedules")
        templates = self.cursor.fetchall()
        count = 0
        today = datetime.now().date()
        for t in templates:
            for i in range(weeks * 7):
                target = today + timedelta(days=i)
                if target.weekday() == t[3]:
                    full_date = f"{target.strftime('%Y-%m-%d')} {t[4]}"
                    self.cursor.execute("SELECT id FROM lessons WHERE schedule_id=? AND lesson_date=?", (t[0], full_date))
                    if not self.cursor.fetchone():
                        self.cursor.execute("INSERT INTO lessons (schedule_id, tutor_id, student_id, lesson_date, duration_min, price) VALUES (?, ?, ?, ?, ?, ?)", 
                                            (t[0], t[1], t[2], full_date, t[5], t[6]))
                        count += 1
        self.conn.commit()
        return count

    # --- КАЛЕНДАРЬ И СПИСКИ ---
    def get_upcoming_lessons(self, role, user_id, days=14):
        # role: 'admin', 'tutor', 'parent'
        limit_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d 23:59")
        
        # Базовый запрос: теперь берем phone репетитора и notes студента
        query = '''
            SELECT l.id, l.lesson_date, t.full_name, s.full_name, l.price, l.duration_min, t.phone, s.notes
            FROM lessons l
            JOIN tutors t ON l.tutor_id = t.id
            JOIN students s ON l.student_id = s.id
            WHERE l.status = 'scheduled' AND l.lesson_date <= ?
        '''
        params = [limit_date]
        
        if role == 'tutor':
            query += " AND l.tutor_id = ?"
            params.append(user_id)
        elif role == 'parent':
            # Находим всех детей этого родителя
            query += " AND s.parent_id = ?"
            params.append(user_id)
            
        query += " ORDER BY l.lesson_date"
        
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def get_debtors(self):
        self.cursor.execute('''
            SELECT s.full_name, l.lesson_date, l.price, p.phone
            FROM lessons l
            JOIN students s ON l.student_id = s.id
            JOIN parents p ON s.parent_id = p.id
            WHERE l.status='completed' AND l.is_paid=0
        ''')
        return self.cursor.fetchall()

    def get_tutors(self):
        self.cursor.execute("SELECT id, full_name, access_code FROM tutors")
        return self.cursor.fetchall()
    
    def get_students(self):
        self.cursor.execute("SELECT id, full_name FROM students")
        return self.cursor.fetchall()

    def get_parents_codes(self):
        self.cursor.execute("SELECT full_name, access_code FROM parents")
        return self.cursor.fetchall()

    def update_lesson(self, lid, status=None, paid=None, new_date=None):
        if status: self.cursor.execute("UPDATE lessons SET status=? WHERE id=?", (status, lid))
        if paid is not None: self.cursor.execute("UPDATE lessons SET is_paid=? WHERE id=?", (paid, lid))
        if new_date: self.cursor.execute("UPDATE lessons SET lesson_date=? WHERE id=?", (new_date, lid))
        self.conn.commit()

    # --- ОТЧЕТЫ И ИСТОРИЯ ---
    def get_history(self, status_filter=None, limit=30):
        query = '''
            SELECT l.lesson_date, t.full_name, s.full_name, l.price, l.status
            FROM lessons l
            JOIN tutors t ON l.tutor_id = t.id
            JOIN students s ON l.student_id = s.id
        '''
        params = []
        if status_filter:
            query += " WHERE l.status = ?"
            params.append(status_filter)
        else:
            query += " WHERE l.status != 'scheduled'"
        
        query += " ORDER BY l.lesson_date DESC LIMIT ?"
        params.append(limit)
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def get_income_by_period(self, start_date, end_date):
        query = '''
            SELECT SUM(price) FROM lessons 
            WHERE status = 'completed' 
            AND lesson_date >= ? AND lesson_date <= ?
        '''
        self.cursor.execute(query, (start_date + " 00:00", end_date + " 23:59"))
        res = self.cursor.fetchone()[0]
        return res if res else 0.0

db = SchoolDB()

# ==========================================
# 3. АВТОРИЗАЦИЯ И МЕНЮ
# ==========================================

def get_session(message):
    return db.get_user_role(message.chat.id)

def check_auth(message):
    session = get_session(message)
    if session: return True
    
    # Попытка входа
    text = message.text.strip()
    role = db.authorize_by_code(message.chat.id, text)
    
    if role:
        bot.send_message(message.chat.id, f"✅ Вы вошли как: {role.upper()}")
        send_menu_by_role(message, role)
        return True
    else:
        bot.send_message(message.chat.id, "🔒 Введите ваш КОД ДОСТУПА:")
        return False

def send_menu_by_role(message, role):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if role == 'admin':
        markup.add("📅 Календарь", "⚡️ Разовый урок")
        markup.add("📊 Отчеты", "🔑 Коды доступа")
        markup.add("💰 Должники", "➕ Добавить Людей")
        markup.add("➕ Шаблон расписания", "🔄 Генерация (2 нед)")
        markup.add("🗑 Удаление", "📋 База данных")
        bot.send_message(message.chat.id, "👨‍💻 Панель Администратора:", reply_markup=markup)
        
    elif role == 'tutor':
        markup.add("📅 Моё Расписание")
        bot.send_message(message.chat.id, "🎓 Панель Репетитора:", reply_markup=markup)
        
    elif role == 'parent':
        markup.add("📅 Расписание Ребенка")
        bot.send_message(message.chat.id, "👨‍👩‍👦 Панель Родителя:", reply_markup=markup)

def send_calendar_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("👀 Всё на 2 недели", "👨‍🏫 Фильтр по Репетитору")
    markup.add("🔙 Назад в меню")
    bot.send_message(message.chat.id, "Режим календаря:", reply_markup=markup)

def send_reports_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📜 Вся история", "✅ Только проведенные")
    markup.add("❌ Только отмены", "💰 Доход (Неделя)")
    markup.add("🔙 Назад в меню")
    bot.send_message(message.chat.id, "Раздел отчетности:", reply_markup=markup)

def send_database_menu(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("👨‍🏫 Список Репетиторов", callback_data="list_tutors"))
    kb.add(types.InlineKeyboardButton("👶 Список Учеников", callback_data="list_students"))
    bot.send_message(message.chat.id, "Какую базу открыть?", reply_markup=kb)

# ==========================================
# 4. ОБРАБОТЧИКИ
# ==========================================

@bot.message_handler(commands=['start'])
def start_handler(message):
    session = get_session(message)
    if session:
        send_menu_by_role(message, session['role'])
    else:
        bot.send_message(message.chat.id, "👋 Добро пожаловать! Введите код доступа (от администратора):")

@bot.message_handler(func=lambda m: get_session(m) is None)
def auth_guard(message):
    check_auth(message)

# --- ГЛАВНЫЙ РОУТЕР ---
@bot.message_handler(func=lambda m: True)
def menu_router(message):
    session = get_session(message)
    if not session: return

    role = session['role']
    uid = session['id']
    t = message.text
    cid = message.chat.id
    
    # === ОБЩИЕ КОМАНДЫ ===
    if t == "🔙 Назад в меню":
        send_menu_by_role(message, role)
        return

    # === АДМИН ===
    if role == 'admin':
        if t == "📊 Отчеты": send_reports_menu(message)
        elif t == "📅 Календарь": send_calendar_menu(message)
        elif t == "📋 База данных": send_database_menu(message)
        
        elif t == "👀 Всё на 2 недели": show_schedule_messages(cid, 'admin', 0, tutor_filter_id=None)
        elif t == "👨‍🏫 Фильтр по Репетитору":
            tutors = db.get_tutors()
            kb = types.InlineKeyboardMarkup()
            for tr in tutors: kb.add(types.InlineKeyboardButton(tr[1], callback_data=f"showCal_{tr[0]}"))
            bot.send_message(cid, "Чье расписание показать?", reply_markup=kb)

        elif t == "📜 Вся история": send_history_table(cid, None, "ВСЯ ИСТОРИЯ")
        elif t == "✅ Только проведенные": send_history_table(cid, "completed", "ПРОВЕДЕННЫЕ")
        elif t == "❌ Только отмены": send_history_table(cid, "canceled", "ОТМЕНЕННЫЕ")
        elif t == "💰 Доход (Неделя)":
            end = datetime.now()
            start = end - timedelta(days=7)
            inc = db.get_income_by_period(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📅 Изменить период", callback_data="change_period"))
            bot.send_message(cid, f"Доход (7 дней): {inc} руб.", reply_markup=kb)

        elif t == "🔄 Генерация (2 нед)":
            count = db.generate_lessons()
            bot.send_message(cid, f"✅ Сгенерировано уроков: {count}")

        elif t == "💰 Должники":
            d = db.get_debtors()
            if not d: bot.send_message(cid, "Долгов нет.")
            else:
                msg = "❗ <b>ДОЛЖНИКИ:</b>\n" + "\n".join([f"{x[0]} ({x[1]}): {x[2]}р." for x in d])
                bot.send_message(cid, msg, parse_mode='HTML')

        elif t == "➕ Добавить Людей":
            msg = bot.send_message(cid, "Напишите: 'Р' для репетитора, 'У' для ученика с родителем.")
            bot.register_next_step_handler(msg, add_human_step1)
        
        elif t == "🔑 Коды доступа":
            # Выводим коды репетиторов
            ts = db.get_tutors()
            msg = "🔑 <b>Коды Репетиторов:</b>\n" + "\n".join([f"{x[1]}: <code>{x[2]}</code>" for x in ts])
            bot.send_message(cid, msg, parse_mode='HTML')
            # Выводим коды родителей
            ps = db.get_parents_codes()
            msg2 = "\n🔑 <b>Коды Родителей:</b>\n" + "\n".join([f"{x[0]}: <code>{x[1]}</code>" for x in ps])
            bot.send_message(cid, msg2, parse_mode='HTML')

        elif t == "🗑 Удаление":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("Репетитора", callback_data="rm_tutor_start"),
                   types.InlineKeyboardButton("Ученика", callback_data="rm_student_start"))
            bot.send_message(cid, "Кого удалить?", reply_markup=kb)

        elif t == "➕ Шаблон расписания":
            start_selection_process(cid, "template")

        elif t == "⚡️ Разовый урок":
            start_selection_process(cid, "oneoff")

    # === РЕПЕТИТОР ===
    elif role == 'tutor':
        if t == "📅 Моё Расписание":
            show_schedule_messages(cid, 'tutor', uid)

    # === РОДИТЕЛЬ ===
    elif role == 'parent':
        if t == "📅 Расписание Ребенка":
            show_schedule_messages(cid, 'parent', uid)

# --- УНИВЕРСАЛЬНЫЙ ВЫВОД РАСПИСАНИЯ ---
def show_schedule_messages(chat_id, role, user_id, tutor_filter_id=None):
    # Если Админ смотрит конкретного репетитора
    if role == 'admin' and tutor_filter_id:
        lessons = db.get_upcoming_lessons('tutor', tutor_filter_id)
        header = "👇 <b>Расписание репетитора:</b>"
    else:
        lessons = db.get_upcoming_lessons(role, user_id)
        header = "👇 <b>Ближайшие занятия:</b>"

    if not lessons:
        bot.send_message(chat_id, "📭 Занятий не найдено.")
        return
    
    bot.send_message(chat_id, header, parse_mode='HTML')
    
    for l in lessons:
        # Структура l: 
        # 0:id, 1:date, 2:tutor_name, 3:student_name, 4:price, 5:dur, 6:tutor_phone, 7:notes
        lid, date_str, t_name, s_name, price, dur, t_phone, notes = l
        
        # Формирование текста
        txt = f"📅 <b>{date_str}</b>\n"
        
        if role == 'admin':
            txt += f"👨‍🏫 {t_name} -> 👶 {s_name}\n"
            txt += f"📝 Заметка: {notes}\n"
            txt += f"⏱ {dur} мин | 💵 {price} р."
            
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(types.InlineKeyboardButton("✅ Оплат", callback_data=f"ok_1_{lid}"),
                   types.InlineKeyboardButton("⚠️ Долг", callback_data=f"ok_0_{lid}"))
            kb.add(types.InlineKeyboardButton("🗓 Перенос", callback_data=f"move_{lid}"),
                   types.InlineKeyboardButton("❌ Отмена", callback_data=f"del_{lid}"))

        elif role == 'tutor':
            txt += f"👶 Ученик: <b>{s_name}</b>\n"
            txt += f"📝 Заметка: {notes}\n"
            txt += f"⏱ Длительность: {dur} мин"
            # Репетитор НЕ видит цену
            
            kb = types.InlineKeyboardMarkup(row_width=2)
            # Репетитор может отметить как "Проведено" (без упоминания денег)
            kb.add(types.InlineKeyboardButton("✅ Проведено", callback_data=f"done_tutor_{lid}")) 
            kb.add(types.InlineKeyboardButton("🗓 Перенос", callback_data=f"move_{lid}"),
                   types.InlineKeyboardButton("❌ Отмена", callback_data=f"del_{lid}"))

        elif role == 'parent':
            txt += f"👨‍🏫 Репетитор: {t_name}\n"
            txt += f"📞 Контакт: {t_phone}\n"
            txt += f"⏱ {dur} мин | 💵 К оплате: <b>{price} р.</b>"
            # Родитель НЕ видит кнопок и заметок
            kb = None

        bot.send_message(chat_id, txt, parse_mode='HTML', reply_markup=kb)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def send_history_table(chat_id, status_filter, title):
    rows = db.get_history(status_filter)
    if not rows:
        bot.send_message(chat_id, "История пуста.")
        return
    report = f"<b>{title}</b>\n<pre>"
    report += "{:<10} | {:<4}\n".format("Дата", "Сум")
    for r in rows:
        report += f"{r[0][5:16]} | {int(r[3])}\n{r[2].split()[0]} ({r[4][0]})\n"
        report += "-"*20 + "\n"
    report += "</pre>"
    bot.send_message(chat_id, report, parse_mode='HTML')

def start_selection_process(chat_id, mode):
    tutors = db.get_tutors()
    if not tutors: 
        bot.send_message(chat_id, "Нет репетиторов.")
        return
    kb = types.InlineKeyboardMarkup()
    for t_obj in tutors:
        kb.add(types.InlineKeyboardButton(t_obj[1], callback_data=f"selT_{mode}_{t_obj[0]}"))
    bot.send_message(chat_id, "1. Выберите репетитора:", reply_markup=kb)

# --- CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    session = get_session(call.message)
    if not session: return # Игнорируем неавторизованных
    
    role = session['role']
    cid = call.message.chat.id
    d = call.data

    # АДМИНСКИЕ ФУНКЦИИ
    if d.startswith("showCal_") and role == 'admin':
        tid = d.split("_")[1]
        show_schedule_messages(cid, 'admin', 0, tutor_filter_id=tid)

    elif d == "list_tutors" and role == 'admin':
        ts = db.get_tutors()
        msg = "👨‍🏫 <b>Репетиторы:</b>\n" + "\n".join([f"• {x[1]}" for x in ts])
        bot.send_message(cid, msg, parse_mode='HTML')
    elif d == "list_students" and role == 'admin':
        st = db.get_students()
        msg = "👶 <b>Ученики:</b>\n" + "\n".join([f"• {x[1]}" for x in st])
        bot.send_message(cid, msg, parse_mode='HTML')
    
    # ДОХОД
    elif d == "change_period" and role == 'admin':
        msg = bot.send_message(cid, "Введите НАЧАЛО (YYYY-MM-DD):")
        bot.register_next_step_handler(msg, ask_end_date)

    # УПРАВЛЕНИЕ УРОКОМ (АДМИН)
    elif d.startswith("ok_") and role == 'admin':
        _, paid, lid = d.split("_")
        db.update_lesson(lid, status='completed', paid=int(paid))
        bot.edit_message_text(f"Завершено ({'ОПЛАТА' if paid=='1' else 'ДОЛГ'})", cid, call.message.message_id)
    
    # УПРАВЛЕНИЕ УРОКОМ (РЕПЕТИТОР)
    elif d.startswith("done_tutor_") and role == 'tutor':
        lid = d.split("_")[2]
        # Репетитор ставит статус "completed", но флаг оплаты is_paid ставим 0 (типа не подтверждено админом или долг)
        # Или можно считать, что репетитор просто провел урок.
        db.update_lesson(lid, status='completed', paid=0) 
        bot.edit_message_text("✅ Урок проведен (отправлено Админу)", cid, call.message.message_id)

    # ОБЩИЕ ДЕЙСТВИЯ (АДМИН + РЕПЕТИТОР)
    elif d.startswith("del_") and role in ['admin', 'tutor']:
        db.update_lesson(d.split("_")[1], status='canceled')
        bot.edit_message_text("❌ Отменено", cid, call.message.message_id)
    
    elif d.startswith("move_") and role in ['admin', 'tutor']:
        lid = d.split("_")[1]
        msg = bot.send_message(cid, "Новая дата (YYYY-MM-DD HH:MM):")
        bot.register_next_step_handler(msg, lambda m: db.update_lesson(lid, new_date=m.text) or bot.send_message(cid, "Перенесено."))

    # УДАЛЕНИЕ (АДМИН)
    elif d == "rm_tutor_start" and role == 'admin':
        kb = types.InlineKeyboardMarkup()
        for r in db.get_tutors(): kb.add(types.InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"killT_{r[0]}"))
        bot.edit_message_text("Кого удалить?", cid, call.message.message_id, reply_markup=kb)
    elif d.startswith("killT_") and role == 'admin':
        db.delete_tutor(d.split("_")[1])
        bot.edit_message_text("Удалено.", cid, call.message.message_id)
    elif d == "rm_student_start" and role == 'admin':
        kb = types.InlineKeyboardMarkup()
        for r in db.get_students(): kb.add(types.InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"killS_{r[0]}"))
        bot.edit_message_text("Кого удалить?", cid, call.message.message_id, reply_markup=kb)
    elif d.startswith("killS_") and role == 'admin':
        db.delete_student(d.split("_")[1])
        bot.edit_message_text("Удалено.", cid, call.message.message_id)

    # СОЗДАНИЕ (АДМИН)
    elif d.startswith("selT_") and role == 'admin':
        _, mode, tid = d.split("_")
        kb = types.InlineKeyboardMarkup()
        for s in db.get_students(): kb.add(types.InlineKeyboardButton(s[1], callback_data=f"selS_{mode}_{tid}_{s[0]}"))
        bot.edit_message_text("2. Ученик:", cid, call.message.message_id, reply_markup=kb)
    elif d.startswith("selS_") and role == 'admin':
        _, mode, tid, sid = d.split("_")
        if mode == "template":
            days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
            kb = types.InlineKeyboardMarkup(row_width=3)
            kb.add(*[types.InlineKeyboardButton(dy, callback_data=f"selD_{tid}_{sid}_{i}") for i, dy in enumerate(days)])
            bot.edit_message_text("3. День:", cid, call.message.message_id, reply_markup=kb)
        else:
            msg = bot.send_message(cid, "3. Данные (2023-11-01 15:00 60 1500):")
            bot.register_next_step_handler(msg, finish_oneoff, tid, sid)
    elif d.startswith("selD_") and role == 'admin':
        _, tid, sid, day = d.split("_")
        msg = bot.send_message(cid, "4. Данные (18:00 60 1500):")
        bot.register_next_step_handler(msg, finish_schedule, tid, sid, day)

# --- INPUT HANDLERS ---
def ask_end_date(message):
    start = message.text
    msg = bot.send_message(message.chat.id, "Введите КОНЕЦ (YYYY-MM-DD):")
    bot.register_next_step_handler(msg, lambda m: bot.send_message(m.chat.id, f"Доход: {db.get_income_by_period(start, m.text)} руб."))

def add_human_step1(message):
    if message.text.lower() == 'р':
        msg = bot.send_message(message.chat.id, "Введите: ФИО, Предмет, Ставка, Телефон")
        bot.register_next_step_handler(msg, add_tutor_finish)
    elif message.text.lower() == 'у':
        msg = bot.send_message(message.chat.id, "Введите: ФИО Родителя, Телефон")
        bot.register_next_step_handler(msg, add_student_step2)

def add_tutor_finish(message):
    try:
        data = [x.strip() for x in message.text.split(',')]
        # full_name, specialty, hourly_rate, phone
        code = db.add_tutor(data[0], data[1], float(data[2]), data[3])
        bot.send_message(message.chat.id, f"✅ Репетитор добавлен!\nЕго код доступа: <code>{code}</code>", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}")

def add_student_step2(message):
    try:
        d = message.text.split(',')
        # Создаем родителя
        pid, code = db.add_parent(d[0].strip(), d[1].strip())
        
        # Сохраняем pid и код во временное хранилище (или через lambda) чтобы передать дальше
        msg = bot.send_message(message.chat.id, f"✅ Родитель создан (Код: <code>{code}</code>).\nТеперь введите: ФИО Ученика, Заметки для репетитора", parse_mode='HTML')
        bot.register_next_step_handler(msg, finish_student_add, pid)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}")

def finish_student_add(message, pid):
    try:
        # Ожидаем: ФИО, Заметки
        d = message.text.split(',')
        name = d[0].strip()
        notes = d[1].strip() if len(d) > 1 else "-"
        db.add_student(pid, name, notes)
        bot.send_message(message.chat.id, "✅ Ученик добавлен!")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}")

def finish_schedule(message, tid, sid, day):
    try:
        p = message.text.split()
        db.add_schedule(tid, sid, int(day), p[0], int(p[1]), float(p[2]))
        bot.send_message(message.chat.id, "✅ Шаблон создан!")
    except: bot.send_message(message.chat.id, "Ошибка.")

def finish_oneoff(message, tid, sid):
    try:
        p = message.text.split()
        db.add_one_off_lesson(tid, sid, f"{p[0]} {p[1]}", int(p[2]), float(p[3]))
        bot.send_message(message.chat.id, "✅ Урок добавлен!")
    except: bot.send_message(message.chat.id, "Ошибка.")

if __name__ == "__main__":
    print("Бот v8.0 Multi-User запущен...")
    try: bot.polling(none_stop=True)
    except Exception as e: print(e)
