#!/usr/bin/env python3
"""
WaveShift TTS Engine - 主应用入口点
重构后的标准Python应用，移除了Ray架构依赖
"""
import sys
import logging
import uvicorn
from config import get_config, init_logging
from launcher import create_service_manager

# 初始化日志和配置
init_logging()
config = get_config()
logger = logging.getLogger(__name__)

def main():
    """主函数 - 启动WaveShift TTS Engine"""
    try:
        logger.info("=" * 60)
        logger.info("WaveShift TTS Engine v2.0 启动中...")
        logger.info("=" * 60)
        
        # 初始化服务管理器
        logger.info("正在初始化服务管理器...")
        service_manager = create_service_manager()
        logger.info("服务管理器初始化成功")
        
        # 显示已初始化的服务
        services = service_manager.get_all_services()
        logger.info(f"已初始化 {len(services)} 个服务:")
        for service_name in services.keys():
            logger.info(f"  ✓ {service_name}")
        
        # 启动FastAPI服务器
        logger.info(f"正在启动HTTP服务器 - {config.SERVER_HOST}:{config.SERVER_PORT}")
        
        # 导入API模块并设置服务管理器
        from api import app, set_service_manager
        set_service_manager(service_manager)
        
        # 启动服务器
        uvicorn.run(
            app,
            host=config.SERVER_HOST,
            port=config.SERVER_PORT,
            log_level="info",
            access_log=True
        )
        
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务...")
    except Exception as e:
        logger.critical(f"应用启动失败: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("WaveShift TTS Engine 已关闭")

if __name__ == "__main__":
    main()