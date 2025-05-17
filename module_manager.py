import json
import os
import sys
import time
import logging
import requests
import smtplib
import subprocess
import threading
import traceback
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import paho.mqtt.client as mqtt
from datetime import datetime
import chardet

class ModuleManager:
    def __init__(self, config_path):
        self.setup_logging()
        
        self.config = self.load_config(config_path)
        self.logger.info("Загрузка конфига прошла успешно")
        
        self.setup_mqtt()

        self.modules = []
        self.module_services = {}
        self.is_running = True
        self.previous_statuses = {}

        self.update_modules_list()
        self.load_existing_services()
    # логирование
    def setup_logging(self):
        self.logger = logging.getLogger("ModuleManager")
        self.logger.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        file_handler = logging.FileHandler("module_manager.log")
        file_handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
    # чтение конфига
    def load_config(self, config_path):
        try:
            with open(config_path, 'r') as config_file:
                config = json.load(config_file)
                return config
        except Exception as e:
            self.logger.error(f"Ошибка загрузки файла конфига: {str(e)}")
            sys.exit(1)
    # подключение к MQTT
    def setup_mqtt(self):
        try:
            mqtt_config = self.config.get("mqtt")
            
            broker = mqtt_config.get("broker")
            port = int(mqtt_config.get("port"))
            
            client_id = f"module_manager_{int(time.time())}"
            self.mqtt_client = mqtt.Client(client_id=client_id)

            if mqtt_config.get("username") and mqtt_config.get("password"):
                self.mqtt_client.username_pw_set(
                    mqtt_config.get("username"),
                    mqtt_config.get("password")
                )

            self.mqtt_topic_prefix = mqtt_config.get("topic_prefix")

            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect((broker, port))
                s.close()
                self.logger.info(f"Подключение к MQTT брокеру прошло успешно")
            except Exception as e:
                self.logger.warning(f"Ошибка при подключении к MQTT брокеру: {str(e)}")
            
            self.mqtt_client.connect(broker, port, 60)
            self.mqtt_client.loop_start()
            
        except Exception as e:
            self.logger.error(f"Ошибка при подключении к MQTT брокеру: {str(e)}")
            self.logger.error(traceback.format_exc())
            sys.exit(1)
    # после подключения подписка на команды
    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            command_topics = [
                f"{self.mqtt_topic_prefix}/command/create_new_systemctl_service",
                f"{self.mqtt_topic_prefix}/command/remove_service",
                f"{self.mqtt_topic_prefix}/command/restart_configs", 
                f"{self.mqtt_topic_prefix}/command/run_command_for_systemd_service",
                f"{self.mqtt_topic_prefix}/command/update_modules_list"
            ]
            
            for topic in command_topics:
                result, mid = self.mqtt_client.subscribe(topic)
                self.logger.info(f"Подписка на команды {topic}: result = {result}, mid = {mid}")

            self.logger.info(f"Публикация сообщений - {self.mqtt_topic_prefix}/status")
        else:
            self.logger.error(f"Ошибка при подключении к MQTT брокеру: {rc}")
            self.logger.error(traceback.format_exc())
    # чтение сообщения
    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))

            topic_parts = msg.topic.split('/')
            if len(topic_parts) >= 3 and topic_parts[-2] == "command":
                command = topic_parts[-1]
                self.logger.info(f"Выполнение команды: {command} с данными: {payload}")

                if command == "create_new_systemctl_service":
                    self.create_service(payload)
                elif command == "remove_service":
                    self.delete_service(payload)
                elif command == "restart_configs":
                    self.restart_all_services()
                elif command == "run_command_for_systemd_service":
                    self.run_command_for_service(payload)
                elif command == "update_modules_list":
                    self.update_modules_list()
                else:
                    self.logger.warning(f"Неизвестная команда: {msg.topic}")
            else:
                self.logger.warning(f"Ошибка при обработке команды: {msg.topic}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Ошибка при обработке данных: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка при обработке сообщения: {str(e)}")
            self.logger.error(traceback.format_exc())
    # отключение от MQTT
    def on_mqtt_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning("Внеплановое отключение")
        else:
            self.logger.info("Отключение MQTT брокера")
    # загрузка существующих серисных файлов для модулей
    def load_existing_services(self):
        try:
            if not self.modules:
                self.logger.warning("Список модулей пуст, невозможно загрузить сервисы")
                return
            
            systemd_path = "/etc/systemd/system"
            service_files = []
            
            try:
                result = subprocess.run(
                    ["find", systemd_path, "-name", "*.service", "-type", "f"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                service_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            except Exception as e:
                self.logger.error(f"Ошибка при сканировании директории {systemd_path}: {str(e)}")
                self.logger.error(traceback.format_exc())
            
            found_services = {}
            
            for module in self.modules:
                module_guid = module.get("guid")
                module_name = module.get("name")
                
                if not module_guid or not module_name:
                    continue

                service_name = self._create_safe_filename(module_name)
                systemd_service_name = f"{service_name}.service"
                service_path = os.path.join(systemd_path, systemd_service_name)

                if service_path in service_files:
                    try:
                        with open(service_path, 'r') as f:
                            service_content = f.read()

                        module_path = None
                        startup_script = None
                        
                        for line in service_content.splitlines():
                            if line.strip().startswith("WorkingDirectory="):
                                module_path = line.strip().split("=", 1)[1]
                            elif line.strip().startswith("ExecStart="):
                                exec_start = line.strip().split("=", 1)[1]
                                parts = exec_start.split()
                                if len(parts) >= 2:
                                    startup_script = parts[-1]
                        
                        if module_path and startup_script:
                            service_info = {
                                "guid": module_guid,
                                "name": module_name,
                                "module_path": module_path,
                                "startup_script": startup_script,
                                "systemd_service": systemd_service_name,
                                "status": "unknown"
                            }
                            
                            self.module_services[module_guid] = service_info
                            found_services[module_guid] = service_name
                        else:
                            self.logger.warning(f"Не удалось извлечь информацию о пути из сервиса {systemd_service_name}")
                    
                    except Exception as e:
                        self.logger.error(f"Ошибка при анализе файла сервиса {service_path}: {str(e)}")
                        self.logger.error(traceback.format_exc())
            
            if found_services:
                self.logger.info(f"Загружено {len(found_services)} существующих сервисов: {', '.join(found_services.values())}")
            else:
                self.logger.info("Не найдено существующих сервисов для модулей")
            
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке существующих сервисов: {str(e)}")
            self.logger.error(traceback.format_exc())
    # выбор команды (запуск\остановка\перезапуск) в зависимости от отправки
    def run_command_for_service(self, data):
        try:
            module_guid = data.get("config_id")
            action = data.get("action")
            
            if not module_guid:
                self.logger.error("Нет параметра GUID модуля")
                return
            
            if not action:
                self.logger.error("Нет параметра action для модуля")
                return
            
            module = self.get_module_by_guid(module_guid)
            if not module:
                self.logger.error(f"Модуль GUID {module_guid} не найден")
                return

            module_name = module.get("name")
            
            if action == "start":
                self.logger.info(f"Запуск сервиса для модуля {module_name} (GUID: {module_guid})")
                self.start_service({"config_id": module_guid, "name": module_name})
            elif action == "stop":
                self.logger.info(f"Остановка сервиса для модуля {module_name} (GUID: {module_guid})")
                self.stop_service({"config_id": module_guid, "name": module_name})
            elif action == "restart":
                self.logger.info(f"Перезапуск сервиса для модуля {module_name} (GUID: {module_guid})")
                self.restart_service({"config_id": module_guid, "name": module_name})
            else:
                self.logger.error(f"Неизвестная команда: {action}")
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении команды: {str(e)}")
            self.logger.error(traceback.format_exc())
    # получить модуль по ID
    def get_module_by_guid(self, guid):
        for module in self.modules:
            if module.get("guid") == guid:
                return module
        return None
    # перезапуск всех сервисов ПМ
    def restart_all_services(self):
        self.logger.info("Перезапуск сервисов")
        
        for module in self.modules:
            try:
                guid = module.get("guid")
                name = module.get("name")
                
                if guid and name:
                    self.restart_service({"config_id": guid, "name": name})
            except Exception as e:
                self.logger.error(f"Ошибка при перезапуске модуля {module.get('name')}: {str(e)}")
        
        self.logger.info("Все сервисы перезапущены")
    # обновление списка модулей
    def update_modules_list(self):
        try:
            base_url = self.config["systemapi"]["base_url"]
            
            response = requests.get(f"{base_url}/api/modules")
            
            if response.status_code == 200:
                self.modules = response.json()

                for module in self.modules:
                    self.logger.debug(f"Модуль: {module.get('name')} (GUID: {module.get('guid')}, Status: {module.get('status')})")

            else:
                self.logger.error(f"Ошибка при получении модулей: {response.status_code}, Response: {response.text}")
        except Exception as e:
            self.logger.error(f"Ошибкуа при обработки модулей: {str(e)}")
    # создать скрипт заглушкку и .service файл и выдать права доступа, после получения команды для создания
    def create_service(self, data):
        try:
            module_guid = data.get("config_id")
            
            if not module_guid:
                self.logger.error("Нет GUID модуля")
                return
            
            module = self.get_module_by_guid(module_guid)
            
            if not module:
                self.logger.error(f"Модуль {module_guid} не найден")

                return
            
            module_name = module.get("name")
            
            service_type = module.get('service_type', 'dummy_service')
            
            base_modules_path = os.path.expanduser("~/modules")
            module_path = os.path.join(base_modules_path, service_type)
            startup_script = os.path.join(module_path, "main.py")
            
            if not os.path.exists(module_path):
                try:
                    os.makedirs(module_path, exist_ok=True)
                except Exception as e:
                    self.logger.error(f"Ошибка при создании директории: {str(e)}")

                    return
            
            if not os.path.exists(startup_script):
                try:
                    with open(startup_script, 'w') as f:
                        f.write('''
import time
while True:
    time.sleep(60)
                                ''')
                    os.chmod(startup_script, 0o755)
                    self.logger.info(f"Создан скрипт заглушка {startup_script}")
                except Exception as e:
                    self.logger.warning(f"Скрипт не был создан: {str(e)}")
            
            service_name = self._create_safe_filename(module_name)
            systemd_service_name = f"{service_name}.service"
            
            service_file_content = self._create_systemd_service_file(
                service_name, module_name, module_path, startup_script
            )
            
            systemd_path = "/etc/systemd/system"
            service_file_path = os.path.join(systemd_path, systemd_service_name)
            
            try:
                tmp_file_path = f"/tmp/{systemd_service_name}"
                with open(tmp_file_path, 'w') as f:
                    f.write(service_file_content)

                subprocess.run(
                    ["sudo", "mv", tmp_file_path, service_file_path],
                    check=True,
                    capture_output=True
                )

                subprocess.run(
                    ["sudo", "chmod", "644", service_file_path],
                    check=True,
                    capture_output=True
                )
                
                subprocess.run(
                    ["sudo", "systemctl", "daemon-reload"],
                    check=True,
                    capture_output=True
                )

                subprocess.run(
                    ["sudo", "systemctl", "disable", tmp_file_path],
                    check=True,
                    capture_output=True
                )

                service_info = {
                    "guid": module_guid,
                    "name": module_name,
                    "module_path": module_path,
                    "startup_script": startup_script,
                    "systemd_service": systemd_service_name,
                    "status": "unknow"
                }
                
                self.module_services[module_guid] = service_info
                
                self.logger.info(f"Создан сервис {systemd_service_name} для модуля {module_name}")
                
                self._update_module_status(module_guid, "inactive")

            except Exception as e:
                self.logger.error(f"Ошибка при создании модуля: {str(e)}")
                self.logger.error(traceback.format_exc())

        except Exception as e:
            self.logger.error(f"FОшибка при создании модуля: {str(e)}")
            self.logger.error(traceback.format_exc())

    # создание .service файла со своими параметрами
    def _create_systemd_service_file(self, service_name, module_name, module_path, startup_script):
        venv_path = os.path.expanduser("~/venv")
        python_path = os.path.join(venv_path, "bin", "python") if os.path.exists(venv_path) else "/usr/bin/python3"
        
        service_content = f"""[Unit]
Description=Module Service for {module_name}
After=network.target

[Service]
Type=simple
User={os.getenv('USER')}
WorkingDirectory={module_path}
ExecStart={python_path} {startup_script}
Restart=no
StandardOutput=journal
StandardError=journal
SyslogIdentifier={service_name}
Environment="PATH={venv_path}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
"""
        return service_content
    # удалить .service файл
    def delete_service(self, data):
        try:
            module_guid = data.get("config_id")
            
            if not module_guid:
                self.logger.error("Нет GUID модуля")
                return
            
            module = self.get_module_by_guid(module_guid)
            
            if not module:
                self.logger.error(f"Модуль {module_guid} не найден")

                return
            
            module_name = module.get("name")
            
            self.stop_service({"config_id": module_guid, "name": module_name})

            service_info = self.module_services[module_guid]
            systemd_service = service_info.get("systemd_service")
            
            if not systemd_service:
                self.logger.warning(f"Сервиса для модуля {module_name} не найдено")
                
                del self.module_services[module_guid]

                return
            
            systemd_service_path = os.path.join("/etc/systemd/system", systemd_service)
            
            try:
                if os.path.exists(systemd_service_path):
                    subprocess.run(["sudo", "systemctl", "disable", systemd_service], 
                                    check=True)
                    
                    subprocess.run(["sudo", "rm", systemd_service_path], 
                                   check=True)
                    
                    subprocess.run(["sudo", "systemctl", "daemon-reload"], 
                                   check=True)
                
                del self.module_services[module_guid]
                
                self.logger.info(f"Сервис удален {systemd_service} для модуля {module_name}")

                self._update_module_status(module_guid, "inactive")

            except Exception as e:
                self.logger.error(f"Ошибка при удаленеии сервиса: {str(e)}")
                self.logger.error(traceback.format_exc())

        except Exception as e:
            self.logger.error(f"Ошибка удаления сервиса {str(e)}")
            self.logger.error(traceback.format_exc())

    # запустить .service файл
    def start_service(self, payload):
        try:
            module_guid = payload.get("config_id")
            module_name = payload.get("name")
            
            if module_guid not in self.module_services:
                self.logger.error(f"Нет сервиса для запуска модуля {module_name}")
                return

            service_info = self.module_services[module_guid]
            systemd_service = service_info.get("systemd_service")
            
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", systemd_service],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.stdout.strip() == "active":
                    self.logger.info(f"Сервис {systemd_service} уже запущен")
                    
                    service_info["status"] = "running"
                    
                    self._update_module_status(module_guid, "active")
                    
                    return
            except Exception as e:
                self.logger.warning(f"Ошибка при проверки статуса: {str(e)}")

            try:
                subprocess.run(["sudo", "systemctl", "start", systemd_service], 
                               check=True)

                service_info["status"] = "running"
                
                self.logger.info(f"Сервис {systemd_service} запущен для модуля {module_name}")

                self._update_module_status(module_guid, "active")

            except Exception as e:
                self.logger.error(f"Ошибка при запуске сервиса {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка при запуске сервиса: {str(e)}")
    # остановить .service файл
    def stop_service(self, payload):
        try:
            module_guid = payload.get("config_id")
            module_name = payload.get("name")
            
            if not module_guid or not module_name:
                self.logger.error("Нет GUID модуля")
                return
            
            if module_guid not in self.module_services:
                self.logger.error(f"Нет сервиса для модуля {module_name}")

                return
            
            service_info = self.module_services[module_guid]
            systemd_service = service_info.get("systemd_service")

            try:
                result = subprocess.run(
                    ["systemctl", "is-active", systemd_service],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.stdout.strip() != "active":
                    self.logger.info(f"Сервис {systemd_service} не запущен")
                    
                    service_info["status"] = "stopped"
                    
                    self._update_module_status(module_guid, "inactive")

                    return
            except Exception as e:
                self.logger.warning(f"Ошибка при получении статуса сервиса: {str(e)}")
            
            try:
                subprocess.run(["sudo", "systemctl", "stop", systemd_service], 
                               check=True)
                
                service_info["status"] = "stopped"
                
                self.logger.info(f"Сервис остановлен {systemd_service} для модуля {module_name}")
                
                self._update_module_status(module_guid, "inactive")

            except Exception as e:
                error_msg = f"Ошибка при остановки сервиса: {str(e)}"
                self.logger.error(error_msg)
                self.logger.error(traceback.format_exc())

        except Exception as e:
            self.logger.error(f"Ошибка остановки сервиса: {str(e)}")
            self.logger.error(traceback.format_exc())

    # перезапуск всех .service файлов
    def restart_service(self, payload):
        try:
            module_guid = payload.get("config_id")
            module_name = payload.get("name")
            
            if not module_guid or not module_name:
                self.logger.error("Нет GUID модуля")
                return
            
            if module_guid not in self.module_services:
                self.logger.error(f"Нет сервиса для модуля {module_name}")

                return
            
            service_info = self.module_services[module_guid]
            systemd_service = service_info.get("systemd_service")
            
            try:
                subprocess.run(["sudo", "systemctl", "restart", systemd_service], 
                               check=True)
                
                service_info["status"] = "running"
                
                self.logger.info(f"Перезапущен сервис {systemd_service} для модуля {module_name}")
                
                self._update_module_status(module_guid, "active")

            except Exception as e:
                error_msg = f"Ошибка при перезапуске сервиса: {str(e)}"
                self.logger.error(error_msg)
                self.logger.error(traceback.format_exc())
                
                service_info["status"] = "failed"
                
                self._update_module_status(module_guid, "failed")
                
                if self.config.get("alerts", {}).get("send_alert_after_service_failed"):
                    self.send_alert_email(module_name, systemd_service)

        except Exception as e:
            self.logger.error(f"Ошибка перезапуска сервиса: {str(e)}")
            self.logger.error(traceback.format_exc())

    # создание безапасного имени файла для .service
    def _create_safe_filename(self, name):
        safe_name = ""
        for char in name:
            if char.isalnum() or char == '_':
                safe_name += char
            else:
                safe_name += '_'
        return safe_name
    # обновление статуса ПМ
    def _update_module_status(self, module_guid, status):
        try:
            base_url = self.config["systemapi"]["base_url"]
            
            response = requests.put(
                f"{base_url}/api/modules/{module_guid}/status",
                json={"status": status}
            )
            
            if response.status_code == 200:
                self.logger.info(f"Обновленый статус {module_guid} - {status}")

                for module in self.modules:
                    if module.get("guid") == module_guid:
                        module["status"] = status
                        break
            else:
                self.logger.error(f"Ошибка при обновлении статуса: {response.status_code}, Response: {response.text}")
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статуса: {str(e)}")
            self.logger.error(traceback.format_exc())
    # мониторинг и логирование статусов ПМ
    def monitor_services(self):
        while self.is_running:
            try:
                all_statuses = {}
                status_changes = {}
                
                for module in self.modules:
                    module_guid = module.get("guid")
                    module_name = module.get("name")

                    if not module_guid or not module_name:
                        continue
                    
                    service_status = "inactive"
                    
                    if module_guid in self.module_services:
                        service_info = self.module_services[module_guid]
                        systemd_service = service_info.get("systemd_service")
                        
                        if systemd_service:
                            try:
                                result = subprocess.run(
                                    ["systemctl", "is-active", systemd_service],
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                status_output = result.stdout.strip()
                                
                                if status_output == "active":
                                    service_status = "active"
                                elif status_output == "inactive":
                                    service_status = "inactive"
                                elif status_output == "failed":
                                    service_status = "failed"
                                else:
                                    service_status = "failed"

                            except Exception as e:
                                self.logger.warning(f"Ошибка при получении статуса сервиса{systemd_service}: {str(e)}")
                                service_status = "failed"
                        else:
                            service_status = "inactive"

                    if service_status == "failed":
                        if service_info.get("status") != "failed":
                            self.logger.info(f"Новая поломка сервиса {module_name}")

                            alert_enabled = self.config.get("alerts", {}).get("send_alert_after_service_failed")

                            if alert_enabled:
                                self.send_alert_email(module_name, systemd_service)
                                self.logger.info(f"Сообщение об ошибке модуля {module_name} отправлено")
                    
                    if module_guid in self.module_services:
                        self.module_services[module_guid]["status"] = service_status
                    
                    all_statuses[module_guid] = service_status
                    
                    previous_status = self.previous_statuses.get(module_guid)
                    if previous_status != service_status:
                        status_changes[module_guid] = service_status
                        self.logger.info(f"Статус модуля {module_name} был изменен из {previous_status} в {service_status}")

                    old_status = module.get("status")
                    if old_status != service_status:
                        self._update_module_status(module_guid, service_status)
                
                self.previous_statuses = all_statuses.copy()
                self.logger.info(f"{all_statuses}")
                
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Ошибка при мониторинге сервисов{str(e)}")
                self.logger.error(traceback.format_exc())
    # отправка письма на почту в случае сбоя
    def send_alert_email(self, module_name, service_name):
        try:
            if not self.config.get("alerts", {}).get("email"):
                self.logger.warning("Не указан email адрес")
                return
            
            log_content = "No logs available"
            try:
                logs_result = subprocess.run(
                    ["sudo", "systemctl", "status", service_name, "-o", "short-iso"],
                    capture_output=True,
                    text=True,
                    check=False,
                    encoding="utf-8",
                    errors="replace"
                )
                log_content = logs_result.stdout

                if len(log_content) > 5000:
                    log_content = "... (truncated) ...\n" + log_content[-5000:]
            except Exception as e:
                log_content = f"Error getting logs: {str(e)}"

            msg = MIMEMultipart()
            msg["Subject"] = f"Service Failure Alert: {module_name}"
            msg["From"] = self.config.get("alerts", {}).get("smtp_username")
            msg["To"] = self.config["alerts"]["email"]
            
            body = f"""
Service failed

Module: {module_name}
Service: {service_name}
Time: {datetime.now().isoformat()}
Server: {self.config.get('servername')}

Recent logs:
{log_content}
"""
            message = MIMEText(body, "plain", "utf-8")
            msg.attach(message)
            
            smtp_server = self.config.get("alerts", {}).get("smtp_server")
            smtp_port = int(self.config.get("alerts", {}).get("smtp_port"))
            smtp_username = self.config.get("alerts", {}).get("smtp_username")
            smtp_password = self.config.get("alerts", {}).get("smtp_password")

            try:
                smtp = smtplib.SMTP(smtp_server, smtp_port)
                smtp.ehlo()
                smtp.starttls()
                if smtp_username and smtp_password:
                    smtp.login(smtp_username, smtp_password)
                
                smtp.sendmail(
                    from_addr=smtp_username,
                    to_addrs=self.config["alerts"]["email"],
                    msg=msg.as_string()
                )
                smtp.quit()
                
            except Exception as e:
                self.logger.error(f"Ошибка SMTP {str(e)}")
                self.logger.error(traceback.format_exc())
                
        except Exception as e:
            self.logger.error(f"Ошибка при отправке сообщения: {str(e)}")
            self.logger.error(traceback.format_exc())
    # запуск модуля
    def start(self):
        monitor_thread = threading.Thread(target=self.monitor_services)
        monitor_thread.daemon = True
        monitor_thread.start()

        self.logger.info("Module Manager запущен")
        
        
        while True:
                time.sleep(1)


if __name__ == "__main__":
    config_path = sys.argv[1]

    manager = ModuleManager(config_path)
    manager.start()
