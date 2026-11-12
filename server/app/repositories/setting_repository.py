from typing import Optional, List
from sqlalchemy.orm import Session
from app.db.models.system_setting import SystemSetting


class SettingRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_key(self, key: str) -> Optional[SystemSetting]:
        return self.db.query(SystemSetting).filter(SystemSetting.key == key).first()

    def get_all(self) -> List[SystemSetting]:
        return self.db.query(SystemSetting).all()

    def set_value(self, key: str, value: str, description: Optional[str] = None) -> SystemSetting:
        setting = self.get_by_key(key)
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = SystemSetting(key=key, value=value, description=description)
            self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting
