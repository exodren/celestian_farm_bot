import os
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
INTERVAL_MINUTES = float(os.getenv("INTERVAL_MINUTES", "15"))
TARGETS_RAW = os.getenv("TARGETS", "")
MESSAGE_TEXT = os.getenv("MESSAGE_TEXT", "Хеллоу! Это тестовое сообщение.")

if not API_ID or not API_HASH:
    raise ValueError("Ошибка: API_ID и API_HASH должны быть указаны в файле .env!")

API_ID = int(API_ID)
def parse_target(target_str: str):
    target_str = target_str.strip()
    # Если строка — число (например -100123456789 или 12345678), преобразуем в int
    if target_str.isdigit() or (target_str.startswith("-") and target_str[1:].isdigit()):
        return int(target_str)
    return target_str

TARGETS = [parse_target(t) for t in TARGETS_RAW.split(",") if t.strip()]

