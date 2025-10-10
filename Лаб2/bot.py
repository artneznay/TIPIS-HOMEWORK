"""
Простейший Telegram бот для проверки лабораторных работ через OpenRouter
"""

import asyncio
import os
import tempfile
from pathlib import Path
import html
import json

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv
from openai import OpenAI

from file_utils import extract_docx, extract_pdf, extract_txt


# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("Добавьте токены в .env файл!")
    exit(1)

# Инициализация
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# OpenRouter клиент
openrouter = OpenAI(
    api_key=OPENROUTER_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# Поддерживаемые форматы
SUPPORTED_FORMATS = ['.pdf', '.docx', '.txt']
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 МБ


def format_llm_to_html(text: str) -> str:
    """Преобразует чистый текст от LLM в безопасный HTML: экранирует содержимое,
    делает жирными строки-заголовки и сохраняет переносы строк.
    Возвращает HTML-строку, безопасную для передачи в Telegram (ParseMode.HTML).
    """
    lines = text.splitlines()
    out_lines = []
    for line in lines:
        s = line.strip()
        if not s:
            out_lines.append('')
            continue
        # Заголовок: если строка заканчивается на ':' или полностью в верхнем регистре
        if s.endswith(':') or (s.isupper() and len(s) < 200):
            out_lines.append(f"<b>{html.escape(s)}</b>")
            continue
        # Буллеты
        if s.startswith('-') or s.startswith('•') or s.startswith('*'):
            content = s.lstrip('-•* ').strip()
            out_lines.append(f"• {html.escape(content)}")
            continue
        # Обычная строка
        out_lines.append(html.escape(s))

    # Соединяем часть строк, сохраняя один перенос между абзацами
    return '\n'.join(out_lines)

# Можно переопределить модель через переменную окружения OPENAI_MODEL
MODEL = os.getenv("OPENAI_MODEL", "qwen/qwen3-235b-a22b:free")

def get_main_keyboard():
    """Главная клавиатура"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])

@dp.message(CommandStart())
async def start_command(message: Message):
    """Команда /start"""
    await message.answer(
        f"🎓 <b>Привет, {html.escape(message.from_user.first_name or '')}!</b>\n\n"
        "Я проверяю лабораторные работы с помощью ИИ.\n\n"
        "📄 <b>Как пользоваться:</b>\n"
        "Просто отправь мне файл с работой!\n\n"
        "📁 <b>Поддерживаю:</b> PDF, DOCX, TXT файлы (до 20 МБ)\n"
        "🤖 <b>Использую:</b> Claude 3.5 Sonnet\n\n",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("help"))
async def help_command(message: Message):
    """Команда /help"""
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ Отправь мне файл с лабораторной работой\n"
        "2️⃣ Жди проверку от ИИ (1-2 минуты)\n"
        "3️⃣ Получи детальную оценку\n\n"
        "<b>📁 Поддерживаемые форматы:</b>\n"
        "• PDF (до 20 МБ)\n"
        "• DOCX (Microsoft Word)\n"
        "• TXT (текстовые файлы)\n\n"
        "<b>📊 Что проверяется:</b>\n"
        "• Качество кода и решения\n"
        "• Полнота документации\n" 
        "• Правильность выводов\n"
        "• Оформление работы\n\n"
        "<b>💡 Результат:</b> Оценка из 100 баллов + рекомендации",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "help")
async def help_callback(callback):
    """Помощь через callback"""
    await help_command(callback.message)

@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: Message):
    """Обработка текстовых сообщений"""
    await message.answer(
        "📄 <b>Отправь файл для проверки!</b>\n\n"
        "Я не анализирую текстовые сообщения.\n"
        "Просто прикрепи файл с лабораторной работой.\n\n"
        "Поддерживаю: PDF, DOCX, TXT",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.document)
async def handle_document(message: Message):
    """Обработка файла"""
    document = message.document
    file_name = document.file_name
    file_size = document.file_size
    
    # Проверка размера
    if file_size > MAX_FILE_SIZE:
        await message.answer(
            f"❌ <b>Файл слишком большой!</b>\n\n"
            f"📏 Размер файла: {file_size / 1024 / 1024:.1f} МБ\n"
            f"📏 Максимум: {MAX_FILE_SIZE / 1024 / 1024} МБ\n\n"
            f"Попробуй сжать файл или выбрать другой.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Проверка формата
    file_ext = Path(file_name).suffix.lower()
    if file_ext not in SUPPORTED_FORMATS:
        await message.answer(
            f"❌ <b>Неподдерживаемый формат!</b>\n\n"
            f"📄 Твой файл: <code>{html.escape(file_ext)}</code>\n"
            f"📁 Поддерживаю: <code>{html.escape(', '.join(SUPPORTED_FORMATS))}</code>\n\n"
            f"Преобразуй файл в подходящий формат.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Показываем статус обработки
    status_msg = await message.answer(
        "⏳ <b>Проверяю работу...</b>\n\n"
        "🔄 Загружаю файл\n"
        "⏳ Извлекаю содержимое\n"
        "⏳ Анализирую с помощью ИИ\n\n"
        "<i>Обычно занимает 1-2 минуты</i>"
    )
    
    temp_path = None
    
    try:
        # Загружаем файл
        file = await bot.get_file(document.file_id)
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp_file:
            await bot.download_file(file.file_path, tmp_file.name)
            temp_path = tmp_file.name
        
        await status_msg.edit_text(
            "⏳ <b>Проверяю работу...</b>\n\n"
            "✅ Файл загружен\n"
            "🔄 Извлекаю содержимое\n"
            "⏳ Анализирую с помощью ИИ"
        )
        
        # Извлекаем содержимое в зависимости от типа файла
        if file_ext == '.txt':
            content = await extract_txt(temp_path)
        elif file_ext == '.docx':
            content = await extract_docx(temp_path)
        elif file_ext == '.pdf':
            content = await extract_pdf(temp_path)
        else:
            raise Exception("Неподдерживаемый формат")
        
        # Проверяем, что содержимое не пустое
        if not content.strip():
            raise Exception("Файл пуст или не содержит читаемого текста")
        
        await status_msg.edit_text(
            "⏳ <b>Проверяю работу...</b>\n\n"
            "✅ Файл загружен\n"
            "✅ Содержимое извлечено\n"
            "🔄 Анализирую с помощью ИИ\n\n"
            "<i>ИИ анализирует работу...</i>"
        )
        
        # Отправляем на проверку
        result = await check_with_ai(content)
        
        # Удаляем временный файл
        if temp_path:
            os.unlink(temp_path)
        
        # Отправляем информацию о файле
        await status_msg.edit_text(
            "✅ <b>Проверка завершена!</b>\n\n"
            f"📄 <b>Файл:</b> <code>{html.escape(file_name)}</code>\n"
            f"📊 <b>Размер:</b> {file_size / 1024:.1f} КБ\n"
            f"📝 <b>Символов:</b> {len(content):,}\n"
            f"🤖 <b>Модель:</b> Claude 3.5 Sonnet"
        )
        
        # Форматируем ответ LLM в безопасный HTML и разбиваем по строкам не ломая тэги
        formatted = format_llm_to_html(result)

        # Разбиваем по строкам, аккумулируя блоки до ~3500 символов, чтобы не превысить лимит
        max_chunk = 3500
        lines = formatted.splitlines(keepends=True)
        chunks = []
        cur = ''
        for ln in lines:
            if len(cur) + len(ln) > max_chunk and cur:
                chunks.append(cur)
                cur = ''
            cur += ln
        if cur:
            chunks.append(cur)

        for i, part in enumerate(chunks):
            if i == 0:
                await message.answer(f"📋 <b>Результат проверки:</b>\n\n{part}")
            else:
                await message.answer(f"📋 <b>Продолжение ({i+1}):</b>\n\n{part}")
        
        # Предлагаем проверить еще файл
        await message.answer(
            "🎉 <b>Готово!</b>\n\n"
            "Можешь отправить еще один файл для проверки 📄",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        # Удаляем временный файл в случае ошибки
        if temp_path:
            try:
                os.unlink(temp_path)
            except:
                pass
        
        await status_msg.edit_text(
            f"❌ <b>Ошибка при обработке файла:</b>\n\n"
            f"<code>{html.escape(str(e))}</code>\n\n"
            f"Попробуй еще раз или выбери другой файл.",
            reply_markup=get_main_keyboard()
        )

async def check_with_ai(content: str) -> str:
    """Проверка работы через OpenRouter"""
    prompt = f"""
Проанализируй эту лабораторную работу студента и дай развернутую оценку.

КРИТЕРИИ ОЦЕНКИ (100 баллов максимум):
1. Качество кода и решения (0-30 баллов)
2. Полнота и правильность реализации (0-30 баллов)  
3. Документация и комментарии (0-20 баллов)
4. Оформление и структура работы (0-20 баллов)

СОДЕРЖИМОЕ РАБОТЫ:
{content}

Дай конструктивную оценку:
- Кратко опиши, что делает работа
- Оцени каждый критерий с обоснованием
- Укажи сильные стороны
- Дай конкретные рекомендации для улучшения
- Поставь итоговую оценку из 100 баллов

Будь справедлив, но требователен. Пиши понятно для студента.
"""

    try:
        response = openrouter.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.5,
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Ошибка при обращении к ИИ: {str(e)}\n\nПопробуйте еще раз через несколько минут."


def format_ai_response_text(raw: str) -> str:
    """Форматирует сырой текстовый ответ от модели в HTML, экранируя контент."""
    safe = html.escape(raw)
    # Заменим заголовки и сделаем аккуратные разделители
    safe = safe.replace('\n\n', '\n').replace('\n', '<br>')
    return f"<b>📋 Результат проверки:</b><br><br>{safe}"


def format_ai_response_json(data: dict) -> str:
    """Формирует читабельный HTML из JSON-ответа модели."""
    parts = []
    # Summary
    summary = data.get('summary') or data.get('description') or ''
    if summary:
        parts.append(f"<b>🔎 Краткое описание:</b><br>{html.escape(str(summary))}")

    # Criteria
    criteria = data.get('criteria') or {}
    if criteria:
        parts.append('<b>📊 Оценка по критериям:</b>')
        for key, val in criteria.items():
            score = val.get('score') if isinstance(val, dict) else None
            comment = val.get('comment') if isinstance(val, dict) else ''
            parts.append(f"<b>• {html.escape(key.capitalize())}:</b> {html.escape(str(score) if score is not None else '-') } / {html.escape(str(comment))}")

    # Strengths
    strengths = data.get('strengths') or []
    if strengths:
        parts.append('<b>⭐ Сильные стороны:</b>')
        for s in strengths:
            parts.append(f"• {html.escape(str(s))}")

    # Recommendations
    recs = data.get('recommendations') or []
    if recs:
        parts.append('<b>🛠 Рекомендации:</b>')
        for r in recs:
            parts.append(f"• {html.escape(str(r))}")

    # Final score
    final = data.get('final_score') or data.get('final')
    if final is not None:
        parts.append(f"<b>✅ Итоговая оценка:</b> {html.escape(str(final))} / 100")

    # Собираем всё в один HTML с переносами
    html_text = '<br>'.join(parts)
    if not html_text:
        return format_ai_response_text(json.dumps(data, ensure_ascii=False, indent=2))
    return f"<b>📋 Результат проверки:</b><br><br>{html_text}"


# Запуск бота
async def main():
    print("🤖 Запускаю бот для проверки лабораторных работ...")
    print("📄 Поддерживаемые форматы: PDF, DOCX, TXT")
    print("🤖 ИИ модель: Claude 3.5 Sonnet")
    print("⚡ Просто отправьте файл для проверки!")
    print("-" * 50)
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n Бот остановлен пользователем")
    except Exception as e:
        print(f"\n Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())

