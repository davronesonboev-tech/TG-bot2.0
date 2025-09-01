# -*- coding: utf-8 -*-
"""
Конфигурационный файл для Telegram бота управления задачами
"""

import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    # Загружаем .env из корня проекта
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except Exception:
    # Не критично, если python-dotenv не установлен
    pass
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class BotConfig:
    """Конфигурация бота"""
    # Telegram Bot Token (получить у @BotFather)
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
    
    # Пароли для доступа
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "CHANGE_ME_ADMIN")
    USER_PASSWORD: str = os.getenv("USER_PASSWORD", "CHANGE_ME_USER")
    
    # База данных
    DATABASE_PATH: str = "task_manager.db"
    
    # Настройки уведомлений
    NOTIFICATION_CHECK_INTERVAL: int = 300  # 5 минут в секундах
    REMINDER_HOURS_BEFORE: List[int] = field(default_factory=lambda: [24, 6, 1])  # За сколько часов напоминать
    
    # Настройки экспорта
    EXPORT_FOLDER: str = "exports"
    
    # Настройки диаграмм
    CHARTS_FOLDER: str = "charts"
    
    # Лимиты
    MAX_TASK_TITLE_LENGTH: int = 100
    MAX_TASK_DESCRIPTION_LENGTH: int = 500
    MAX_TASKS_PER_PAGE: int = 5

    # Часовой пояс отображения (сдвиг в часах относительно UTC)
    DISPLAY_TZ_OFFSET_HOURS: int = int(os.getenv("TZ_OFFSET_HOURS", "5"))

# Глобальная конфигурация
config = BotConfig()

# Эмодзи для красивого интерфейса
EMOJIS = {
    'menu': '📋',
    'create_task': '➕',
    'my_tasks': '📝',
    'all_tasks': '📊',
    'reports': '📈',
    'gantt': '📉',
    'settings': '⚙️',
    'back': '⬅️',
    'next': '➡️',
    'done': '✅',
    'pending': '🕐',
    'overdue': '🔴',
    'new': '🆕',
    'admin': '👑',
    'user': '👤',
    'deadline': '⏰',
    'priority_high': '🔥',
    'priority_medium': '🟡',
    'priority_low': '🟢',
    'excel': '📊',
    'chart': '📈',
    'notification': '🔔',
    'warning': '⚠️',
    'success': '✅',
    'error': '❌',
    'info': 'ℹ️'
}

# Статусы задач
TASK_STATUS = {
    'new': 'Новая',
    'in_progress': 'В работе',
    'completed': 'Выполнена',
    'overdue': 'Просрочена',
    'cancelled': 'Отменена'
}

# Приоритеты задач
TASK_PRIORITY = {
    'low': 'Низкий',
    'medium': 'Средний',
    'high': 'Высокий'
}

# Роли пользователей
USER_ROLES = {
    'admin': 'Администратор',
    'user': 'Исполнитель'
}
