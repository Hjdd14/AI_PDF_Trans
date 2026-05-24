"""Configuration data models and persistence."""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

from src.utils.crypto import encrypt_value, decrypt_value


PROVIDER_TYPES = ["anthropic", "openai", "compatible"]

LANGUAGES = {
    "English": "english",
    "Chinese": "chinese",
    "Japanese": "japanese",
    "Korean": "korean",
    "French": "french",
    "German": "german",
    "Spanish": "spanish",
    "Russian": "russian",
    "Arabic": "arabic",
    "Portuguese": "portuguese",
    "Italian": "italian",
    "Dutch": "dutch",
    "Turkish": "turkish",
    "Thai": "thai",
    "Vietnamese": "vietnamese",
}

CJK_LANGUAGES = {"chinese", "japanese", "korean"}


@dataclass
class LLMConfig:
    provider_type: str = "openai"
    api_url: Optional[str] = None
    api_key: str = ""
    model_name: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("API Key is required")
        if not self.model_name:
            errors.append("Model name is required")
        if self.provider_type not in PROVIDER_TYPES:
            errors.append(f"Invalid provider type: {self.provider_type}")
        return errors

    def get_litellm_model(self) -> str:
        if self.provider_type == "compatible":
            return self.model_name
        prefix = "anthropic" if self.provider_type == "anthropic" else "openai"
        if "/" in self.model_name:
            return self.model_name
        return f"{prefix}/{self.model_name}"


@dataclass
class AppConfig:
    source_lang: str = "English"
    target_lang: str = "Chinese"
    tectonic_path: Optional[str] = None
    output_dir: str = ""
    data_dir: str = ""
    ui_lang: str = "zh"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FullConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    app: AppConfig = field(default_factory=AppConfig)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        llm_data = asdict(self.llm)
        if llm_data.get("api_key"):
            llm_data["api_key"] = encrypt_value(llm_data["api_key"])
            llm_data["api_key_encrypted"] = True
        data = {
            "llm": llm_data,
            "app": self.app.to_dict(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "FullConfig":
        if not os.path.exists(path):
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        llm_data = data.get("llm", {})
        if llm_data.get("api_key_encrypted"):
            try:
                llm_data["api_key"] = decrypt_value(llm_data["api_key"])
            except Exception:
                llm_data["api_key"] = ""
            llm_data.pop("api_key_encrypted", None)
        llm = LLMConfig(**{k: v for k, v in llm_data.items() if k in LLMConfig.__dataclass_fields__})
        app = AppConfig.from_dict(data.get("app", {}))
        return cls(llm=llm, app=app)
