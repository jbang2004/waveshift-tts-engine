"""
简化的流水线框架 - 用于TTS任务编排
"""

from .base import Pipeline, Step
from .tts_pipeline import TTSPipeline

__all__ = ['Pipeline', 'Step', 'TTSPipeline']