import logging
import asyncio
from typing import List, Dict, Optional, Tuple
from ray import serve
from pathlib import Path
import aiofiles

from config import get_config
from core.cloudflare.d1_client import D1Client, TranscriptionData
from core.cloudflare.r2_client import R2Client
from core.sentence_tools import Sentence
from utils.path_manager import PathManager

logger = logging.getLogger(__name__)

@serve.deployment(
    name="data_fetcher",
    ray_actor_options={"num_cpus": 1},
    logging_config={"log_level": "INFO"}
)
class DataFetcher:
    """数据获取服务 - 从Cloudflare D1和R2获取任务数据"""
    
    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)
        
        # 初始化Cloudflare客户端
        self.d1_client = D1Client(
            account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
            api_token=self.config.CLOUDFLARE_API_TOKEN,
            database_id=self.config.CLOUDFLARE_D1_DATABASE_ID
        )
        
        self.r2_client = R2Client(
            account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
            access_key_id=self.config.CLOUDFLARE_R2_ACCESS_KEY_ID,
            secret_access_key=self.config.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
            bucket_name=self.config.CLOUDFLARE_R2_BUCKET_NAME
        )
        
        self.logger.info("数据获取服务初始化完成")
    
    async def fetch_task_data(self, task_id: str) -> Dict:
        """
        获取任务数据 - 直接使用 Worker 数据结构
        
        Args:
            task_id: 任务ID
            
        Returns:
            Dict: 包含句子列表和音频文件路径的字典
        """
        try:
            self.logger.info(f"[{task_id}] 开始获取任务数据")
            
            # 直接获取 Worker 的句子数据
            sentences = await self.d1_client.get_transcription_segments_from_worker(task_id)
            
            if not sentences:
                return {"status": "error", "message": "未找到转录数据"}
            
            # 获取媒体文件路径
            media_paths = await self.d1_client.get_worker_media_paths(task_id)
            
            # 下载音频文件
            audio_file_path = None
            if media_paths.get('audio_path'):
                audio_file_path = await self._download_audio_file(
                    task_id, media_paths['audio_path']
                )
            
            # 下载视频文件
            video_file_path = None
            if media_paths.get('video_path'):
                video_file_path = await self._download_video_file(
                    task_id, media_paths['video_path']
                )
            
            result = {
                "status": "success",
                "sentences": sentences,
                "audio_file_path": audio_file_path,
                "video_file_path": video_file_path,
                "transcription_count": len(sentences)
            }
            
            self.logger.info(f"[{task_id}] 成功获取任务数据: {len(sentences)} 个句子")
            return result
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 获取任务数据失败: {e}")
            return {"status": "error", "message": f"获取任务数据失败: {e}"}
    
    async def _download_audio_file(self, task_id: str, audio_path_r2: str) -> Optional[str]:
        """下载音频文件到本地"""
        try:
            # 创建路径管理器
            path_manager = PathManager(task_id)
            
            # 下载音频数据
            audio_data = await self.r2_client.download_audio(audio_path_r2)
            if not audio_data:
                self.logger.error(f"[{task_id}] 下载音频文件失败: {audio_path_r2}")
                return None
            
            # 保存到本地
            local_audio_path = path_manager.temp.media_dir / "separated_vocals.wav"
            async with aiofiles.open(local_audio_path, 'wb') as f:
                await f.write(audio_data)
            
            self.logger.info(f"[{task_id}] 音频文件已下载: {local_audio_path}")
            return str(local_audio_path)
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 下载音频文件异常: {e}")
            return None
    
    async def _download_video_file(self, task_id: str, video_path_r2: str) -> Optional[str]:
        """下载视频文件到本地"""
        try:
            # 创建路径管理器
            path_manager = PathManager(task_id)
            
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