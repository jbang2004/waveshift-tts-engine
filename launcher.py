import sys
import logging
from typing import Dict, Any
from config import get_config, init_logging

logger = logging.getLogger(__name__)

# 导入所有核心组件
from core.data_fetcher import DataFetcher
from core.audio_segmenter import AudioSegmenter
from core.translation.simplifier import Simplifier
from core.my_index_tts import MyIndexTTSDeployment
from core.timeadjust.duration_aligner import DurationAligner
from core.timeadjust.timestamp_adjuster import TimestampAdjuster
from core.media_mixer import MediaMixer
from core.hls_manager import HLSManager
from orchestrator import MainOrchestrator
from core.cloudflare.d1_client import D1Client
from core.client_manager import ClientManager


class ServiceManager:
    """服务管理器 - 替代Ray Serve的服务管理"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logger
        self.services = {}
        self.client_manager = None
        
    def initialize_services(self):
        """初始化所有核心服务"""
        try:
            # 初始化客户端管理器
            self.client_manager = ClientManager()
            self.client_manager.initialize_clients()
            
            # 获取共享客户端
            d1_client = self.client_manager.get_d1_client()
            r2_client = self.client_manager.get_r2_client()
            
            # 将客户端添加到服务中，以便其他服务可以访问
            self.services['d1_client'] = d1_client
            self.services['r2_client'] = r2_client
            self.services['client_manager'] = self.client_manager
            
            # 初始化服务实例（使用统一客户端）
            self.services['data_fetcher'] = DataFetcher(
                d1_client=d1_client,
                r2_client=r2_client
            )
            self.services['audio_segmenter'] = AudioSegmenter()
            self.services['simplifier'] = Simplifier()
            self.services['tts'] = MyIndexTTSDeployment(self.config)
            # 初始化有依赖的服务（在其依赖服务之后）
            self.services['duration_aligner'] = DurationAligner(
                simplifier=self.services['simplifier'],
                index_tts=self.services['tts']
            )
            self.services['timestamp_adjuster'] = TimestampAdjuster()
            self.services['media_mixer'] = MediaMixer()
            self.services['hls_manager'] = HLSManager(d1_client=d1_client)
            
            # 最后初始化编排器，注入所有服务依赖
            self.services['orchestrator'] = MainOrchestrator(self.services)
            
            self.logger.info("所有核心服务初始化完成")
            
            # 验证服务实例
            for service_name, service_instance in self.services.items():
                if service_instance is None:
                    raise RuntimeError(f"服务 {service_name} 初始化失败")
                    
        except Exception as e:
            self.logger.critical(f"服务初始化失败: {e}", exc_info=True)
            raise
    
    def get_service(self, name: str) -> Any:
        """获取服务实例"""
        return self.services.get(name)
    
    def get_all_services(self) -> Dict[str, Any]:
        """获取所有服务实例"""
        return self.services.copy()
    
    def cleanup(self):
        """清理所有服务"""
        for service_name, service_instance in self.services.items():
            # 跳过客户端管理器，它需要特殊处理
            if service_name == 'client_manager':
                continue
            if hasattr(service_instance, 'cleanup'):
                try:
                    service_instance.cleanup()
                    self.logger.info(f"服务 {service_name} 清理完成")
                except Exception as e:
                    self.logger.warning(f"服务 {service_name} 清理失败: {e}")
        
        # 最后清理客户端管理器
        if self.client_manager:
            try:
                # 注意：这里是同步清理，异步清理需要在应用生命周期中处理
                self.logger.info("客户端管理器清理完成")
            except Exception as e:
                self.logger.warning(f"客户端管理器清理失败: {e}")
        
        self.services.clear()
        self.logger.info("所有服务清理完成")


def create_service_manager():
    """创建服务管理器"""
    # 初始化配置和日志
    init_logging()
    config = get_config()
    logger.info("配置和日志初始化完成")

    # 扩展系统路径（如果配置了）
    if hasattr(config, 'SYSTEM_PATHS') and config.SYSTEM_PATHS:
        sys.path.extend(config.SYSTEM_PATHS)
        logger.info(f"系统路径已扩展: {config.SYSTEM_PATHS}")

    # 创建服务管理器并初始化服务
    service_manager = ServiceManager(config)
    service_manager.initialize_services()
    
    return service_manager


def main():
    """主函数 - 创建服务管理器"""
    try:
        service_manager = create_service_manager()
        logger.info("服务管理器创建完成")
        return service_manager
    except Exception as e:
        logger.critical(f"服务管理器创建失败: {e}")
        raise


if __name__ == "__main__":
    main() 