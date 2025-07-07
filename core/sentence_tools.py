import numpy as np
from typing import Dict
from dataclasses import dataclass, field

@dataclass
class Sentence:
    # Worker 一致的字段名
    original_text: str              # 原 raw_text
    translated_text: str            # 原 trans_text  
    sequence: int                   # 原 sentence_id
    speaker: str                    # 原 speaker_id: int，现在改为 str
    start_ms: float                 # 原 start
    end_ms: float                   # 原 end
    
    # TTS 专用字段（保持不变）
    task_id: str = field(default="")
    audio: str = field(default="")  # 音频文件路径
    target_duration: float = field(default=None)
    duration: float = field(default=0.0)
    speech_duration: float = field(default=0.0)
    diff: float = field(default=0.0)
    silence_duration: float = field(default=0.0)
    speed: float = field(default=1.0)
    is_first: bool = field(default=False)
    is_last: bool = field(default=False)
    model_input: Dict = field(default_factory=dict)
    generated_audio: np.ndarray = field(default=None)
    adjusted_start: float = field(default=0.0)
    adjusted_duration: float = field(default=0.0)
    ending_silence: float = field(default=0.0)
    
    def __post_init__(self):
        """初始化后自动计算缺失字段"""
        # 计算 target_duration（秒）
        if self.target_duration is None:
            self.target_duration = (self.end_ms - self.start_ms) / 1000.0
        
        # 计算其他时长相关字段
        if self.duration == 0.0:
            self.duration = self.target_duration
        
        if self.speech_duration == 0.0:
            self.speech_duration = self.duration * 0.9  # 假设90%是语音
        
        if self.silence_duration == 0.0:
            self.silence_duration = self.duration * 0.1  # 假设10%是静音

