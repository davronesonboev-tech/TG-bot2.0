# -*- coding: utf-8 -*-
"""
Модуль уведомлений и напоминаний
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from telegram import Bot
from telegram.error import TelegramError

from config import config, EMOJIS
from database import db
from utils import format_task, format_datetime, get_current_tashkent_time

logger = logging.getLogger(__name__)

class NotificationManager:
    """Менеджер уведомлений и напоминаний"""
    
    def __init__(self):
        self.bot = None
        self.is_running = False
    
    async def start_notification_loop(self, application):
        """Запуск цикла проверки уведомлений"""
        self.bot = application.bot
        self.is_running = True
        
        logger.info("🔔 Служба уведомлений запущена")
        
        while self.is_running:
            try:
                await self.check_and_send_notifications()
                await self.check_overdue_tasks()
                await self.schedule_deadline_reminders()
                
                # Ждём указанный интервал
                await asyncio.sleep(config.NOTIFICATION_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле уведомлений: {e}")
                await asyncio.sleep(60)  # Короткая пауза при ошибке
    
    async def check_and_send_notifications(self):
        """Проверка и отправка запланированных уведомлений"""
        notifications = db.get_pending_notifications()
        
        for notification in notifications:
            try:
                await self.send_notification(
                    telegram_id=notification['telegram_id'],
                    message=notification['message'],
                    task_id=notification['task_id']
                )
                
                # Отмечаем уведомление как отправленное
                db.mark_notification_sent(notification['id'])
                
                logger.info(f"Отправлено уведомление пользователю {notification['telegram_id']}")
                
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления {notification['id']}: {e}")
    
    async def check_overdue_tasks(self):
        """Проверка и обновление просроченных задач"""
        # Обновляем статус просроченных задач
        db.update_overdue_tasks()
        
        # Получаем просроченные задачи для уведомлений
        overdue_tasks = db.get_overdue_tasks()
        
        for task in overdue_tasks:
            # Шлём единожды: если уже есть уведомление типа 'deadline' по этой задаче, пропускаем
            if db.exists_notification_by_task_type(task['id'], 'deadline'):
                continue

            if task['assignee_telegram_id']:
                assignee = db.get_user_by_telegram_id(task['assignee_telegram_id'])
                if assignee:
                    # Создаём запись уведомления (история + предотвращение дублей)
                    message = (
                        f"{EMOJIS['warning']} **ЗАДАЧА ПРОСРОЧЕНА!**\n\n"
                        f"{format_task(task, detailed=True)}\n\n"
                        f"Пожалуйста, обновите статус задачи или свяжитесь с руководителем."
                    )
                    notif_id = db.create_notification(
                        user_id=assignee['id'],
                        task_id=task['id'],
                        notification_type='deadline',
                        message=message,
                        scheduled_at=get_current_tashkent_time()
                    )
                    # Отправляем немедленно и помечаем отправленным
                    await self.send_notification(
                        telegram_id=task['assignee_telegram_id'],
                        message=message,
                        task_id=task['id']
                    )
                    db.mark_notification_sent(notif_id)
    
    async def schedule_deadline_reminders(self):
        """Планирование напоминаний о дедлайнах"""
        # Получаем активные задачи с дедлайнами
        active_tasks = db.get_all_tasks(status='new')
        active_tasks.extend(db.get_all_tasks(status='in_progress'))
        
        now = datetime.utcnow()
        
        for task in active_tasks:
            if not task['deadline'] or not task['assignee_id']:
                continue
            
            deadline = datetime.fromisoformat(task['deadline'].replace('Z', '+00:00'))
            
            # Планируем напоминания за определённое время до дедлайна
            for hours_before in config.REMINDER_HOURS_BEFORE:
                reminder_time = deadline - timedelta(hours=hours_before)
                
                # Проверяем, нужно ли создать напоминание
                if reminder_time > now and reminder_time <= now + timedelta(hours=1):
                    await self.create_deadline_reminder(task, hours_before, reminder_time)
    
    async def create_deadline_reminder(self, task: Dict, hours_before: int, reminder_time: datetime):
        """Создание напоминания о дедлайне"""
        assignee = db.get_user_by_telegram_id(task['assignee_telegram_id'])
        if not assignee:
            return
        
        # Проверяем, не создано ли уже такое напоминание
        # Проверяем, не создано ли уже такое напоминание по задаче и типу
        existing_notifications = db.get_unsent_notifications_by_task_type(task['id'], 'reminder')
        for notif in existing_notifications:
            if f"{hours_before} часов" in notif['message']:
                return  # Напоминание уже создано
        
        message = (
            f"{EMOJIS['deadline']} **НАПОМИНАНИЕ О ДЕДЛАЙНЕ**\n\n"
            f"⏰ До завершения задачи осталось **{hours_before} часов**!\n\n"
            f"{format_task(task, detailed=True)}"
        )
        
        db.create_notification(
            user_id=assignee['id'],
            task_id=task['id'],
            notification_type='reminder',
            message=message,
            scheduled_at=reminder_time
        )
        
        logger.info(f"Создано напоминание для задачи {task['id']} за {hours_before} часов")
    
    async def send_notification(self, telegram_id: int, message: str, task_id: int = None):
        """Отправка уведомления пользователю"""
        if not self.bot:
            logger.error("Bot не инициализирован")
            return
        
        try:
            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode='Markdown'
            )
        except TelegramError as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {telegram_id}: {e}")
            raise
    
    async def notify_task_assigned(self, task: Dict, assignee_telegram_id: int):
        """Уведомление о назначении задачи"""
        message = (
            f"{EMOJIS['new']} **НОВАЯ ЗАДАЧА НАЗНАЧЕНА**\n\n"
            f"{format_task(task, detailed=True)}\n\n"
            f"Задача ожидает выполнения. Удачи! 💪"
        )
        
        await self.send_notification(assignee_telegram_id, message, task['id'])
    
    async def notify_task_status_changed(self, task: Dict, old_status: str, new_status: str, 
                                       creator_telegram_id: int):
        """Уведомление об изменении статуса задачи"""
        status_emojis = {
            'new': EMOJIS['new'],
            'in_progress': EMOJIS['pending'],
            'completed': EMOJIS['done'],
            'overdue': EMOJIS['overdue'],
            'cancelled': EMOJIS['error']
        }
        
        message = (
            f"{status_emojis.get(new_status, EMOJIS['info'])} **СТАТУС ЗАДАЧИ ИЗМЕНЁН**\n\n"
            f"📝 **Задача:** {task['title']}\n"
            f"📊 **Было:** {old_status}\n"
            f"📊 **Стало:** {new_status}\n\n"
            f"🎯 **Исполнитель:** {task['assignee_name']}"
        )
        
        if new_status == 'completed':
            message += f"\n\n🎉 **Поздравляем с выполнением задачи!**"
        
        await self.send_notification(creator_telegram_id, message, task['id'])
    
    async def notify_task_deadline_approaching(self, task: Dict, hours_left: int):
        """Уведомление о приближающемся дедлайне"""
        if not task['assignee_telegram_id']:
            return
        
        urgency_level = "🔥" if hours_left <= 1 else "⚠️" if hours_left <= 6 else "🕐"
        
        message = (
            f"{urgency_level} **ДЕДЛАЙН ПРИБЛИЖАЕТСЯ**\n\n"
            f"⏰ До завершения задачи осталось: **{hours_left} ч.**\n\n"
            f"{format_task(task, detailed=True)}\n\n"
            f"Не забудьте обновить статус задачи! 📋"
        )
        
        await self.send_notification(task['assignee_telegram_id'], message, task['id'])
    
    async def send_daily_summary(self, user_telegram_id: int, user_id: int):
        """Отправка ежедневной сводки"""
        user_stats = db.get_user_stats(user_id)
        active_tasks = db.get_tasks_by_user(user_id, 'in_progress')
        new_tasks = db.get_tasks_by_user(user_id, 'new')
        
        message = (
            f"{EMOJIS['menu']} **ЕЖЕДНЕВНАЯ СВОДКА**\n\n"
            f"📊 **Ваша статистика:**\n"
            f"• Всего задач: {user_stats['total_tasks']}\n"
            f"• Выполнено: {user_stats['completed_tasks']}\n"
            f"• В работе: {len(active_tasks)}\n"
            f"• Новых: {len(new_tasks)}\n"
            f"• Просрочено: {user_stats['overdue_tasks']}\n\n"
        )
        
        if new_tasks:
            message += f"🆕 **Новые задачи ({len(new_tasks)}):**\n"
            for task in new_tasks[:3]:  # Показываем только первые 3
                deadline_str = format_datetime(task['deadline'], show_time=False) if task['deadline'] else "Без дедлайна"
                message += f"• {task['title'][:30]}... ({deadline_str})\n"
            
            if len(new_tasks) > 3:
                message += f"• ... и ещё {len(new_tasks) - 3} задач\n"
            message += "\n"
        
        if active_tasks:
            message += f"🔄 **В работе ({len(active_tasks)}):**\n"
            for task in active_tasks[:3]:
                deadline_str = format_datetime(task['deadline'], show_time=False) if task['deadline'] else "Без дедлайна"
                message += f"• {task['title'][:30]}... ({deadline_str})\n"
            
            if len(active_tasks) > 3:
                message += f"• ... и ещё {len(active_tasks) - 3} задач\n"
        
        message += f"\n🚀 **Удачного дня!**"
        
        await self.send_notification(user_telegram_id, message)
    
    async def send_weekly_report(self, user_telegram_id: int, user_id: int):
        """Отправка еженедельного отчёта"""
        # Статистика за неделю
        week_ago = datetime.utcnow() - timedelta(days=7)
        
        # Здесь можно добавить специальные запросы для статистики за неделю
        user_stats = db.get_user_stats(user_id)
        
        message = (
            f"{EMOJIS['reports']} **ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ**\n\n"
            f"📅 **Период:** {format_datetime(week_ago, show_time=False)} - {format_datetime(get_current_tashkent_time(), show_time=False)}\n\n"
            f"📊 **Общая статистика:**\n"
            f"• Всего задач: {user_stats['total_tasks']}\n"
            f"• Выполнено: {user_stats['completed_tasks']}\n"
            f"• Активных: {user_stats['active_tasks']}\n"
            f"• Просрочено: {user_stats['overdue_tasks']}\n\n"
            f"💪 **Продуктивность:** {int(user_stats['completed_tasks'] / max(user_stats['total_tasks'], 1) * 100)}%\n\n"
            f"🎯 **Продолжайте в том же духе!**"
        )
        
        await self.send_notification(user_telegram_id, message)
    
    def stop(self):
        """Остановка службы уведомлений"""
        self.is_running = False
        logger.info("🔕 Служба уведомлений остановлена")

