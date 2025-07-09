#!/usr/bin/env python3
"""
调试数据库状态脚本
"""
import asyncio
from config import get_config
from core.cloudflare.d1_client import D1Client

async def debug_task_status():
    """调试任务状态"""
    config = get_config()
    
    # 创建D1客户端
    d1_client = D1Client(
        account_id=config.CLOUDFLARE_ACCOUNT_ID,
        api_token=config.CLOUDFLARE_API_TOKEN,
        database_id=config.CLOUDFLARE_D1_DATABASE_ID
    )
    
    task_id = "db3228f0-afde-4029-8fe1-078af2767873"
    
    try:
        # 查看任务基本信息
        task_info = await d1_client.get_task_info(task_id)
        print(f"任务信息: {task_info}")
        
        # 直接查询数据库看看状态
        sql = """
        SELECT 
            id, status, error_message, created_at, updated_at
        FROM media_tasks 
        WHERE id = ?
        """
        
        result = await d1_client._execute_query(sql, [task_id])
        print(f"直接查询结果: {result}")
        
        # 查看转录段数据
        sentences = await d1_client.get_transcription_segments_from_worker(task_id)
        print(f"转录段数量: {len(sentences)}")
        
        # 查看媒体路径
        media_paths = await d1_client.get_worker_media_paths(task_id)
        print(f"媒体路径: {media_paths}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await d1_client.close()

if __name__ == "__main__":
    asyncio.run(debug_task_status())