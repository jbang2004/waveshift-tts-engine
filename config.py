import os
from pathlib import Path
from dotenv import load_dotenv
import logging.config

current_dir = Path(__file__).parent
env_path = current_dir / '.env'
load_dotenv(env_path)

project_dir = current_dir.parent
storage_dir = project_dir / 'storage'

class Config:
    # 服务器配置
    SERVER_HOST = "0.0.0.0"
    SERVER_PORT = 8000
    LOG_LEVEL = "DEBUG"

    # 路径配置
    BASE_DIR = storage_dir
    TASKS_DIR = BASE_DIR / "tasks"
    PUBLIC_DIR = BASE_DIR / "public"
    MODEL_DIR = project_dir / "models"

    # Cloudflare配置
    CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
    CLOUDFLARE_D1_DATABASE_ID = os.getenv("CLOUDFLARE_D1_DATABASE_ID")
    CLOUDFLARE_R2_ACCESS_KEY_ID = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID")
    CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
    CLOUDFLARE_R2_BUCKET_NAME = os.getenv("CLOUDFLARE_R2_BUCKET_NAME")
    

    # 音频处理配置
    BATCH_SIZE = 6
    TARGET_SPEAKER_AUDIO_DURATION = 10
    VAD_SR = 16000
    TARGET_SR = 24000
    VOCALS_VOLUME = 0.7
    BACKGROUND_VOLUME = 0.3
    AUDIO_OVERLAP = 1024
    SILENCE_FADE_MS = 25
    NORMALIZATION_THRESHOLD = 0.9
    
    # 音频切片配置
    AUDIO_CLIP_GOAL_DURATION_MS = 12000  # 目标片段时长12秒
    AUDIO_CLIP_MIN_DURATION_MS = 1000    # 最小片段时长1秒
    AUDIO_CLIP_PADDING_MS = 200          # 切片padding时长200ms
    AUDIO_CLIP_ALLOW_CROSS_NON_SPEECH = False  # 是否允许跨越非speech片段合并

    # HLS配置
    ENABLE_HLS_STORAGE = os.getenv("ENABLE_HLS_STORAGE", "true").lower() == "true"
    HLS_STORAGE_BUCKET = os.getenv("HLS_STORAGE_BUCKET", "hls-streams")
    CLEANUP_LOCAL_HLS_FILES = os.getenv("CLEANUP_LOCAL_HLS_FILES", "true").lower() == "true"
    SEGMENT_MINUTES = 5
    MIN_SEGMENT_MINUTES = 3

    # AI模型配置
    TRANSLATION_MODEL = os.getenv("TRANSLATION_MODEL", "deepseek")
    ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    XAI_API_KEY = os.getenv("XAI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


    # 处理参数
    SIMPLIFICATION_BATCH_SIZE = 50
    TTS_BATCH_SIZE = 3
    MAX_PARALLEL_SEGMENTS = 2

    # 资源配置
    SIMPLIFIER_ACTOR_NUM_CPUS = 0.5
    MEDIA_MIXER_ACTOR_NUM_CPUS = 0.5


    @classmethod
    def init_directories(cls):
        """初始化所有必要目录"""
        directories = [
            cls.BASE_DIR,
            cls.TASKS_DIR,
            cls.PUBLIC_DIR,
            cls.PUBLIC_DIR / "playlists",
            cls.PUBLIC_DIR / "segments"
        ]
        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)
            os.chmod(str(dir_path), 0o755)

# 全局配置实例
_config_instance = None

def get_config():
    """获取全局配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
        _config_instance.init_directories()
    return _config_instance

# 日志配置
LOG_DIR = storage_dir / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(levelname)s | %(asctime)s | %(name)s | L%(lineno)d | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "standard",
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["console", "file"],
    },
}

def init_logging():
    """初始化全局日志配置"""
    logging.config.dictConfig(LOGGING_CONFIG)