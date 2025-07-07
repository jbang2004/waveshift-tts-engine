"""
最小化的流水线框架基础类
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Any

logger = logging.getLogger(__name__)


class Step(ABC):
    """流水线步骤基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"Step.{name}")
    
    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        执行步骤
        
        Args:
            context: 流水线上下文，包含task_id和其他数据
            
        Returns:
            Tuple[bool, str]: (是否成功, 错误信息或None)
        """
        pass


class Pipeline:
    """简化的流水线执行器"""
    
    def __init__(self, name: str, steps: List[Step]):
        self.name = name
        self.steps = steps
        self.logger = logging.getLogger(f"Pipeline.{name}")
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行流水线
        
        Args:
            context: 包含task_id的上下文字典
            
        Returns:
            Dict: {"status": "success/error", "message": str, "data": context}
        """
        task_id = context.get('task_id', 'unknown')
        self.logger.info(f"[{task_id}] 开始执行流水线: {self.name}")
        
        for step in self.steps:
            self.logger.info(f"[{task_id}] 执行步骤: {step.name}")
            
            try:
                success, error_msg = await step.execute(context)
                
                if success:
                    self.logger.info(f"[{task_id}] 步骤 {step.name} 成功完成")
                else:
                    self.logger.error(f"[{task_id}] 步骤 {step.name} 失败: {error_msg}")
                    return {
                        "status": "error",
                        "message": f"步骤 {step.name} 失败: {error_msg}",
                        "failed_step": step.name
                    }
                    
            except Exception as e:
                error_msg = f"步骤 {step.name} 异常: {e}"
                self.logger.exception(f"[{task_id}] {error_msg}")
                return {
                    "status": "error",
                    "message": error_msg,
                    "failed_step": step.name
                }
        
        self.logger.info(f"[{task_id}] 流水线 {self.name} 执行成功")
        return {
            "status": "success",
            "message": f"流水线 {self.name} 执行成功",
            "data": context
        }