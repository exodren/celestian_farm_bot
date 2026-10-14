import asyncio
import logging
import time
import os
import json
import random
from datetime import datetime, timedelta
import pyrogram.utils
from pyrogram import Client
from pyrogram.enums import ChatAction
from pyrogram.errors import FloodWait, RPCError
import config

# Патч для поддержки 64-битных ID супергрупп и каналов в Telegram (ID > 2147483647)
pyrogram.utils.MIN_CHANNEL_ID = -1009999999999

# ─── Настройки рандомизации задержки (защита от детекта бота) ────────────────
RANDOM_DELAY_MIN = 30.0        # от 30 секунд
RANDOM_DELAY_MAX = 180.0    # до 3 минут (180 секунд)

# ─── Логирование ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─── Таблица уровней и действий ───────────────────────────────────────────────
#
# Структура:
#   level        — номер уровня (1–18)
#   name         — название уровня
#   sparks_req   — сколько искр нужно иметь чтобы РАЗБЛОКИРОВАТЬ этот уровень
#   cmd          — команда обычного действия
#   label        — короткое название действия
#   cooldown     — кулдаун в секундах
#   reward       — искры за выполнение
#
LEVELS = [
    # lvl  название уровня              порог     команда                              метка             КД сек   искры
    ( 1,  "Зарождение интереса",              0, ".отн сделать комплимент",      "Комплимент",      5 * 60,    15),
    ( 2,  "Первые искры",                 1_000, ".отн сделать завтрак",         "Завтрак",         8 * 60,    35),
    ( 3,  "Взаимное притяжение",          2_000, ".отн подарить цветы",          "Цветы",          11 * 60,    60),
    ( 4,  "Глубокое узнавание",           3_000, ".отн посмотреть фильм",        "Фильм",          15 * 60,    80),
    ( 5,  "Первая близость",              6_000, ".отн сделать массаж",          "Массаж",         20 * 60,   120),
    ( 6,  "Романтическое увлечение",     10_000, ".отн романтический ужин",      "Ужин",           30 * 60,   170),
    ( 7,  "Прочная связь",               22_000, ".отн сделать подарок",         "Подарок",        38 * 60,   230),
    ( 8,  "Гармония и понимание",         34_000, ".отн туристическая поездка",   "Поездка",        45 * 60,   300),
    ( 9,  "Совместное будущее",           40_000, ".отн вечер астрономии",        "Астрономия",     60 * 60,   400),
    (10,  "Безусловная любовь",           55_000, ".отн приятные воспоминания",   "Воспоминания",   80 * 60,   500),
    (11,  "Слияние сердец",               70_000, ".отн совместная фотосессия",   "Фотосессия",     90 * 60,   700),
    (12,  "Духовная связь",              100_000, ".отн создать традицию",        "Традиция",      100 * 60,   900),
    (13,  "Полное доверие",              150_000, ".отн совместный проект",       "Проект",        110 * 60,  1100),
    (14,  "Неразрывная близость",        230_000, ".отн исследовать родословную", "Родословная",   120 * 60,  1400),
    (15,  "Гармоничная связь",           340_000, ".отн спланировать будущее",    "Будущее",       130 * 60,  1700),
    (16,  "Абсолютное единство",         560_000, ".отн исполнить желание",       "Желание",       140 * 60,  2100),
    (17,  "Вечная преданность",          790_000, ".отн годовщина отношений",     "Годовщина",     150 * 60,  2500),
    (18,  "Бесконечная любовь",        1_100_000, ".отн обустроить жилище",       "Жилище",        160 * 60,  3000),
]

# ─── Файл состояния (сохраняется между перезапусками) ─────────────────────────
STATE_FILE = "farmer_state.json"

def load_state() -> dict:
    """Загружает сохранённое состояние."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"Состояние загружено: {state['total_sparks']:,} искр, ур. {state['current_level']}")
            return state
        except Exception as e:
            logger.warning(f"Не удалось загрузить state: {e} — начинаем заново.")
    return {
        "total_sparks": 0,
        "current_level": 1,
        "next_available": {},   # "idx": timestamp
        "total_actions": 0,
        "session_sparks": 0,
    }

def save_state(state: dict):
    """Сохраняет состояние на диск."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Не удалось сохранить state: {e}")


def format_time(seconds: float, show_ms: bool = False) -> str:
    """Форматирует секунды в человекочитаемый вид (с поддержкой миллисекунд)."""
    if seconds <= 0:
        return "сейчас"
    total_sec = int(seconds)
    ms = int(round((seconds - total_sec) * 1000))
    if ms >= 1000:
        total_sec += 1
        ms = 0

    if total_sec < 60:
        return f"{total_sec}.{ms:03d}с" if show_ms and ms > 0 else f"{total_sec}с"
    elif total_sec < 3600:
        m, s = divmod(total_sec, 60)
        return f"{m}м {s}.{ms:03d}с" if show_ms and ms > 0 else f"{m}м {s}с"
    else:
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h}ч {m}м {s}с"


def get_current_level(total_sparks: int) -> int:
    """Определяет текущий уровень по количеству искр."""
    current = 1
    for lvl, _, threshold, *_ in LEVELS:
        # НЕ делаем break — проходим все уровни, т.к. пороги растут монотонно
        # и пропускать нельзя (иначе при gaps в порогах уровень будет неверным)
        if total_sparks >= threshold:
            current = lvl
    return current


def get_unlocked_actions(total_sparks: int) -> list:
    """
    Возвращает список индексов разблокированных действий
    (те уровни, порог которых <= total_sparks).
    """
    unlocked = []
    for idx, (lvl, _, threshold, cmd, label, cooldown, reward) in enumerate(LEVELS):
        if total_sparks >= threshold:
            unlocked.append(idx)
    return unlocked


def get_best_action(state: dict) -> tuple | None:
    """
    Выбирает лучшее следующее действие среди разблокированных.

    Стратегия:
      1. Если есть разблокированные действия БЕЗ кулдауна — выбираем то,
         которое даёт больше искр в минуту (sparks/cooldown).
      2. Если все на кулдауне — выбираем то, у которого кулдаун истечёт
         раньше всего.

    Возвращает (idx, wait_seconds) или None.
    """
    total_sparks = state["total_sparks"]
    next_avail = state["next_available"]
    now = time.time()

    unlocked = get_unlocked_actions(total_sparks)
    if not unlocked:
        return None

    # Разделяем на "готовые сейчас" и "на кулдауне"
    ready = []
    on_cd = []
    for idx in unlocked:
        avail_at = float(next_avail.get(str(idx), 0))
        remaining = avail_at - now
        if remaining <= 0:
            ready.append(idx)
        else:
            on_cd.append((remaining, idx))

    if ready:
        # Из готовых — берём с лучшим соотношением искры/минута
        def efficiency(idx):
            lvl, _, _, cmd, label, cooldown, reward = LEVELS[idx]
            return reward / (cooldown / 60)  # искры в минуту

        best_idx = max(ready, key=efficiency)
        return best_idx, 0.0

    if on_cd:
        # Ждём ближайшее
        on_cd.sort()
        wait, best_idx = on_cd[0]
        return best_idx, wait

    return None


async def farm_loop(app: Client, chat_id: int, state: dict):
    """Основной цикл фарминга с учётом уровней."""
    prev_level = state["current_level"]

    logger.info("=" * 55)
    logger.info("  ОТН-ФАРМЕР  |  умный режим (учёт уровней)")
    logger.info("=" * 55)
    logger.info(f"  Накоплено:  {state['total_sparks']:>12,} искр")
    logger.info(f"  Уровень:    {prev_level:>12}")
    unlocked_count = len(get_unlocked_actions(state["total_sparks"]))
    logger.info(f"  Доступно действий: {unlocked_count} из {len(LEVELS)}")
    logger.info("=" * 55)

    while True:
        result = get_best_action(state)
        if result is None:
            logger.warning("Нет доступных действий. Ждём 30с...")
            await asyncio.sleep(30)
            continue

        idx, wait = result
        lvl, lvl_name, threshold, cmd, label, cooldown, reward = LEVELS[idx]

        # Если нужно ждать — сообщаем и ждём
        if wait > 0:
            available_at = datetime.now() + timedelta(seconds=wait)
            logger.info(
                f"[КД] Все действия на кулдауне. Ждём [{label}] "
                f"ещё {format_time(wait)} (в {available_at.strftime('%H:%M:%S')})"
            )
            while True:
                now = time.time()
                avail_ts = float(state["next_available"].get(str(idx), 0))
                remaining = avail_ts - now
                if remaining <= 0:
                    break
                await asyncio.sleep(min(5.0, remaining))

        # ── Отправляем команду с человеческой неточностью ─────────────────
        try:
            # 1. Естественная задержка реакции человека (не ровно в миллисекунду таймера)
            reaction_delay = random.uniform(0.700, 2.300)
            await asyncio.sleep(reaction_delay)

            # 2. Имитация набора текста (статус 'печатает...' в Telegram)
            try:
                await app.send_chat_action(chat_id, ChatAction.TYPING)
                # Время набора текста с естественным разбросом миллисекунд
                typing_delay = len(cmd) * random.uniform(0.040, 0.075) + random.uniform(0.300, 0.800)
                await asyncio.sleep(typing_delay)
            except Exception:
                pass

            # 3. Отправка команды
            await app.send_message(chat_id=chat_id, text=cmd)
            now_ts = time.time()

            # 4. Неточный разброс следующего КД с дробными миллисекундами (float)
            random_extra = random.uniform(RANDOM_DELAY_MIN, RANDOM_DELAY_MAX)
            total_cd = cooldown + random_extra

            # Обновляем состояние
            state["next_available"][str(idx)] = now_ts + total_cd
            state["total_sparks"] += reward
            state["total_actions"] += 1
            state["session_sparks"] = state.get("session_sparks", 0) + reward

            # Проверяем левел-ап
            new_level = get_current_level(state["total_sparks"])
            leveled_up = new_level > prev_level

            if leveled_up:
                state["current_level"] = new_level
                logger.info("=" * 55)
                logger.info(f"  ЛЕВЕЛ АП!  Ур. {new_level} — {lvl_name if new_level == lvl else LEVELS[new_level-1][1]}")
                new_unlocked = len(get_unlocked_actions(state["total_sparks"]))
                logger.info(f"  Доступно действий: {new_unlocked} из {len(LEVELS)}")
                logger.info("=" * 55)

                # Показываем все только что разблокированные действия
                for ul_lvl in range(prev_level + 1, new_level + 1):
                    if ul_lvl <= len(LEVELS):
                        ul_idx = ul_lvl - 1
                        _, _, _, ul_cmd, ul_label, ul_cd, ul_reward = LEVELS[ul_idx]
                        ul_eff = round(ul_reward / (ul_cd / 60), 1)
                        logger.info(
                            f"  + Разблокировано: [{ul_label}] "
                            f"+{ul_reward} искр / {format_time(ul_cd)} КД "
                            f"({ul_eff} искр/мин)"
                        )

                prev_level = new_level

            # Вычисляем эффективность текущего действия
            eff = round(reward / (cooldown / 60), 1)

            logger.info(
                f"[OK] Ур.{lvl:>2} [{label:<16}] "
                f"+{reward:>5} искр | "
                f"КД {format_time(cooldown)} (+{format_time(random_extra, show_ms=True)} рандом) | "
                f"{eff:>5} искр/мин | "
                f"Всего: {state['total_sparks']:>9,}"
            )

            # Следующий порог (current_level — это актуальный уровень после возможного левел-апа)
            cur_lvl = state["current_level"]
            if cur_lvl < len(LEVELS):
                next_lvl_data = LEVELS[cur_lvl]  # cur_lvl как индекс даёт следующий уровень (0-based)
                next_thresh = next_lvl_data[2]
                needed = next_thresh - state["total_sparks"]
                if needed > 0:
                    logger.info(f"       До ур.{cur_lvl + 1} ({next_lvl_data[1]}): ещё {needed:,} искр")

            # Сохраняем на диск каждые 10 действий
            if state["total_actions"] % 10 == 0:
                save_state(state)

            # Естественная пауза чтения ответа бота с неточностью миллисекунд
            human_pause = random.uniform(2.200, 4.600)
            await asyncio.sleep(human_pause)

        except FloodWait as e:
            logger.warning(f"[FLOOD] Telegram просит подождать {e.value}с...")
            await asyncio.sleep(e.value + 1)

        except RPCError as e:
            logger.error(f"[RPC] Ошибка для [{label}]: {e}")
            await asyncio.sleep(10)

        except Exception as e:
            logger.exception(f"[ERR] Неизвестная ошибка для [{label}]: {e}")
            await asyncio.sleep(10)


# ─── Клиент ───────────────────────────────────────────────────────────────────
app = Client(
    "my_userbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH
)


async def main():
    if not config.TARGETS:
        logger.error("TARGETS в .env пуст! Укажи chat_id или @username чата.")
        return

    # Загружаем сохранённое состояние
    state = load_state()

    chat_target = config.TARGETS[0]

    await app.start()
    logger.info("Авторизация успешна!")

    try:
        chat = None
        # 1. Попытка получить чат напрямую
        try:
            chat = await app.get_chat(chat_target)
        except Exception as e:
            logger.info(f"Прямой поиск чата {chat_target} не удался ({e}). Синхронизируем диалоги...")
            # 2. Предзагрузка диалогов для наполнения кэша access_hash пиров
            async for dialog in app.get_dialogs():
                c = dialog.chat
                if c.id == chat_target or (c.username and f"@{c.username.lower()}" == str(chat_target).lower()):
                    chat = c
                    break

            # 3. Если всё ещё не найден, повторяем get_chat после прогрева кэша
            if chat is None:
                chat = await app.get_chat(chat_target)

        chat_id = chat.id
        title = getattr(chat, "title", None) or getattr(chat, "first_name", str(chat_id))
        logger.info(f"Чат: {title} (ID: {chat_id})")
        await farm_loop(app, chat_id, state)

    except KeyboardInterrupt:
        logger.info("Остановлено пользователем.")
    except Exception as e:
        logger.error(f"Не удалось подключиться к чату {chat_target}: {e}")
        logger.info("Убедитесь, что аккаунт состоит в этой группе/канале, либо укажите @username группы в .env")
    finally:
        save_state(state)
        logger.info(
            f"Сохранено. Итог сессии: {state.get('session_sparks', 0):,} искр "
            f"за {state['total_actions']} действий всего."
        )
        try:
            if app.is_connected:
                await app.stop()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
