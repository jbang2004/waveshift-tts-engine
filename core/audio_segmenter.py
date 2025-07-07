import logging
import asyncio
import numpy as np
import soundfile as sf
import librosa
from typing import List
from ray import serve

from config import get_config
from core.sentence_tools import Sentence
from utils.path_manager import PathManager

logger = logging.getLogger(__name__)

@serve.deployment(
    name="audio_segmenter", 
    ray_actor_options={"num_cpus": 1},
    logging_config={"log_level": "INFO"}
)
class AudioSegmenter:
    """音频切分服务 - 根据时间戳切分音频，生成语音克隆样本"""
    
    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)
        self.target_sr = self.config.TARGET_SR
        
        self.logger.info("音频切分服务初始化完成")
    
    async def segment_audio_for_sentences(self, task_id: str, audio_file_path: str, 
                                        sentences: List[Sentence]) -> List[Sentence]:
        """
        为句子列表切分音频，生成语音克隆样本
        
        Args:
            task_id: 任务ID
            audio_file_path: 音频文件路径
            sentences: 句子列表
            
        Returns:
            List[Sentence]: 更新了音频路径的句子列表
        """
        try:
            self.logger.info(f"[{task_id}] 开始为 {len(sentences)} 个句子切分音频")
            
            # 加载完整的音频文件
            audio_data, sr = await asyncio.to_thread(sf.read, audio_file_path)
            
            # 重采样到目标采样率
            if sr != self.target_sr:
                audio_data = await asyncio.to_thread(
                    librosa.resample, audio_data, orig_sr=sr, target_sr=self.target_sr
                )
                sr = self.target_sr
            
            # 确保音频是单声道
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            self.logger.info(f"[{task_id}] 音频加载完成: {len(audio_data)/sr:.2f}秒, {sr}Hz")
            
            # 创建音频提示目录
            path_manager = PathManager(task_id)
            audio_prompts_dir = path_manager.temp.audio_prompts_dir
            audio_prompts_dir.mkdir(parents=True, exist_ok=True)
            
            # 为每个句子切分音频
            updated_sentences = []
            for i, sentence in enumerate(sentences):
                try:
                    # 计算时间范围（毫秒转秒）
                    start_time = sentence.start_ms / 1000.0
                    end_time = sentence.end_ms / 1000.0
                    
                    # 扩展音频片段用于语音克隆（前后各扩展1秒）
                    extended_start = max(0, start_time - 1.0)
                    extended_end = min(len(audio_data) / sr, end_time + 1.0)
                    
                    # 提取音频片段
                    start_sample = int(extended_start * sr)
                    end_sample = int(extended_end * sr)
                    audio_segment = audio_data[start_sample:end_sample]
                    
                    # 确保音频片段足够长（至少0.5秒）
                    min_samples = int(0.5 * sr)
                    if len(audio_segment) < min_samples:
                        # 如果太短，尝试扩展
                        padding_needed = min_samples - len(audio_segment)
                        padding_before = padding_needed // 2
                        padding_after = padding_needed - padding_before
                        
                        new_start = max(0, start_sample - padding_before)
                        new_end = min(len(audio_data), end_sample + padding_after)
                        audio_segment = audio_data[new_start:new_end]
                    
                    # 保存音频片段
                    audio_filename = f"sentence_{sentence.sequence}_{i:04d}.wav"
                    audio_prompt_path = audio_prompts_dir / audio_filename
                    
                    await asyncio.to_thread(
                        sf.write, str(audio_prompt_path), audio_segment, sr
                    )
                    
                    # 更新句子的音频路径
                    sentence.audio = str(audio_prompt_path)
                    
                    # 计算实际的音频时长（用于语音克隆参考）
                    actual_duration = len(audio_segment) / sr
                    sentence.speech_duration = actual_duration
                    
                    updated_sentences.append(sentence)
                    
                    if i % 10 == 0:
                        self.logger.debug(f"[{task_id}] 已处理 {i+1}/{len(sentences)} 个句子")
                        
                except Exception as e:
                    self.logger.error(f"[{task_id}] 处理句子 {i} 失败: {e}")
                    # 即使失败也要保留句子，只是没有音频路径
                    updated_sentences.append(sentence)
            
            self.logger.info(f"[{task_id}] 音频切分完成，成功处理 {len([s for s in updated_sentences if s.audio])} 个句子")
            return updated_sentences
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 音频切分失败: {e}")
            return sentences
    
