import logging
import asyncio
import httpx
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from core.sentence_tools import Sentence

logger = logging.getLogger(__name__)

@dataclass
class TranscriptionData:
    """转录数据结构"""
    sentence_id: int
    raw_text: str
    trans_text: str
    start_ms: float
    end_ms: float
    speaker_id: int
    target_duration_ms: float = None
    speech_duration_ms: float = None
    audio_prompt_path: str = ""
    is_first: bool = False
    is_last: bool = False
    ending_silence_ms: float = 0.0

class D1Client:
    """Cloudflare D1 数据库客户端"""
    
    def __init__(self, account_id: str, api_token: str, database_id: str):
        self.account_id = account_id
        self.api_token = api_token
        self.database_id = database_id
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}"
        self.logger = logging.getLogger(__name__)
        
        # 创建HTTP客户端
        self.http_client = None
        
    async def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端实例"""
        if self.http_client is None:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            self.http_client = httpx.AsyncClient(
                headers=headers,
                timeout=30.0
            )
        return self.http_client
    
    async def close(self):
        """关闭HTTP客户端"""
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None
    
    async def _execute_query(self, sql: str, params: List[Any] = None) -> Dict:
        """执行D1查询"""
        try:
            client = await self._get_client()
            payload = {
                "sql": sql
            }
            if params:
                payload["params"] = params
                
            response = await client.post(
                f"{self.base_url}/query",
                json=payload
            )
            
            if response.status_code != 200:
                self.logger.error(f"D1查询失败: {response.status_code} - {response.text}")
                return None
                
            result = response.json()
            if not result.get("success"):
                self.logger.error(f"D1查询错误: {result.get('errors', [])}")
                return None
                
            return result.get("result", [{}])[0]
            
        except Exception as e:
            self.logger.error(f"D1查询异常: {e}")
            return None
    
    async def get_transcriptions(self, task_id: str) -> List[TranscriptionData]:
        """获取任务的转录数据"""
        sql = """
        SELECT 
            id as sentence_id,
            raw_text,
            trans_text,
            start_ms,
            end_ms,
            speaker_id,
            target_duration_ms,
            speech_duration_ms,
            audio_prompt_path,
            is_first,
            is_last,
            ending_silence_ms
        FROM sentences 
        WHERE task_id = ? 
        ORDER BY start_ms ASC
        """
        
        result = await self._execute_query(sql, [task_id])
        
        if not result or "results" not in result:
            self.logger.warning(f"任务 {task_id} 没有找到转录数据")
            return []
            
        transcriptions = []
        for row in result["results"]:
            transcription = TranscriptionData(
                sentence_id=row["sentence_id"],
                raw_text=row["raw_text"] or "",
                trans_text=row["trans_text"] or "",
                start_ms=float(row["start_ms"]),
                end_ms=float(row["end_ms"]),
                speaker_id=int(row["speaker_id"]),
                target_duration_ms=float(row["target_duration_ms"]) if row["target_duration_ms"] else None,
                speech_duration_ms=float(row["speech_duration_ms"]) if row["speech_duration_ms"] else None,
                audio_prompt_path=row["audio_prompt_path"] or "",
                is_first=bool(row["is_first"]),
                is_last=bool(row["is_last"]),
                ending_silence_ms=float(row["ending_silence_ms"]) if row["ending_silence_ms"] else 0.0
            )
            transcriptions.append(transcription)
            
        self.logger.info(f"获取到任务 {task_id} 的 {len(transcriptions)} 条转录数据")
        return transcriptions
    
    async def get_task_info(self, task_id: str) -> Optional[Dict]:
        """获取任务基本信息"""
        sql = """
        SELECT 
            id,
            status,
            target_language,
            audio_path,
            video_path,
            error_message,
            created_at,
            transcription_id
        FROM media_tasks 
        WHERE id = ?
        """
        
        result = await self._execute_query(sql, [task_id])
        
        if not result or "results" not in result or not result["results"]:
            self.logger.warning(f"任务 {task_id} 不存在")
            return None
            
        task_data = result["results"][0]
        self.logger.info(f"获取到任务 {task_id} 的信息")
        return task_data
    
    async def update_task_status(self, task_id: str, status: str, error_message: str = None) -> bool:
        """更新任务状态"""
        try:
            # 构建更新字段
            fields = ["status = ?"]
            params = [status]
            
            if error_message is not None:
                fields.append("error_message = ?")
                params.append(error_message)
                
            params.append(task_id)
            
            sql = f"""
            UPDATE media_tasks 
            SET {', '.join(fields)}
            WHERE id = ?
            """
            
            result = await self._execute_query(sql, params)
            
            if result and result.get("meta", {}).get("changes", 0) > 0:
                self.logger.info(f"任务 {task_id} 状态更新为: {status}")
                return True
            else:
                self.logger.warning(f"任务 {task_id} 状态更新失败")
                return False
                
        except Exception as e:
            self.logger.error(f"更新任务状态失败: {e}")
            return False
    
    async def to_sentence_objects(self, transcriptions: List[TranscriptionData], task_id: str) -> List[Sentence]:
        """将转录数据转换为Sentence对象"""
        sentences = []
        
        for trans in transcriptions:
            sentence = Sentence(
                original_text=trans.raw_text,
                start_ms=trans.start_ms,
                end_ms=trans.end_ms,
                speaker=str(trans.speaker_id),
                translated_text=trans.trans_text,
                sequence=trans.sentence_id,
                target_duration=trans.target_duration_ms if trans.target_duration_ms else None,
                is_first=trans.is_first,
                is_last=trans.is_last,
                task_id=task_id,
                ending_silence=trans.ending_silence_ms if trans.ending_silence_ms else 0.0
            )
            sentences.append(sentence)
            
        return sentences
    
    async def get_transcription_segments_from_worker(self, task_id: str) -> List[Sentence]:
        """直接从 Worker 的表获取转录片段"""
        # 第一步：获取 media_task 信息
        task_sql = """
        SELECT 
            id, 
            transcription_id,
            target_language,
            translation_style,
            audio_path,
            video_path
        FROM media_tasks 
        WHERE id = ?
        """
        
        task_result = await self._execute_query(task_sql, [task_id])
        if not task_result or "results" not in task_result or not task_result["results"]:
            self.logger.warning(f"任务 {task_id} 不存在")
            return []
        
        task_info = task_result["results"][0]
        transcription_id = task_info.get('transcription_id')
        
        if not transcription_id:
            self.logger.warning(f"任务 {task_id} 没有转录ID")
            return []
        
        # 第二步：获取转录信息（用于判断 is_last）
        trans_sql = """
        SELECT total_segments
        FROM transcriptions 
        WHERE id = ?
        """
        
        trans_result = await self._execute_query(trans_sql, [transcription_id])
        total_segments = 0
        if trans_result and "results" in trans_result and trans_result["results"]:
            total_segments = trans_result["results"][0].get('total_segments', 0)
        
        # 第三步：获取所有片段
        segments_sql = """
        SELECT 
            sequence,
            start_ms,
            end_ms,
            content_type,
            speaker,
            original_text,
            translated_text
        FROM transcription_segments 
        WHERE transcription_id = ? 
        ORDER BY sequence ASC
        """
        
        segments_result = await self._execute_query(segments_sql, [transcription_id])
        
        if not segments_result or "results" not in segments_result:
            self.logger.warning(f"转录 {transcription_id} 没有片段数据")
            return []
        
        # 直接创建 Sentence 对象，使用 Worker 字段名
        sentences = []
        segments = segments_result["results"]
        
        for idx, segment in enumerate(segments):
            sentence = Sentence(
                sequence=segment['sequence'],
                start_ms=float(segment['start_ms']),
                end_ms=float(segment['end_ms']),
                speaker=segment['speaker'] or 'unknown',
                original_text=segment['original_text'] or '',
                translated_text=segment['translated_text'] or '',
                task_id=task_id,
                is_first=(segment['sequence'] == 1),
                is_last=(segment['sequence'] == total_segments)
            )
            sentences.append(sentence)
        
        self.logger.info(f"获取到任务 {task_id} 的 {len(sentences)} 个句子")
        return sentences
    
    async def get_worker_media_paths(self, task_id: str) -> Dict[str, str]:
        """获取 Worker 的媒体文件路径"""
        sql = """
        SELECT audio_path, video_path
        FROM media_tasks 
        WHERE id = ?
        """
        
        result = await self._execute_query(sql, [task_id])
        
        if not result or "results" not in result or not result["results"]:
            return {}
        
        task_info = result["results"][0]
        return {
            'audio_path': task_info.get('audio_path', ''),
            'video_path': task_info.get('video_path', '')
        }