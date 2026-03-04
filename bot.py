import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from quiz_data import QUESTIONS, FLOWER_RESULTS, get_flower_from_answers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
storage = MemoryStorage()


class QuizState(StatesGroup):
    answering = State()


INTRO_TEXT = (
    "<b>Привет! Время расцветать!</b>\n\n"
    "Внимательно прочитай вопросы и выбери один ответ в каждом из них. "
    "Выбирай тот ответ, который наиболее близок к твоему поведению в реальной жизни.\n\n"
    "По итогам теста ты узнаешь, какой цветок лучше всего отражает твою индивидуальность."
)

START_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="НАЧАТЬ", callback_data="start_quiz")]
    ]
)

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
    q = QUESTIONS[question_num]
    options_text = "\n".join(
        f"<b>{letter}</b>) {text}" for letter, text in q["options"].items()
    )
    return (
        f"<b>Вопрос №{q['num']}</b>\n\n"
        f"{q['text']}\n\n"
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

    await message.answer(INTRO_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")


@router.callback_query(F.data == "start_quiz")
async def start_quiz(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(QuizState.answering)
    await state.update_data(answers=[])
    await send_question(callback, 0, state)


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
    result_text = (
        f"<b>{flower['name']}</b>\n\n"
        f"{flower['description']}\n\n"
        
        "Ищи садовника Ритку-Маргаритку - и забирай себя себе на память!\n\n"

        "<i>Хочешь пройти тест ещё раз? Нажми /start</i>\n\n"
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
