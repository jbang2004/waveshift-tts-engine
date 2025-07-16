#!/usr/bin/env python3
"""
WaveShift TTS Engine - 阿里云函数计算入口点
最小化修改方案：直接使用原有的api.py和服务
"""
import os
import sys
import json
import asyncio
from datetime import datetime

# 设置函数计算环境标识
os.environ['FC_FUNC_CODE_PATH'] = '/code'
os.environ['FC_RUNTIME_API'] = 'true'

# 确保项目路径在Python路径中  
sys.path.insert(0, '/code')

# 导入原有模块
from launcher import create_services
from config import init_logging
import logging

# 初始化日志
init_logging()
logger = logging.getLogger(__name__)

# 全局服务实例（利用容器复用）
_services = None
_initialized = False


def initialize_services():
    """初始化服务（仅在冷启动时执行）"""
    global _services, _initialized
    
    if _initialized and _services is not None:
        return _services
    
    try:
        logger.info("🚀 初始化TTS服务...")
        _services = create_services()
        _initialized = True
        logger.info("✅ 服务初始化完成")
        return _services
    except Exception as e:
        logger.error(f"❌ 服务初始化失败: {e}")
        raise


async def handle_request(event, context):
    """处理HTTP请求"""
    try:
        # 解析请求
        method = event.get('httpMethod', 'GET')
        path = event.get('path', '/')
        body = event.get('body', '{}')
        
        logger.info(f"📨 收到请求: {method} {path}")
        
        # 初始化服务
        services = initialize_services()
        orchestrator = services['orchestrator']
        
        # 路由处理
        if method == 'POST' and path == '/api/start_tts':
            # 解析请求体
            if isinstance(body, str):
                data = json.loads(body)
            else:
                data = body
            
            task_id = data.get('task_id')
            if not task_id:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': '缺少task_id参数'}, ensure_ascii=False)
                }
            
            # 执行TTS流水线
            result = await orchestrator.run_complete_tts_pipeline(task_id)
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'success',
                    'task_id': task_id,
                    'result': result
                }, ensure_ascii=False)
            }
            
        elif method == 'GET' and path.startswith('/api/task/') and path.endswith('/status'):
            # 任务状态查询
            task_id = path.split('/')[3]
            status_result = await orchestrator.get_task_status(task_id)
            
            if status_result["status"] != "success":
                return {
                    'statusCode': 404,
                    'body': json.dumps({'error': '任务不存在'}, ensure_ascii=False)
                }
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'task_id': task_id,
                    'status': status_result.get('task_status'),
                    'hls_playlist_url': status_result.get('hls_playlist_url')
                }, ensure_ascii=False)
            }
            
        elif method == 'GET' and path == '/api/health':
            # 健康检查
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'healthy',
                    'version': '2.0.0-fc',
                    'services_initialized': _initialized,
                    'timestamp': datetime.now().isoformat()
                }, ensure_ascii=False)
            }
            
        else:
            # 未知路径
            return {
                'statusCode': 404,
                'body': json.dumps({'error': f'路径未找到: {method} {path}'}, ensure_ascii=False)
            }
            
    except Exception as e:
        logger.error(f"❌ 请求处理失败: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)}, ensure_ascii=False)
        }


def handler(event, context):
    """阿里云函数计算入口函数"""
    return asyncio.get_event_loop().run_until_complete(handle_request(event, context))