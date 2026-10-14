import asyncio
import logging
from pyrogram import Client
from pyrogram.errors import FloodWait, UserIsBlocked, PeerFlood, PeerIdInvalid, UsernameInvalid, RPCError
import config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Инициализация клиента Pyrogram (юзербот)
app = Client(
    "my_userbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH
)

async def send_broadcast():
    """Функция отправки одного круга рассылки."""
    logger.info("Starting broadcast cycle...")
    
    if not config.TARGETS:
        logger.warning("Список получателей TARGETS пуст! Проверьте файл .env.")
        return

    for target in config.TARGETS:
        try:
            # Получаем объект чата для предзагрузки access_hash пира в кеш Pyrogram
            chat = await app.get_chat(target)
            await app.send_message(chat_id=chat.id, text=config.MESSAGE_TEXT)
            logger.info(f"Успешно отправлено: {target} (ID: {chat.id})")
            
            # Пауза между сообщениями для защиты от спам-фильтра
            await asyncio.sleep(2)
            
        except FloodWait as e:
            logger.warning(f"Telegram просит подождать (FloodWait): {e.value} секунд. Ждем...")
            await asyncio.sleep(e.value)
        except PeerFlood:
            logger.error(f"Аккаунт получил флуд-бан (PeerFlood) при попытке отправить в {target}. Рассылка приостановлена.")
            break
        except PeerIdInvalid:
            logger.error(
                f"Ошибка PEER_ID_INVALID для {target}. "
                f"Причина: юзербот не состоит в этом чате/группе или текущая сессия ещё не 'видела' этот ID/юзернейм."
            )
        except UsernameInvalid:
            logger.error(f"Юзернейм {target} указан неверно.")
        except UserIsBlocked:
            logger.warning(f"Пользователь {target} заблокировал аккаунт.")
        except RPCError as e:
            logger.error(f"Ошибка RPC при отправке в {target}: {e}")
        except Exception as e:
            logger.exception(f"Неизвестная ошибка для {target}: {e}")

async def main():
    await app.start()
    logger.info("Юзербот успешно запущен!")
    
    interval_seconds = config.INTERVAL_MINUTES * 60
    logger.info(f"Интервал рассылки: {config.INTERVAL_MINUTES} минут ({interval_seconds} секунд).")

    try:
        while True:
            await send_broadcast()
            logger.info(f"Ожидание {config.INTERVAL_MINUTES} мин. до следующей рассылки...")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Остановка рассылки по запросу.")
    finally:
        await app.stop()
        logger.info("Юзербот остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Программа завершена.")
