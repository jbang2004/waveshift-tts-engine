import logging
import asyncio
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Body, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import get_config
from core.cloudflare.d1_client import D1Client
from utils.async_utils import BackgroundTaskManager

# 获取配置
config = get_config()
logger = logging.getLogger(__name__)

app = FastAPI(debug=True, title="WaveShift TTS Engine API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 应用状态存储
class AppState:
    def __init__(self):
        self.service_manager = None
        self.task_manager = None
        self.initialized = False

# 应用状态实例
app_state = AppState()

def set_service_manager(sm):
    """设置服务管理器实例"""
    app_state.service_manager = sm
    app_state.task_manager = BackgroundTaskManager()
    app_state.initialized = True
    logger.info("API服务管理器已设置")

# 依赖注入函数
async def get_service_manager():
    """获取服务管理器依赖"""
    if not app_state.initialized:
        raise HTTPException(status_code=500, detail="服务管理器未初始化")
    return app_state.service_manager

async def get_orchestrator(service_manager = Depends(get_service_manager)):
    """获取编排器依赖"""
    return service_manager.get_service('orchestrator')

async def get_d1_client(service_manager = Depends(get_service_manager)):
    """获取D1客户端依赖"""
    return service_manager.get_service('d1_client')

async def get_task_manager():
    """获取任务管理器依赖"""
    if not app_state.initialized:
        raise HTTPException(status_code=500, detail="任务管理器未初始化")
    return app_state.task_manager

# 应用生命周期事件
@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("WaveShift TTS Engine API 启动中...")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("WaveShift TTS Engine API 关闭中...")
    if app_state.task_manager:
        await app_state.task_manager.close()
        logger.info("任务管理器已关闭")

@app.post("/api/start_tts")
async def start_tts(
    task_id: str = Body(..., embed=True),
    orchestrator = Depends(get_orchestrator),
    d1_client = Depends(get_d1_client),
    task_manager = Depends(get_task_manager)
):
    """
    启动TTS合成流程 - 直接使用 Worker 数据
    """
    try:
        # 使用后台任务管理器启动流水线
        async def tts_error_handler(e: Exception):
            """TTS任务错误处理器"""
            logger.error(f"TTS流水线执行失败 [任务ID: {task_id}]: {e}", exc_info=True)
            # 更新任务状态为错误
            try:
                await d1_client.update_task_status(task_id, 'error', str(e))
            except Exception as db_error:
                logger.error(f"更新任务状态失败 [任务ID: {task_id}]: {db_error}")
        
        # 创建管理的后台任务
        task_manager.create_task(
            orchestrator.run_complete_tts_pipeline(task_id),
            name=f"tts_pipeline_{task_id}",
            error_handler=tts_error_handler
        )
        
        return JSONResponse(content={
            'status': 'processing', 
            'task_id': task_id, 
            'message': 'TTS合成流程已开始'
        })
        
    except Exception as e:
        logger.error(f"启动TTS失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动TTS失败: {e}")

@app.get("/api/task/{task_id}/status")
async def get_task_status(
    task_id: str,
    orchestrator = Depends(get_orchestrator)
):
    """获取任务状态和HLS播放列表URL"""
    try:
        # 通过编排器获取任务状态（包含更丰富的信息）
        status_result = await orchestrator.get_task_status(task_id)
        
        if status_result["status"] != "success":
            raise HTTPException(status_code=404, detail=status_result.get("message", "任务不存在"))
        
        return JSONResponse(content={
            'task_id': task_id,
            'status': status_result.get('task_status'),
            'hls_playlist_url': status_result.get('hls_playlist_url'),
            'error_message': status_result.get('error_message')
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {e}")

@app.post("/api/task")
async def create_task(request: Dict[str, Any] = Body(...)):
    """
    创建新任务（可选接口，用于外部系统集成）
    """
    try:
        # 这个接口主要用于外部系统创建任务记录
        # 实际的转录和翻译数据应该由Cloudflare Worker预先处理并存储到D1
        required_fields = ['video_id', 'audio_path_r2', 'video_path_r2']
        for field in required_fields:
            if field not in request:
                raise HTTPException(status_code=400, detail=f"缺少必需字段: {field}")
        
        # 这里可以添加创建任务的逻辑
        # 但通常任务应该由Cloudflare Worker预先创建
        
        return JSONResponse(content={
            'status': 'created',
            'message': '任务创建成功，请使用/api/start_tts启动TTS处理'
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建任务失败: {e}")

@app.get("/api/health")
async def health_check(service_manager = Depends(get_service_manager)):
    """健康检查接口"""
    try:
        # 检查服务状态
        services_status = {}
        if service_manager:
            services = service_manager.get_all_services()
            for name, service in services.items():
                services_status[name] = service is not None
        
        return JSONResponse(content={
            'status': 'healthy',
            'services': services_status,
            'timestamp': asyncio.get_event_loop().time(),
            'version': '2.0.0'
        })
        
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=503, detail=f"服务不健康: {e}")

@app.get("/")
async def root():
    """根路径"""
    return JSONResponse(content={
        'name': 'WaveShift TTS Engine',
        'version': '2.0.0',
        'description': '基于IndexTTS的语音合成引擎',
        'endpoints': {
            'start_tts': 'POST /api/start_tts',
            'task_status': 'GET /api/task/{task_id}/status', 
            'create_task': 'POST /api/task',
            'health': 'GET /api/health',
            'debug': 'GET /api/debug/{task_id}'
        }
    })

@app.get("/api/debug/{task_id}")
async def debug_task_data(
    task_id: str, 
    d1_client = Depends(get_d1_client)
):
    """调试接口：查看任务数据"""
    try:
        sentences = await d1_client.get_transcription_segments_from_worker(task_id)
        media_paths = await d1_client.get_worker_media_paths(task_id)
        
        return JSONResponse(content={
            'task_id': task_id,
            'segments_count': len(sentences),
            'media_paths': media_paths,
            'first_segment': {
                'sequence': sentences[0].sequence if sentences else None,
                'speaker': sentences[0].speaker if sentences else None,
                'start_ms': sentences[0].start_ms if sentences else None,
                'end_ms': sentences[0].end_ms if sentences else None,
                'original_text': sentences[0].original_text[:50] if sentences else None,
                'translated_text': sentences[0].translated_text[:50] if sentences else None,
            } if sentences else None
        })
        
    except Exception as e:
        return JSONResponse(content={
            'error': str(e)
        }, status_code=500)

# 重复的shutdown事件处理器已删除，使用上面的统一处理器

def run_server():
    """运行标准的FastAPI服务器"""
    uvicorn.run(
        app, 
        host=config.SERVER_HOST, 
        port=config.SERVER_PORT,
        log_level="info"
    )

if __name__ == "__main__":
    run_server()