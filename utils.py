# -*- coding: utf-8 -*-
"""
Утилиты для форматирования и валидации данных
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from config import EMOJIS, TASK_STATUS, TASK_PRIORITY, config

def _to_local_time(dt: datetime) -> datetime:
    """Интерпретируем на входе UTC (если tzinfo отсутствует) и конвертируем в локальный сдвиг из конфигурации."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    target_tz = timezone(timedelta(hours=config.DISPLAY_TZ_OFFSET_HOURS))
    return dt.astimezone(target_tz)

def get_current_tashkent_time() -> datetime:
    """Получить текущее время в Ташкенте (UTC+5)"""
    utc_now = datetime.utcnow().replace(tzinfo=timezone.utc)
    tashkent_tz = timezone(timedelta(hours=config.DISPLAY_TZ_OFFSET_HOURS))
    return utc_now.astimezone(tashkent_tz).replace(tzinfo=None)

def to_utc(dt: datetime) -> Optional[datetime]:
    """Конвертировать локальное время (по DISPLAY_TZ_OFFSET_HOURS) в UTC (naive)."""
    if not dt:
        return None
    if dt.tzinfo is None:
        local_tz = timezone(timedelta(hours=config.DISPLAY_TZ_OFFSET_HOURS))
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

def format_datetime(dt: datetime, show_time: bool = True, is_deadline: bool = False) -> str:
    """
    Форматирование даты и времени
    
    Args:
        dt: Объект datetime
        show_time: Показывать ли время
        
    Returns:
        Отформатированная строка
    """
    if not dt:
        return "Не указано"
    
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    dt_local = _to_local_time(dt)
    if show_time:
        return dt_local.strftime("%d.%m.%Y %H:%M")
    return dt_local.strftime("%d.%m.%Y")

def format_task(task: Dict, detailed: bool = False) -> str:
    """
    Форматирование информации о задаче
    
    Args:
        task: Словарь с данными задачи
        detailed: Показывать ли подробную информацию
        
    Returns:
        Отформатированная строка
    """
    # Эмодзи для статуса и приоритета
    status_emoji = EMOJIS.get(task['status'], EMOJIS['pending'])
    priority_emoji = EMOJIS.get(f'priority_{task["priority"]}', '')
    
    # Заголовок
    text = f"{status_emoji} **{task['title']}**\n\n"
    
    if detailed:
        # Подробная информация
        text += f"🆔 **ID:** {task['id']}\n"
        text += f"📝 **Описание:** {task['description'] or 'Не указано'}\n\n"
        
        text += f"👤 **Создатель:** {task['creator_name'] or 'Неизвестно'}\n"
        text += f"🎯 **Исполнитель:** {task['assignee_name'] or 'Не назначен'}\n\n"
        
        text += f"📊 **Статус:** {TASK_STATUS[task['status']]} {status_emoji}\n"
        text += f"🔥 **Приоритет:** {TASK_PRIORITY[task['priority']]} {priority_emoji}\n\n"
        
        # Даты
        created_at = format_datetime(task['created_at'])
        text += f"📅 **Создано:** {created_at}\n"
        
        if task['deadline']:
            deadline = format_datetime(task['deadline'], is_deadline=True)
            text += f"⏰ **Дедлайн:** {deadline}\n"
        
        if task['completed_at']:
            completed_at = format_datetime(task['completed_at'])
            text += f"✅ **Выполнено:** {completed_at}\n"
        
        # Статус просрочки (сравнение в UTC)
        if task['deadline'] and task['status'] not in ['completed', 'cancelled']:
            deadline_dt = datetime.fromisoformat(task['deadline'].replace('Z', '+00:00')) if isinstance(task['deadline'], str) else task['deadline']
            if isinstance(deadline_dt, datetime):
                if deadline_dt.tzinfo is None:
                    deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
                now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
                if deadline_dt < now_utc:
                    text += f"\n⚠️ **ЗАДАЧА ПРОСРОЧЕНА!**"
    else:
        # Краткая информация
        text += f"🎯 {task['assignee_name'] or 'Не назначен'}\n"
        text += f"🔥 {TASK_PRIORITY[task['priority']]}\n"
        
        if task['deadline']:
            deadline = format_datetime(task['deadline'], show_time=False)
            text += f"⏰ {deadline}\n"
    
    return text

def validate_deadline(deadline_str: str) -> Optional[datetime]:
    """
    Валидация и парсинг дедлайна
    
    Args:
        deadline_str: Строка с дедлайном
        
    Returns:
        Объект datetime или None если формат неверный
    """
    if not deadline_str:
        return None
    
    # Поддерживаемые форматы
    formats = [
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d/%m/%Y %H:%M", 
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(deadline_str, fmt)
            # Если время не указано, устанавливаем конец дня
            if "%H:%M" not in fmt:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError:
            continue
    
    # Попробуем относительные форматы
    deadline_str = deadline_str.lower().strip()
    
    # "через X дней/часов/минут"
    current_time = get_current_tashkent_time()
    patterns = [
        (r'через (\d+) дн', lambda x: current_time + timedelta(days=int(x))),
        (r'через (\d+) ч', lambda x: current_time + timedelta(hours=int(x))),
        (r'через (\d+) мин', lambda x: current_time + timedelta(minutes=int(x))),
        (r'завтра', lambda x: current_time.replace(hour=23, minute=59, second=59) + timedelta(days=1)),
        (r'послезавтра', lambda x: current_time.replace(hour=23, minute=59, second=59) + timedelta(days=2)),
    ]
    
    for pattern, func in patterns:
        match = re.search(pattern, deadline_str)
        if match:
            return func(match.group(1) if match.groups() else None)
    
    return None

def format_file_size(size_bytes: int) -> str:
    """Форматирование размера файла"""
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f} КБ"
    elif size_bytes < 1024**3:
        return f"{size_bytes/1024**2:.1f} МБ"
    else:
        return f"{size_bytes/1024**3:.1f} ГБ"

def truncate_text(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """Обрезка текста с добавлением суффикса"""
    if len(text) <= max_length:
        return text
    return text[:max_length-len(suffix)] + suffix

def format_user_mention(user_name: str, user_id: int = None) -> str:
    """Форматирование упоминания пользователя"""
    if user_id:
        return f"[@{user_name}](tg://user?id={user_id})"
    return f"**{user_name}**"

def get_status_emoji(status: str) -> str:
    """Получение эмодзи для статуса"""
    return EMOJIS.get(status, EMOJIS['pending'])

def get_priority_emoji(priority: str) -> str:
    """Получение эмодзи для приоритета"""
    return EMOJIS.get(f'priority_{priority}', '')

def format_progress_bar(completed: int, total: int, length: int = 10) -> str:
    """Создание полосы прогресса"""
    if total == 0:
        return "█" * length
    
    filled = int(length * completed / total)
    bar = "█" * filled + "░" * (length - filled)
    percentage = int(100 * completed / total)
    
    return f"{bar} {percentage}%"

def parse_priority(priority_str: str) -> str:
    """Парсинг приоритета из строки"""
    priority_str = priority_str.lower().strip()
    
    priority_map = {
        'низкий': 'low',
        'низ': 'low',
        'low': 'low',
        'l': 'low',
        '1': 'low',
        
        'средний': 'medium',
        'сред': 'medium',
        'medium': 'medium',
        'm': 'medium',
        '2': 'medium',
        
        'высокий': 'high',
        'выс': 'high',
        'high': 'high',
        'h': 'high',
        '3': 'high',
    }
    
    return priority_map.get(priority_str, 'medium')

def is_valid_telegram_username(username: str) -> bool:
    """Проверка валидности Telegram username"""
    if not username:
        return False
    
    # Убираем @ если есть
    username = username.lstrip('@')
    
    # Проверяем формат: 5-32 символа, буквы, цифры, подчеркивания
    pattern = r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$'
    return bool(re.match(pattern, username))

def format_duration(start_time: datetime, end_time: datetime = None) -> str:
    """Форматирование продолжительности"""
    if not end_time:
        end_time = get_current_tashkent_time()
    
    duration = end_time - start_time
    
    if duration.days > 0:
        return f"{duration.days} дн. {duration.seconds // 3600} ч."
    elif duration.seconds >= 3600:
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        return f"{hours} ч. {minutes} мин."
    else:
        minutes = duration.seconds // 60
        return f"{minutes} мин."

