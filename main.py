# -*- coding: utf-8 -*-
"""
Главный файл запуска Telegram бота для управления задачами
"""

import sys
import logging
import asyncio
from pathlib import Path

# Добавляем текущую директорию в PATH
sys.path.append(str(Path(__file__).parent))

from config import config
from bot import TaskManagerBot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def check_config():
    """Проверка конфигурации перед запуском"""
    if config.TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ Не установлен токен Telegram бота!")
        logger.info("Получите токен у @BotFather и установите в config.py")
        return False
    
    logger.info("✅ Конфигурация проверена")
    return True

def main():
    """Главная функция запуска бота"""
    logger.info("🚀 Запуск Telegram бота для управления задачами")
    
    # Проверяем конфигурацию
    if not check_config():
        sys.exit(1)
    
    try:
        # Создаём и запускаем бота
        bot = TaskManagerBot()
        bot.run()
        
    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
    finally:
        logger.info("🏁 Бот остановлен")

if __name__ == "__main__":
    main()

