import sys
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import ray
from ray import serve

from config import get_config, init_logging
from core.cloudflare.d1_client import D1Client

# 初始化配置和日志
config = get_config()
init_logging()

logger = logging.getLogger(__name__)

app = FastAPI(debug=True, title="WaveShift TTS Engine API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局 D1Client 实例
d1_client = D1Client(
    account_id=config.CLOUDFLARE_ACCOUNT_ID,
    api_token=config.CLOUDFLARE_API_TOKEN,
    database_id=config.CLOUDFLARE_D1_DATABASE_ID
)

@app.on_event("startup")
async def startup_d1():
    """FastAPI 启动时初始化 D1 客户端"""
    logger.info("D1客户端已初始化")

@serve.deployment(
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.5}
)
@serve.ingress(app)
class TTSEngineAPI:
    """TTS引擎API服务"""
    def __init__(self):
        self.logger = logger
        self.config = config
        self.d1_client = d1_client
        
        try:
            self.orchestrator_handle = serve.get_deployment_handle(
                "MainOrchestratorDeployment", 
                app_name="MainOrchestratorApp"
            )
            self.logger.info("TTSEngineAPI初始化完成")
        except Exception as e:
            self.logger.error(f"TTSEngineAPI初始化失败: {e}", exc_info=True)
            raise RuntimeError(f"无法连接到MainOrchestrator: {e}")

    @app.post("/api/start_tts")
    async def start_tts(self, task_id: str = Body(..., embed=True)):
        """
        启动TTS合成流程
        直接从D1获取预处理数据，从R2下载音频，进行TTS合成
        """
        try:
            # 验证任务是否存在
            task_info = await self.d1_client.get_task_info(task_id)
            if not task_info:
                raise HTTPException(status_code=404, detail="任务不存在")
            
            # 检查任务状态
            current_status = task_info.get('status')
            if current_status in ['processing', 'completed']:
                return JSONResponse(content={
                    'status': current_status,
                    'task_id': task_id,
                    'message': f'任务已处于{current_status}状态'
                })
            
            # 启动完整TTS流水线
            self.orchestrator_handle.run_complete_tts_pipeline.remote(task_id)
            
            return JSONResponse(content={
                'status': 'processing', 
                'task_id': task_id, 
                'message': 'TTS合成流程已开始'
            })
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"启动TTS失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"启动TTS失败: {e}")

    @app.get("/api/task/{task_id}/status")
    async def get_task_status(self, task_id: str):
        """获取任务状态和HLS播放列表URL"""
        try:
            # 通过编排器获取任务状态（包含更丰富的信息）
            status_result = await self.orchestrator_handle.get_task_status.remote(task_id)
            
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
            self.logger.error(f"获取任务状态失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"获取任务状态失败: {e}")

    @app.post("/api/task")
    async def create_task(self, request: Dict[str, Any] = Body(...)):
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
            self.logger.error(f"创建任务失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"创建任务失败: {e}")

    @app.get("/api/health")
    async def health_check(self):
        """健康检查接口"""
        try:
            # 检查D1连接
            # 这里可以添加简单的D1查询测试
            
            # 检查Ray Serve连接
            ray_status = ray.is_initialized()
            
            return JSONResponse(content={
                'status': 'healthy',
                'ray_initialized': ray_status,
                'timestamp': asyncio.get_event_loop().time(),
                'version': '2.0.0'
            })
            
        except Exception as e:
            self.logger.error(f"健康检查失败: {e}")
            raise HTTPException(status_code=503, detail=f"服务不健康: {e}")

    @app.get("/")
    async def root(self):
        """根路径"""
        return JSONResponse(content={
            'name': 'WaveShift TTS Engine',
            'version': '2.0.0',
            'description': '基于IndexTTS的语音合成引擎',
            'endpoints': {
                'start_tts': 'POST /api/start_tts',
                'task_status': 'GET /api/task/{task_id}/status', 
                'create_task': 'POST /api/task',
                'health': 'GET /api/health'
            }
        })

def setup_server():
    """初始化Ray Serve服务器，部署API服务"""
    # 连接到Ray集群
    if not ray.is_initialized():
        ray.init(address="auto", namespace="videotrans", ignore_reinit_error=True)
        logger.info("已连接到Ray集群")

    # 检查主编排器应用
    try:
        serve.get_app_handle("MainOrchestratorApp")
        logger.info("成功连接到 MainOrchestratorApp")
    except Exception as e:
        logger.error(f"连接 MainOrchestratorApp 失败: {e}")
        raise RuntimeError(f"无法连接到核心应用: {e}")

    # 部署API服务
    tts_api = TTSEngineAPI.bind()
    serve.run(tts_api, name="TTSAPI", route_prefix="/", blocking=True)
    logger.info("TTS API服务部署完成")

if __name__ == "__main__":
    setup_server()