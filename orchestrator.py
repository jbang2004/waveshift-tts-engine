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
from ray import serve

from config import get_config
from core.cloudflare.d1_client import D1Client
from core.pipeline import TTSPipeline

logger = logging.getLogger(__name__)


@serve.deployment(
    name="MainOrchestratorDeployment",
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.5},
    logging_config={"log_level": "INFO"}
)
class MainOrchestrator:
    """优化后的主编排器 - 使用流水线模式简化代码"""
    
    # 服务配置表 - 从原版复制，保持一致
    SERVICE_CONFIGS = [
        ("data_fetcher", "data_fetcher", "DataFetcherApp", {}),
        ("audio_segmenter", "audio_segmenter", "AudioSegmenterApp", {}),
        ("tts", "my_index_tts", "TTSApp", {"stream": True}),
        ("duration_aligner", "duration_aligner", "DurationAlignerApp", {}),
        ("timestamp_adjuster", "timestamp_adjuster", "TimestampAdjusterApp", {}),
        ("media_mixer", "media_mixer", "MediaMixerApp", {}),
        ("hls_manager", "hls_manager", "HLSManagerApp", {})
    ]
    
    def __init__(self):
        self.logger = logger
        self.config = get_config()
        
        # 初始化D1客户端
        self.d1_client = D1Client(
            account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
            api_token=self.config.CLOUDFLARE_API_TOKEN,
            database_id=self.config.CLOUDFLARE_D1_DATABASE_ID
        )
        
        # 初始化所有服务句柄
        self.services = self._init_all_services()
        
        # 创建TTS流水线
        self.tts_pipeline = TTSPipeline.create(self.services, self.config)
        
        self.logger.info("MainOrchestrator初始化完成，所有服务句柄已就绪")
    
    def _init_all_services(self) -> Dict:
        """初始化所有服务句柄"""
        services = {}
        
        for attr_name, deployment_name, app_name, options in self.SERVICE_CONFIGS:
            try:
                handle = serve.get_deployment_handle(deployment_name, app_name=app_name)
                if options:
                    handle = handle.options(**options)
                services[attr_name] = handle
                self.logger.info(f"成功初始化服务: {attr_name}")
            except Exception as e:
                self.logger.error(f"初始化服务 {attr_name} 失败: {e}")
                raise RuntimeError(f"服务句柄初始化失败: {attr_name}")
        
        return services
    
    async def run_complete_tts_pipeline(self, task_id: str) -> Dict:
        """
        执行完整的TTS流水线 - 使用流水线模式简化
        
        Args:
            task_id: 任务ID
            
        Returns:
            Dict: 处理结果，与原版API兼容
        """
        start_time = time.time()
        self.logger.info(f"[{task_id}] 开始完整TTS流程")
        
        # 准备上下文
        context = {'task_id': task_id}
        path_manager = None
        
        try:
            # 更新任务状态
            await self._update_task_status(task_id, 'processing')
            
            # 执行流水线
            result = await self.tts_pipeline.execute(context)
            
            # 处理结果
            elapsed_time = time.time() - start_time
            
            if result["status"] == "success":
                await self._update_task_status(task_id, 'completed')
                self.logger.info(f"[{task_id}] 完整TTS流程成功完成，总耗时: {elapsed_time:.2f}s")
                
                # 返回TTS结果，保持与原版API兼容
                tts_result = context.get('tts_result', {})
                return tts_result if tts_result else {"status": "success", "message": "TTS流程完成"}
            else:
                await self._update_task_status(task_id, 'error', result.get('message'))
                self.logger.error(f"[{task_id}] 完整TTS流程失败，总耗时: {elapsed_time:.2f}s")
                return {
                    "status": "error", 
                    "message": result.get('message'),
                    "failed_step": result.get('failed_step')
                }
                
        except Exception as e:
            error_msg = f"TTS流程异常: {e}"
            self.logger.exception(f"[{task_id}] {error_msg}")
            await self._update_task_status(task_id, 'error', error_msg)
            return {"status": "error", "message": error_msg}
            
        finally:
            # 清理资源
            path_manager = context.get('path_manager')
            if path_manager:
                path_manager.cleanup()
            self._clean_memory()
    
    async def _update_task_status(self, task_id: str, status: str, error_message: str = None):
        """统一的任务状态更新 - 与原版保持一致"""
        try:
            asyncio.create_task(self.d1_client.update_task_status(task_id, status, error_message))
        except Exception as e:
            self.logger.warning(f"[{task_id}] 更新任务状态失败: {e}")
    
    def _clean_memory(self):
        """清理内存和GPU缓存 - 与原版保持一致"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
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