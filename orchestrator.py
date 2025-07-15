"""
优化后的任务编排器 - 使用简化的流水线模式
保持与原版完全兼容的API，只是内部实现更清晰
"""
import logging
import asyncio
import time
import gc
import torch
from typing import Dict, List, Tuple

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
            
            # 步骤1: 获取任务数据（包含音频分离）
            self.logger.info(f"[{task_id}] 步骤1: 获取任务数据和音频分离")
            task_data = await self._fetch_task_data(task_id, path_manager)
            
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
    
    async def _fetch_task_data(self, task_id: str, path_manager: PathManager) -> Dict:
        """获取任务数据 - 使用并行化优化版本"""
        try:
            data_fetcher = self.services.get('data_fetcher')
            if not data_fetcher:
                raise ValueError("data_fetcher服务未找到")
            
            # 使用并行化版本，大幅提升数据获取性能
            task_data = await data_fetcher.fetch_task_data_parallel(task_id, path_manager)
            
            if task_data.get("status") != "success":
                raise ValueError(f"获取任务数据失败: {task_data.get('message', 'Unknown error')}")
            
            # 验证必需数据
            sentences = task_data.get("sentences", [])
            audio_file_path = task_data.get("audio_file_path")
            video_file_path = task_data.get("video_file_path")
            vocals_file_path = task_data.get("vocals_file_path")
            instrumental_file_path = task_data.get("instrumental_file_path")
            
            if not sentences:
                raise ValueError("没有找到句子数据")
            if not audio_file_path:
                raise ValueError("没有找到音频文件")
            
            # 记录性能提升信息
            if task_data.get("performance"):
                perf = task_data["performance"]
                self.logger.info(
                    f"[{task_id}] 并行数据获取性能报告: "
                    f"总耗时: {perf.get('total_duration', 0):.2f}s, "
                    f"D1查询: {perf.get('d1_duration', 0):.2f}s, "
                    f"下载处理: {perf.get('download_duration', 0):.2f}s, "
                    f"效率提升: {perf.get('efficiency_gain', 'N/A')}"
                )
            
            # 如果有分离音频信息，记录到日志
            if vocals_file_path and instrumental_file_path:
                self.logger.info(f"[{task_id}] 音频分离成功: vocals={vocals_file_path}, instrumental={instrumental_file_path}")
            elif vocals_file_path:
                self.logger.info(f"[{task_id}] 使用原始音频作为人声: {vocals_file_path}")
            
            self.logger.info(f"[{task_id}] 并行获取到 {len(sentences)} 个句子和音频文件")
            return {
                "sentences": sentences,
                "audio_file_path": audio_file_path,  # 兼容性：返回人声路径
                "video_file_path": video_file_path,
                "vocals_file_path": vocals_file_path,
                "instrumental_file_path": instrumental_file_path
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
        """TTS流处理 - 使用生产者-消费者模式解耦TTS生成与后续处理"""
        try:
            # 获取服务实例
            tts = self.services.get('tts')
            duration_aligner = self.services.get('duration_aligner')
            timestamp_adjuster = self.services.get('timestamp_adjuster')
            media_mixer = self.services.get('media_mixer')
            hls_manager = self.services.get('hls_manager')
            
            if not all([tts, duration_aligner, timestamp_adjuster, media_mixer, hls_manager]):
                raise ValueError("TTS服务实例未完整找到")
            
            self.logger.info(f"[{task_id}] 启动解耦TTS流处理，句子数: {len(sentences)}")
            
            # 创建异步队列，设置最大容量避免内存堆积
            tts_queue = asyncio.Queue(maxsize=5)  # 最多缓存5个批次
            
            # 并发启动TTS生产者和处理消费者
            producer_task = asyncio.create_task(
                self._tts_producer(task_id, tts, sentences, path_manager, tts_queue),
                name=f"tts_producer_{task_id}"
            )
            
            consumer_task = asyncio.create_task(
                self._processing_consumer(
                    task_id, tts_queue, video_file_path, path_manager,
                    duration_aligner, timestamp_adjuster, media_mixer, hls_manager
                ),
                name=f"processing_consumer_{task_id}"
            )
            
            # 等待两个任务完成，添加并发监控
            self.logger.info(f"[{task_id}] TTS生产者和处理消费者并发启动")
            concurrent_start_time = time.time()
            
            # 使用gather监控并发执行
            producer_result, consumer_result = await asyncio.gather(
                producer_task, consumer_task, return_exceptions=True
            )
            
            concurrent_duration = time.time() - concurrent_start_time
            self.logger.info(f"[{task_id}] 并发处理完成，总耗时: {concurrent_duration:.2f}s")
            
            # 检查结果
            if isinstance(producer_result, Exception):
                self.logger.error(f"[{task_id}] TTS生产者异常: {producer_result}")
                return {"status": "error", "message": f"TTS生产失败: {producer_result}"}
            
            if isinstance(consumer_result, Exception):
                self.logger.error(f"[{task_id}] 处理消费者异常: {consumer_result}")
                return {"status": "error", "message": f"后续处理失败: {consumer_result}"}
            
            # 获取消费者结果
            success, processed_segment_paths, added_hls_segments = consumer_result
            
            if not success:
                return {"status": "error", "message": "批次处理失败"}
            
            self.logger.info(f"[{task_id}] 并发处理完成，共生成 {added_hls_segments} 个HLS段")
            
            # HLS最终化
            self.logger.info(f"[{task_id}] 开始HLS最终化处理")
            result = await hls_manager.finalize_merge(
                task_id=task_id,
                all_processed_segment_paths=processed_segment_paths,
                path_manager=path_manager
            )
            
            if result and result.get("status") == "success":
                self.logger.info(f"[{task_id}] HLS最终化成功，解耦流程完成")
                return result
            else:
                err_msg = result.get('message') if result else '无效的最终化结果'
                self.logger.error(f"[{task_id}] HLS最终化失败: {err_msg}")
                return {"status": "error", "message": err_msg}
                
        except Exception as e:
            self.logger.error(f"[{task_id}] 解耦TTS流处理异常: {e}")
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

    async def _tts_producer(self, task_id: str, tts_service, sentences: List, path_manager: PathManager, 
                           tts_queue: asyncio.Queue) -> None:
        """
        TTS生产者协程 - 专门负责TTS音频生成，将完成的批次放入队列
        
        Args:
            task_id: 任务ID
            tts_service: TTS服务实例
            sentences: 句子列表
            path_manager: 路径管理器
            tts_queue: 异步队列，用于传递TTS完成的批次
        """
        start_time = time.time()
        batch_counter = 0
        failed_batches = 0
        
        try:
            self.logger.info(f"[{task_id}] TTS生产者启动，待处理句子数: {len(sentences)}")
            
            # 使用TTS生成器逐批次生成音频
            async for tts_batch in tts_service.generate_audio_stream(sentences, path_manager):
                if not tts_batch:
                    continue
                
                batch_start_time = time.time()
                try:
                    # 验证TTS批次质量
                    valid_sentences = [s for s in tts_batch if s.generated_audio is not None]
                    if len(valid_sentences) != len(tts_batch):
                        self.logger.warning(
                            f"[{task_id}] TTS批次 {batch_counter} 质量检查: "
                            f"{len(valid_sentences)}/{len(tts_batch)} 个句子生成成功"
                        )
                    
                    self.logger.info(
                        f"[{task_id}] TTS生产者完成批次 {batch_counter}，"
                        f"包含 {len(tts_batch)} 个句子，队列大小: {tts_queue.qsize()}"
                    )
                    
                    # 将完成的TTS批次放入队列
                    await tts_queue.put({
                        'type': 'batch',
                        'data': tts_batch,
                        'batch_counter': batch_counter
                    })
                    
                    batch_duration = time.time() - batch_start_time
                    batch_counter += 1
                    
                    self.logger.info(
                        f"[{task_id}] TTS生产者批次 {batch_counter-1} 入队完成，"
                        f"耗时: {batch_duration:.2f}s"
                    )
                    
                except Exception as e:
                    failed_batches += 1
                    self.logger.error(f"[{task_id}] TTS生产者批次 {batch_counter} 处理失败: {e}")
                    continue
                
                # 清理内存
                self._clean_memory()
            
            # 发送完成信号
            await tts_queue.put({'type': 'complete'})
            
            # 计算性能指标
            total_duration = time.time() - start_time
            success_rate = (batch_counter / (batch_counter + failed_batches) * 100) if (batch_counter + failed_batches) > 0 else 0
            
            self.logger.info(
                f"[{task_id}] TTS生产者完成 - "
                f"成功批次: {batch_counter}, 失败批次: {failed_batches}, "
                f"成功率: {success_rate:.1f}%, 总耗时: {total_duration:.2f}s"
            )
            
        except Exception as e:
            self.logger.error(f"[{task_id}] TTS生产者严重异常: {e}", exc_info=True)
            # 发送错误信号
            try:
                await tts_queue.put({'type': 'error', 'message': str(e)})
            except Exception:
                self.logger.error(f"[{task_id}] 无法发送错误信号到队列")
            raise

    async def _processing_consumer(self, task_id: str, tts_queue: asyncio.Queue, video_file_path: str, 
                                 path_manager: PathManager, duration_aligner, timestamp_adjuster, 
                                 media_mixer, hls_manager) -> Tuple[bool, List[str], int]:
        """
        处理消费者协程 - 专门负责后续处理，从队列获取TTS批次进行处理
        
        Args:
            task_id: 任务ID
            tts_queue: 异步队列，从中获取TTS完成的批次
            video_file_path: 视频文件路径
            path_manager: 路径管理器
            duration_aligner: 时长对齐器
            timestamp_adjuster: 时间戳调整器
            media_mixer: 媒体混合器
            hls_manager: HLS管理器
            
        Returns:
            Tuple[bool, List[str], int]: (是否成功, 处理的段路径列表, HLS段数量)
        """
        start_time = time.time()
        processed_segment_paths = []
        added_hls_segments = 0
        current_audio_time_ms = 0.0
        failed_batches = 0
        
        try:
            self.logger.info(f"[{task_id}] 处理消费者启动")
            
            while True:
                try:
                    # 设置队列获取超时，避免无限等待
                    queue_item = await asyncio.wait_for(tts_queue.get(), timeout=60.0)
                    
                    # 检查任务项类型
                    if queue_item['type'] == 'complete':
                        self.logger.info(f"[{task_id}] 处理消费者收到完成信号")
                        break
                    elif queue_item['type'] == 'error':
                        error_msg = queue_item.get('message', '未知TTS错误')
                        self.logger.error(f"[{task_id}] 处理消费者收到错误信号: {error_msg}")
                        return False, processed_segment_paths, added_hls_segments
                    elif queue_item['type'] == 'batch':
                        # 处理TTS批次
                        tts_batch = queue_item['data']
                        batch_counter = queue_item['batch_counter']
                        batch_start_time = time.time()
                        
                        self.logger.info(
                            f"[{task_id}] 处理消费者开始处理批次 {batch_counter}，"
                            f"包含 {len(tts_batch)} 个句子，队列大小: {tts_queue.qsize()}"
                        )
                        
                        # 执行后续处理链
                        batch_result = await self._process_single_batch(
                            task_id, tts_batch, batch_counter, current_audio_time_ms,
                            video_file_path, path_manager, duration_aligner, timestamp_adjuster, 
                            media_mixer, hls_manager
                        )
                        
                        batch_duration = time.time() - batch_start_time
                        
                        if batch_result:
                            added_hls_segments += 1
                            processed_segment_paths.append(batch_result["segment_path"])
                            current_audio_time_ms = batch_result["new_time_ms"]
                            self.logger.info(
                                f"[{task_id}] 处理消费者成功完成批次 {batch_counter}，"
                                f"耗时: {batch_duration:.2f}s，总段数: {added_hls_segments}"
                            )
                        else:
                            failed_batches += 1
                            self.logger.warning(
                                f"[{task_id}] 处理消费者批次 {batch_counter} 处理失败，"
                                f"失败批次数: {failed_batches}"
                            )
                    
                    # 清理内存
                    self._clean_memory()
                    
                except asyncio.TimeoutError:
                    self.logger.warning(f"[{task_id}] 处理消费者等待队列超时，检查生产者状态")
                    # 继续等待
                    continue
                except Exception as e:
                    failed_batches += 1
                    self.logger.error(f"[{task_id}] 处理消费者处理批次异常: {e}", exc_info=True)
                    # 继续处理下一个批次
                    continue
            
            # 计算性能指标
            total_duration = time.time() - start_time
            success_rate = ((added_hls_segments) / (added_hls_segments + failed_batches) * 100) if (added_hls_segments + failed_batches) > 0 else 0
            
            self.logger.info(
                f"[{task_id}] 处理消费者完成 - "
                f"成功段数: {added_hls_segments}, 失败批次: {failed_batches}, "
                f"成功率: {success_rate:.1f}%, 总耗时: {total_duration:.2f}s"
            )
            
            return True, processed_segment_paths, added_hls_segments
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 处理消费者严重异常: {e}", exc_info=True)
            return False, processed_segment_paths, added_hls_segments