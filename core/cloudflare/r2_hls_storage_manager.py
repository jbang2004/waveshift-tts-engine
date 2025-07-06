import logging
import asyncio
import aiofiles
from pathlib import Path
from typing import Dict, List, Optional
from core.cloudflare.r2_client import R2Client
from config import Config

logger = logging.getLogger(__name__)

class R2HLSStorageManager:
    """R2 HLS存储管理器 - 负责将HLS文件上传到Cloudflare R2"""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.logger = logging.getLogger(__name__)
        
        # 初始化R2客户端
        self.r2_client = R2Client(
            account_id=self.config.CLOUDFLARE_ACCOUNT_ID,
            access_key_id=self.config.CLOUDFLARE_R2_ACCESS_KEY_ID,
            secret_access_key=self.config.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
            bucket_name=self.config.CLOUDFLARE_R2_BUCKET_NAME
        )
        
        self.logger.info("R2 HLS存储管理器已初始化")
    
    async def upload_segment(self, task_id: str, segment_file_path: str, segment_name: str) -> Dict:
        """
        上传单个TS分段文件到R2
        
        Args:
            task_id: 任务ID
            segment_file_path: 本地分段文件路径
            segment_name: 分段文件名
            
        Returns:
            Dict: 包含上传结果的字典
        """
        try:
            # R2存储路径：hls/{task_id}/{segment_name}
            r2_path = f"hls/{task_id}/{segment_name}"
            
            # 读取文件内容
            async with aiofiles.open(segment_file_path, 'rb') as f:
                file_bytes = await f.read()
            
            # 上传到R2
            public_url = await self.r2_client.upload_file(
                file_data=file_bytes,
                r2_path=r2_path,
                content_type='video/mp2t'
            )
            
            if public_url:
                self.logger.info(f"[{task_id}] 成功上传分段文件: {segment_name}")
                return {
                    "status": "success",
                    "storage_path": r2_path,
                    "segment_name": segment_name,
                    "file_size": len(file_bytes),
                    "public_url": public_url
                }
            else:
                return {
                    "status": "error",
                    "message": "上传到R2失败",
                    "segment_name": segment_name
                }
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 上传分段文件失败 {segment_name}: {e}")
            return {
                "status": "error",
                "message": f"上传分段文件失败: {str(e)}",
                "segment_name": segment_name
            }
    
    async def upload_playlist(self, task_id: str, playlist_content: str) -> Dict:
        """
        上传M3U8播放列表到R2
        
        Args:
            task_id: 任务ID
            playlist_content: M3U8播放列表内容
            
        Returns:
            Dict: 包含上传结果的字典
        """
        try:
            # R2存储路径：hls/{task_id}/playlist.m3u8
            r2_path = f"hls/{task_id}/playlist.m3u8"
            
            # 将字符串转换为字节
            file_bytes = playlist_content.encode('utf-8')
            
            # 上传到R2
            public_url = await self.r2_client.upload_file(
                file_data=file_bytes,
                r2_path=r2_path,
                content_type='application/vnd.apple.mpegurl'
            )
            
            if public_url:
                self.logger.info(f"[{task_id}] 成功上传播放列表: {r2_path}")
                return {
                    "status": "success",
                    "storage_path": r2_path,
                    "file_size": len(file_bytes),
                    "public_url": public_url
                }
            else:
                return {
                    "status": "error",
                    "message": "上传播放列表到R2失败"
                }
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 上传播放列表失败: {e}")
            return {
                "status": "error",
                "message": f"上传播放列表失败: {str(e)}"
            }
    
    async def get_existing_playlist_content(self, task_id: str) -> Optional[str]:
        """
        从R2获取现有播放列表内容
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[str]: 播放列表内容，如果不存在则返回None
        """
        try:
            r2_path = f"hls/{task_id}/playlist.m3u8"
            
            # 检查文件是否存在
            if not await self.r2_client.file_exists(r2_path):
                return None
            
            # 下载播放列表文件
            playlist_bytes = await self.r2_client.download_audio(r2_path)  # 复用下载方法
            if playlist_bytes:
                playlist_content = playlist_bytes.decode('utf-8')
                self.logger.info(f"[{task_id}] 从R2恢复播放列表，长度: {len(playlist_content)}")
                return playlist_content
            
            return None
            
        except Exception as e:
            self.logger.debug(f"[{task_id}] 无法从R2获取现有播放列表: {e}")
            return None
    
    async def upload_final_video(self, task_id: str, video_file_path: str) -> Optional[str]:
        """
        上传最终合并的视频文件到R2
        
        Args:
            task_id: 任务ID
            video_file_path: 本地视频文件路径
            
        Returns:
            Optional[str]: 视频文件的公共URL
        """
        try:
            r2_path = f"videos/{task_id}/final_video.mp4"
            
            # 上传视频文件
            public_url = await self.r2_client.upload_file(
                file_data=video_file_path,
                r2_path=r2_path,
                content_type='video/mp4'
            )
            
            if public_url:
                self.logger.info(f"[{task_id}] 成功上传最终视频: {r2_path}")
                return public_url
            else:
                self.logger.error(f"[{task_id}] 上传最终视频失败")
                return None
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 上传最终视频异常: {e}")
            return None
    
    async def list_segments(self, task_id: str) -> List[Dict]:
        """
        列出任务的所有分段文件
        
        Args:
            task_id: 任务ID
            
        Returns:
            List[Dict]: 分段文件信息列表
        """
        try:
            prefix = f"hls/{task_id}/"
            files = await self.r2_client.list_files(prefix)
            
            # 过滤出TS分段文件
            segments = []
            for file_info in files:
                if file_info['key'].endswith('.ts'):
                    segments.append({
                        'segment_name': Path(file_info['key']).name,
                        'size': file_info['size'],
                        'last_modified': file_info['last_modified'],
                        'r2_path': file_info['key']
                    })
            
            self.logger.info(f"[{task_id}] 找到 {len(segments)} 个分段文件")
            return segments
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 列出分段文件失败: {e}")
            return []
    
    async def cleanup_segments(self, task_id: str, keep_final_video: bool = True) -> Dict:
        """
        清理任务的分段文件
        
        Args:
            task_id: 任务ID
            keep_final_video: 是否保留最终视频文件
            
        Returns:
            Dict: 清理结果
        """
        try:
            prefix = f"hls/{task_id}/"
            files = await self.r2_client.list_files(prefix)
            
            deleted_count = 0
            errors = []
            
            for file_info in files:
                file_path = file_info['key']
                
                # 如果要保留最终视频，跳过播放列表文件
                if keep_final_video and file_path.endswith('playlist.m3u8'):
                    continue
                
                try:
                    success = await self.r2_client.delete_file(file_path)
                    if success:
                        deleted_count += 1
                    else:
                        errors.append(f"删除失败: {file_path}")
                except Exception as e:
                    errors.append(f"删除异常 {file_path}: {e}")
            
            result = {
                "deleted_count": deleted_count,
                "total_files": len(files),
                "errors": errors
            }
            
            if errors:
                self.logger.warning(f"[{task_id}] 清理完成，但有错误: {result}")
            else:
                self.logger.info(f"[{task_id}] 清理完成: 删除 {deleted_count} 个文件")
            
            return result
            
        except Exception as e:
            self.logger.error(f"[{task_id}] 清理分段文件失败: {e}")
            return {"deleted_count": 0, "total_files": 0, "errors": [str(e)]}
    
    async def batch_upload_segments(self, task_id: str, segment_file_paths: List[str]) -> Dict:
        """
        批量上传分段文件到R2
        
        Args:
            task_id: 任务ID
            segment_file_paths: 分段文件路径列表
            
        Returns:
            Dict: 批量上传结果
        """
        uploaded_count = 0
        failed_count = 0
        errors = []
        
        for segment_path in segment_file_paths:
            try:
                segment_name = Path(segment_path).name
                result = await self.upload_segment(task_id, segment_path, segment_name)
                
                if result["status"] == "success":
                    uploaded_count += 1
                else:
                    failed_count += 1
                    errors.append(result.get("message", f"上传失败: {segment_name}"))
                    
            except Exception as e:
                failed_count += 1
                errors.append(f"上传异常 {Path(segment_path).name}: {e}")
        
        total_count = len(segment_file_paths)
        
        if failed_count == 0:
            status = "success"
        elif uploaded_count > 0:
            status = "partial"
        else:
            status = "error"
        
        result = {
            "status": status,
            "uploaded_count": uploaded_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "errors": errors
        }
        
        self.logger.info(f"[{task_id}] 批量上传分段文件完成: {uploaded_count}/{total_count} 成功")
        
        if errors:
            self.logger.warning(f"[{task_id}] 批量上传错误: {errors}")
        
        return result
    
    def get_public_playlist_url(self, task_id: str) -> str:
        """
        获取播放列表的公共URL
        
        Args:
            task_id: 任务ID
            
        Returns:
            str: 播放列表的公共URL
        """
        return f"https://pub-{self.config.CLOUDFLARE_ACCOUNT_ID}.r2.dev/hls/{task_id}/playlist.m3u8"