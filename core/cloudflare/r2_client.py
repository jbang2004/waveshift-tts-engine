import logging
import asyncio
import aiofiles
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import Dict, List, Optional, Union
from pathlib import Path
import io

logger = logging.getLogger(__name__)

class R2Client:
    """Cloudflare R2 对象存储客户端"""
    
    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str, bucket_name: str):
        self.account_id = account_id
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket_name = bucket_name
        self.logger = logging.getLogger(__name__)
        
        # R2的S3兼容端点
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        
        # 创建S3客户端配置
        self.s3_config = Config(
            region_name='auto',
            retries={'max_attempts': 3},
            s3={'addressing_style': 'path'}
        )
        
        # 初始化S3客户端
        self.s3_client = None
        
    def _get_client(self):
        """获取S3客户端实例"""
        if self.s3_client is None:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=self.s3_config
            )
        return self.s3_client
    
    async def download_audio(self, audio_path: str) -> Optional[bytes]:
        """
        从R2下载音频文件
        
        Args:
            audio_path: R2中的音频文件路径
            
        Returns:
            bytes: 音频文件数据，失败时返回None
        """
        try:
            client = self._get_client()
            
            # 使用asyncio.to_thread异步执行S3下载
            response = await asyncio.to_thread(
                client.get_object,
                Bucket=self.bucket_name,
                Key=audio_path
            )
            
            # 读取文件内容
            audio_data = await asyncio.to_thread(response['Body'].read)
            
            self.logger.info(f"成功从R2下载音频文件: {audio_path} ({len(audio_data)} bytes)")
            return audio_data
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                self.logger.error(f"R2中未找到音频文件: {audio_path}")
            else:
                self.logger.error(f"下载音频文件失败 {audio_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"下载音频文件异常 {audio_path}: {e}")
            return None
    
    async def download_video(self, video_path: str) -> Optional[bytes]:
        """
        从R2下载视频文件
        
        Args:
            video_path: R2中的视频文件路径
            
        Returns:
            bytes: 视频文件数据，失败时返回None
        """
        try:
            client = self._get_client()
            
            # 使用asyncio.to_thread异步执行S3下载
            response = await asyncio.to_thread(
                client.get_object,
                Bucket=self.bucket_name,
                Key=video_path
            )
            
            # 读取文件内容
            video_data = await asyncio.to_thread(response['Body'].read)
            
            self.logger.info(f"成功从R2下载视频文件: {video_path} ({len(video_data)} bytes)")
            return video_data
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                self.logger.error(f"R2中未找到视频文件: {video_path}")
            else:
                self.logger.error(f"下载视频文件失败 {video_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"下载视频文件异常 {video_path}: {e}")
            return None
    
    async def upload_file(self, file_data: Union[bytes, str], r2_path: str, 
                         content_type: str = None) -> Optional[str]:
        """
        上传文件到R2
        
        Args:
            file_data: 文件数据（bytes）或本地文件路径（str）
            r2_path: R2中的存储路径
            content_type: 文件MIME类型
            
        Returns:
            str: 文件的公共URL，失败时返回None
        """
        try:
            client = self._get_client()
            
            # 准备上传数据
            if isinstance(file_data, str):
                # 如果是文件路径，读取文件
                async with aiofiles.open(file_data, 'rb') as f:
                    upload_data = await f.read()
                    
                # 自动检测content_type
                if not content_type:
                    file_ext = Path(file_data).suffix.lower()
                    content_type_map = {
                        '.mp4': 'video/mp4',
                        '.ts': 'video/mp2t',
                        '.m3u8': 'application/vnd.apple.mpegurl',
                        '.wav': 'audio/wav',
                        '.mp3': 'audio/mpeg'
                    }
                    content_type = content_type_map.get(file_ext, 'application/octet-stream')
            else:
                upload_data = file_data
                
            # 准备上传参数
            upload_args = {
                'Bucket': self.bucket_name,
                'Key': r2_path,
                'Body': upload_data
            }
            
            if content_type:
                upload_args['ContentType'] = content_type
                
            # 执行上传
            await asyncio.to_thread(client.put_object, **upload_args)
            
            # 生成公共URL（假设存储桶配置了公共访问）
            public_url = f"https://pub-{self.account_id}.r2.dev/{r2_path}"
            
            self.logger.info(f"成功上传文件到R2: {r2_path} ({len(upload_data)} bytes)")
            return public_url
            
        except Exception as e:
            self.logger.error(f"上传文件到R2失败 {r2_path}: {e}")
            return None
    
    async def upload_hls_segment(self, task_id: str, segment_file_path: str, 
                               segment_name: str) -> Optional[str]:
        """
        上传HLS分段文件到R2
        
        Args:
            task_id: 任务ID
            segment_file_path: 本地分段文件路径
            segment_name: 分段文件名
            
        Returns:
            str: 分段文件的公共URL
        """
        r2_path = f"hls/{task_id}/{segment_name}"
        return await self.upload_file(segment_file_path, r2_path, 'video/mp2t')
    
    async def upload_hls_playlist(self, task_id: str, playlist_content: str) -> Optional[str]:
        """
        上传HLS播放列表到R2
        
        Args:
            task_id: 任务ID
            playlist_content: M3U8播放列表内容
            
        Returns:
            str: 播放列表的公共URL
        """
        r2_path = f"hls/{task_id}/playlist.m3u8"
        playlist_bytes = playlist_content.encode('utf-8')
        return await self.upload_file(playlist_bytes, r2_path, 'application/vnd.apple.mpegurl')
    
    async def list_files(self, prefix: str = "") -> List[Dict]:
        """
        列出R2中的文件
        
        Args:
            prefix: 文件路径前缀
            
        Returns:
            List[Dict]: 文件信息列表
        """
        try:
            client = self._get_client()
            
            response = await asyncio.to_thread(
                client.list_objects_v2,
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'],
                    'etag': obj['ETag']
                })
                
            self.logger.info(f"列出R2文件: {len(files)} 个文件 (前缀: {prefix})")
            return files
            
        except Exception as e:
            self.logger.error(f"列出R2文件失败: {e}")
            return []
    
    async def delete_file(self, r2_path: str) -> bool:
        """
        删除R2中的文件
        
        Args:
            r2_path: R2中的文件路径
            
        Returns:
            bool: 删除是否成功
        """
        try:
            client = self._get_client()
            
            await asyncio.to_thread(
                client.delete_object,
                Bucket=self.bucket_name,
                Key=r2_path
            )
            
            self.logger.info(f"成功删除R2文件: {r2_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"删除R2文件失败 {r2_path}: {e}")
            return False
    
    async def file_exists(self, r2_path: str) -> bool:
        """
        检查文件是否存在于R2中
        
        Args:
            r2_path: R2中的文件路径
            
        Returns:
            bool: 文件是否存在
        """
        try:
            client = self._get_client()
            
            await asyncio.to_thread(
                client.head_object,
                Bucket=self.bucket_name,
                Key=r2_path
            )
            
            return True
            
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                self.logger.error(f"检查R2文件存在性失败 {r2_path}: {e}")
                return False
        except Exception as e:
            self.logger.error(f"检查R2文件存在性异常 {r2_path}: {e}")
            return False