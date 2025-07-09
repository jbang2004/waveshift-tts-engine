#!/usr/bin/env python3
"""
修复任务状态脚本
"""
import asyncio
from config import get_config
from core.cloudflare.d1_client import D1Client

async def fix_task_status():
    """修复任务状态"""
    config = get_config()
    
    # 创建D1客户端
    d1_client = D1Client(
        account_id=config.CLOUDFLARE_ACCOUNT_ID,
        api_token=config.CLOUDFLARE_API_TOKEN,
        database_id=config.CLOUDFLARE_D1_DATABASE_ID
    )
    
    task_id = "db3228f0-afde-4029-8fe1-078af2767873"
    
    try:
        # 查看任务当前状态
        task_info = await d1_client.get_task_info(task_id)
        print(f"当前任务状态: {task_info.get('status')}")
        print(f"当前错误信息: {task_info.get('error_message')}")
        
        # 尝试手动更新任务状态为completed
        print("\n正在更新任务状态为completed...")
        result = await d1_client.update_task_status(task_id, 'completed', None)
        print(f"状态更新结果: {result}")
        
        # 再次查看任务状态
        task_info = await d1_client.get_task_info(task_id)
        print(f"\n更新后任务状态: {task_info.get('status')}")
        print(f"更新后错误信息: {task_info.get('error_message')}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await d1_client.close()

if __name__ == "__main__":
    asyncio.run(fix_task_status())