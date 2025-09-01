# -*- coding: utf-8 -*-
"""
Модуль для работы с базой данных SQLite
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager
from config import config

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Менеджер базы данных для управления задачами"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для подключения к БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Инициализация базы данных и создание таблиц"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                    is_active BOOLEAN DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица задач
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    creator_id INTEGER NOT NULL,
                    assignee_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'new' 
                        CHECK (status IN ('new', 'in_progress', 'completed', 'overdue', 'cancelled')),
                    priority TEXT NOT NULL DEFAULT 'medium' 
                        CHECK (priority IN ('low', 'medium', 'high')),
                    deadline TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (creator_id) REFERENCES users (id),
                    FOREIGN KEY (assignee_id) REFERENCES users (id)
                )
            ''')
            
            # Таблица уведомлений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('reminder', 'assignment', 'deadline', 'completed')),
                    message TEXT NOT NULL,
                    is_sent BOOLEAN DEFAULT 0,
                    scheduled_at TIMESTAMP NOT NULL,
                    sent_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (task_id) REFERENCES tasks (id)
                )
            ''')
            
            # Таблица истории изменений задач
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            conn.commit()
            logger.info("База данных инициализирована успешно")
    
    # ПОЛЬЗОВАТЕЛИ
    def create_user(self, telegram_id: int, username: str, first_name: str, 
                   last_name: str, role: str) -> bool:
        """Создание нового пользователя"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO users (telegram_id, username, first_name, last_name, role)
                    VALUES (?, ?, ?, ?, ?)
                ''', (telegram_id, username, first_name, last_name, role))
                conn.commit()
                logger.info(f"Пользователь {username} создан с ролью {role}")
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"Пользователь с telegram_id {telegram_id} уже существует")
            return False
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        """Получение пользователя по Telegram ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Получение пользователя по внутреннему ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_user_activity(self, telegram_id: int):
        """Обновление времени последней активности"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET last_activity = CURRENT_TIMESTAMP 
                WHERE telegram_id = ?
            ''', (telegram_id,))
            conn.commit()
    
    def get_all_users(self) -> List[Dict]:
        """Получение всех пользователей"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY first_name')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_users_by_role(self, role: str) -> List[Dict]:
        """Получение пользователей по роли"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE role = ? AND is_active = 1', (role,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ЗАДАЧИ
    def create_task(self, title: str, description: str, creator_id: int, 
                   assignee_id: int = None, priority: str = 'medium', 
                   deadline: datetime = None) -> int:
        """Создание новой задачи"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (title, description, creator_id, assignee_id, priority, deadline)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (title, description, creator_id, assignee_id, priority, deadline))
            task_id = cursor.lastrowid
            
            # Добавляем запись в историю
            self._add_task_history(cursor, task_id, creator_id, 'created', None, 'Задача создана')
            
            conn.commit()
            logger.info(f"Задача '{title}' создана с ID {task_id}")
            return task_id
    
    def get_task_by_id(self, task_id: int) -> Optional[Dict]:
        """Получение задачи по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, 
                       c.first_name || ' ' || c.last_name as creator_name,
                       a.first_name || ' ' || a.last_name as assignee_name,
                       a.telegram_id as assignee_telegram_id
                FROM tasks t
                LEFT JOIN users c ON t.creator_id = c.id
                LEFT JOIN users a ON t.assignee_id = a.id
                WHERE t.id = ?
            ''', (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_tasks_by_user(self, user_id: int, status: str = None) -> List[Dict]:
        """Получение задач пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.*, 
                       c.first_name || ' ' || c.last_name as creator_name,
                       a.first_name || ' ' || a.last_name as assignee_name
                FROM tasks t
                LEFT JOIN users c ON t.creator_id = c.id
                LEFT JOIN users a ON t.assignee_id = a.id
                WHERE t.assignee_id = ?
            '''
            params = [user_id]
            
            if status:
                query += ' AND t.status = ?'
                params.append(status)
            
            query += ' ORDER BY t.deadline ASC, t.created_at DESC'
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_tasks(self, status: str = None, limit: int = None, offset: int = 0) -> List[Dict]:
        """Получение всех задач с пагинацией"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.*, 
                       c.first_name || ' ' || c.last_name as creator_name,
                       a.first_name || ' ' || a.last_name as assignee_name
                FROM tasks t
                LEFT JOIN users c ON t.creator_id = c.id
                LEFT JOIN users a ON t.assignee_id = a.id
            '''
            params = []
            
            if status:
                query += ' WHERE t.status = ?'
                params.append(status)
            
            query += ' ORDER BY t.deadline ASC, t.created_at DESC'
            
            if limit:
                query += ' LIMIT ? OFFSET ?'
                params.extend([limit, offset])
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_task_fields(self, task_id: int, updates: Dict, user_id: int) -> bool:
        """Обновление произвольных полей задачи с ведением истории"""
        allowed_fields = {'title', 'description', 'priority', 'deadline', 'assignee_id'}
        changes = {k: v for k, v in updates.items() if k in allowed_fields}
        if not changes:
            return True
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Получим текущую задачу
                cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Задача {task_id} не найдена для обновления полей")
                    return False
                current = dict(row)
                # Построим SQL
                set_parts = []
                params = []
                for field, value in changes.items():
                    set_parts.append(f"{field} = ?")
                    params.append(value)
                set_parts.append("updated_at = CURRENT_TIMESTAMP")
                params.append(task_id)
                sql = f"UPDATE tasks SET {' , '.join(set_parts)} WHERE id = ?"
                cursor.execute(sql, params)
                # История по каждому измененному полю
                for field, value in changes.items():
                    old_value = current.get(field)
                    self._add_task_history(cursor, task_id, user_id, f"{field}_updated", str(old_value) if old_value is not None else None, str(value) if value is not None else None)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении полей задачи: {e}")
            return False

    def search_tasks(self, query_text: str = '', status: Optional[str] = None, priority: Optional[str] = None, assignee_id: Optional[int] = None, creator_id: Optional[int] = None, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Поиск задач по тексту и фильтрам"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            base = '''
                SELECT t.*, 
                       c.first_name || ' ' || c.last_name as creator_name,
                       a.first_name || ' ' || a.last_name as assignee_name
                FROM tasks t
                LEFT JOIN users c ON t.creator_id = c.id
                LEFT JOIN users a ON t.assignee_id = a.id
                WHERE 1=1
            '''
            params: List = []
            if query_text:
                base += " AND (t.title LIKE ? OR t.description LIKE ? OR c.first_name || ' ' || c.last_name LIKE ? OR a.first_name || ' ' || a.last_name LIKE ?)"
                like = f"%{query_text}%"
                params.extend([like, like, like, like])
            if status:
                base += " AND t.status = ?"
                params.append(status)
            if priority:
                base += " AND t.priority = ?"
                params.append(priority)
            if assignee_id:
                base += " AND t.assignee_id = ?"
                params.append(assignee_id)
            if creator_id:
                base += " AND t.creator_id = ?"
                params.append(creator_id)
            base += " ORDER BY t.deadline ASC, t.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor.execute(base, params)
            return [dict(row) for row in cursor.fetchall()]

    def cancel_task(self, task_id: int, user_id: int) -> bool:
        """Отменить задачу (status = cancelled)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT status FROM tasks WHERE id = ?', (task_id,))
                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Задача {task_id} не найдена для отмены")
                    return False
                old_status = row[0]
                cursor.execute('''
                    UPDATE tasks SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (task_id,))
                self._add_task_history(cursor, task_id, user_id, 'status_changed', old_status, 'cancelled')
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при отмене задачи: {e}")
            return False
    
    def update_task_status(self, task_id: int, status: str, user_id: int) -> bool:
        """Обновление статуса задачи"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Получаем старый статус
                cursor.execute('SELECT status FROM tasks WHERE id = ?', (task_id,))
                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Задача {task_id} не найдена для обновления статуса")
                    return False
                old_status = row[0]
                
                # Обновляем статус
                completed_at = datetime.utcnow() if status == 'completed' else None
                cursor.execute('''
                    UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP, completed_at = ?
                    WHERE id = ?
                ''', (status, completed_at, task_id))
                
                # Добавляем в историю
                self._add_task_history(cursor, task_id, user_id, 'status_changed', old_status, status)
                
                conn.commit()
                logger.info(f"Статус задачи {task_id} изменен на {status}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса задачи: {e}")
            return False
    
    def assign_task(self, task_id: int, assignee_id: int, user_id: int) -> bool:
        """Назначение задачи исполнителю"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Получаем текущего исполнителя
                cursor.execute('SELECT assignee_id FROM tasks WHERE id = ?', (task_id,))
                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Задача {task_id} не найдена для назначения")
                    return False
                old_assignee = row[0]
                
                # Назначаем нового исполнителя
                cursor.execute('''
                    UPDATE tasks SET assignee_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (assignee_id, task_id))
                
                # Добавляем в историю
                self._add_task_history(cursor, task_id, user_id, 'assigned', 
                                     str(old_assignee) if old_assignee else None, str(assignee_id))
                
                conn.commit()
                logger.info(f"Задача {task_id} назначена пользователю {assignee_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при назначении задачи: {e}")
            return False
    
    def get_overdue_tasks(self) -> List[Dict]:
        """Получение просроченных задач"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, 
                       c.first_name || ' ' || c.last_name as creator_name,
                       a.first_name || ' ' || a.last_name as assignee_name,
                       a.telegram_id as assignee_telegram_id
                FROM tasks t
                LEFT JOIN users c ON t.creator_id = c.id
                LEFT JOIN users a ON t.assignee_id = a.id
                WHERE t.deadline < datetime('now') 
                AND t.status NOT IN ('completed', 'cancelled')
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def update_overdue_tasks(self):
        """Обновление статуса просроченных задач"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tasks SET status = 'overdue', updated_at = CURRENT_TIMESTAMP
                WHERE deadline < datetime('now') 
                AND status NOT IN ('completed', 'cancelled', 'overdue')
            ''')
            conn.commit()
            affected = cursor.rowcount
            if affected > 0:
                logger.info(f"Обновлено {affected} просроченных задач")
    
    # УВЕДОМЛЕНИЯ
    def create_notification(self, user_id: int, task_id: int, notification_type: str, 
                          message: str, scheduled_at: datetime) -> int:
        """Создание уведомления"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notifications (user_id, task_id, type, message, scheduled_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, task_id, notification_type, message, scheduled_at))
            notification_id = cursor.lastrowid
            conn.commit()
            return notification_id
    
    def get_pending_notifications(self) -> List[Dict]:
        """Получение неотправленных уведомлений"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.*, u.telegram_id, t.title as task_title
                FROM notifications n
                JOIN users u ON n.user_id = u.id
                JOIN tasks t ON n.task_id = t.id
                WHERE n.is_sent = 0 AND n.scheduled_at <= datetime('now')
                ORDER BY n.scheduled_at
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def get_unsent_notifications_by_task_type(self, task_id: int, notif_type: str) -> List[Dict]:
        """Получение несент уведомлений по задаче и типу (включая будущие)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM notifications 
                WHERE is_sent = 0 AND task_id = ? AND type = ?
            ''', (task_id, notif_type))
            return [dict(row) for row in cursor.fetchall()]

    def exists_notification_by_task_type(self, task_id: int, notif_type: str) -> bool:
        """Проверка существования уведомления любого статуса для задачи и типа"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 1 FROM notifications WHERE task_id = ? AND type = ? LIMIT 1
            ''', (task_id, notif_type))
            return cursor.fetchone() is not None
    
    def mark_notification_sent(self, notification_id: int):
        """Отметка уведомления как отправленного"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE notifications SET is_sent = 1, sent_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (notification_id,))
            conn.commit()
    
    # ИСТОРИЯ
    def _add_task_history(self, cursor, task_id: int, user_id: int, action: str, 
                         old_value: str = None, new_value: str = None):
        """Добавление записи в историю задач"""
        cursor.execute('''
            INSERT INTO task_history (task_id, user_id, action, old_value, new_value)
            VALUES (?, ?, ?, ?, ?)
        ''', (task_id, user_id, action, old_value, new_value))
    
    def get_task_history(self, task_id: int) -> List[Dict]:
        """Получение истории изменений задачи"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT th.*, u.first_name || ' ' || u.last_name as user_name
                FROM task_history th
                JOIN users u ON th.user_id = u.id
                WHERE th.task_id = ?
                ORDER BY th.created_at DESC
            ''', (task_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    # СТАТИСТИКА
    def get_user_stats(self, user_id: int) -> Dict:
        """Получение статистики пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_tasks,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
                    SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue_tasks,
                    SUM(CASE WHEN status IN ('new', 'in_progress') THEN 1 ELSE 0 END) as active_tasks
                FROM tasks WHERE assignee_id = ?
            ''', (user_id,))
            return dict(cursor.fetchone())
    
    def get_general_stats(self) -> Dict:
        """Получение общей статистики"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_tasks,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
                    SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue_tasks,
                    SUM(CASE WHEN status IN ('new', 'in_progress') THEN 1 ELSE 0 END) as active_tasks,
                    COUNT(DISTINCT assignee_id) as active_users
                FROM tasks
            ''')
            stats = dict(cursor.fetchone())
            
            # Добавляем статистику по пользователям
            cursor.execute('SELECT COUNT(*) as total_users FROM users WHERE is_active = 1')
            stats.update(dict(cursor.fetchone()))
            
            return stats

# Создаем глобальный экземпляр менеджера БД
db = DatabaseManager()

