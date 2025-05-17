import sys
import json
import logging
import uvicorn
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from database import Database

CONFIG_FILE = "config.json"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("system_api.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("SystemAPI")
# чтение конфига
def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.critical('Нет файла конфигурации')
        sys.exit(1)
        
config = load_config()

db = Database(config["database"]["path"])

app = FastAPI(title="System API")
templates = Jinja2Templates(directory="templates")

class ModuleStatus(BaseModel):
    status: str = Field(...)

class ModuleBase(BaseModel):
    guid: str = Field(...)
    name: str = Field(...)
    description: Optional[str] = Field("")
    status: Optional[str] = Field("inactive")
    service_type: str = Field(...)

class ModuleCreate(ModuleBase):
    pass

class Module(ModuleBase):
    pass

class StatusResponse(BaseModel):
    success: bool
    updated_count: int
    updated_modules: List[str] = []

def get_db():
    return db
# главная страница
@app.get("/")
async def home(request: Request, db: Database = Depends(get_db)):
    modules = db.get_modules()
    return templates.TemplateResponse("dashboard.html", {"request": request, "modules": modules})
# список модулей
@app.get("/api/modules", response_model=List[Module])
async def get_modules(db: Database = Depends(get_db)):
    modules = db.get_modules()
    logger.info(f"Получено {len(modules)} модулей")
    return modules
# получить модуль по ID 
@app.get("/api/modules/{guid}", response_model=Module)
async def get_module(guid: str, db: Database = Depends(get_db)):
    module = db.get_module(guid)
    if module:
        return module
    raise HTTPException(status_code=404, detail="Не найден модуль")
# добавить новый модуль
@app.post("/api/modules", response_model=Module)
async def add_module(module: ModuleCreate, db: Database = Depends(get_db)):
    existing_module = db.get_module(module.guid)
    if existing_module:
        raise HTTPException(status_code=409, detail="Такой модуль уже существует")
    
    module_dict = module.model_dump()
    if db.add_module(module_dict):
        logger.info(f"Добавлен новый модуль: {module_dict('name')} (GUID: {module_dict('guid')})")
        return module_dict
    else:
        raise HTTPException(status_code=500, detail="Ошибка при добавлении модуля")
# обновить параменты модуля
@app.put("/api/modules/{guid}", response_model=Module)
async def update_module(guid: str, module_update: dict, db: Database = Depends(get_db)):
    existing_module = db.get_module(guid)
    if not existing_module:
        raise HTTPException(status_code=404, detail="Модуль не найден")
    
    if db.update_module(guid, module_update):
        updated_module = db.get_module(guid)
        logger.info(f"Обновленный модуль: {updated_module['name']} (GUID: {guid})")
        return updated_module
    else:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении модуля")
# обновить статус модуля
@app.put("/api/modules/{guid}/status", response_model=dict)
async def update_module_status(guid: str, status_update: ModuleStatus, db: Database = Depends(get_db)):
    status = status_update.status
    
    existing_module = db.get_module(guid)
    if not existing_module:
        raise HTTPException(status_code=404, detail="Модуль не найден")

    if db.update_module_status(guid, status):
        logger.info(f"Обновлен статус для: {existing_module['name']} (GUID: {guid}) - {status}")
        return {"success": True}
    else:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении статуса")
# обновить все статусы модулей
@app.put("/api/modules/statuses", response_model=StatusResponse)
async def update_all_statuses(status_updates: List[Dict[str, Any]], db: Database = Depends(get_db)):
    if not status_updates:
        return {"success": True, "updated_count": 0, "updated_modules": []}
    
    success, updated_count, updated_modules = db.update_modules_status(status_updates)
    
    if success:
        if updated_count > 0:
            logger.info(f"Обновлены статусы для {updated_count} модулей: {', '.join(updated_modules)}")
        return {"success": True, "updated_count": updated_count, "updated_modules": updated_modules}
    else:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении статусов")
# удлаить модуль
@app.delete("/api/modules/{guid}", response_model=dict)
async def delete_module(guid: str, db: Database = Depends(get_db)):
    existing_module = db.get_module(guid)
    if not existing_module:
        raise HTTPException(status_code=404, detail="Модуль не найден")
    
    if db.delete_module(guid):
        logger.info(f"Удаленный модуль: {existing_module['name']} (GUID: {guid})")
        return {"success": True}
    else:
        raise HTTPException(status_code=500, detail="Ошибка при удалении модуля")

if __name__ == "__main__":
    logger.info("Starting System API server on http://0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
