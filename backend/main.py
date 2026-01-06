import os
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional

from database import engine, get_db, Base
from models import User, UserStatus

# === Настройка логирования ===
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "activity.log"

# Логгер для активности пользователей
activity_logger = logging.getLogger("activity")
activity_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
activity_logger.addHandler(file_handler)


def log_activity(user: User, old_status: str, new_status: str, lat: float = None, lon: float = None):
    """Запись активности в лог-файл."""
    location = f" | GPS: {lat:.6f}, {lon:.6f}" if lat and lon else ""
    activity_logger.info(f"{user.full_name} | {old_status} -> {new_status}{location}")


# Создание таблиц
Base.metadata.create_all(bind=engine)

app = FastAPI(title="СКУД-лайт API", version="1.1.0")

# Настройка CORS для работы с фронтендом
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Pydantic схемы ===

class RegisterRequest(BaseModel):
    full_name: str


class RegisterResponse(BaseModel):
    user_id: str
    full_name: str
    status: str


class StatusUpdate(BaseModel):
    status: str  # inside, work, day_off, request
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class UserStatusResponse(BaseModel):
    user_id: str
    full_name: str
    status: str
    last_update: str


class StatsResponse(BaseModel):
    inside: int
    work: int
    day_off: int
    request: int
    total: int


class AbsentUser(BaseModel):
    full_name: str
    status: str
    status_label: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    has_location: bool = False


# === Маппинг статусов ===

STATUS_LABELS = {
    "inside": "В здании",
    "work": "На работе",
    "day_off": "На сутки",
    "request": "По заявлению",
}


# === API Endpoints ===

@app.post("/api/register", response_model=RegisterResponse)
def register_user(data: RegisterRequest, db: Session = Depends(get_db)):
    """Регистрация нового жильца."""
    if not data.full_name or len(data.full_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Введите корректное ФИО")
    
    user = User(full_name=data.full_name.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    
    log_activity(user, "NEW", user.status.value)
    
    return RegisterResponse(
        user_id=user.uuid,
        full_name=user.full_name,
        status=user.status.value
    )


@app.get("/api/status/{user_id}", response_model=UserStatusResponse)
def get_status(user_id: str, db: Session = Depends(get_db)):
    """Получить статус пользователя по UUID."""
    user = db.query(User).filter(User.uuid == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return UserStatusResponse(
        user_id=user.uuid,
        full_name=user.full_name,
        status=user.status.value,
        last_update=user.last_update.isoformat() if user.last_update else ""
    )


@app.post("/api/status/{user_id}", response_model=UserStatusResponse)
def update_status(user_id: str, data: StatusUpdate, db: Session = Depends(get_db)):
    """Обновить статус пользователя."""
    user = db.query(User).filter(User.uuid == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Проверка валидности статуса
    try:
        new_status = UserStatus(data.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный статус")
    
    old_status = user.status.value
    user.status = new_status
    
    # Сохранение геолокации
    if data.latitude is not None and data.longitude is not None:
        user.latitude = data.latitude
        user.longitude = data.longitude
    
    db.commit()
    db.refresh(user)
    
    # Логирование
    log_activity(user, old_status, new_status.value, data.latitude, data.longitude)
    
    return UserStatusResponse(
        user_id=user.uuid,
        full_name=user.full_name,
        status=user.status.value,
        last_update=user.last_update.isoformat() if user.last_update else ""
    )


@app.get("/api/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    """Статистика по всем пользователям."""
    stats = db.query(
        User.status, func.count(User.id)
    ).group_by(User.status).all()
    
    result = {"inside": 0, "work": 0, "day_off": 0, "request": 0}
    for status, count in stats:
        result[status.value] = count
    
    total = sum(result.values())
    
    return StatsResponse(
        inside=result["inside"],
        work=result["work"],
        day_off=result["day_off"],
        request=result["request"],
        total=total
    )


@app.get("/api/absent", response_model=list[AbsentUser])
def get_absent(db: Session = Depends(get_db)):
    """Список отсутствующих (все кроме inside) с геолокацией."""
    users = db.query(User).filter(User.status != UserStatus.inside).order_by(User.full_name).all()
    
    return [
        AbsentUser(
            full_name=u.full_name,
            status=u.status.value,
            status_label=STATUS_LABELS.get(u.status.value, u.status.value),
            latitude=u.latitude,
            longitude=u.longitude,
            has_location=u.latitude is not None and u.longitude is not None
        )
        for u in users
    ]


@app.post("/api/reset")
def reset_all(db: Session = Depends(get_db)):
    """Сбросить всех пользователей в статус 'В здании'."""
    db.query(User).update({User.status: UserStatus.inside})
    db.commit()
    activity_logger.info("ADMIN | Сброс всех статусов на 'inside'")
    return {"message": "Все статусы сброшены", "new_status": "inside"}


@app.get("/api/users")
def get_all_users(db: Session = Depends(get_db)):
    """Получить список всех пользователей."""
    users = db.query(User).order_by(User.full_name).all()
    return [
        {
            "id": u.id,
            "uuid": u.uuid,
            "full_name": u.full_name,
            "status": u.status.value,
            "status_label": STATUS_LABELS.get(u.status.value, u.status.value),
        }
        for u in users
    ]


@app.get("/api/users/search")
def search_users(q: str, db: Session = Depends(get_db)):
    """Поиск пользователей по ФИО."""
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="Минимум 2 символа для поиска")
    
    users = db.query(User).filter(User.full_name.ilike(f"%{q}%")).order_by(User.full_name).limit(10).all()
    return [
        {
            "id": u.id,
            "uuid": u.uuid,
            "full_name": u.full_name,
            "status": u.status.value,
            "status_label": STATUS_LABELS.get(u.status.value, u.status.value),
        }
        for u in users
    ]


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    """Удалить пользователя по ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    full_name = user.full_name
    db.delete(user)
    db.commit()
    
    activity_logger.info(f"ADMIN | Удалён пользователь: {full_name}")
    return {"message": f"Пользователь '{full_name}' удалён", "deleted_id": user_id}


# === Раздача статических файлов ===

# Путь к папке frontend (на уровень выше от backend)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Монтируем статику для CSS/JS
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    """Отдаём index.html по корневому URL."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "СКУД-лайт API работает", "version": "1.1.0", "note": "Frontend не найден"}


@app.get("/{filename}")
def serve_static(filename: str):
    """Отдаём статические файлы (css, js)."""
    file_path = FRONTEND_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Файл не найден")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
