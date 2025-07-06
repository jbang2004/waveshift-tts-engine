import logging
import asyncio
import time
import gc
import torch
from typing import List, Dict
from pathlib import Path

from ray import serve
from ray.serve.handle import DeploymentHandle

from config import get_config
from utils.task_storage import TaskPaths
from core.cloudflare.d1_client import D1Client

logger = logging.getLogger(__name__)

@serve.deployment(
    name="MainOrchestratorDeployment",
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.5},
    logging_config={"log_level": "INFO"}
)
class MainOrchestrator:
    def __init__(self):
        self.logger = logger
        self.config = get_config()
        
        # 初始化D1客户端
        self.d1_client = D1Client(
            account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
            api_token=self.config.CLOUDFLARE_API_TOKEN,
            database_id=self.config.CLOUDFLARE_D1_DATABASE_ID
        )

        # 获取所有服务句柄
        self._init_service_handles()
        
        # 验证所有句柄是否正确初始化
        required_handles = [
            'data_fetcher_handle', 'audio_segmenter_handle', 'my_index_tts_handle',
            'duration_aligner_handle', 'timestamp_adjuster_handle', 
            'media_mixer_handle', 'hls_manager_handle'
        ]
        
        missing_handles = [handle for handle in required_handles if not hasattr(self, handle)]
        if missing_handles:
            self.logger.error(f"缺少以下句柄: {missing_handles}")
            raise RuntimeError(f"服务句柄初始化失败: {missing_handles}")
        
        self.logger.info("MainOrchestrator初始化完成，所有服务句柄已就绪")

    def _init_service_handles(self):
        """初始化所有服务句柄"""
        handle_configs = [
            ("data_fetcher", "data_fetcher", "DataFetcherApp"),
            ("audio_segmenter", "audio_segmenter", "AudioSegmenterApp"),
            ("my_index_tts", "my_index_tts", "TTSApp"),
            ("duration_aligner", "duration_aligner", "DurationAlignerApp"),
            ("timestamp_adjuster", "timestamp_adjuster", "TimestampAdjusterApp"),
            ("media_mixer", "media_mixer", "MediaMixerApp"),
            ("hls_manager", "hls_manager", "HLSManagerApp")
        ]
        
        for attr_name, deployment_name, app_name in handle_configs:
            try:
                handle = serve.get_deployment_handle(deployment_name, app_name=app_name)
                if attr_name == "my_index_tts":
                    handle = handle.options(stream=True)
                setattr(self, f"{attr_name}_handle", handle)
                self.logger.info(f"成功初始化 {attr_name}_handle")
            except Exception as e:
                self.logger.error(f"初始化 {attr_name}_handle 失败: {e}")
                raise

    async def _update_task_status(self, task_id: str, status: str, error_message: str = None):
        """统一的任务状态更新"""
        try:
            asyncio.create_task(self.d1_client.update_task_status(task_id, status, error_message))
        except Exception as e:
            self.logger.warning(f"[{task_id}] 更新任务状态失败: {e}")

    def _clean_memory(self):
        """清理内存和GPU缓存"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    async def run_complete_tts_pipeline(self, task_id: str):
        """
        执行完整的TTS流水线
        从D1获取转录数据，从R2下载音频，进行音频切分，TTS合成，最终生成HLS流
        """
        start_time = time.time()
        self.logger.info(f"[{task_id}] 开始完整TTS流程")
        
        try:
            await self._update_task_status(task_id, 'processing')
            
            # 第一步：获取任务数据
            self.logger.info(f"[{task_id}] 第1步：获取任务数据")
            task_data = await self.data_fetcher_handle.fetch_task_data.remote(task_id)
            
            if task_data["status"] != "success":
                error_msg = f"获取任务数据失败: {task_data.get('message', 'Unknown error')}"
                await self._update_task_status(task_id, 'error', error_msg)
                return {"status": "error", "message": error_msg}
            
            sentences = task_data["sentences"]
            audio_file_path = task_data["audio_file_path"]
            video_file_path = task_data["video_file_path"]
            
            if not sentences:
                error_msg = "没有找到句子数据"
                await self._update_task_status(task_id, 'error', error_msg)
                return {"status": "error", "message": error_msg}
            
            if not audio_file_path:
                error_msg = "没有找到音频文件"
                await self._update_task_status(task_id, 'error', error_msg)
                return {"status": "error", "message": error_msg}
            
            self.logger.info(f"[{task_id}] 获取到 {len(sentences)} 个句子和音频文件")
            
            # 第二步：音频切分
            self.logger.info(f"[{task_id}] 第2步：音频切分和语音克隆样本生成")
            segmented_sentences = await self.audio_segmenter_handle.segment_audio_for_sentences.remote(
                task_id, audio_file_path, sentences
            )
            
            if not segmented_sentences:
                error_msg = "音频切分失败"
                await self._update_task_status(task_id, 'error', error_msg)
                return {"status": "error", "message": error_msg}
            
            self.logger.info(f"[{task_id}] 音频切分完成，处理了 {len(segmented_sentences)} 个句子")
            
            # 第三步：初始化HLS管理器
            self.logger.info(f"[{task_id}] 第3步：初始化HLS管理器")
            task_paths = TaskPaths(self.config, task_id)
            await asyncio.to_thread(task_paths.create_directories)
            
            hls_init_response = await self.hls_manager_handle.create_manager.remote(task_id, task_paths)
            if not (isinstance(hls_init_response, dict) and hls_init_response.get("status") == "success"):
                error_msg = f"HLS管理器初始化失败: {hls_init_response}"
                await self._update_task_status(task_id, 'error', error_msg)
                return {"status": "error", "message": error_msg}
            
            # 第四步：TTS处理流
            self.logger.info(f"[{task_id}] 第4步：开始TTS合成和HLS生成")
            result = await self._process_tts_stream_with_segmented_audio(
                task_id, task_paths, segmented_sentences, video_file_path
            )
            
            elapsed_time = time.time() - start_time
            if result["status"] == "success":
                await self._update_task_status(task_id, 'completed')
                self.logger.info(f"[{task_id}] 完整TTS流程成功完成，总耗时: {elapsed_time:.2f}s")
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
            self._clean_memory()

    async def _process_tts_stream_with_segmented_audio(self, task_id: str, task_paths: TaskPaths, 
                                                     sentences: List, video_file_path: str):
        """处理TTS流并生成HLS段（使用已切分的音频）"""
        added_hls_segments = 0
        current_audio_time_ms = 0.0
        processed_segment_paths = []
        batch_counter = 0

        try:
            # 使用新的TTS生成方法，传入已切分的句子
            async for tts_sentence_batch in self.my_index_tts_handle.batch_generate.options(stream=True).remote(
                sentences, batch_size=self.config.TTS_BATCH_SIZE
            ):
                if not tts_sentence_batch:
                    continue

                self.logger.info(f"[{task_id}] 处理TTS批次 {batch_counter}，包含 {len(tts_sentence_batch)} 个句子")

                # 时长对齐
                aligned_batch = await self.duration_aligner_handle.remote(tts_sentence_batch, max_speed=1.2)
                if not aligned_batch:
                    self.logger.warning(f"[{task_id}] 批次 {batch_counter} 时长对齐失败，跳过")
                    continue

                # 时间戳调整
                adjusted_batch = await self.timestamp_adjuster_handle.remote(
                    aligned_batch, self.config.TARGET_SR, current_audio_time_ms
                )
                if not adjusted_batch:
                    self.logger.warning(f"[{task_id}] 批次 {batch_counter} 时间戳调整失败，跳过")
                    continue

                # 更新当前音频时间
                last_sentence = adjusted_batch[-1]
                current_audio_time_ms = last_sentence.adjusted_start + last_sentence.adjusted_duration

                # 媒体混合（需要传入视频文件路径）
                output_segment_path = await self.media_mixer_handle.mix_media.remote(
                    sentences_batch=adjusted_batch,
                    task_paths=task_paths,
                    batch_counter=batch_counter,
                    task_id=task_id,
                    video_file_path=video_file_path  # 新增参数
                )
                
                if not output_segment_path:
                    self.logger.warning(f"[{task_id}] 批次 {batch_counter} 媒体混合失败，跳过")
                    continue

                # 添加HLS段
                hls_add_result = await self.hls_manager_handle.add_segment.remote(
                    task_id, output_segment_path, batch_counter + 1
                )
                
                if hls_add_result and hls_add_result.get("status") == "success":
                    added_hls_segments += 1
                    processed_segment_paths.append(output_segment_path)
                    batch_counter += 1
                    self.logger.info(f"[{task_id}] 成功添加HLS段 {batch_counter}")
                else:
                    err_msg = hls_add_result.get('message') if hls_add_result else '未知HLS添加错误'
                    self.logger.error(f"[{task_id}] 添加HLS段失败: {err_msg}")
                
                self._clean_memory()

            # 最终化HLS并合并
            self.logger.info(f"[{task_id}] 开始HLS最终化处理")
            result = await self.hls_manager_handle.finalize_merge.remote(
                task_id=task_id,
                all_processed_segment_paths=processed_segment_paths,
                task_paths=task_paths
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
            return {"status": "error", "message": f"TTS流处理失败: {e}")

    async def get_task_status(self, task_id: str) -> Dict:
        """获取任务状态"""
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