import asyncio
import json
import logging
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS
from quiz_data import QUESTIONS, FLOWER_RESULTS, get_flower_from_answers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
storage = MemoryStorage()


class QuizState(StatesGroup):
    answering = State()


class AdminState(StatesGroup):
    waiting_intro = State()
    waiting_question = State()
    waiting_result = State()


SETTINGS_FILE = "settings.json"


def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load settings")
        return {}


def save_settings(data: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save settings")


settings: dict = load_settings()


DEFAULT_INTRO_TEXT = (
    "<b>Привет! Время расцветать!</b>\n\n"
    "Внимательно прочитай вопросы и выбери один ответ в каждом из них. "
    "Выбирай тот ответ, который наиболее близок к твоему поведению в реальной жизни.\n\n"
    "По итогам теста ты узнаешь, какой цветок лучше всего отражает твою индивидуальность."
)


def get_intro_text() -> str:
    return settings.get("intro_text") or DEFAULT_INTRO_TEXT

START_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="НАЧАТЬ", callback_data="start_quiz")]
    ]
)


def is_admin(user_id: int | None) -> bool:
    return bool(user_id) and int(user_id) in ADMIN_IDS

def make_question_keyboard(question_num: int) -> InlineKeyboardMarkup:
    q = QUESTIONS[question_num]
    letters = list(q["options"].keys())
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=letters[0], callback_data=f"q{question_num}_{letters[0]}"),
            InlineKeyboardButton(text=letters[1], callback_data=f"q{question_num}_{letters[1]}"),
        ],
        [
            InlineKeyboardButton(text=letters[2], callback_data=f"q{question_num}_{letters[2]}"),
            InlineKeyboardButton(text=letters[3], callback_data=f"q{question_num}_{letters[3]}"),
        ],
    ])


def get_user_answers(state_data: dict) -> list:
    return state_data.get("answers", [])


def format_question_message(question_num: int) -> str:
    # базовый вопрос
    q = QUESTIONS[question_num]
    # возможные переопределения из настроек
    q_overrides = settings.get("questions", {}).get(str(q["num"]), {})
    text = q_overrides.get("text") or q["text"]
    options_text = "\n".join(
        f"<b>{letter}</b>) {text}" for letter, text in q["options"].items()
    )
    return (
        f"<b>Вопрос №{q['num']}</b>\n\n"
        f"{text}\n\n"
        f"{options_text}"
    )


async def send_question(message_or_callback, question_num: int, state: FSMContext):
    keyboard = make_question_keyboard(question_num)
    text = format_question_message(question_num)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.answer()
        await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    # логируем id пользователя в текстовый файл
    try:
        with open("users.txt", "a", encoding="utf-8") as f:
            f.write(f"{message.from_user.id}\n")
    except Exception as e:
        logger.exception("Failed to save user id: %s", e)

    await message.answer(get_intro_text(), reply_markup=START_KEYBOARD, parse_mode="HTML")


@router.callback_query(F.data == "start_quiz")
async def start_quiz(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(QuizState.answering)
    await state.update_data(answers=[])
    await send_question(callback, 0, state)


@router.message(F.text == "/set_intro")
async def set_intro(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения приветствия.")
        return
    await state.set_state(AdminState.waiting_intro)
    await message.answer("Пришли новый текст приветственного сообщения (можно с HTML-разметкой).")


@router.message(AdminState.waiting_intro)
async def save_intro(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения приветствия.")
        return
    text = message.html_text or message.text
    settings["intro_text"] = text
    save_settings(settings)
    await state.clear()
    await message.answer("Приветственное сообщение обновлено.")


@router.message(F.text.startswith("/set_question"))
async def set_question(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения вопросов.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /set_question N, где N — номер вопроса от 1 до 7.")
        return
    q_num = int(parts[1])
    if q_num < 1 or q_num > len(QUESTIONS):
        await message.answer("Номер вопроса должен быть от 1 до 7.")
        return
    await state.set_state(AdminState.waiting_question)
    await state.update_data(edit_question_num=q_num)
    await message.answer(
        f"Пришли новый текст для вопроса {q_num}.\n"
        "Если хочешь добавить картинку, пришли фото с подписью — подпись станет текстом вопроса."
    )


@router.message(AdminState.waiting_question)
async def save_question(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения вопросов.")
        return
    data = await state.get_data()
    q_num = data.get("edit_question_num")
    if not q_num:
        await state.clear()
        await message.answer("Состояние потеряно, попробуй ещё раз /set_question.")
        return

    text = message.caption_html or message.html_text or message.text
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id

    settings.setdefault("questions", {})
    settings["questions"][str(q_num)] = {
        "text": text,
        "photo_id": photo_id,
    }
    save_settings(settings)
    await state.clear()
    await message.answer(f"Вопрос {q_num} обновлён.")


@router.message(F.text == "/set_result")
async def set_result(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения итога.")
        return
    await state.set_state(AdminState.waiting_result)
    await message.answer(
        "Пришли новый текст итогового блока (что пишется после описания цветка).\n"
        "Можно использовать HTML-разметку."
    )


@router.message(AdminState.waiting_result)
async def save_result(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения итога.")
        return
    text = message.html_text or message.text
    settings["result_suffix"] = text
    save_settings(settings)
    await state.clear()
    await message.answer("Итоговый блок обновлён.")


@router.callback_query(F.data.startswith("q"), QuizState.answering)
async def process_answer(callback: CallbackQuery, state: FSMContext):
    try:
        part = callback.data.split("_", 1)
        if len(part) != 2:
            await callback.answer("Ошибка выбора.")
            return
        q_num = int(part[0][1:])  # q0 -> 0
        letter = part[1].strip().upper()
        if letter not in ("A", "B", "C", "D"):
            await callback.answer("Неверный вариант.")
            return
    except (ValueError, IndexError):
        await callback.answer("Ошибка.")
        return

    data = await state.get_data()
    answers = get_user_answers(data)
    if len(answers) != q_num:
        await callback.answer("Ответ на этот вопрос уже дан. Пройди тест заново: /start")
        return

    answers = answers + [letter]
    await state.update_data(answers=answers)

    if len(answers) < 7:
        await send_question(callback, len(answers), state)
        return

    # Все 7 ответов получены — показываем результат
    flower_key = get_flower_from_answers(answers)
    flower = FLOWER_RESULTS[flower_key]
    result_suffix = settings.get(
        "result_suffix",
        "Ищи садовника Ритку-Маргаритку - и забирай себя себе на память!\n\n"
        "<i>Хочешь пройти тест ещё раз? Нажми /start</i>\n\n",
    )
    result_text = (
        f"Вау, ты — <b>{flower['name']}</b>!\n\n"
        f"{flower['description']}\n\n"
        f"{result_suffix}"
    )
    await callback.message.edit_text(result_text, parse_mode="HTML")
    await state.clear()
    await callback.answer()


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
