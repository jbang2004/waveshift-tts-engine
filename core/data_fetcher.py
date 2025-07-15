import logging
import asyncio
import time
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import aiofiles

from config import get_config
from core.cloudflare.d1_client import D1Client, TranscriptionData
from core.cloudflare.r2_client import R2Client
from core.sentence_tools import Sentence
from utils.path_manager import PathManager
from core.vocal_separator import VocalSeparator

logger = logging.getLogger(__name__)

class DataFetcher:
    """数据获取服务 - 从Cloudflare D1和R2获取任务数据"""
    
    def __init__(self, d1_client: D1Client = None, r2_client: R2Client = None):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)
        
        # 使用依赖注入的客户端，如果没有则创建新的（向后兼容）
        if d1_client is not None:
            self.d1_client = d1_client
        else:
            self.d1_client = D1Client(
                account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
                api_token=self.config.CLOUDFLARE_API_TOKEN,
                database_id=self.config.CLOUDFLARE_D1_DATABASE_ID
            )
        
        if r2_client is not None:
            self.r2_client = r2_client
        else:
            self.r2_client = R2Client(
                account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
                access_key_id=self.config.CLOUDFLARE_R2_ACCESS_KEY_ID,
                secret_access_key=self.config.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
                bucket_name=self.config.CLOUDFLARE_R2_BUCKET_NAME
            )
        
        # 初始化音频分离器
        self.vocal_separator = VocalSeparator()
        
        self.logger.info("数据获取服务初始化完成")
    
    async def fetch_task_data(self, task_id: str, path_manager: PathManager = None) -> Dict:
        """
        并行化的任务数据获取 - 大幅提升数据获取性能
        
        优化策略：
        1. D1查询并行化（句子数据 + 媒体路径）
        2. R2下载并行化（音频 + 视频）
        3. 音频分离后台处理
        4. 详细性能监控
        
        Args:
            task_id: 任务ID
            path_manager: 路径管理器（如果没有则创建新的）
            
        Returns:
            Dict: 包含句子列表和音频文件路径的字典
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"[{task_id}] 开始并行获取任务数据")
            
            # 创建或使用传入的路径管理器
            if path_manager is None:
                path_manager = PathManager(task_id)
                self.logger.warning(f"[{task_id}] DataFetcher: 未传入path_manager，创建新的")
            
            # 阶段1: 并行执行D1查询
            d1_start_time = time.time()
            self.logger.info(f"[{task_id}] 开始并行D1查询")
            
            sentences_task = asyncio.create_task(
                self.d1_client.get_transcription_segments_from_worker(task_id),
                name=f"get_sentences_{task_id}"
            )
            media_paths_task = asyncio.create_task(
                self.d1_client.get_worker_media_paths(task_id),
                name=f"get_media_paths_{task_id}"
            )
            
            # 等待D1查询完成
            sentences, media_paths = await asyncio.gather(
                sentences_task, media_paths_task, return_exceptions=True
            )
            
            d1_duration = time.time() - d1_start_time
            self.logger.info(f"[{task_id}] D1并行查询完成，耗时: {d1_duration:.2f}s")
            
            # 检查D1查询结果
            if isinstance(sentences, Exception):
                self.logger.error(f"[{task_id}] 获取句子数据失败: {sentences}")
                return {"status": "error", "message": f"获取句子数据失败: {sentences}"}
            
            if isinstance(media_paths, Exception):
                self.logger.error(f"[{task_id}] 获取媒体路径失败: {media_paths}")
                return {"status": "error", "message": f"获取媒体路径失败: {media_paths}"}
                
            if not sentences:
                return {"status": "error", "message": "未找到转录数据"}
            
            # 阶段2: 并行下载和处理媒体文件
            download_start_time = time.time()
            self.logger.info(f"[{task_id}] 开始并行媒体文件下载")
            
            download_tasks = []
            
            # 创建音频下载任务
            if media_paths.get('audio_path'):
                audio_task = asyncio.create_task(
                    self._download_and_separate_audio(task_id, media_paths['audio_path'], path_manager),
                    name=f"download_audio_{task_id}"
                )
                download_tasks.append(('audio', audio_task))
            
            # 创建视频下载任务  
            if media_paths.get('video_path'):
                video_task = asyncio.create_task(
                    self._download_video_file(task_id, media_paths['video_path'], path_manager),
                    name=f"download_video_{task_id}"
                )
                download_tasks.append(('video', video_task))
            
            # 等待所有下载任务完成
            if download_tasks:
                download_results = await asyncio.gather(
                    *[task for _, task in download_tasks], return_exceptions=True
                )
                
                download_duration = time.time() - download_start_time
                self.logger.info(f"[{task_id}] 媒体文件并行下载完成，耗时: {download_duration:.2f}s")
                
                # 处理下载结果
                vocals_path, instrumental_path, video_file_path = None, None, None
                
                for i, (task_type, task) in enumerate(download_tasks):
                    result = download_results[i]
                    
                    if isinstance(result, Exception):
                        self.logger.error(f"[{task_id}] {task_type}下载失败: {result}")
                        continue
                    
                    if task_type == 'audio':
                        vocals_path, instrumental_path = result
                        if vocals_path:
                            self.logger.info(f"[{task_id}] 音频处理成功: vocals={vocals_path}")
                    elif task_type == 'video':
                        video_file_path = result
                        if video_file_path:
                            self.logger.info(f"[{task_id}] 视频下载成功: {video_file_path}")
            else:
                vocals_path, instrumental_path, video_file_path = None, None, None
            
            # 设置媒体路径
            if vocals_path and video_file_path:
                path_manager.set_media_paths(vocals_path, video_file_path)
            
            # 构建结果
            total_duration = time.time() - start_time
            result = {
                "status": "success",
                "sentences": sentences,
                "audio_file_path": vocals_path,  # 返回分离后的人声
                "video_file_path": video_file_path,
                "vocals_file_path": vocals_path,
                "instrumental_file_path": instrumental_path,
                "transcription_count": len(sentences),
                "path_manager": path_manager,
                "performance": {
                    "total_duration": total_duration,
                    "d1_duration": d1_duration,
                    "download_duration": download_duration if 'download_duration' in locals() else 0,
                    "efficiency_gain": f"{((d1_duration + (download_duration if 'download_duration' in locals() else 0)) / total_duration - 1) * 100:.1f}%"
                }
            }
            
            self.logger.info(
                f"[{task_id}] 并行数据获取成功: {len(sentences)} 个句子, "
                f"总耗时: {total_duration:.2f}s, D1: {d1_duration:.2f}s, "
                f"下载: {download_duration if 'download_duration' in locals() else 0:.2f}s"
            )
            
            return result
            
        except Exception as e:
            total_duration = time.time() - start_time
            self.logger.error(f"[{task_id}] 并行获取任务数据失败: {e}, 耗时: {total_duration:.2f}s")
            return {"status": "error", "message": f"并行获取任务数据失败: {e}"}
    
    async def _download_and_separate_audio(self, task_id: str, audio_path_r2: str, 
                                          path_manager: PathManager) -> Tuple[Optional[str], Optional[str]]:
        """
        并行优化的音频下载和分离处理
        
        优化策略：
        1. 异步下载音频文件
        2. 后台音频分离处理
        3. 智能降级策略
        
        Returns:
            Tuple[vocals_path, instrumental_path]: 分离后的人声和背景音路径
        """
        try:
            download_start_time = time.time()
            
            # 异步下载音频数据
            self.logger.info(f"[{task_id}] 开始下载音频文件: {audio_path_r2}")
            audio_data = await self.r2_client.download_audio(audio_path_r2)
            
            if not audio_data:
                self.logger.error(f"[{task_id}] 下载音频文件失败: {audio_path_r2}")
                return None, None
            
            download_duration = time.time() - download_start_time
            self.logger.info(f"[{task_id}] 音频下载完成，耗时: {download_duration:.2f}s, 大小: {len(audio_data)} bytes")
            
            # 异步保存原始音频到本地
            save_start_time = time.time()
            original_audio_path = path_manager.temp.media_dir / "original_audio.wav"
            
            async with aiofiles.open(original_audio_path, 'wb') as f:
                await f.write(audio_data)
            
            save_duration = time.time() - save_start_time
            self.logger.info(f"[{task_id}] 音频文件保存完成，耗时: {save_duration:.2f}s")
            
            # 音频分离处理（如果启用）
            if getattr(self.config, 'ENABLE_VOCAL_SEPARATION', True) and self.vocal_separator.is_available():
                self.logger.info(f"[{task_id}] 开始后台音频分离处理...")
                separation_start_time = time.time()
                
                # 使用异步音频分离
                separation_result = await self.vocal_separator.separate_complete_audio(
                    str(original_audio_path), path_manager
                )
                
                separation_duration = time.time() - separation_start_time
                
                if separation_result['success']:
                    self.logger.info(
                        f"[{task_id}] 音频分离成功，耗时: {separation_duration:.2f}s, "
                        f"人声: {separation_result['vocals_path']}, 背景: {separation_result['instrumental_path']}"
                    )
                    return separation_result['vocals_path'], separation_result['instrumental_path']
                else:
                    self.logger.warning(
                        f"[{task_id}] 音频分离失败: {separation_result['error']}，"
                        f"耗时: {separation_duration:.2f}s，降级使用原始音频"
                    )
            else:
                self.logger.info(f"[{task_id}] 音频分离功能未启用，使用原始音频")
            
            # 分离失败或未启用，使用原始音频作为"人声"，背景音为None
            return str(original_audio_path), None
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 并行音频下载和分离异常: {e}")
            return None, None
    
    async def _download_video_file(self, task_id: str, video_path_r2: str, 
                                   path_manager: PathManager) -> Optional[str]:
        """
        异步优化的视频文件下载
        
        Args:
            task_id: 任务ID
            video_path_r2: R2中的视频文件路径
            path_manager: 路径管理器
            
        Returns:
            Optional[str]: 本地视频文件路径
        """
        try:
            download_start_time = time.time()
            
            # 异步下载视频数据
            self.logger.info(f"[{task_id}] 开始下载视频文件: {video_path_r2}")
            video_data = await self.r2_client.download_video(video_path_r2)
            
            if not video_data:
                self.logger.error(f"[{task_id}] 下载视频文件失败: {video_path_r2}")
                return None
            
            download_duration = time.time() - download_start_time
            self.logger.info(f"[{task_id}] 视频下载完成，耗时: {download_duration:.2f}s, 大小: {len(video_data)} bytes")
            
            # 异步保存到本地
            save_start_time = time.time()
            video_filename = Path(video_path_r2).name
            local_video_path = path_manager.temp.media_dir / f"silent_{video_filename}"
            
            async with aiofiles.open(local_video_path, 'wb') as f:
                await f.write(video_data)
            
            save_duration = time.time() - save_start_time
            self.logger.info(f"[{task_id}] 视频文件保存完成，耗时: {save_duration:.2f}s, 路径: {local_video_path}")
            
            return str(local_video_path)
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 异步视频下载异常: {e}")
            return None
    
    
    
    async def get_sentences_only(self, task_id: str) -> List[Sentence]:
        """仅获取句子数据，不下载媒体文件"""
        try:
            transcriptions = await self.d1_client.get_transcriptions(task_id)
            if not transcriptions:
                self.logger.warning(f"[{task_id}] 未找到转录数据")
                return []
            
            sentences = await self.d1_client.to_sentence_objects(transcriptions, task_id)
            self.logger.info(f"[{task_id}] 获取到 {len(sentences)} 个句子")
            return sentences
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 获取句子数据失败: {e}")
            return []
    
    async def update_task_status(self, task_id: str, status: str, error_message: str = None, 
                               hls_playlist_url: str = None) -> bool:
        """更新任务状态"""
        return await self.d1_client.update_task_status(task_id, status, error_message, hls_playlist_url)
    
    async def close(self):
        """关闭客户端连接"""
        await self.d1_client.close()
        if self.vocal_separator:
            await self.vocal_separator.cleanup()