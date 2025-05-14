import os
import sqlite3
import logging
from typing import List, Dict, Any, Optional, Tuple

class Database:
    def __init__(self, db_path: str):
        self.logger = logging.getLogger("Database")
        self.db_path = db_path
        
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self._initialize_db()
    
    def _get_connection(self) -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        return conn, cursor
    
    def _initialize_db(self):
        try:
            conn, cursor = self._get_connection()

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS modules (
                guid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'inactive',
                service_type TEXT NOT NULL
            )
            ''')
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"База данных была создана: {self.db_path}")
            
        except Exception as e:
            self.logger.error(f"Ошибка создания базы данных: {str(e)}")
            raise
    
    def get_modules(self) -> List[Dict[str, Any]]:
        try:
            conn, cursor = self._get_connection()
            
            cursor.execute("SELECT * FROM modules")
            modules = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            
            return modules
        except Exception as e:
            self.logger.error(f"Ошибка при получении модулей: {str(e)}")
            return []
    
    def get_module(self, guid: str) -> Optional[Dict[str, Any]]:
        try:
            conn, cursor = self._get_connection()
            
            cursor.execute("SELECT * FROM modules WHERE guid = ?", (guid,))
            row = cursor.fetchone()
            
            conn.close()
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при получении модуля: {guid}: {str(e)}")
            return None
    
    def add_module(self, module: Dict[str, Any]) -> bool:
        try:
            conn, cursor = self._get_connection()
            
            cursor.execute(
                """
                INSERT INTO modules (guid, name, description, status, service_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    module.get('guid'),
                    module.get('name'),
                    module.get('description', ''),
                    module.get('status', 'inactive'),
                    module.get('service_type', 'dummy_service')
                )
            )
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Добавлен новый модуль: {module.get('name')} (GUID: {module.get('guid')})")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении модуля: {str(e)}")
            return False
    
    def update_module(self, guid: str, update_data: Dict[str, Any]) -> bool:
        try:
            conn, cursor = self._get_connection()

            cursor.execute("SELECT * FROM modules WHERE guid = ?", (guid,))
            existing = cursor.fetchone()
            
            if not existing:
                conn.close()
                self.logger.warning(f"Модуль {guid} не найден")
                return False
            
            updates = []
            values = []
            
            for key, value in update_data.items():
                if key in ['guid', 'name', 'description', 'status', 'service_type']:
                    updates.append(f"{key} = ?")
                    values.append(value)
            
            if not updates:
                conn.close()
                return True
            
            values.append(guid)
            
            query = f"UPDATE modules SET {', '.join(updates)} WHERE guid = ?"
            cursor.execute(query, values)
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Модуль обнавлен {guid}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении модуля {guid}: {str(e)}")
            return False
    
    def update_module_status(self, guid: str, status: str) -> bool:
        try:
            conn, cursor = self._get_connection()
            
            cursor.execute("SELECT status FROM modules WHERE guid = ?", (guid,))
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                self.logger.warning(f"Модуль {guid} не найден")
                return False
            
            old_status = row['status']
            
            cursor.execute(
                "UPDATE modules SET status = ? WHERE guid = ?",
                (status, guid)
            )
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Обновлен статус для {guid} из {old_status} в {status}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статуса модуля {guid}: {str(e)}")
            return False
    
    def update_modules_status(self, status_updates_modules: List[Dict[str, Any]]) -> Tuple[bool, int, List[str]]:
        try:
            conn, cursor = self._get_connection()
            
            updated_count = 0
            updated_modules = []
            
            for update in status_updates_modules:
                guid = update.get('guid')
                status = update.get('status')
                
                cursor.execute("SELECT name, status FROM modules WHERE guid = ?", (guid,))
                row = cursor.fetchone()
                
                if row:
                    old_status = row['status']
                    name = row['name']
                    
                    cursor.execute(
                        "UPDATE modules SET status = ? WHERE guid = ?",
                        (status, guid)
                    )
                    
                    updated_count += 1
                    updated_modules.append(name)
                    
                    if old_status != status:
                        self.logger.info(f"Обновленый статус для {name} из {old_status} в {status}")
            
            conn.commit()
            conn.close()
            
            return True, updated_count, updated_modules
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статусов модулей: {str(e)}")
            return False, 0, []
    
    def delete_module(self, guid: str) -> bool:
        try:
            conn, cursor = self._get_connection()
            
            cursor.execute("SELECT name FROM modules WHERE guid = ?", (guid,))
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                self.logger.warning(f"Модуль {guid} не найден для удаления")
                return False
            
            name = row['name']
            
            cursor.execute("DELETE FROM modules WHERE guid = ?", (guid,))
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Модуль был удален: {name} (GUID: {guid})")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при удалении модуля {guid}: {str(e)}")
            return False