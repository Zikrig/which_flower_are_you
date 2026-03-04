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


def make_question_keyboard(question_num: int) -> InlineKeyboardMarkup:
    q = QUESTIONS[question_num]
    buttons = []
    for letter, text in q["options"].items():
        btn_text = f"{letter}) {text[:60]}..." if len(text) > 60 else f"{letter}) {text}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"q{question_num}_{letter}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_answers(state_data: dict) -> list:
    return state_data.get("answers", [])


async def send_question(message_or_callback, question_num: int, state: FSMContext):
    intro = (
        "Внимательно прочитай вопросы и выбери один ответ в каждом из них. "
        "Выбирай тот ответ, который наиболее близок к твоему поведению в реальной жизни. "
        "По итогам теста ты узнаешь, какой цветок лучше всего отражает твою индивидуальность.\n\n"
        if question_num == 0
        else ""
    )
    q = QUESTIONS[question_num]
    text = f"{intro}Вопрос №{q['num']}\n\n{q['text']}"
    keyboard = make_question_keyboard(question_num)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.answer()
        await message_or_callback.message.edit_text(text, reply_markup=keyboard)
    else:
        await message_or_callback.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(QuizState.answering)
    await state.update_data(answers=[])
    await send_question(message, 0, state)


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
        f"{flower['description']}\n\n"
        "Хочешь пройти тест ещё раз? Нажми /start"
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
