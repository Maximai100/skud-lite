import enum
import uuid as uuid_lib
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, Enum as SQLEnum

from database import Base


class UserStatus(str, enum.Enum):
    """Статусы пользователя."""
    inside = "inside"       # В здании
    work = "work"           # На работе
    day_off = "day_off"     # На сутки
    request = "request"     # По заявлению


class User(Base):
    """Модель пользователя (жильца)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, index=True, default=lambda: str(uuid_lib.uuid4()))
    full_name = Column(String, nullable=False)
    status = Column(SQLEnum(UserStatus), default=UserStatus.inside)
    last_update = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Геолокация (последние известные координаты)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
