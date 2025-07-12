"""
优化后的任务编排器 - 使用简化的流水线模式
保持与原版完全兼容的API，只是内部实现更清晰
"""
import logging
import asyncio
import time
import gc
import torch
from typing import Dict

from config import get_config
from core.cloudflare.d1_client import D1Client
from utils.path_manager import PathManager
from utils.async_utils import BackgroundTaskManager, async_retry

logger = logging.getLogger(__name__)


class MainOrchestrator:
    """优化后的主编排器 - 使用流水线模式简化代码"""
    
    def __init__(self, services: Dict = None):
        self.logger = logger
        self.config = get_config()
        
        # 使用传入的服务实例
        self.services = services or {}
        
        # 从服务管理器获取D1客户端
        self.d1_client = self.services.get('d1_client')
        if not self.d1_client:
            # 如果services中没有d1_client，创建一个（向后兼容）
            self.d1_client = D1Client(
                account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
                api_token=self.config.CLOUDFLARE_API_TOKEN,
                database_id=self.config.CLOUDFLARE_D1_DATABASE_ID
            )
        
        # 直接使用服务实例（移除流水线框架）
        
        # 创建后台任务管理器
        self.task_manager = BackgroundTaskManager()
        
        self.logger.info("MainOrchestrator初始化完成，所有服务实例已就绪")
    
    @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def _update_task_status(self, task_id: str, status: str, error_message: str = None):
        """
        安全的任务状态更新方法 - 带重试机制
        
        Args:
            task_id: 任务ID
            status: 任务状态
            error_message: 错误消息（可选）
        """
        try:
            result = await self.d1_client.update_task_status(task_id, status, error_message)
            if result:
                self.logger.info(f"任务状态更新成功 [任务ID: {task_id}] [状态: {status}]")
            else:
                self.logger.warning(f"任务状态更新失败 [任务ID: {task_id}] [状态: {status}]")
            return result
        except Exception as e:
            self.logger.error(f"任务状态更新异常 [任务ID: {task_id}] [状态: {status}]: {e}")
            raise
    
    def _create_status_update_task(self, task_id: str, status: str, error_message: str = None):
        """
        创建状态更新后台任务
        
        Args:
            task_id: 任务ID
            status: 任务状态
            error_message: 错误消息（可选）
        """
        def error_handler(e: Exception):
            self.logger.error(f"后台状态更新任务失败 [任务ID: {task_id}] [状态: {status}]: {e}")
        
        self.task_manager.create_task(
            self._update_task_status(task_id, status, error_message),
            name=f"status_update_{task_id}_{status}",
            error_handler=error_handler
        )
    
    async def run_complete_tts_pipeline(self, task_id: str) -> Dict:
        """
        执行完整的TTS流水线 - 直接集成所有步骤，移除流水线框架
        
        Args:
            task_id: 任务ID
            
        Returns:
            Dict: 处理结果，与原版API兼容
        """
        start_time = time.time()
        self.logger.info(f"[{task_id}] 开始完整TTS流程")
        
        # 在任务开始时创建统一的PathManager
        path_manager = PathManager(task_id)
        self.logger.info(f"[{task_id}] 创建统一的PathManager: {path_manager.temp.temp_dir}")
        
        try:
            # 更新任务状态
            await self._update_task_status(task_id, 'processing')
            
            # 步骤1: 获取任务数据
            self.logger.info(f"[{task_id}] 步骤1: 获取任务数据")
            task_data = await self._fetch_task_data(task_id)
            
            # 步骤2: 音频切分 - 传递path_manager
            self.logger.info(f"[{task_id}] 步骤2: 音频切分")
            segmented_sentences = await self._segment_audio(
                task_id, task_data['audio_file_path'], task_data['sentences'], path_manager
            )
            
            # 步骤3: 初始化HLS管理器 - 使用已创建的path_manager
            self.logger.info(f"[{task_id}] 步骤3: 初始化HLS管理器")
            await self._init_hls_manager(
                task_id, task_data['audio_file_path'], task_data['video_file_path'], path_manager
            )
            
            # 步骤4: TTS流处理
            self.logger.info(f"[{task_id}] 步骤4: TTS流处理")
            result = await self._process_tts_stream(
                task_id, segmented_sentences, task_data['video_file_path'], path_manager
            )
            
            # 处理结果
            elapsed_time = time.time() - start_time
            
            if result.get("status") == "success":
                await self._update_task_status(task_id, 'completed')
                self.logger.info(f"[{task_id}] 完整TTS流程成功完成，总耗时: {elapsed_time:.2f}s")
                return result
            else:
                await self._update_task_status(task_id, 'error', result.get('message'))
                self.logger.error(f"[{task_id}] 完整TTS流程失败，总耗时: {elapsed_time:.2f}s")
                return result
                
        except Exception as e:
            error_msg = f"TTS流程异常: {e}"
            self.logger.exception(f"[{task_id}] {error_msg}")
            await self._update_task_status(task_id, 'error', error_msg)
            return {"status": "error", "message": error_msg}
            
        finally:
            # 清理资源
            if path_manager:
                path_manager.cleanup()
            self._clean_memory()
    
    async def _update_task_status_legacy(self, task_id: str, status: str, error_message: str = None):
        """统一的任务状态更新 - 旧版本，使用新的安全方法"""
        self._create_status_update_task(task_id, status, error_message)
    
    def _clean_memory(self):
        """清理内存和GPU缓存 - 与原版保持一致"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
    async def cleanup(self):
        """清理编排器资源"""
        try:
            if self.task_manager:
                self.logger.info("正在清理后台任务...")
                await self.task_manager.close()
                self.logger.info("后台任务管理器已关闭")
        except Exception as e:
            self.logger.error(f"编排器清理失败: {e}")
    
    async def get_task_status(self, task_id: str) -> Dict:
        """获取任务状态 - 与原版保持完全一致"""
        try:
            task_info = await self.d1_client.get_task_info(task_id)
            if not task_info:
                return {"status": "error", "message": "任务不存在"}
            
            return {
                "status": "success",
                "task_id": task_id,
                "task_status": task_info.get('status'),
                "hls_playlist_url": task_info.get('hls_playlist_url'),
                "error_message": task_info.get('error_message')
            }
        except Exception as e:
            self.logger.error(f"[{task_id}] 获取任务状态失败: {e}")
            return {"status": "error", "message": f"获取任务状态失败: {e}"}
    
    async def _fetch_task_data(self, task_id: str) -> Dict:
        """获取任务数据 - 替代FetchDataStep"""
        try:
            data_fetcher = self.services.get('data_fetcher')
            if not data_fetcher:
                raise ValueError("data_fetcher服务未找到")
            
            task_data = await data_fetcher.fetch_task_data(task_id)
            
            if task_data.get("status") != "success":
                raise ValueError(f"获取任务数据失败: {task_data.get('message', 'Unknown error')}")
            
            # 验证必需数据
            sentences = task_data.get("sentences", [])
            audio_file_path = task_data.get("audio_file_path")
            video_file_path = task_data.get("video_file_path")
            
            if not sentences:
                raise ValueError("没有找到句子数据")
            if not audio_file_path:
                raise ValueError("没有找到音频文件")
            
            self.logger.info(f"[{task_id}] 获取到 {len(sentences)} 个句子和音频文件")
            return {
                "sentences": sentences,
                "audio_file_path": audio_file_path,
                "video_file_path": video_file_path
            }
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 获取任务数据异常: {e}")
            raise
    
    async def _segment_audio(self, task_id: str, audio_file_path: str, sentences: list, path_manager: PathManager) -> list:
        """音频切分 - 替代SegmentAudioStep
        
        Args:
            task_id: 任务ID
            audio_file_path: 音频文件路径
            sentences: 句子列表
            path_manager: 共享的路径管理器
        """
        try:
            audio_segmenter = self.services.get('audio_segmenter')
            if not audio_segmenter:
                raise ValueError("audio_segmenter服务未找到")
            
            segmented_sentences = await audio_segmenter.segment_audio_for_sentences(
                task_id, audio_file_path, sentences, path_manager
            )
            
            if not segmented_sentences:
                raise ValueError("音频切分失败")
            
            self.logger.info(f"[{task_id}] 音频切分完成，处理了 {len(segmented_sentences)} 个句子")
            return segmented_sentences
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 音频切分异常: {e}")
            raise
    
    async def _init_hls_manager(self, task_id: str, audio_file_path: str, video_file_path: str, path_manager: PathManager) -> None:
        """初始化HLS管理器 - 替代InitHLSStep
        
        Args:
            task_id: 任务ID
            audio_file_path: 音频文件路径
            video_file_path: 视频文件路径
            path_manager: 共享的路径管理器
        """
        try:
            hls_manager = self.services.get('hls_manager')
            if not hls_manager:
                raise ValueError("hls_manager服务未找到")
            
            # 设置媒体文件路径
            if audio_file_path and video_file_path:
                path_manager.set_media_paths(audio_file_path, video_file_path)
            
            # 初始化HLS管理器
            response = await hls_manager.create_manager(task_id, path_manager)
            
            if not (isinstance(response, dict) and response.get("status") == "success"):
                raise ValueError(f"HLS管理器初始化失败: {response}")
            
            self.logger.info(f"[{task_id}] HLS管理器初始化完成")
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 初始化HLS管理器异常: {e}")
            raise
    
    async def _process_tts_stream(self, task_id: str, sentences: list, video_file_path: str, path_manager: PathManager) -> Dict:
        """TTS流处理 - 替代TTSStreamProcessingStep"""
        try:
            # 获取服务实例
            tts = self.services.get('tts')
            duration_aligner = self.services.get('duration_aligner')
            timestamp_adjuster = self.services.get('timestamp_adjuster')
            media_mixer = self.services.get('media_mixer')
            hls_manager = self.services.get('hls_manager')
            
            if not all([tts, duration_aligner, timestamp_adjuster, media_mixer, hls_manager]):
                raise ValueError("TTS服务实例未完整找到")
            
            added_hls_segments = 0
            current_audio_time_ms = 0.0
            processed_segment_paths = []
            batch_counter = 0
            
            # TTS批处理流 - 传递path_manager以确保使用统一的临时目录
            async for tts_batch in tts.generate_audio_stream(sentences, path_manager):
                if not tts_batch:
                    continue
                    
                self.logger.info(f"[{task_id}] 处理TTS批次 {batch_counter}，包含 {len(tts_batch)} 个句子")
                
                # 处理单个批次
                batch_result = await self._process_single_batch(
                    task_id, tts_batch, batch_counter, current_audio_time_ms,
                    video_file_path, path_manager, duration_aligner, timestamp_adjuster, media_mixer, hls_manager
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
            result = await hls_manager.finalize_merge(
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
            self.logger.error(f"[{task_id}] TTS流处理异常: {e}")
            return {"status": "error", "message": f"TTS流处理失败: {e}"}
    
    async def _process_single_batch(self, task_id: str, batch: list, batch_counter: int,
                                  current_time_ms: float, video_file_path: str, path_manager: PathManager,
                                  duration_aligner, timestamp_adjuster, media_mixer, hls_manager) -> Dict:
        """处理单个TTS批次"""
        try:
            # 时长对齐 - 传递path_manager
            aligned_batch = await duration_aligner(batch, max_speed=1.2, path_manager=path_manager)
            if not aligned_batch:
                self.logger.warning(f"[{task_id}] 批次 {batch_counter} 时长对齐失败")
                return None
                
            # 时间戳调整
            adjusted_batch = await timestamp_adjuster(
                aligned_batch, self.config.TARGET_SR, current_time_ms
            )
            if not adjusted_batch:
                self.logger.warning(f"[{task_id}] 批次 {batch_counter} 时间戳调整失败")
                return None
                
            # 计算新的时间位置
            last_sentence = adjusted_batch[-1]
            new_time_ms = last_sentence.adjusted_start + last_sentence.adjusted_duration
            
            # 媒体混合
            segment_path = await media_mixer.mix_media(
                sentences_batch=adjusted_batch,
                path_manager=path_manager,
                batch_counter=batch_counter,
                task_id=task_id
            )
            
            if not segment_path:
                self.logger.warning(f"[{task_id}] 批次 {batch_counter} 媒体混合失败")
                return None
                
            # 添加HLS段
            hls_result = await hls_manager.add_segment(
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