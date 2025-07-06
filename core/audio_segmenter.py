import logging
import asyncio
import numpy as np
import soundfile as sf
import librosa
from typing import List, Dict, Optional, Tuple
from ray import serve
from pathlib import Path
import aiofiles
import tempfile

from config import get_config
from core.sentence_tools import Sentence
from utils.task_storage import TaskPaths

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
            task_paths = TaskPaths(self.config, task_id)
            audio_prompts_dir = task_paths.audio_prompts_dir
            audio_prompts_dir.mkdir(parents=True, exist_ok=True)
            
            # 为每个句子切分音频
            updated_sentences = []
            for i, sentence in enumerate(sentences):
                try:
                    # 计算时间范围（毫秒转秒）
                    start_time = sentence.start / 1000.0
                    end_time = sentence.end / 1000.0
                    
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
                    audio_filename = f"sentence_{sentence.sentence_id}_{i:04d}.wav"
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
    
    async def extract_speaker_samples(self, task_id: str, audio_file_path: str, 
                                    sentences: List[Sentence]) -> Dict[int, str]:
        """
        为每个说话人提取代表性音频样本
        
        Args:
            task_id: 任务ID
            audio_file_path: 音频文件路径
            sentences: 句子列表
            
        Returns:
            Dict[int, str]: 说话人ID到音频样本路径的映射
        """
        try:
            self.logger.info(f"[{task_id}] 开始提取说话人音频样本")
            
            # 按说话人分组句子
            speaker_sentences = {}
            for sentence in sentences:
                speaker_id = sentence.speaker_id
                if speaker_id not in speaker_sentences:
                    speaker_sentences[speaker_id] = []
                speaker_sentences[speaker_id].append(sentence)
            
            # 加载音频
            audio_data, sr = await asyncio.to_thread(sf.read, audio_file_path)
            if sr != self.target_sr:
                audio_data = await asyncio.to_thread(
                    librosa.resample, audio_data, orig_sr=sr, target_sr=self.target_sr
                )
                sr = self.target_sr
            
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # 创建说话人样本目录
            task_paths = TaskPaths(self.config, task_id)
            speaker_samples_dir = task_paths.audio_prompts_dir / "speaker_samples"
            speaker_samples_dir.mkdir(parents=True, exist_ok=True)
            
            speaker_samples = {}
            
            for speaker_id, speaker_sentences_list in speaker_sentences.items():
                try:
                    # 选择最长的几个句子作为样本
                    sorted_sentences = sorted(
                        speaker_sentences_list, 
                        key=lambda s: s.end - s.start, 
                        reverse=True
                    )
                    
                    # 取前3个最长的句子
                    sample_sentences = sorted_sentences[:3]
                    
                    # 合并这些句子的音频
                    combined_audio = []
                    
                    for sentence in sample_sentences:
                        start_time = sentence.start / 1000.0
                        end_time = sentence.end / 1000.0
                        
                        start_sample = int(start_time * sr)
                        end_sample = int(end_time * sr)
                        
                        segment = audio_data[start_sample:end_sample]
                        
                        # 添加短暂的静音分隔
                        if combined_audio:
                            silence = np.zeros(int(0.1 * sr))  # 0.1秒静音
                            combined_audio.extend(silence)
                        
                        combined_audio.extend(segment)
                    
                    combined_audio = np.array(combined_audio)
                    
                    # 限制样本长度（最多20秒）
                    max_samples = int(20 * sr)
                    if len(combined_audio) > max_samples:
                        combined_audio = combined_audio[:max_samples]
                    
                    # 保存说话人样本
                    sample_filename = f"speaker_{speaker_id}_sample.wav"
                    sample_path = speaker_samples_dir / sample_filename
                    
                    await asyncio.to_thread(
                        sf.write, str(sample_path), combined_audio, sr
                    )
                    
                    speaker_samples[speaker_id] = str(sample_path)
                    
                    self.logger.info(f"[{task_id}] 说话人 {speaker_id} 样本已保存: {len(combined_audio)/sr:.2f}秒")
                    
                except Exception as e:
                    self.logger.error(f"[{task_id}] 提取说话人 {speaker_id} 样本失败: {e}")
            
            self.logger.info(f"[{task_id}] 说话人音频样本提取完成，共 {len(speaker_samples)} 个说话人")
            return speaker_samples
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 提取说话人样本失败: {e}")
            return {}
    
    async def validate_audio_segments(self, sentences: List[Sentence]) -> List[Sentence]:
        """验证音频片段的质量"""
        validated_sentences = []
        
        for sentence in sentences:
            if not sentence.audio or not Path(sentence.audio).exists():
                self.logger.warning(f"句子 {sentence.sentence_id} 缺少音频文件")
                validated_sentences.append(sentence)
                continue
            
            try:
                # 检查音频文件是否可读
                audio_data, sr = await asyncio.to_thread(sf.read, sentence.audio)
                
                # 检查音频时长
                duration = len(audio_data) / sr
                if duration < 0.1:
                    self.logger.warning(f"句子 {sentence.sentence_id} 音频太短: {duration:.2f}秒")
                elif duration > 30:
                    self.logger.warning(f"句子 {sentence.sentence_id} 音频太长: {duration:.2f}秒")
                
                # 更新实际音频时长
                sentence.speech_duration = duration
                
            except Exception as e:
                self.logger.error(f"验证句子 {sentence.sentence_id} 音频失败: {e}")
            
            validated_sentences.append(sentence)
        
        return validated_sentences