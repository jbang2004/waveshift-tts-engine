import re
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Tuple, Optional

try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None
    print("⚠️ pydub 未安装，音频切片功能将不可用")

from config import get_config
from core.sentence_tools import Sentence
from utils.path_manager import PathManager

logger = logging.getLogger(__name__)

class AudioSegmenter:
    """音频切分服务 - 基于说话人分组的智能音频切片"""
    
    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)
        
        # 音频切片配置
        self.goal_duration_ms = self.config.AUDIO_CLIP_GOAL_DURATION_MS
        self.min_duration_ms = self.config.AUDIO_CLIP_MIN_DURATION_MS
        self.padding_ms = self.config.AUDIO_CLIP_PADDING_MS
        self.allow_cross_non_speech = self.config.AUDIO_CLIP_ALLOW_CROSS_NON_SPEECH
        
        if AudioSegment is None:
            self.logger.error("pydub 未安装，音频切片功能将不可用")
            raise ImportError("需要安装 pydub 库: pip install pydub")
            
        self.logger.info("音频切分服务初始化完成")
    
    def _time_str_to_ms(self, time_str: str) -> int:
        """时间字符串转毫秒的辅助函数"""
        match = re.match(r'(\d+)m(\d+)s(\d+)ms', time_str)
        if not match: 
            return 0
        m, s, ms = map(int, match.groups())
        return m * 60 * 1000 + s * 1000 + ms
    
    def _ms_to_time_str(self, ms: float) -> str:
        """毫秒转时间字符串的辅助函数"""
        ms_int = int(ms)  # 转换为整数
        minutes = ms_int // 60000
        seconds = (ms_int % 60000) // 1000
        milliseconds = ms_int % 1000
        return f"{minutes}m{seconds}s{milliseconds}ms"
    
    def _sentences_to_transcript_data(self, sentences: List[Sentence]) -> List[Dict]:
        """将Sentence对象转换为外部audio.py需要的格式"""
        transcript_data = []
        for sentence in sentences:
            transcript_data.append({
                'sequence': sentence.sequence,
                'start': self._ms_to_time_str(sentence.start_ms),
                'end': self._ms_to_time_str(sentence.end_ms),
                'speaker': sentence.speaker,
                'original': sentence.original_text,
                'translation': sentence.translated_text,
                'content_type': 'speech'  # 假设所有句子都是speech类型
            })
        return transcript_data
    
    def _create_audio_clips(self, transcript_data: List[Dict]) -> Tuple[Dict, Dict]:
        """根据转录数据创建音频切片计划（支持padding过渡）"""
        # 预处理：只处理speech类型的内容
        sentences = []
        for item in transcript_data:
            if item.get('content_type') != 'speech':
                continue
            
            start_ms = self._time_str_to_ms(item['start'])
            end_ms = self._time_str_to_ms(item['end'])
            
            # 添加padding：开头减去padding，结尾加上padding
            padded_start = max(0, start_ms - self.padding_ms)
            padded_end = end_ms + self.padding_ms
            
            item['original_segment'] = [start_ms, end_ms]  # 保存原始时间段
            item['padded_segment'] = [padded_start, padded_end]  # 带padding的时间段
            item['segment_duration'] = padded_end - padded_start
            
            if item['segment_duration'] > 0:
                sentences.append(item)

        if not sentences:
            return {}, {}

        # 识别同说话人连续块
        large_blocks = []
        if sentences:
            current_block = [sentences[0]]
            for i in range(1, len(sentences)):
                current_sentence = sentences[i]
                last_sentence = current_block[-1]
                
                # 检查说话人是否相同
                same_speaker = current_sentence['speaker'] == last_sentence['speaker']
                
                # 检查序列是否连续，或者如果允许跨越非speech，则检查中间是否有非speech片段
                if same_speaker:
                    if self.allow_cross_non_speech:
                        # 允许跨越非speech片段，直接检查说话人相同即可
                        current_block.append(current_sentence)
                    else:
                        # 不允许跨越非speech片段，需要检查序列是否严格连续
                        if current_sentence['sequence'] == last_sentence['sequence'] + 1:
                            current_block.append(current_sentence)
                        else:
                            # 序列不连续，说明中间有非speech片段，开始新块
                            large_blocks.append(current_block)
                            current_block = [current_sentence]
                else:
                    large_blocks.append(current_block)
                    current_block = [current_sentence]
            large_blocks.append(current_block)

        # 简化的逻辑：每个large_blocks生成一个clip
        clips_library = {}
        sentence_to_clip_id_map = {}
        clip_id_counter = 0

        for block in large_blocks:
            block_total_duration = sum(s['segment_duration'] for s in block)
            
            # 只处理总时长大于等于min_duration_ms的块
            if block_total_duration >= self.min_duration_ms:
                clip_id_counter += 1
                clip_id = f"Clip_{clip_id_counter}"
                
                # 如果总时长超过goal_duration_ms，需要截取前goal_duration_ms的音频
                if block_total_duration > self.goal_duration_ms:
                    # 计算需要截取的句子
                    accumulated_duration = 0
                    sentences_to_include = []
                    
                    for sentence in block:
                        if accumulated_duration + sentence['segment_duration'] <= self.goal_duration_ms:
                            sentences_to_include.append(sentence)
                            accumulated_duration += sentence['segment_duration']
                        else:
                            # 添加部分句子以达到goal_duration_ms
                            remaining_duration = self.goal_duration_ms - accumulated_duration
                            if remaining_duration > 0:
                                # 创建截取的句子副本
                                truncated_sentence = sentence.copy()
                                # 调整截取句子的segment_duration
                                truncated_sentence['segment_duration'] = remaining_duration
                                # 调整padded_segment的结束时间
                                start_time = truncated_sentence['padded_segment'][0]
                                truncated_sentence['padded_segment'] = [start_time, start_time + remaining_duration]
                                sentences_to_include.append(truncated_sentence)
                            break
                    
                    final_sentences = sentences_to_include
                else:
                    final_sentences = block
                
                # 合并重叠的segments
                merged_segments = self._merge_overlapping_segments(final_sentences)
                
                clips_library[clip_id] = {
                    "speaker": block[0]['speaker'],
                    "total_duration_ms": sum(end - start for start, end in merged_segments),
                    "segments_to_concatenate": merged_segments,
                    "padding_ms": self.padding_ms,
                    "sentences": [{
                        "sequence": s['sequence'], 
                        "original": s['original'], 
                        "translation": s['translation'],
                        "original_time": s['original_segment']
                    } for s in final_sentences]
                }
                
                # 为所有原始句子映射clip_id（包括未截取的部分）
                for sentence in block:
                    sentence_to_clip_id_map[sentence['sequence']] = clip_id

        return clips_library, sentence_to_clip_id_map
    
    def _merge_overlapping_segments(self, block: List[Dict]) -> List[List[int]]:
        """合并重叠的segments，确保平滑过渡"""
        if not block:
            return []
        
        segments = []
        for sentence in block:
            segments.append(sentence['padded_segment'])
        
        # 按开始时间排序
        segments.sort(key=lambda x: x[0])
        
        merged = [segments[0]]
        for current in segments[1:]:
            last = merged[-1]
            
            # 如果当前segment与上一个重叠，合并它们
            if current[0] <= last[1]:
                merged[-1] = [last[0], max(last[1], current[1])]
            else:
                merged.append(current)
        
        return merged
    
    async def _extract_and_save_audio_clips(self, audio_path: str, clips_library: Dict, 
                                          output_dir: str) -> Dict[str, str]:
        """并行版本的音频切片提取"""
        # 创建输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 检查音频文件是否存在
        audio_file = Path(audio_path)
        if not audio_file.exists():
            error_msg = f"音频文件不存在: {audio_path}"
            self.logger.error(f"❌ {error_msg}")
            raise FileNotFoundError(error_msg)
        
        if not audio_file.is_file():
            error_msg = f"路径不是文件: {audio_path}"
            self.logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        # 异步加载音频文件
        file_size = audio_file.stat().st_size
        self.logger.info(f"🎵 加载音频文件: {audio_path} (大小: {file_size/1024/1024:.1f}MB)")
        
        try:
            audio = await asyncio.to_thread(AudioSegment.from_file, audio_path)
            self.logger.info(f"✅ 音频文件加载成功，时长: {len(audio)/1000:.1f}秒")
        except Exception as e:
            error_msg = f"加载音频文件失败: {e}"
            self.logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg) from e
        
        # 并行处理所有切片
        async def process_single_clip(clip_id: str, clip_info: Dict) -> Tuple[str, Optional[str]]:
            """处理单个音频切片"""
            try:
                padding_ms = clip_info['padding_ms']
                self.logger.info(f"🎬 处理 {clip_id}: {clip_info['speaker']} ({clip_info['total_duration_ms']/1000:.1f}秒) [padding: {padding_ms}ms]")
                
                # 合并所有片段，使用padding进行平滑过渡
                combined_audio = AudioSegment.empty()
                segments_to_process = clip_info['segments_to_concatenate']
                
                for i, (start_ms, end_ms) in enumerate(segments_to_process):
                    # 边界检查
                    if start_ms < 0:
                        start_ms = 0
                    if end_ms > len(audio):
                        end_ms = len(audio)
                    if start_ms >= end_ms:
                        continue
                        
                    segment = audio[start_ms:end_ms]
                    
                    # 使用padding实现平滑过渡
                    if len(segment) > padding_ms * 2:
                        # 为了避免突然的开始和结束，在padding区域应用淡入淡出
                        fade_duration = min(padding_ms // 2, 100)  # 淡入淡出时长
                        
                        if i == 0:
                            # 第一个segment：在开头应用淡入
                            segment = segment.fade_in(fade_duration)
                        
                        if i == len(segments_to_process) - 1:
                            # 最后一个segment：在结尾应用淡出
                            segment = segment.fade_out(fade_duration)
                        else:
                            # 中间的segments：两端都进行轻微的淡入淡出以确保平滑
                            segment = segment.fade_in(fade_duration // 2).fade_out(fade_duration // 2)
                    
                    combined_audio += segment
                
                if len(combined_audio) == 0:
                    self.logger.warning(f"   ⚠️ {clip_id} 片段为空，跳过")
                    return clip_id, None
                
                # 保存音频片段
                speaker_name = clip_info['speaker'].replace(' ', '_').replace('/', '_')
                clip_filename = f"{clip_id}_{speaker_name}.wav"
                clip_filepath = output_path / clip_filename
                
                # 添加最终的音频标准化并异步保存
                combined_audio = combined_audio.normalize()
                await asyncio.to_thread(combined_audio.export, str(clip_filepath), format="wav")
                
                self.logger.info(f"   ✅ 已保存: {clip_filepath}")
                return clip_id, str(clip_filepath)
                
            except Exception as e:
                self.logger.error(f"处理切片 {clip_id} 失败: {e}")
                return clip_id, None
        
        # 并行执行所有切片处理
        self.logger.info(f"🚀 开始并行处理 {len(clips_library)} 个音频切片")
        tasks = [process_single_clip(clip_id, clip_info) for clip_id, clip_info in clips_library.items()]
        results = await asyncio.gather(*tasks)
        
        # 收集成功的结果
        clip_files = {clip_id: filepath for clip_id, filepath in results if filepath}
        
        self.logger.info(f"✅ 并行处理完成，成功生成 {len(clip_files)} 个音频切片")
        return clip_files
    
    def _map_clips_to_sentences(self, sentences: List[Sentence], clips_library: Dict, 
                              clip_files: Dict, sentence_to_clip_id_map: Dict) -> List[Sentence]:
        """将切片映射回句子对象"""
        updated_sentences = []
        
        for sentence in sentences:
            # 获取句子对应的clip_id
            clip_id = sentence_to_clip_id_map.get(sentence.sequence)
            
            if clip_id and clip_id in clip_files:
                # 更新句子的音频路径
                sentence.audio = clip_files[clip_id]
                
                # 获取clip信息
                clip_info = clips_library[clip_id]
                
                # 计算实际的音频时长（用于语音克隆参考）
                sentence.speech_duration = clip_info['total_duration_ms'] / 1000.0
                
                self.logger.debug(f"句子 {sentence.sequence} 映射到切片 {clip_id}")
            else:
                self.logger.warning(f"句子 {sentence.sequence} 未找到对应的音频切片")
            
            updated_sentences.append(sentence)
        
        return updated_sentences
    
    async def segment_audio_for_sentences(self, task_id: str, audio_file_path: str, 
                                        sentences: List[Sentence], path_manager=None) -> List[Sentence]:
        """
        为句子列表切分音频，基于说话人分组的智能切片
        
        Args:
            task_id: 任务ID
            audio_file_path: 音频文件路径
            sentences: 句子列表
            path_manager: 共享的路径管理器（可选）
            
        Returns:
            List[Sentence]: 更新了音频路径的句子列表
        """
        try:
            self.logger.info(f"[{task_id}] 开始为 {len(sentences)} 个句子进行智能音频切片")
            
            # 转换数据格式
            transcript_data = self._sentences_to_transcript_data(sentences)
            self.logger.info(f"[{task_id}] 转换了 {len(transcript_data)} 个转录片段")
            
            # 生成切片计划
            clips_library, sentence_to_clip_id_map = self._create_audio_clips(transcript_data)
            
            if not clips_library:
                self.logger.warning(f"[{task_id}] 未能生成有效的音频切片")
                return sentences
            
            self.logger.info(f"[{task_id}] 生成了 {len(clips_library)} 个音频切片")
            
            # 使用传入的path_manager，如果没有则创建新的（向后兼容）
            if path_manager is None:
                path_manager = PathManager(task_id)
                self.logger.warning(f"[{task_id}] AudioSegmenter: 未传入path_manager，创建新的临时目录")
            
            audio_clips_dir = path_manager.temp.audio_prompts_dir
            
            # 提取并保存音频切片
            try:
                clip_files = await self._extract_and_save_audio_clips(
                    audio_file_path, clips_library, str(audio_clips_dir)
                )
                
                if not clip_files:
                    error_msg = f"音频切片提取失败：未生成任何切片文件"
                    self.logger.error(f"[{task_id}] {error_msg}")
                    raise ValueError(error_msg)
                    
            except Exception as e:
                error_msg = f"音频切片提取异常: {e}"
                self.logger.error(f"[{task_id}] {error_msg}")
                raise RuntimeError(error_msg) from e
            
            # 映射切片到句子
            updated_sentences = self._map_clips_to_sentences(
                sentences, clips_library, clip_files, sentence_to_clip_id_map
            )
        
            successful_clips = len([s for s in updated_sentences if s.audio])
            self.logger.info(f"[{task_id}] 智能音频切片完成，成功处理 {successful_clips} 个句子")
            
            return updated_sentences
        except Exception as e:
            self.logger.error(f"[{task_id}] 音频切片处理失败: {e}")
            raise