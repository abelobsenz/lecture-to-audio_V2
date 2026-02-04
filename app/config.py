from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    # Core
    env: str = Field(default="dev")
    public_base_url: str = Field(default="http://localhost:8000")

    # Storage
    data_dir: Path = Field(default=Path("data"))
    uploads_dir: Path = Field(default=Path("data/uploads"))
    extracted_dir: Path = Field(default=Path("data/extracted"))
    scripts_dir: Path = Field(default=Path("data/scripts"))
    audio_dir: Path = Field(default=Path("data/audio"))
    rss_dir: Path = Field(default=Path("data/rss"))
    chunks_dir: Path = Field(default=Path("data/chunks"))

    # Limits
    max_upload_mb: int = Field(default=50)

    # OpenAI
    openai_api_key: Optional[str] = Field(default=None)
    openai_model_analysis: str = Field(default="gpt-5.2")
    openai_model_fallback: str = Field(default="gpt-5-mini")
    openai_tts_model: str = Field(default="gpt-4o-mini-tts")
    openai_tts_voice: str = Field(default="alloy")
    openai_tts_format: str = Field(default="m4a")
    openai_realtime_model: str = Field(default="gpt-realtime")
    openai_realtime_voice: str = Field(default="alloy")
    upload_token: Optional[str] = Field(default=None)

    # Processing
    max_pages_per_chunk: int = Field(default=3)
    worker_poll_interval_sec: float = Field(default=0.5)
    chunk_target_seconds: int = Field(default=15)
    chunk_words_per_second: float = Field(default=2.5)
    realtime_rate_limit_per_min: int = Field(default=10)
    enable_audio_generation: bool = Field(default=False)
    enable_rss: bool = Field(default=False)
    cors_allow_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )

    # iCloud / iPhone sync
    ios_sync_dir: Optional[Path] = Field(default=None)

    @classmethod
    def from_env(cls) -> "Settings":
        def _p(name: str, default: Optional[str] = None) -> Optional[str]:
            return os.environ.get(name, default)

        def _bool(name: str, default: bool) -> bool:
            value = os.environ.get(name)
            if value is None:
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        ios_dir = _p("IOS_SYNC_DIR")
        origins_env = _p("CORS_ALLOW_ORIGINS", "")
        if origins_env:
            origins = [item.strip() for item in origins_env.split(",") if item.strip()]
        else:
            origins = [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ]
        return cls(
            env=_p("ENV", "dev"),
            public_base_url=_p("PUBLIC_BASE_URL", "http://localhost:8000"),
            max_upload_mb=int(_p("MAX_UPLOAD_MB", "50")),
            openai_api_key=_p("OPENAI_API_KEY"),
            openai_model_analysis=_p("OPENAI_MODEL_ANALYSIS", "gpt-5.2"),
            openai_model_fallback=_p("OPENAI_MODEL_FALLBACK", "gpt-5-mini"),
            openai_tts_model=_p("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            openai_tts_voice=_p("OPENAI_TTS_VOICE", "alloy"),
            openai_tts_format=_p("OPENAI_TTS_FORMAT", "m4a"),
            openai_realtime_model=_p("OPENAI_REALTIME_MODEL", "gpt-realtime"),
            openai_realtime_voice=_p("OPENAI_REALTIME_VOICE", "alloy"),
            upload_token=_p("UPLOAD_TOKEN"),
            max_pages_per_chunk=int(_p("MAX_PAGES_PER_CHUNK", "3")),
            worker_poll_interval_sec=float(_p("WORKER_POLL_INTERVAL_SEC", "0.5")),
            chunk_target_seconds=int(_p("CHUNK_TARGET_SECONDS", "15")),
            chunk_words_per_second=float(_p("CHUNK_WORDS_PER_SECOND", "2.5")),
            realtime_rate_limit_per_min=int(_p("REALTIME_RATE_LIMIT_PER_MIN", "10")),
            enable_audio_generation=_bool("ENABLE_AUDIO_GENERATION", False),
            enable_rss=_bool("ENABLE_RSS", False),
            cors_allow_origins=origins,
            ios_sync_dir=Path(ios_dir).expanduser() if ios_dir else None,
        )


settings = Settings.from_env()
