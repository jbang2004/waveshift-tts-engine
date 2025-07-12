import logging
import asyncio
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
        获取任务数据并集成音频分离 - 直接使用 Worker 数据结构
        
        Args:
            task_id: 任务ID
            path_manager: 路径管理器（如果没有则创建新的）
            
        Returns:
            Dict: 包含句子列表和音频文件路径的字典
        """
        try:
            self.logger.info(f"[{task_id}] 开始获取任务数据")
            
            # 创建或使用传入的路径管理器
            if path_manager is None:
                path_manager = PathManager(task_id)
                self.logger.warning(f"[{task_id}] DataFetcher: 未传入path_manager，创建新的")
            
            # 直接获取 Worker 的句子数据
            sentences = await self.d1_client.get_transcription_segments_from_worker(task_id)
            
            if not sentences:
                return {"status": "error", "message": "未找到转录数据"}
            
            # 获取媒体文件路径
            media_paths = await self.d1_client.get_worker_media_paths(task_id)
            
            # 下载并分离音频文件
            vocals_path, instrumental_path = None, None
            if media_paths.get('audio_path'):
                vocals_path, instrumental_path = await self._download_and_separate_audio(
                    task_id, media_paths['audio_path'], path_manager
                )
            
            # 下载视频文件
            video_file_path = None
            if media_paths.get('video_path'):
                video_file_path = await self._download_video_file(
                    task_id, media_paths['video_path'], path_manager
                )
            
            # 设置媒体路径
            if vocals_path and video_file_path:
                path_manager.set_media_paths(vocals_path, video_file_path)
            
            result = {
                "status": "success",
                "sentences": sentences,
                "audio_file_path": vocals_path,  # 返回分离后的人声
                "video_file_path": video_file_path,
                "vocals_file_path": vocals_path,
                "instrumental_file_path": instrumental_path,
                "transcription_count": len(sentences),
                "path_manager": path_manager  # 返回路径管理器
            }
            
            self.logger.info(f"[{task_id}] 成功获取任务数据: {len(sentences)} 个句子")
            return result
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 获取任务数据失败: {e}")
            return {"status": "error", "message": f"获取任务数据失败: {e}"}
    
    async def _download_and_separate_audio(self, task_id: str, audio_path_r2: str, path_manager: PathManager):
        """下载音频文件并进行人声分离
        
        Returns:
            Tuple[vocals_path, instrumental_path]: 分离后的人声和背景音路径
        """
        try:
            # 下载音频数据
            audio_data = await self.r2_client.download_audio(audio_path_r2)
            if not audio_data:
                self.logger.error(f"[{task_id}] 下载音频文件失败: {audio_path_r2}")
                return None, None
            
            # 保存原始音频到本地
            original_audio_path = path_manager.temp.media_dir / "original_audio.wav"
            async with aiofiles.open(original_audio_path, 'wb') as f:
                await f.write(audio_data)
            
            self.logger.info(f"[{task_id}] 原始音频文件已下载: {original_audio_path}")
            
            # 尝试音频分离
            if getattr(self.config, 'ENABLE_VOCAL_SEPARATION', True) and self.vocal_separator.is_available():
                self.logger.info(f"[{task_id}] 开始音频分离...")
                
                separation_result = await self.vocal_separator.separate_complete_audio(
                    str(original_audio_path), path_manager
                )
                
                if separation_result['success']:
                    self.logger.info(f"[{task_id}] 音频分离成功")
                    return separation_result['vocals_path'], separation_result['instrumental_path']
                else:
                    self.logger.warning(f"[{task_id}] 音频分离失败: {separation_result['error']}，使用原始音频")
            else:
                self.logger.info(f"[{task_id}] 音频分离功能未启用，使用原始音频")
            
            # 分离失败或未启用，使用原始音频作为"人声"，背景音为None
            return str(original_audio_path), None
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 下载和分离音频异常: {e}")
            return None, None
    
    async def _download_video_file(self, task_id: str, video_path_r2: str, path_manager: PathManager) -> Optional[str]:
        """下载视频文件到本地"""
        try:
            # 下载视频数据
            video_data = await self.r2_client.download_video(video_path_r2)
            if not video_data:
                self.logger.error(f"[{task_id}] 下载视频文件失败: {video_path_r2}")
                return None
            
            # 保存到本地
            video_filename = Path(video_path_r2).name
            local_video_path = path_manager.temp.media_dir / f"silent_{video_filename}"
            async with aiofiles.open(local_video_path, 'wb') as f:
                await f.write(video_data)
            
            self.logger.info(f"[{task_id}] 视频文件已下载: {local_video_path}")
            return str(local_video_path)
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 下载视频文件异常: {e}")
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