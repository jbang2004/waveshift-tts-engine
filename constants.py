"""
统一的常量管理 - 避免重复定义
"""

# 音频处理常量
class AudioConstants:
    """音频处理相关常量"""
    SAMPLE_RATE = 24000
    BATCH_SIZE = 20
    MAX_VOLUME = 1.0
    DEFAULT_CHANNELS = 1
    DEFAULT_DTYPE = "float32"
    FADE_DURATION = 0.1  # 淡入淡出时长（秒）

# 时间相关常量
class TimeConstants:
    """时间相关常量"""
    DEFAULT_TIMEOUT = 30.0
    MAX_DURATION = 600.0  # 最大处理时长（秒）
    RETRY_DELAY = 1.0
    RETRY_BACKOFF = 2.0
    MAX_RETRIES = 3

# 状态常量
class StatusConstants:
    """任务状态常量"""
    SUCCESS = "success"
    ERROR = "error"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    CANCELLED = "cancelled"

# 文件相关常量
class FileConstants:
    """文件处理相关常量"""
    TEMP_DIR_PREFIX = "tts_"
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    ALLOWED_AUDIO_FORMATS = ['.wav', '.mp3', '.aac', '.flac', '.m4a']
    ALLOWED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv']
    DEFAULT_AUDIO_FORMAT = '.wav'
    DEFAULT_VIDEO_FORMAT = '.mp4'

# 网络相关常量
class NetworkConstants:
    """网络请求相关常量"""
    DEFAULT_TIMEOUT = 30.0
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    USER_AGENT = "WaveShift-TTS-Engine/2.0"
    MAX_CONCURRENT_REQUESTS = 10

# 批处理常量
class BatchConstants:
    """批处理相关常量"""
    DEFAULT_BATCH_SIZE = 20
    MAX_BATCH_SIZE = 100
    MIN_BATCH_SIZE = 1
    PARALLEL_WORKERS = 4

# 日志相关常量
class LogConstants:
    """日志相关常量"""
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

# HLS相关常量
class HLSConstants:
    """HLS流媒体相关常量"""
    SEGMENT_DURATION = 10.0  # 片段时长（秒）
    TARGET_BITRATE = "1000k"
    PLAYLIST_TYPE = "vod"
    SEGMENT_FORMAT = "ts"
    PLAYLIST_EXTENSION = ".m3u8"

# 翻译相关常量
class TranslationConstants:
    """翻译服务相关常量"""
    DEFAULT_MODEL = "deepseek"
    MAX_TEXT_LENGTH = 4000
    DEFAULT_TEMPERATURE = 0.1
    MAX_TOKENS = 1000
    SUPPORTED_LANGUAGES = ["en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru"]

# 错误消息常量
class ErrorMessages:
    """标准错误消息"""
    INVALID_TASK_ID = "无效的任务ID"
    TASK_NOT_FOUND = "未找到指定任务"
    AUDIO_PROCESSING_FAILED = "音频处理失败"
    VIDEO_PROCESSING_FAILED = "视频处理失败"
    NETWORK_ERROR = "网络连接错误"
    TIMEOUT_ERROR = "操作超时"
    INSUFFICIENT_RESOURCES = "系统资源不足"
    INVALID_FILE_FORMAT = "不支持的文件格式"
    FILE_TOO_LARGE = "文件大小超过限制"
    TRANSLATION_FAILED = "翻译服务失败"
    
# 成功消息常量
class SuccessMessages:
    """标准成功消息"""
    TASK_CREATED = "任务创建成功"
    TASK_COMPLETED = "任务完成"
    AUDIO_PROCESSED = "音频处理完成"
    VIDEO_PROCESSED = "视频处理完成"
    TRANSLATION_COMPLETED = "翻译完成"
    FILE_UPLOADED = "文件上传成功"
    HLS_GENERATED = "HLS流媒体生成成功"