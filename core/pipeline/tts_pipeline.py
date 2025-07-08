"""
TTS流水线定义 - 封装现有服务为步骤
"""
import logging
from typing import Dict, Any, Tuple, List
from .base import Step, Pipeline
from utils.path_manager import PathManager

logger = logging.getLogger(__name__)


class FetchDataStep(Step):
    """获取任务数据步骤"""
    
    def __init__(self, data_fetcher):
        super().__init__("获取任务数据")
        self.data_fetcher = data_fetcher
    
    async def execute(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        task_id = context['task_id']
        
        try:
            task_data = await self.data_fetcher.fetch_task_data(task_id)
            
            if task_data.get("status") != "success":
                return False, f"获取任务数据失败: {task_data.get('message', 'Unknown error')}"
            
            # 验证必需数据
            sentences = task_data.get("sentences", [])
            audio_file_path = task_data.get("audio_file_path")
            video_file_path = task_data.get("video_file_path")
            
            if not sentences:
                return False, "没有找到句子数据"
            if not audio_file_path:
                return False, "没有找到音频文件"
            
            # 保存到上下文
            context.update({
                "sentences": sentences,
                "audio_file_path": audio_file_path,
                "video_file_path": video_file_path
            })
            
            self.logger.info(f"[{task_id}] 获取到 {len(sentences)} 个句子和音频文件")
            return True, None
            
        except Exception as e:
            return False, f"获取任务数据异常: {e}"


class SegmentAudioStep(Step):
    """音频切分步骤"""
    
    def __init__(self, audio_segmenter):
        super().__init__("音频切分")
        self.audio_segmenter = audio_segmenter
    
    async def execute(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        task_id = context['task_id']
        sentences = context.get('sentences')
        audio_file_path = context.get('audio_file_path')
        
        if not sentences or not audio_file_path:
            return False, "缺少必需的句子数据或音频文件路径"
        
        try:
            segmented_sentences = await self.audio_segmenter.segment_audio_for_sentences(
                task_id, audio_file_path, sentences
            )
            
            if not segmented_sentences:
                return False, "音频切分失败"
            
            context['segmented_sentences'] = segmented_sentences
            self.logger.info(f"[{task_id}] 音频切分完成，处理了 {len(segmented_sentences)} 个句子")
            return True, None
            
        except Exception as e:
            return False, f"音频切分异常: {e}"


class InitHLSStep(Step):
    """初始化HLS管理器步骤"""
    
    def __init__(self, hls_manager):
        super().__init__("初始化HLS管理器")
        self.hls_manager = hls_manager
    
    async def execute(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        task_id = context['task_id']
        
        try:
            # 创建路径管理器
            path_manager = PathManager(task_id)
            context['path_manager'] = path_manager
            
            # 初始化HLS管理器
            response = await self.hls_manager.create_manager(task_id, path_manager)
            
            if not (isinstance(response, dict) and response.get("status") == "success"):
                return False, f"HLS管理器初始化失败: {response}"
            
            return True, None
            
        except Exception as e:
            return False, f"初始化HLS管理器异常: {e}"


class TTSStreamProcessingStep(Step):
    """TTS流处理步骤 - 包含完整的批处理逻辑"""
    
    def __init__(self, services: Dict[str, Any], config):
        super().__init__("TTS流处理")
        self.tts = services['tts']
        self.duration_aligner = services['duration_aligner']
        self.timestamp_adjuster = services['timestamp_adjuster']
        self.media_mixer = services['media_mixer']
        self.hls_manager = services['hls_manager']
        self.config = config
    
    async def execute(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        task_id = context['task_id']
        segmented_sentences = context.get('segmented_sentences')
        video_file_path = context.get('video_file_path')
        path_manager = context.get('path_manager')
        
        if not segmented_sentences:
            return False, "缺少切分后的句子数据"
        
        try:
            result = await self._process_tts_stream(
                task_id, segmented_sentences, video_file_path, path_manager
            )
            
            if result.get("status") == "success":
                context['tts_result'] = result
                return True, None
            else:
                return False, result.get("message", "TTS流处理失败")
                
        except Exception as e:
            return False, f"TTS流处理异常: {e}"
    
    async def _process_tts_stream(self, task_id: str, sentences: List, 
                                video_file_path: str, path_manager: PathManager) -> Dict:
        """TTS流处理核心逻辑 - 复用原有逻辑"""
        added_hls_segments = 0
        current_audio_time_ms = 0.0
        processed_segment_paths = []
        batch_counter = 0
        
        try:
            # TTS批处理流
            async for tts_batch in self.tts.batch_generate(
                sentences, batch_size=self.config.TTS_BATCH_SIZE
            ):
                if not tts_batch:
                    continue
                    
                self.logger.info(f"[{task_id}] 处理TTS批次 {batch_counter}，包含 {len(tts_batch)} 个句子")
                
                # 处理单个批次
                batch_result = await self._process_single_batch(
                    task_id, tts_batch, batch_counter, current_audio_time_ms,
                    video_file_path, path_manager
                )
                
                if batch_result:
                    added_hls_segments += 1
                    processed_segment_paths.append(batch_result["segment_path"])
                    current_audio_time_ms = batch_result["new_time_ms"]
                    batch_counter += 1
                    self.logger.info(f"[{task_id}] 成功添加HLS段 {batch_counter}")
                
                # 清理内存
                self._clean_memory()
            
            # HLS最终化
            self.logger.info(f"[{task_id}] 开始HLS最终化处理")
            result = await self.hls_manager.finalize_merge(
                task_id=task_id,
                all_processed_segment_paths=processed_segment_paths,
                path_manager=path_manager
            )
            
            if result and result.get("status") == "success":
                self.logger.info(f"[{task_id}] HLS最终化成功，生成 {added_hls_segments} 个段")
                return result
            else:
                err_msg = result.get('message') if result else '无效的最终化结果'
                self.logger.error(f"[{task_id}] HLS最终化失败: {err_msg}")
                return {"status": "error", "message": err_msg}
                
        except Exception as e:
            self.logger.exception(f"[{task_id}] TTS流处理异常: {e}")
            return {"status": "error", "message": f"TTS流处理失败: {e}"}
    
    async def _process_single_batch(self, task_id: str, batch: List, batch_counter: int,
                                  current_time_ms: float, video_file_path: str, 
                                  path_manager: PathManager) -> Dict:
        """处理单个TTS批次"""
        try:
            # 时长对齐
            aligned_batch = await self.duration_aligner(batch, max_speed=1.2)
            if not aligned_batch:
                self.logger.warning(f"[{task_id}] 批次 {batch_counter} 时长对齐失败")
                return None
                
            # 时间戳调整
            adjusted_batch = await self.timestamp_adjuster(
                aligned_batch, self.config.TARGET_SR, current_time_ms
            )
            if not adjusted_batch:
                self.logger.warning(f"[{task_id}] 批次 {batch_counter} 时间戳调整失败")
                return None
                
            # 计算新的时间位置
            last_sentence = adjusted_batch[-1]
            new_time_ms = last_sentence.adjusted_start + last_sentence.adjusted_duration
            
            # 媒体混合
            segment_path = await self.media_mixer.mix_media(
                sentences_batch=adjusted_batch,
                path_manager=path_manager,
                batch_counter=batch_counter,
                task_id=task_id,
                video_file_path=video_file_path
            )
            
            if not segment_path:
                self.logger.warning(f"[{task_id}] 批次 {batch_counter} 媒体混合失败")
                return None
                
            # 添加HLS段
            hls_result = await self.hls_manager.add_segment(
                task_id, segment_path, batch_counter + 1
            )
            
            if hls_result and hls_result.get("status") == "success":
                return {"segment_path": segment_path, "new_time_ms": new_time_ms}
            else:
                self.logger.error(f"[{task_id}] 添加HLS段失败: {hls_result.get('message')}")
                return None
                
        except Exception as e:
            self.logger.error(f"[{task_id}] 处理批次 {batch_counter} 异常: {e}")
            return None
    
    def _clean_memory(self):
        """清理内存和GPU缓存"""
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


class TTSPipeline:
    """TTS流水线工厂类"""
    
    @staticmethod
    def create(services: Dict[str, Any], config) -> Pipeline:
        """创建TTS流水线"""
        steps = [
            FetchDataStep(services['data_fetcher']),
            SegmentAudioStep(services['audio_segmenter']),
            InitHLSStep(services['hls_manager']),
            TTSStreamProcessingStep({
                'tts': services['tts'],
                'duration_aligner': services['duration_aligner'],
                'timestamp_adjuster': services['timestamp_adjuster'],
                'media_mixer': services['media_mixer'],
                'hls_manager': services['hls_manager']
            }, config)
        ]
        
        return Pipeline("TTS处理流水线", steps)