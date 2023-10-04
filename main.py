import sqlite3
import aiogram.utils.markdown as md
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import (ParseMode)
from aiogram.utils import executor
import time

import config

# Инициализируем бота и диспетчер
bot = Bot(token=config.token)
dp = Dispatcher(bot)
logging_middleware = LoggingMiddleware()
dp.middleware.setup(logging_middleware)

# Функция для получения ID админа и чата при добавлении бота в чат
@dp.message_handler(content_types=[types.ContentType.NEW_CHAT_MEMBERS])
async def on_new_chat_members(message: types.Message):
    if message.new_chat_members:
        for new_member in message.new_chat_members:
            if new_member.is_bot and new_member.id == bot.id:
                # Бот был добавлен в чат
                chat_id = message.chat.id
                admin_id = None
                chat_admins = await bot.get_chat_administrators(chat_id)
                for chat_admin in chat_admins:
                    if not chat_admin.user.is_bot:
                        admin_id = chat_admin.user.id
                        break
                if admin_id is not None:
                    print(f'Бот добавлен в чат с ID: {chat_id}')
                    print(f'ID админа чата: {admin_id}')

# Создаем базы данных, если они не существуют
def create_databases():
    conn = sqlite3.connect('запрещенные_слова.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS запрещенные_слова (
            id INTEGER PRIMARY KEY,
            слово TEXT UNIQUE
        )
    ''')
    conn.close()

    conn = sqlite3.connect('предупреждения.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS предупреждения (
            user_id INTEGER PRIMARY KEY,
            warnings INTEGER DEFAULT 0
        )
    ''')
    conn.close()

create_databases()

# Функция для проверки сообщения на наличие запрещенных слов
async def check_for_prohibited_words(message: types.Message):
    try:
        conn = sqlite3.connect('запрещенные_слова.db')
        cursor = conn.cursor()
        cursor.execute('SELECT слово FROM запрещенные_слова')
        prohibited_words = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Приводим все запрещенные слова и текст сообщения к нижнему регистру
        prohibited_words = [word.lower() for word in prohibited_words]
        text = message.text.lower()

        for word in prohibited_words:
            if word in text:
                user_id = message.from_user.id

                # Проверяем, если пользователь администратор чата
                chat_member = await bot.get_chat_member(message.chat.id, user_id)
                if chat_member.status in ['administrator', 'creator']:
                    return

                # Проверяем, сколько у пользователя уже предупреждений
                conn = sqlite3.connect('предупреждения.db')
                cursor = conn.cursor()
                cursor.execute('SELECT warnings FROM предупреждения WHERE user_id = ?', (user_id,))
                user_warnings = cursor.fetchone()
                if user_warnings:
                    warnings = user_warnings[0]
                else:
                    warnings = 0

                # Увеличиваем количество предупреждений и проверяем на мут
                warnings += 1
                if warnings >= 3:
                    # Применяем мут (удаление сообщений пользователя в течение минуты)
                    await message.chat.restrict(message.from_user.id, types.ChatPermissions(), until_date=time.time() + 60)

                    # Сбрасываем количество предупреждений
                    cursor.execute('DELETE FROM предупреждения WHERE user_id = ?', (user_id,))
                else:
                    # Обновляем количество предупреждений в базе данных
                    cursor.execute('INSERT OR REPLACE INTO предупреждения (user_id, warnings) VALUES (?, ?)', (user_id, warnings))
                conn.commit()
                conn.close()

                # Отправляем предупреждение пользователю
                await message.reply(f'Использование слова "{word}" запрещено. У вас {warnings} предупреждений.')

                # Удаляем сообщение с запрещенным словом
                await message.delete()
                return

    except Exception as e:
        print(f'Произошла ошибка при проверке сообщения: {str(e)}')

# Обработчик команды /add
@dp.message_handler(commands=['add'])
async def add_word(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, если пользователь администратор чата
    chat_member = await bot.get_chat_member(message.chat.id, user_id)
    if chat_member.status not in ['administrator', 'creator']:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    word = message.get_args()  # Получаем аргумент (запрещенное слово) из сообщения
    if word:
        try:
            conn = sqlite3.connect('запрещенные_слова.db')
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO запрещенные_слова (слово) VALUES (?)', (word,))
            conn.commit()
            conn.close()
            await message.reply(f'Слово "{word}" добавлено в список запрещенных слов.')
        except Exception as e:
            await message.reply(f'Произошла ошибка при добавлении слова: {str(e)}')
    else:
        await message.reply('Пожалуйста, укажите слово для добавления.')

# Обработчик команды /remove
@dp.message_handler(commands=['remove'])
async def remove_word(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, если пользователь администратор чата
    chat_member = await bot.get_chat_member(message.chat.id, user_id)
    if chat_member.status not in ['administrator', 'creator']:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    word = message.get_args()  # Получаем аргумент (запрещенное слово) из сообщения
    if word:
        try:
            conn = sqlite3.connect('запрещенные_слова.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM запрещенные_слова WHERE слово = ?', (word,))
            conn.commit()
            conn.close()
            await message.reply(f'Слово "{word}" удалено из списка запрещенных слов.')
        except Exception as e:
            error_message = f'Произошла ошибка при удалении слова: {str(e)}'
            await message.reply(error_message)
            print(error_message)  # Вывести ошибку в консоль для дополнительного анализа
    else:
        await message.reply('Пожалуйста, укажите слово для удаления.')

# Обработчик команды /mute
@dp.message_handler(commands=['mute'])
async def mute_user(message: types.Message):
    # Получаем информацию о пользователе, отправившем сообщение
    user_id = message.from_user.id

    # Проверяем, если пользователь администратор чата
    chat_member = await bot.get_chat_member(message.chat.id, user_id)
    if chat_member.status not in ['administrator', 'creator']:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    # Получаем информацию о сообщении, на которое была дана команда
    reply_message = message.reply_to_message

    if reply_message:
        # Парсим аргумент команды - время в секундах
        args = message.get_args()
        try:
            mute_time = int(args)
        except ValueError:
            await message.reply('Неправильный формат аргумента. Используйте: /mute <время_в_секундах>')
            return

        # Применяем мут к автору ответного сообщения
        await message.chat.restrict(reply_message.from_user.id, types.ChatPermissions(), until_date=time.time() + mute_time)

        await message.reply(f'Пользователь {reply_message.from_user.first_name} замучен на {mute_time} секунд.')
    else:
        await message.reply('Вы должны ответить на сообщение пользователя, которого вы хотите замутить.')

# Обработчик для команды /help
@dp.message_handler(commands=['help'])
async def show_help(message: types.Message):
    help_text = """
            Список доступных команд:
            /add <слово> - добавить слово в список запрещенных.
            /remove <слово> - удалить слово из списка запрещенных.
            /mute <time> - замутить пользователя.
            /list - показать список запрещённых слов.
            /help - показать это сообщение.
            """
    await message.reply(help_text, parse_mode=ParseMode.MARKDOWN)

@dp.message_handler(commands=['list'])
async def list_prohibited_words(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, если пользователь администратор чата
    chat_member = await bot.get_chat_member(message.chat.id, user_id)
    if chat_member.status in ['administrator', 'creator']:
        # Здесь вы можете добавить код для вывода списка запрещенных слов
        conn = sqlite3.connect('запрещенные_слова.db')
        cursor = conn.cursor()
        cursor.execute('SELECT слово FROM запрещенные_слова')
        prohibited_words = [row[0] for row in cursor.fetchall()]
        conn.close()

        if prohibited_words:
            prohibited_words_str = "\n".join(prohibited_words)
            await message.reply(f"Список запрещенных слов:\n{prohibited_words_str}")
        else:
            await message.reply("Список запрещенных слов пока пуст.")
    else:
        await message.reply("У вас нет прав для выполнения этой команды.")

    # Обработчик текстовых сообщений для проверки на запрещенные слова
    @dp.message_handler(content_types=[types.ContentType.TEXT])
    async def check_message(message: types.Message):
        await check_for_prohibited_words(message)

# Обработчик текстовых сообщений для проверки на запрещенные слова
@dp.message_handler(content_types=[types.ContentType.TEXT])
async def check_message(message: types.Message):
    await check_for_prohibited_words(message)

# Запуск бота
if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
