# Модуль управления программными модулями

## Описание проекта

Система для управления работой программных модулей через REST API и MQTT. Включает в себя:

- REST API для управления модулями (system-api)
- Модуль управления (module-manager) для создания и управления системными сервисами systemd
- База данных SQLite для хранения информации о модулях

## Структура проекта

- `config.json` - конфигурация проекта
- `database.py` - модуль для работы с базой данных SQLite
- `system_api.py` - веб-сервис с REST API для управления модулями
- `module_manager.py` - менеджер модулей, взаимодействующий с systemd и MQTT
- `system-api.service` - systemd сервис для API
- `module-manager.service` - systemd сервис для менеджера модулей
- `system_api.log` - файл с логами для SystemAPI и Database
- `module_manager.log` - файл с логами ModuleManager

## Возможности

- Создание/удаление сервисов systemd для программных модулей
- Запуск/остановка/перезапуск сервисов ПМ
- Отправка статуса (логов) сервиса ПМ
- Мониторинг статуса всех сервисов 
- Отправка оповещений по email при сбоях
- Веб-интерфейс для просмотра статусов

### Предварительные требования

- Операционная система на базе Linux с systemd 
- Python 3.7+
- SQLite3
- Mosquitto MQTT брокер

### Установка

1. Установите зависимости:
```
sudo apt-get install python3 python3-pip python3-venv sqlite3 mosquitto mosquitto-clients
```

2. Создайте виртуальное окружение:
```
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn paho-mqtt requests jinja2 email
```

3. Отредактируйте systemd сервисы:

system-api.service
```
[Unit]
Description=System API Service
After=network.target

[Service]
Type=simple
User=yourusername
WorkingDirectory=/home/yourusername/yourPath/
ExecStart=/home/yourusername/yourPath/venv/bin/python /home/yourusername/yourPath/system_api.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=system-api
Environment="PATH=/home/yourusername/yourPath/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin/:/usr/bin/:/sbin/:/bin"
Environment="VIRTUAL_ENV=/home/yourusername/yourPath/venv"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

module-manager.service
```
[Unit]
Description=Module Manager Service
After=network.target mosquitto.service system-api.service

[Service]
Type=simple
User=yourusername
WorkingDirectory=/home/yourusername/yourPath/
ExecStart=/home/yourusername/yourPath/venv/bin/python /home/yourusername/yourPath/module_manager.py /home/yourusername/yourPath/config.json  
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=module-manager
Environment="PATH=/home/yourusername/yourPath/venv/bin:/usr/local/sbin/:/usr/local/bin/:/usr/sbin/:usr/bin/:/sbin/:/bin"
Environment="VIRTUAL_ENV=/home/yourusername/yourPath/venv"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target

```

4. Создайте файл паролей
```
sudo mosquitto_passwd -c /etc/mosquitto/passwd yourusername
sudo nano /etc/mosquitto/conf.d/default.conf
```
Добавьте строки
```
listener 1883
allow_anonymous false
password_file /etc/mosquitto/passwd
```

5. Отредактируйте config.json
```
{
    "servername": "demo.systemapi",
    "storage": "systemapi",
    "loglevel": "debug",
    "service": {
        "config_path": "/home/yourusername/yourPath",
        "config_global_file": "/home/yourusername/yourPath/config.json"
    },
    "alerts": {
       "send_alert_after_service_failed": true,
       "emails": "youremail to receive",
       "smtp_server": "smtp.gmail.com",
       "smtp_port": 587,
       "smtp_username": "youremail to send",
       "smtp_password": "your-app-password"
    }, 
    "mqtt":{
        "broker": "localhost",
        "port": 1883,
        "username": "yourusername", 
        "password": "yourpassword",
        "topic_prefix": "module_manager"
    },   
    "systemapi": {
        "base_url": "http://localhost:8080"
    },
    "database": {
        "path": "/home/yourusername/yourPath/modules.db"
    }
}
```

6. Установите systemd сервисы:
```
sudo cp system-api.service /etc/systemd/system/
sudo cp module-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
```

7. Редактирование sudoers:
```
sudo visudo
```
Добавьте это в файл
```
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl start
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl status
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl is-active
yourusername ALL=(ALL) NOPASSWD: /usr/bin/systemctl disable
yourusername ALL=(ALL) NOPASSWD: /usr/bin/mv
yourusername ALL=(ALL) NOPASSWD: /usr/bin/rm
yourusername ALL=(ALL) NOPASSWD: /usr/bin/chmod
```

8. Запустите сервисы:
```
sudo systemctl enable system-api
sudo systemctl enable module-manager
sudo systemctl start system-api
sudo systemctl start module-manager
```

9. Запустите HTTP
http://localhost:8080

## Использование

### MQTT команды

Создать сервис модуля:
```
mosquitto_pub -h localhost -p 1883 -u yourusername -P yourpassword -t "module_manager/command/create_new_systemctl_service" -m '{"config_id":"123"}'
```

Удалить сервис:
```
mosquitto_pub -h localhost -p 1883 -u yourusername -P yourpassword -t "module_manager/command/remove_service" -m '{"config_id":"123"}'
```

Запустить сервис:
```
mosquitto_pub -h localhost -p 1883 -u yourusername -P yourpassword -t "module_manager/command/run_command_for_systemd_service" -m '{"config_id":"123","action":"start"}'
```

Остановить сервис:
```
mosquitto_pub -h localhost -p 1883 -u yourusername -P yourpassword -t "module_manager/command/run_command_for_systemd_service" -m '{"config_id":"123","action":"stop"}'
```

Перезапустить сервис:
```
mosquitto_pub -h localhost -p 1883 -u yourusername -P yourpassword -t "module_manager/command/run_command_for_systemd_service" -m '{"config_id":"123","action":"restart"}'
```

Перезапуск всех сервисов:
```
mosquitto_pub -h localhost -p 1883 -u yourusername -P yourpassword -t "module_manager/command/restart_configs" -m '{}'
```

### REST API

- GET `/api/modules` `get_modules` - получить список модулей
- GET `/api/modules/{guid}` `get_module` - получить информацию о модуле
- POST `/api/modules` `add_module` - добавить новый модуль
- PUT `/api/modules/{guid}` `update_module` - обновить модуль
- PUT `/api/modules/{guid}/status` `update_module_status` - обновить статус модуля
- PUT `/api/modules/statuses` `update_all_statuses` - обновить все статусы модулей
- DELETE `/api/modules/{guid}` `delete_module`  - удалить модуль

## Структура базы данных

База данных SQLite содержит таблицу `modules` со следующими полями:

- `guid` - уникальный идентификатор модуля (TEXT, PRIMARY KEY)
- `name` - название модуля (TEXT)
- `description` - описание модуля (TEXT)
- `status` - статус модуля (TEXT): 'active', 'inactive', 'failed', 'other'
- `service_type` - тип сервиса (TEXT)

Управление базой данных происходит с помощью методов доступных на http://localhost:8080/docs

## Проверка статуса сервисов

```
sudo systemctl status system-api
sudo systemctl status module-manager
sudo systemctl status <module_name>.service
```

## Проверка логов
Файлы module_manager.log и system_api.log


## Для остановки сервиса
```
sudo systemctl stop module-manager
sudo systemctl stop system-api
```