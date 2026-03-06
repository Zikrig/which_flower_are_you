import asyncio
import json
import logging
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS
from quiz_data import QUESTIONS, FLOWER_RESULTS, FLOWER_IMAGE_FILES, get_flower_from_answers

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


@router.message(F.text.in_(("admin", "/admin")))
async def admin_menu(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав доступа к админ-меню.")
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔹 Приветствие", callback_data="admin_intro")],
            [InlineKeyboardButton(text="🔹 Вопросы", callback_data="admin_questions")],
            [InlineKeyboardButton(text="🔹 Итог", callback_data="admin_result")],
        ]
    )
    await state.clear()
    await message.answer("Админ-меню:", reply_markup=keyboard)


@router.callback_query(F.data == "admin_intro")
async def admin_intro(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    current = get_intro_text()
    await state.set_state(AdminState.waiting_intro)
    await callback.message.edit_text(
        "Текущее приветствие:\n\n"
        f"{current}\n\n"
        "Пришли новый текст приветственного сообщения (можно с HTML-разметкой).",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_intro)
async def save_intro(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения приветствия.")
        return
    text = message.text
    settings["intro_text"] = text
    save_settings(settings)
    await state.clear()
    await message.answer("Приветственное сообщение обновлено.")


@router.callback_query(F.data == "admin_questions")
async def admin_questions(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    # клавиатура выбора номера вопроса
    rows = []
    for i in range(1, len(QUESTIONS) + 1):
        rows.append(
            [InlineKeyboardButton(text=f"Вопрос {i}", callback_data=f"admin_q_{i}")]
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(
        "Выбери вопрос, который хочешь изменить:", reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_q_"))
async def admin_question_pick(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    try:
        q_num = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка номера вопроса.", show_alert=True)
        return
    if q_num < 1 or q_num > len(QUESTIONS):
        await callback.answer("Неверный номер вопроса.", show_alert=True)
        return

    await state.set_state(AdminState.waiting_question)
    await state.update_data(edit_question_num=q_num)

    base_q = QUESTIONS[q_num - 1]
    overrides = settings.get("questions", {}).get(str(q_num), {})
    current_text = overrides.get("text") or base_q["text"]

    await callback.message.edit_text(
        f"Текущий текст вопроса {q_num}:\n\n"
        f"{current_text}\n\n"
        f"Пришли новый текст для вопроса {q_num}.\n"
        "Если хочешь добавить картинку, пришли фото с подписью — подпись станет текстом вопроса.",
    )
    await callback.answer()


@router.message(AdminState.waiting_question)
async def save_question(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения вопросов.")
        return
    data = await state.get_data()
    q_num = data.get("edit_question_num")
    if not q_num:
        await state.clear()
        await message.answer("Состояние потеряно, попробуй ещё раз через admin-меню.")
        return

    # для простоты считаем, что админ шлёт обычный текст или фото с подписью
    text = message.caption or message.text
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


@router.callback_query(F.data == "admin_result")
async def admin_result(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    await state.set_state(AdminState.waiting_result)
    current = settings.get(
        "result_suffix",
        "Ищи садовника Ритку-Маргаритку - и забирай себя себе на память!\n\n"
        "<i>Хочешь пройти тест ещё раз? Нажми /start</i>\n\n",
    )
    await callback.message.edit_text(
        "Текущий итоговый блок:\n\n"
        f"{current}\n\n"
        "Пришли новый текст итогового блока (что пишется после описания цветка).\n"
        "Можно использовать HTML-разметку.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_result)
async def save_result(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав для изменения итога.")
        return
    text = message.text
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

    image_path = FLOWER_IMAGE_FILES.get(flower_key)
    if image_path:
        try:
            photo = FSInputFile(image_path)
            await callback.message.answer_photo(photo=photo, caption=result_text, parse_mode="HTML")
            await callback.message.delete()
        except Exception as e:
            logger.exception("Failed to send result image: %s", e)
            await callback.message.edit_text(result_text, parse_mode="HTML")
    else:
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
