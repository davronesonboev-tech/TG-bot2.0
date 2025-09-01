# -*- coding: utf-8 -*-
"""
Telegram бот для управления задачами
Красивый и интуитивно понятный интерфейс
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters,
    ContextTypes,
    ConversationHandler
)

from config import config, EMOJIS, TASK_STATUS, TASK_PRIORITY, USER_ROLES
from database import db
from auth import AuthManager
from utils import format_task, format_datetime, validate_deadline, to_utc
from notifications import NotificationManager
from reports import ReportGenerator

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(WAITING_PASSWORD, CREATING_TASK_TITLE, CREATING_TASK_DESCRIPTION, 
 CREATING_TASK_ASSIGNEE, CREATING_TASK_DEADLINE, CREATING_TASK_PRIORITY,
 EDIT_FIELD_SELECT, EDIT_FIELD_INPUT, CONFIRM_CANCEL) = range(9)

class TaskManagerBot:
    """Основной класс Telegram бота для управления задачами"""
    
    def __init__(self):
        self.auth_manager = AuthManager()
        self.notification_manager = NotificationManager()
        self.report_generator = ReportGenerator()
        self.user_states = {}  # Состояния пользователей
        
    def create_main_menu_keyboard(self, user_role: str) -> InlineKeyboardMarkup:
        """Создание главного меню в зависимости от роли"""
        keyboard = []
        
        if user_role == 'admin':
            keyboard.extend([
                [InlineKeyboardButton(f"{EMOJIS['create_task']} Создать задачу", callback_data="create_task")],
                [InlineKeyboardButton(f"{EMOJIS['all_tasks']} Все задачи", callback_data="all_tasks"),
                 InlineKeyboardButton(f"{EMOJIS['my_tasks']} Мои задачи", callback_data="my_tasks")],
                [InlineKeyboardButton("🔽 Фильтры", callback_data="filters_menu")],
                [InlineKeyboardButton(f"{EMOJIS['reports']} Отчёты", callback_data="reports"),
                 InlineKeyboardButton(f"{EMOJIS['gantt']} Диаграмма Ганта", callback_data="gantt_chart")],
                [InlineKeyboardButton(f"{EMOJIS['settings']} Управление пользователями", callback_data="user_management")]
            ])
        else:
            keyboard.extend([
                [InlineKeyboardButton(f"{EMOJIS['my_tasks']} Мои задачи", callback_data="my_tasks")],
                [InlineKeyboardButton(f"{EMOJIS['pending']} Активные", callback_data="active_tasks"),
                 InlineKeyboardButton(f"{EMOJIS['done']} Выполненные", callback_data="completed_tasks")],
                [InlineKeyboardButton("🔽 Фильтры", callback_data="filters_menu")],
                [InlineKeyboardButton(f"{EMOJIS['reports']} Мой отчёт", callback_data="report_my_excel")]
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['notification']} Настройки", callback_data="user_settings")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def create_filters_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("Статус: Новая", callback_data="filter_status_new"), InlineKeyboardButton("В работе", callback_data="filter_status_in_progress")],
            [InlineKeyboardButton("Выполнена", callback_data="filter_status_completed"), InlineKeyboardButton("Просрочена", callback_data="filter_status_overdue")],
            [InlineKeyboardButton("Приоритет: Высокий", callback_data="filter_priority_high"), InlineKeyboardButton("Средний", callback_data="filter_priority_medium")],
            [InlineKeyboardButton("Низкий", callback_data="filter_priority_low")],
            [InlineKeyboardButton(f"{EMOJIS['back']} Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def create_task_list_keyboard(self, tasks: List[Dict], page: int = 0, 
                                 callback_prefix: str = "task", user_id: int = None) -> InlineKeyboardMarkup:
        """Создание клавиатуры со списком задач"""
        keyboard = []
        start_idx = page * config.MAX_TASKS_PER_PAGE
        end_idx = start_idx + config.MAX_TASKS_PER_PAGE
        page_tasks = tasks[start_idx:end_idx]
        
        for task in page_tasks:
            status_emoji = EMOJIS.get(task['status'], EMOJIS['pending'])
            priority_emoji = EMOJIS.get(f'priority_{task["priority"]}', '')
            
            button_text = f"{status_emoji} {priority_emoji} {task['title'][:30]}..."
            if len(task['title']) <= 30:
                button_text = f"{status_emoji} {priority_emoji} {task['title']}"
            
            task_row = [InlineKeyboardButton(
                button_text, 
                callback_data=f"{callback_prefix}_{task['id']}"
            )]
            keyboard.append(task_row)
            
            if user_id and task['assignee_id'] == user_id:
                action_buttons = []
                
                if task['status'] == 'new':
                    action_buttons.extend([
                        InlineKeyboardButton(f"🔴 В РАБОТУ", 
                                           callback_data=f"task_status_{task['id']}_in_progress"),
                        InlineKeyboardButton(f"✅ ВЫПОЛНЕНО", 
                                           callback_data=f"task_status_{task['id']}_completed")
                    ])
                elif task['status'] == 'in_progress':
                    action_buttons.append(
                        InlineKeyboardButton(f"✅ ВЫПОЛНЕНО", 
                                           callback_data=f"task_status_{task['id']}_completed")
                    )
                
                if action_buttons:
                    keyboard.append(action_buttons)
        
        nav_buttons = []
        total_pages = (len(tasks) + config.MAX_TASKS_PER_PAGE - 1) // config.MAX_TASKS_PER_PAGE
        
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                f"{EMOJIS['back']} Назад", 
                callback_data=f"{callback_prefix}_page_{page-1}"
            ))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                f"Далее {EMOJIS['next']}", 
                callback_data=f"{callback_prefix}_page_{page+1}"
            ))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton(
            f"{EMOJIS['menu']} Главное меню", 
            callback_data="main_menu"
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    def create_task_detail_keyboard(self, task: Dict, user_role: str, 
                                   user_id: int) -> InlineKeyboardMarkup:
        """Создание клавиатуры для детального просмотра задачи"""
        keyboard = []
        
        if task['assignee_id'] == user_id:
            if task['status'] == 'new':
                keyboard.append([
                    InlineKeyboardButton(f"🔴 ВЗЯТЬ В РАБОТУ", 
                                       callback_data=f"task_status_{task['id']}_in_progress")
                ])
                keyboard.append([
                    InlineKeyboardButton(f"✅ ЗАДАЧА ВЫПОЛНЕНА", 
                                       callback_data=f"task_status_{task['id']}_completed")
                ])
            elif task['status'] == 'in_progress':
                keyboard.append([
                    InlineKeyboardButton(f"✅ ЗАДАЧА ВЫПОЛНЕНА", 
                                       callback_data=f"task_status_{task['id']}_completed")
                ])
        
        if user_role == 'admin':
            keyboard.extend([
                [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_task_{task['id']}")],
                [InlineKeyboardButton(f"{EMOJIS['user']} Переназначить", 
                                    callback_data=f"reassign_task_{task['id']}")],
                [InlineKeyboardButton(f"{EMOJIS['settings']} Изменить статус", 
                                    callback_data=f"change_status_{task['id']}")],
                [InlineKeyboardButton("🛑 Отменить задачу", callback_data=f"cancel_task_{task['id']}")]
            ])
        
        keyboard.extend([
            [InlineKeyboardButton(f"{EMOJIS['info']} История", 
                                callback_data=f"task_history_{task['id']}")],
            [InlineKeyboardButton(f"{EMOJIS['back']} Назад", callback_data="all_tasks"),
             InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")]
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        
        db_user = db.get_user_by_telegram_id(user.id)
        
        if db_user:
            db.update_user_activity(user.id)
            welcome_text = (
                f"🎉 Добро пожаловать обратно, {user.first_name}!\n\n"
                f"Ваша роль: {USER_ROLES[db_user['role']]} {EMOJIS['admin'] if db_user['role'] == 'admin' else EMOJIS['user']}\n\n"
                f"Выберите действие:"
            )
            
            await update.message.reply_text(
                welcome_text,
                reply_markup=self.create_main_menu_keyboard(db_user['role'])
            )
        else:
            welcome_text = (
                f"👋 Привет, {user.first_name}!\n\n"
                f"🔐 Для доступа к боту введите пароль:\n"
                f"• Пароль администратора для создания и управления задачами\n"
                f"• Пароль пользователя для выполнения задач\n\n"
                f"Введите пароль:"
            )
            
            await update.message.reply_text(welcome_text)
            return WAITING_PASSWORD
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            f"{EMOJIS['info']} Команды:\n\n"
            f"/start — главное меню\n"
            f"/menu — главное меню\n"
            f"/my — мои задачи\n"
            f"/help — помощь\n"
        )
        await update.message.reply_text(text)
    
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        db_user = db.get_user_by_telegram_id(user.id)
        if not db_user:
            await update.message.reply_text("Используйте /start")
            return
        await update.message.reply_text(
            f"Главное меню:",
            reply_markup=self.create_main_menu_keyboard(db_user['role'])
        )
    
    async def my_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        db_user = db.get_user_by_telegram_id(user.id)
        if not db_user:
            await update.message.reply_text("Используйте /start")
            return
        fake_query = type('Q', (), {'edit_message_text': update.message.reply_text})
        await self.show_my_tasks(fake_query, db_user)
    
    async def handle_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода пароля"""
        password = update.message.text
        user = update.effective_user
        
        role = self.auth_manager.validate_password(password)
        
        if role:
            success = db.create_user(
                telegram_id=user.id,
                username=user.username or "",
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                role=role
            )
            
            if success:
                success_text = (
                    f"✅ Регистрация успешна!\n\n"
                    f"👤 Имя: {user.first_name} {user.last_name or ''}\n"
                    f"🎭 Роль: {USER_ROLES[role]} {EMOJIS['admin'] if role == 'admin' else EMOJIS['user']}\n\n"
                    f"Добро пожаловать в систему управления задачами!"
                )
                
                await update.message.reply_text(
                    success_text,
                    reply_markup=self.create_main_menu_keyboard(role)
                )
            else:
                await update.message.reply_text(
                    f"{EMOJIS['error']} Ошибка при регистрации. Попробуйте позже."
                )
            
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"{EMOJIS['error']} Неверный пароль. Попробуйте ещё раз:"
            )
            return WAITING_PASSWORD
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        db_user = db.get_user_by_telegram_id(user.id)
        
        if not db_user:
            await query.edit_message_text("❌ Пользователь не найден. Используйте /start")
            return
        
        db.update_user_activity(user.id)
        data = query.data
        
        if data == "main_menu":
            await self.show_main_menu(query, db_user)
        elif data == "all_tasks":
            await self.show_all_tasks(query, db_user)
        elif data == "my_tasks":
            await self.show_my_tasks(query, db_user)
        elif data == "active_tasks":
            await self.show_active_tasks(query, db_user, page=0)
        elif data == "completed_tasks":
            await self.show_completed_tasks(query, db_user, page=0)
        elif data.startswith("task_status_"):
            await self.change_task_status(query, data, db_user)
        elif data.startswith("task_"):
            await self.show_task_detail(query, data, db_user)
        elif data == "reports":
            await self.show_reports_menu(query, db_user)
        elif data == "gantt_chart":
            await self.generate_gantt_chart(query, db_user)
        elif data.startswith("task_page_") or data.startswith("my_task_page_") or data.startswith("active_task_page_") or data.startswith("completed_task_page_"):
            await self.handle_task_page_navigation(query, data, db_user)
        elif data.startswith("reassign_task_"):
            await self.handle_reassign_task(query, data, db_user)
        elif data.startswith("assign_to_"):
            await self.handle_assign_to_user(query, data, db_user)
        elif data.startswith("change_status_"):
            await self.handle_change_status_menu(query, data, db_user)
        elif data.startswith("task_history_"):
            await self.show_task_history(query, data, db_user)
        elif data == "report_general_excel":
            await self.generate_general_excel_report(query, db_user)
        elif data == "report_my_excel":
            await self.generate_my_excel_report(query, db_user)
        # report_users_stats удалено
        elif data == "report_my_stats":
            await self.show_my_stats(query, db_user)
        elif data == "user_management":
            await self.show_user_management(query, db_user)
        elif data == "user_settings":
            await self.show_user_settings(query, db_user)
        
        elif data.startswith("filter_"):
            await self.apply_filter(query, data, db_user)
        elif data == "filters_menu":
            await self.show_filters_menu(query)
        elif data.startswith("edit_task_"):
            await self.start_edit_task(query, data, db_user)
        elif data.startswith("cancel_task_"):
            await self.start_cancel_task(query, data, db_user)
        elif data.startswith("confirm_cancel_"):
            await self.confirm_cancel_task(query, data, db_user)
        else:
            await self.show_main_menu(query, db_user)
    
    async def show_main_menu(self, query, db_user):
        """Показать главное меню"""
        user_stats = db.get_user_stats(db_user['id'])
        
        menu_text = (
            f"📋 **Главное меню**\n\n"
            f"👤 {db_user['first_name']} {db_user['last_name']}\n"
            f"🎭 Роль: {USER_ROLES[db_user['role']]}\n\n"
            f"📊 **Ваша статистика:**\n"
            f"• Всего задач: {user_stats['total_tasks']}\n"
            f"• Выполнено: {user_stats['completed_tasks']}\n"
            f"• Активных: {user_stats['active_tasks']}\n"
            f"• Просрочено: {user_stats['overdue_tasks']}\n"
        )
        
        await query.edit_message_text(
            menu_text,
            reply_markup=self.create_main_menu_keyboard(db_user['role']),
            parse_mode='Markdown'
        )
    
    async def show_all_tasks(self, query, db_user, page=0):
        tasks = db.get_all_tasks()
        
        if not tasks:
            await query.edit_message_text(
                f"{EMOJIS['info']} Задач пока нет.\n\nСоздайте первую задачу!",
                reply_markup=InlineKeyboardMarkup([[\
                    InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        text = f"📋 **Все задачи** (Всего: {len(tasks)})\n\n"
        
        await query.edit_message_text(
            text,
            reply_markup=self.create_task_list_keyboard(tasks, page, "task", db_user['id'] if db_user['role'] == 'user' else None),
            parse_mode='Markdown'
        )
    
    async def show_my_tasks(self, query, db_user, page=0):
        if db_user['role'] == 'admin':
            tasks = db.get_all_tasks()
        else:
            tasks = db.get_tasks_by_user(db_user['id'])
        
        if not tasks:
            await query.edit_message_text(
                f"{EMOJIS['info']} У вас пока нет задач.",
                reply_markup=InlineKeyboardMarkup([[\
                    InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        text = f"📝 **Мои задачи** (Всего: {len(tasks)})\n\n"
        
        await query.edit_message_text(
            text,
            reply_markup=self.create_task_list_keyboard(tasks, page, "my_task", db_user['id']),
            parse_mode='Markdown'
        )
    
    async def show_active_tasks(self, query, db_user, page=0):
        tasks = db.get_tasks_by_user(db_user['id'], 'in_progress')
        tasks.extend(db.get_tasks_by_user(db_user['id'], 'new'))
        
        if not tasks:
            await query.edit_message_text(
                f"{EMOJIS['info']} У вас нет активных задач.",
                reply_markup=InlineKeyboardMarkup([[\
                    InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        text = f"🕐 **Активные задачи** (Всего: {len(tasks)})\n\n"
        
        await query.edit_message_text(
            text,
            reply_markup=self.create_task_list_keyboard(tasks, page, "active_task", db_user['id']),
            parse_mode='Markdown'
        )
    
    async def show_completed_tasks(self, query, db_user, page=0):
        tasks = db.get_tasks_by_user(db_user['id'], 'completed')
        
        if not tasks:
            await query.edit_message_text(
                f"{EMOJIS['info']} У вас нет выполненных задач.",
                reply_markup=InlineKeyboardMarkup([[\
                    InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        text = f"✅ **Выполненные задачи** (Всего: {len(tasks)})\n\n"
        
        await query.edit_message_text(
            text,
            reply_markup=self.create_task_list_keyboard(tasks, page, "completed_task", db_user['id']),
            parse_mode='Markdown'
        )
    
    async def show_task_detail(self, query, data, db_user):
        task_id = int(data.split('_')[-1])
        task = db.get_task_by_id(task_id)
        
        if not task:
            await query.edit_message_text("❌ Задача не найдена.")
            return
        
        text = format_task(task, detailed=True)
        
        await query.edit_message_text(
            text,
            reply_markup=self.create_task_detail_keyboard(task, db_user['role'], db_user['id']),
            parse_mode='Markdown'
        )
    
    async def start_search(self, query):
        await query.edit_message_text(
            "🔎 Введите текст для поиска по задачам (название, описание, исполнитель)")
        return SEARCH_QUERY
    
    async def handle_search_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.message.text.strip()
        user = update.effective_user
        db_user = db.get_user_by_telegram_id(user.id)
        tasks = db.search_tasks(query_text=q, assignee_id=None if db_user['role']=='admin' else db_user['id'])
        if not tasks:
            await update.message.reply_text("Ничего не найдено")
            return ConversationHandler.END
        await update.message.reply_text(
            f"Найдено: {len(tasks)}",
            reply_markup=self.create_task_list_keyboard(tasks, 0, 'task', db_user['id'] if db_user['role']=='user' else None)
        )
        return ConversationHandler.END
    
    async def show_filters_menu(self, query):
        await query.edit_message_text("Выберите фильтры:", reply_markup=self.create_filters_keyboard())
    
    async def apply_filter(self, query, data, db_user):
        parts = data.split('_')
        ftype = parts[1]
        fval = '_'.join(parts[2:])
        kwargs = {}
        if ftype == 'status':
            kwargs['status'] = fval
        if ftype == 'priority':
            kwargs['priority'] = fval
        if db_user['role'] == 'user':
            kwargs['assignee_id'] = db_user['id']
        tasks = db.search_tasks(**kwargs)
        if not tasks:
            await query.edit_message_text("По фильтру ничего не найдено", reply_markup=self.create_filters_keyboard())
            return
        await query.edit_message_text(
            f"Найдено: {len(tasks)}",
            reply_markup=self.create_task_list_keyboard(tasks, 0, 'task', db_user['id'] if db_user['role']=='user' else None)
        )
    
    async def change_task_status(self, query, data, db_user):
        parts = data.split('_')
        task_id = int(parts[2])
        new_status = parts[3]
        
        task = db.get_task_by_id(task_id)
        if not task:
            await query.answer("❌ Задача не найдена.")
            return
        
        if task['assignee_id'] != db_user['id'] and db_user['role'] != 'admin':
            await query.answer("❌ У вас нет прав для изменения этой задачи.")
            return
        
        old_status = task['status']
        success = db.update_task_status(task_id, new_status, db_user['id'])
        
        if success:
            if new_status == 'completed':
                await query.answer("🎉 Отлично! Задача выполнена!")
            elif new_status == 'in_progress':
                await query.answer("🔴 Задача взята в работу!")
            else:
                await query.answer(f"✅ Статус изменён на '{TASK_STATUS[new_status]}'")
            
            if task['creator_id'] != db_user['id']:
                try:
                    all_users = db.get_all_users()
                    creator = None
                    for user in all_users:
                        if user['id'] == task['creator_id']:
                            creator = user
                            break
                    
                    if creator:
                        updated_task = db.get_task_by_id(task_id)
                        await self.notification_manager.notify_task_status_changed(
                            updated_task, old_status, new_status, creator['telegram_id']
                        )
                        if new_status == 'completed':
                            completion_message = (
                                f"🎉 **ЗАДАЧА ВЫПОЛНЕНА!**\n\n"
                                f"📝 **Задача:** {updated_task['title']}\n"
                                f"👤 **Исполнитель:** {db_user['first_name']} {db_user['last_name']}\n"
                                f"⏰ **Время выполнения:** {format_datetime(datetime.now())}\n"
                                f"📊 **Статус:** {TASK_STATUS[new_status]}\n\n"
                                f"Отличная работа! 👏"
                            )
                            await self.notification_manager.send_notification(
                                creator['telegram_id'], completion_message, task_id
                            )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления: {e}")
            await self.show_task_detail(query, f"task_{task_id}", db_user)
        else:
            await query.answer("❌ Ошибка при изменении статуса.")
    
    async def start_create_task(self, query, context):
        text = (
            f"{EMOJIS['create_task']} **Создание новой задачи**\n\n"
            f"Введите название задачи (до {config.MAX_TASK_TITLE_LENGTH} символов):"
        )
        
        await query.edit_message_text(text, parse_mode='Markdown')
        context.user_data['creating_task'] = {}
        return CREATING_TASK_TITLE
    
    async def handle_task_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        title = update.message.text.strip()
        
        if len(title) > config.MAX_TASK_TITLE_LENGTH:
            await update.message.reply_text(
                f"{EMOJIS['error']} Название слишком длинное! Максимум {config.MAX_TASK_TITLE_LENGTH} символов.\n"
                f"Введите название ещё раз:"
            )
            return CREATING_TASK_TITLE
        
        context.user_data['creating_task']['title'] = title
        
        text = (
            f"✅ **Название:** {title}\n\n"
            f"Теперь введите описание задачи (до {config.MAX_TASK_DESCRIPTION_LENGTH} символов)\n"
            f"или отправьте '-' чтобы пропустить:"
        )
        
        await update.message.reply_text(text, parse_mode='Markdown')
        return CREATING_TASK_DESCRIPTION
    
    async def handle_task_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        description = update.message.text.strip()
        
        if description == '-':
            description = ""
        elif len(description) > config.MAX_TASK_DESCRIPTION_LENGTH:
            await update.message.reply_text(
                f"{EMOJIS['error']} Описание слишком длинное! Максимум {config.MAX_TASK_DESCRIPTION_LENGTH} символов.\n"
                f"Введите описание ещё раз или '-' чтобы пропустить:"
            )
            return CREATING_TASK_DESCRIPTION
        
        context.user_data['creating_task']['description'] = description
        
        users = db.get_all_users()
        if not users:
            await update.message.reply_text(f"{EMOJIS['error']} Нет доступных исполнителей!")
            return ConversationHandler.END
        
        keyboard = []
        for user in users:
            user_name = f"{user['first_name']} {user['last_name']}"
            role_emoji = EMOJIS['admin'] if user['role'] == 'admin' else EMOJIS['user']
            keyboard.append([InlineKeyboardButton(
                f"{role_emoji} {user_name}", 
                callback_data=f"assign_user_{user['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['back']} Отмена", callback_data="cancel_create_task")])
        
        text = (
            f"✅ **Название:** {context.user_data['creating_task']['title']}\n"
            f"✅ **Описание:** {context.user_data['creating_task']['description'] or 'Не указано'}\n\n"
            f"👤 **Выберите исполнителя:**"
        )
        
        await update.message.reply_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return CREATING_TASK_ASSIGNEE
    
    async def handle_task_assignee(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_create_task":
            await query.edit_message_text("❌ Создание задачи отменено.")
            return ConversationHandler.END
        
        if query.data.startswith("assign_user_"):
            assignee_id = int(query.data.split("_")[-1])
            context.user_data['creating_task']['assignee_id'] = assignee_id
            
            assignee = None
            for user in db.get_all_users():
                if user['id'] == assignee_id:
                    assignee = user
                    break
            
            keyboard = [
                [InlineKeyboardButton("📅 Через 1 день", callback_data="deadline_1d"),
                 InlineKeyboardButton("📅 Через 3 дня", callback_data="deadline_3d")],
                [InlineKeyboardButton("📅 Через неделю", callback_data="deadline_7d"),
                 InlineKeyboardButton("📅 Через месяц", callback_data="deadline_30d")],
                [InlineKeyboardButton("📝 Ввести вручную", callback_data="deadline_manual"),
                 InlineKeyboardButton("⏰ Без дедлайна", callback_data="deadline_none")],
                [InlineKeyboardButton(f"{EMOJIS['back']} Отмена", callback_data="cancel_create_task")]
            ]
            
            assignee_name = f"{assignee['first_name']} {assignee['last_name']}" if assignee else "Неизвестен"
            
            text = (
                f"✅ **Название:** {context.user_data['creating_task']['title']}\n"
                f"✅ **Описание:** {context.user_data['creating_task']['description'] or 'Не указано'}\n"
                f"✅ **Исполнитель:** {assignee_name}\n\n"
                f"⏰ **Выберите дедлайн:**"
            )
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return CREATING_TASK_DEADLINE
    
    async def handle_task_deadline(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_create_task":
            await query.edit_message_text("❌ Создание задачи отменено.")
            return ConversationHandler.END
        
        deadline = None
        if query.data == "deadline_1d":
            deadline = to_utc(datetime.now() + timedelta(days=1))
        elif query.data == "deadline_3d":
            deadline = to_utc(datetime.now() + timedelta(days=3))
        elif query.data == "deadline_7d":
            deadline = to_utc(datetime.now() + timedelta(days=7))
        elif query.data == "deadline_30d":
            deadline = to_utc(datetime.now() + timedelta(days=30))
        elif query.data == "deadline_none":
            deadline = None
        elif query.data == "deadline_manual":
            text = (
                f"📅 **Введите дедлайн в формате:**\n"
                f"• `25.12.2024 18:00`\n"
                f"• `25.12.2024`\n"
                f"• `завтра`\n"
                f"• `через 5 дней`\n"
                f"• `через 2 часа`"
            )
            await query.edit_message_text(text, parse_mode='Markdown')
            return CREATING_TASK_DEADLINE
        
        context.user_data['creating_task']['deadline'] = deadline
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['priority_high']} Высокий", callback_data="priority_high")],
            [InlineKeyboardButton(f"{EMOJIS['priority_medium']} Средний", callback_data="priority_medium")],
            [InlineKeyboardButton(f"{EMOJIS['priority_low']} Низкий", callback_data="priority_low")],
            [InlineKeyboardButton(f"{EMOJIS['back']} Отмена", callback_data="cancel_create_task")]
        ]
        
        deadline_text = format_datetime(deadline) if deadline else "Не указан"
        
        text = (
            f"✅ **Название:** {context.user_data['creating_task']['title']}\n"
            f"✅ **Описание:** {context.user_data['creating_task']['description'] or 'Не указано'}\n"
            f"✅ **Дедлайн:** {deadline_text}\n\n"
            f"🔥 **Выберите приоритет:**"
        )
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return CREATING_TASK_PRIORITY
    
    async def handle_manual_deadline(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        deadline_str = update.message.text.strip()
        deadline = validate_deadline(deadline_str)
        
        if not deadline:
            await update.message.reply_text(
                f"{EMOJIS['error']} Неверный формат даты!\n\n"
                f"Попробуйте:\n"
                f"• `25.12.2024 18:00`\n"
                f"• `25.12.2024`\n"
                f"• `завтра`\n"
                f"• `через 5 дней`",
                parse_mode='Markdown'
            )
            return CREATING_TASK_DEADLINE
        
        context.user_data['creating_task']['deadline'] = to_utc(deadline)
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['priority_high']} Высокий", callback_data="priority_high")],
            [InlineKeyboardButton(f"{EMOJIS['priority_medium']} Средний", callback_data="priority_medium")],
            [InlineKeyboardButton(f"{EMOJIS['priority_low']} Низкий", callback_data="priority_low")],
            [InlineKeyboardButton(f"{EMOJIS['back']} Отмена", callback_data="cancel_create_task")]
        ]
        
        deadline_text = format_datetime(deadline)
        
        text = (
            f"✅ **Название:** {context.user_data['creating_task']['title']}\n"
            f"✅ **Описание:** {context.user_data['creating_task']['description'] or 'Не указано'}\n"
            f"✅ **Дедлайн:** {deadline_text}\n\n"
            f"🔥 **Выберите приоритет:**"
        )
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return CREATING_TASK_PRIORITY
    
    async def handle_task_priority(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_create_task":
            await query.edit_message_text("❌ Создание задачи отменено.")
            return ConversationHandler.END
        
        priority_map = {
            "priority_high": "high",
            "priority_medium": "medium", 
            "priority_low": "low"
        }
        priority = priority_map.get(query.data, "medium")
        
        user = update.effective_user
        db_user = db.get_user_by_telegram_id(user.id)
        
        try:
            task_id = db.create_task(
                title=context.user_data['creating_task']['title'],
                description=context.user_data['creating_task']['description'],
                creator_id=db_user['id'],
                assignee_id=context.user_data['creating_task']['assignee_id'],
                priority=priority,
                deadline=context.user_data['creating_task']['deadline']
            )
            
            if context.user_data['creating_task']['assignee_id']:
                assignee = None
                for user_data in db.get_all_users():
                    if user_data['id'] == context.user_data['creating_task']['assignee_id']:
                        assignee = user_data
                        break
                
                if assignee:
                    task = db.get_task_by_id(task_id)
                    await self.notification_manager.notify_task_assigned(task, assignee['telegram_id'])
            
            task = db.get_task_by_id(task_id)
            success_text = (
                f"{EMOJIS['success']} **Задача создана успешно!**\n\n"
                f"{format_task(task, detailed=True)}"
            )
            
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['create_task']} Создать ещё", callback_data="create_task")],
                [InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")]
            ]
            
            await query.edit_message_text(
                success_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка при создании задачи: {e}")
            await query.edit_message_text(
                f"{EMOJIS['error']} Ошибка при создании задачи. Попробуйте ещё раз."
            )
        
        context.user_data.pop('creating_task', None)
        return ConversationHandler.END
    
    async def show_reports_menu(self, query, db_user):
        keyboard = []
        
        if db_user['role'] == 'admin':
            keyboard.extend([
                [InlineKeyboardButton(f"{EMOJIS['excel']} Общий отчёт Excel", callback_data="report_general_excel")],
                [InlineKeyboardButton(f"{EMOJIS['gantt']} Диаграмма Ганта", callback_data="gantt_chart")]
            ])
        else:
            keyboard.extend([
                [InlineKeyboardButton(f"{EMOJIS['excel']} Мой отчёт Excel", callback_data="report_my_excel")],
                [InlineKeyboardButton(f"{EMOJIS['chart']} Моя статистика", callback_data="report_my_stats")]
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"{EMOJIS['reports']} **Отчёты и аналитика**\n\nВыберите тип отчёта:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def generate_gantt_chart(self, query, db_user):
        await query.answer("📊 Генерирую диаграмму Ганта...")
        
        try:
            tasks = db.get_all_tasks()
            chart_path = self.report_generator.create_gantt_chart(tasks)
            
            await query.message.reply_photo(
                photo=open(chart_path, 'rb'),
                caption=f"{EMOJIS['gantt']} **Диаграмма Ганта**\n\nАктуальное состояние всех задач проекта",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при генерации диаграммы Ганта: {e}")
            await query.message.reply_text(f"{EMOJIS['error']} Ошибка при генерации диаграммы.")
    
    async def handle_task_page_navigation(self, query, data, db_user):
        parts = data.split("_")
        page = int(parts[-1])
        
        if data.startswith("task_page_"):
            await self.show_all_tasks(query, db_user, page)
        elif data.startswith("my_task_page_"):
            await self.show_my_tasks(query, db_user, page)
        elif data.startswith("active_task_page_"):
            await self.show_active_tasks(query, db_user, page)
        elif data.startswith("completed_task_page_"):
            await self.show_completed_tasks(query, db_user, page)
    
    async def handle_reassign_task(self, query, data, db_user):
        if db_user['role'] != 'admin':
            await query.answer("❌ Недостаточно прав")
            return
        
        task_id = int(data.split("_")[-1])
        task = db.get_task_by_id(task_id)
        
        if not task:
            await query.edit_message_text("❌ Задача не найдена")
            return
        
        users = db.get_all_users()
        keyboard = []
        
        for user in users:
            user_name = f"{user['first_name']} {user['last_name']}"
            role_emoji = EMOJIS['admin'] if user['role'] == 'admin' else EMOJIS['user']
            keyboard.append([InlineKeyboardButton(
                f"{role_emoji} {user_name}", 
                callback_data=f"assign_to_{user['id']}_{task_id}"
            )])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['back']} Назад", callback_data=f"task_{task_id}")])
        
        text = f"👤 **Переназначить задачу:**\n\n{task['title']}\n\nВыберите нового исполнителя:"
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def handle_assign_to_user(self, query, data, db_user):
        if db_user['role'] != 'admin':
            await query.answer("❌ Недостаточно прав")
            return
        
        parts = data.split("_")
        new_assignee_id = int(parts[2])
        task_id = int(parts[3])
        
        success = db.assign_task(task_id, new_assignee_id, db_user['id'])
        
        if success:
            task = db.get_task_by_id(task_id)
            
            if task['assignee_telegram_id']:
                await self.notification_manager.notify_task_assigned(task, task['assignee_telegram_id'])
            
            await query.answer("✅ Задача переназначена!")
            await self.show_task_detail(query, f"task_{task_id}", db_user)
        else:
            await query.answer("❌ Ошибка при переназначении задачи")
    
    async def handle_change_status_menu(self, query, data, db_user):
        task_id = int(data.split("_")[-1])
        task = db.get_task_by_id(task_id)
        
        if not task:
            await query.edit_message_text("❌ Задача не найдена")
            return
        
        if db_user['role'] != 'admin' and task['assignee_id'] != db_user['id']:
            await query.answer("❌ Недостаточно прав")
            return
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['new']} Новая", callback_data=f"task_status_{task_id}_new")],
            [InlineKeyboardButton(f"{EMOJIS['pending']} В работе", callback_data=f"task_status_{task_id}_in_progress")],
            [InlineKeyboardButton(f"{EMOJIS['done']} Выполнена", callback_data=f"task_status_{task_id}_completed")],
            [InlineKeyboardButton(f"{EMOJIS['error']} Отменена", callback_data=f"task_status_{task_id}_cancelled")],
            [InlineKeyboardButton(f"{EMOJIS['back']} Назад", callback_data=f"task_{task_id}")]
        ]
        
        text = f"📊 **Изменить статус задачи:**\n\n{task['title']}\n\nТекущий статус: {TASK_STATUS[task['status']]}"
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def show_task_history(self, query, data, db_user):
        task_id = int(data.split("_")[-1])
        task = db.get_task_by_id(task_id)
        
        if not task:
            await query.edit_message_text("❌ Задача не найдена")
            return
        
        history = db.get_task_history(task_id)
        
        text = f"📋 **История задачи:** {task['title']}\n\n"
        
        if history:
            for entry in history:
                action_time = format_datetime(entry['created_at'])
                text += f"🕐 {action_time}\n👤 {entry['user_name']}\n📝 {entry['action']}\n\n"
        else:
            text += "История пуста"
        
        keyboard = [[InlineKeyboardButton(f"{EMOJIS['back']} Назад", callback_data=f"task_{task_id}")]]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def generate_general_excel_report(self, query, db_user):
        if db_user['role'] != 'admin':
            await query.answer("❌ Недостаточно прав")
            return
        
        await query.answer("📊 Генерирую отчёт...")
        
        try:
            tasks = db.get_all_tasks()
            report_path = self.report_generator.create_excel_report(tasks)
            
            await query.message.reply_document(
                document=open(report_path, 'rb'),
                caption=f"{EMOJIS['excel']} **Общий отчёт по задачам**\n\nВсего задач: {len(tasks)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при генерации Excel отчёта: {e}")
            await query.message.reply_text(f"{EMOJIS['error']} Ошибка при генерации отчёта")
    
    async def generate_my_excel_report(self, query, db_user):
        await query.answer("📊 Генерирую ваш отчёт...")
        
        try:
            tasks = db.get_tasks_by_user(db_user['id'])
            
            if not tasks:
                await query.message.reply_text("📝 У вас пока нет задач для отчёта")
                return
            
            filename = f"my_tasks_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            report_path = self.report_generator.create_excel_report(tasks, filename)
            
            await query.message.reply_document(
                document=open(report_path, 'rb'),
                caption=f"{EMOJIS['excel']} **Ваш личный отчёт**\n\nВаши задачи: {len(tasks)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при генерации личного Excel отчёта: {e}")
            await query.message.reply_text(f"{EMOJIS['error']} Ошибка при генерации отчёта")
    
    # Метод show_users_stats удалён по запросу
    
    async def show_my_stats(self, query, db_user):
        stats = db.get_user_stats(db_user['id'])
        
        completion_rate = (stats['completed_tasks'] / max(stats['total_tasks'], 1)) * 100
        
        text = (
            f"{EMOJIS['chart']} **Ваша статистика**\n\n"
            f"📊 **Общие показатели:**\n"
            f"• Всего задач: {stats['total_tasks']}\n"
            f"• Выполнено: {stats['completed_tasks']}\n"
            f"• Активных: {stats['active_tasks']}\n"
            f"• Просрочено: {stats['overdue_tasks']}\n\n"
            f"📈 **Эффективность:** {completion_rate:.1f}%\n\n"
        )
        
        if completion_rate >= 90:
            text += f"🏆 **Отличная работа!**"
        elif completion_rate >= 70:
            text += f"👍 **Хорошие результаты!**"
        else:
            text += f"💪 **Есть куда стремиться!**"
        
        keyboard = [[InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")]]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def show_user_management(self, query, db_user):
        if db_user['role'] != 'admin':
            await query.answer("❌ Недостаточно прав")
            return
        
        users = db.get_all_users()
        general_stats = db.get_general_stats()
        
        text = (
            f"{EMOJIS['admin']} **Управление пользователями**\n\n"
            f"👥 **Всего пользователей:** {general_stats['total_users']}\n"
            f"📋 **Всего задач:** {general_stats['total_tasks']}\n"
            f"✅ **Выполнено:** {general_stats['completed_tasks']}\n"
            f"🔴 **Просрочено:** {general_stats['overdue_tasks']}\n\n"
            f"**Список пользователей:**\n"
        )
        
        for user in users[:10]:
            role_emoji = EMOJIS['admin'] if user['role'] == 'admin' else EMOJIS['user']
            text += f"• {role_emoji} {user['first_name']} {user['last_name']} ({USER_ROLES[user['role']]})\n"
        
        if len(users) > 10:
            text += f"\n... и ещё {len(users) - 10} пользователей"
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def show_user_settings(self, query, db_user):
        text = (
            f"{EMOJIS['settings']} **Настройки пользователя**\n\n"
            f"👤 **Имя:** {db_user['first_name']} {db_user['last_name']}\n"
            f"🎭 **Роль:** {USER_ROLES[db_user['role']]}\n"
            f"📅 **Дата регистрации:** {format_datetime(db_user['registered_at'], show_time=False)}\n\n"
            f"🔔 **Уведомления:** Включены\n"
            f"⏰ **Напоминания:** За 24ч, 6ч, 1ч до дедлайна"
        )
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['chart']} Моя статистика", callback_data="report_my_stats")],
            [InlineKeyboardButton(f"{EMOJIS['excel']} Мой отчёт", callback_data="report_my_excel")],
            [InlineKeyboardButton(f"{EMOJIS['menu']} Главное меню", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def start_edit_task(self, query, data, db_user):
        if db_user['role'] != 'admin':
            await query.answer("❌ Недостаточно прав")
            return
        task_id = int(data.split('_')[-1])
        context = query.message.chat  # not used, kept for symmetry
        keyboard = [
            [InlineKeyboardButton("Название", callback_data=f"edit_field_title_{task_id}")],
            [InlineKeyboardButton("Описание", callback_data=f"edit_field_description_{task_id}")],
            [InlineKeyboardButton("Приоритет", callback_data=f"edit_field_priority_{task_id}")],
            [InlineKeyboardButton("Дедлайн", callback_data=f"edit_field_deadline_{task_id}")],
            [InlineKeyboardButton(f"{EMOJIS['back']} Назад", callback_data=f"task_{task_id}")]
        ]
        await query.edit_message_text("Что изменить?", reply_markup=InlineKeyboardMarkup(keyboard))

    async def start_cancel_task(self, query, data, db_user):
        if db_user['role'] != 'admin':
            await query.answer("❌ Недостаточно прав")
            return
        task_id = int(data.split('_')[-1])
        keyboard = [
            [InlineKeyboardButton("Да, отменить", callback_data=f"confirm_cancel_yes_{task_id}")],
            [InlineKeyboardButton("Нет", callback_data=f"task_{task_id}")]
        ]
        await query.edit_message_text("Вы уверены, что хотите отменить задачу?", reply_markup=InlineKeyboardMarkup(keyboard))

    async def confirm_cancel_task(self, query, data, db_user):
        parts = data.split('_')
        if parts[2] != 'yes':
            await query.answer("Отменено")
            return
        task_id = int(parts[3])
        if db.cancel_task(task_id, db_user['id']):
            await query.answer("Задача отменена")
            await self.show_task_detail(query, f"task_{task_id}", db_user)
        else:
            await query.answer("Ошибка при отмене")

    async def start_create_task_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = update.effective_user
        db_user = db.get_user_by_telegram_id(user.id)
        
        if not db_user or db_user['role'] != 'admin':
            await query.answer("❌ У вас нет прав для создания задач.")
            return ConversationHandler.END
        
        await query.answer()
        return await self.start_create_task(query, context)
    
    async def cancel_create_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("❌ Создание задачи отменено.")
        context.user_data.pop('creating_task', None)
        return ConversationHandler.END
    
    def run(self):
        application = Application.builder().token(config.TELEGRAM_TOKEN).build()
        
        registration_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_password)],
            },
            fallbacks=[CommandHandler("start", self.start_command)]
        )
        
        create_task_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_create_task_conversation, pattern="^create_task$")],
            states={
                CREATING_TASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_task_title)],
                CREATING_TASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_task_description)],
                CREATING_TASK_ASSIGNEE: [CallbackQueryHandler(self.handle_task_assignee)],
                CREATING_TASK_DEADLINE: [
                    CallbackQueryHandler(self.handle_task_deadline),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_manual_deadline)
                ],
                CREATING_TASK_PRIORITY: [CallbackQueryHandler(self.handle_task_priority)],
            },
            fallbacks=[CallbackQueryHandler(self.cancel_create_task, pattern="^cancel_create_task$")]
        )

        application.add_handler(registration_handler)
        application.add_handler(create_task_handler)
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("menu", self.menu_command))
        application.add_handler(CommandHandler("my", self.my_command))
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        async def post_init(app):
            loop = asyncio.get_event_loop()
            loop.create_task(self.notification_manager.start_notification_loop(app))
        
        application.post_init = post_init
        
        logger.info("🚀 Бот запущен!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    bot = TaskManagerBot()
    bot.run()
