# -*- coding: utf-8 -*-
"""
Модуль аутентификации и авторизации
"""

import hashlib
import logging
from typing import Optional
from config import config

logger = logging.getLogger(__name__)

class AuthManager:
    """Менеджер аутентификации и авторизации"""
    
    def __init__(self):
        self.admin_password_hash = self._hash_password(config.ADMIN_PASSWORD)
        self.user_password_hash = self._hash_password(config.USER_PASSWORD)
    
    def _hash_password(self, password: str) -> str:
        """Хеширование пароля"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def validate_password(self, password: str) -> Optional[str]:
        """
        Проверка пароля и возврат роли
        
        Args:
            password: Введённый пароль
            
        Returns:
            Роль пользователя или None если пароль неверный
        """
        password_hash = self._hash_password(password)
        
        if password_hash == self.admin_password_hash:
            logger.info("Успешная аутентификация администратора")
            return 'admin'
        elif password_hash == self.user_password_hash:
            logger.info("Успешная аутентификация пользователя")
            return 'user'
        else:
            logger.warning("Неудачная попытка аутентификации")
            return None
    
    def is_admin(self, user_role: str) -> bool:
        """Проверка является ли пользователь администратором"""
        return user_role == 'admin'
    
    def can_create_tasks(self, user_role: str) -> bool:
        """Проверка может ли пользователь создавать задачи"""
        return user_role == 'admin'
    
    def can_assign_tasks(self, user_role: str) -> bool:
        """Проверка может ли пользователь назначать задачи"""
        return user_role == 'admin'
    
    def can_modify_task(self, user_role: str, user_id: int, task_creator_id: int, 
                       task_assignee_id: int) -> bool:
        """
        Проверка может ли пользователь модифицировать задачу
        
        Args:
            user_role: Роль пользователя
            user_id: ID пользователя
            task_creator_id: ID создателя задачи
            task_assignee_id: ID исполнителя задачи
            
        Returns:
            True если может модифицировать
        """
        # Админ может модифицировать любые задачи
        if user_role == 'admin':
            return True
        
        # Исполнитель может изменять статус своих задач
        if user_id == task_assignee_id:
            return True
        
        return False
    
    def can_view_all_tasks(self, user_role: str) -> bool:
        """Проверка может ли пользователь просматривать все задачи"""
        return user_role == 'admin'
    
    def can_generate_reports(self, user_role: str) -> bool:
        """Проверка может ли пользователь генерировать отчёты"""
        return user_role == 'admin'
    
    def can_manage_users(self, user_role: str) -> bool:
        """Проверка может ли пользователь управлять пользователями"""
        return user_role == 'admin'

