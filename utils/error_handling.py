"""
统一的错误处理装饰器 - 消除重复的错误处理逻辑
"""
import logging
import functools
from typing import Callable, Any, Dict, Optional, Union, List, Type
from enum import Enum
import asyncio
import traceback

logger = logging.getLogger(__name__)


class ErrorHandlingStrategy(Enum):
    """错误处理策略枚举"""
    LOG_AND_RAISE = "log_and_raise"        # 记录日志并重新抛出异常
    LOG_AND_RETURN = "log_and_return"      # 记录日志并返回默认值
    SILENT_RETURN = "silent_return"        # 静默返回默认值
    CUSTOM_HANDLER = "custom_handler"      # 使用自定义处理器


class ServiceError(Exception):
    """服务错误基类"""
    
    def __init__(self, message: str, error_code: str = None, details: Dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "UNKNOWN_ERROR"
        self.details = details or {}


class APIError(ServiceError):
    """API调用错误"""
    pass


class ValidationError(ServiceError):
    """数据验证错误"""
    pass


class ConfigurationError(ServiceError):
    """配置错误"""
    pass


def handle_service_errors(
    strategy: ErrorHandlingStrategy = ErrorHandlingStrategy.LOG_AND_RAISE,
    default_return: Any = None,
    custom_handler: Optional[Callable] = None,
    catch_types: Optional[List[Type[Exception]]] = None,
    log_level: str = "ERROR",
    include_traceback: bool = True,
    error_prefix: str = ""
):
    """
    统一的服务错误处理装饰器
    
    Args:
        strategy: 错误处理策略
        default_return: 默认返回值（当strategy为LOG_AND_RETURN或SILENT_RETURN时使用）
        custom_handler: 自定义错误处理函数
        catch_types: 要捕获的异常类型列表，默认捕获所有Exception
        log_level: 日志级别 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        include_traceback: 是否包含堆栈跟踪
        error_prefix: 错误日志前缀
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                return _handle_exception(
                    e, func, args, kwargs, strategy, default_return, 
                    custom_handler, catch_types, log_level, include_traceback, error_prefix
                )
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return _handle_exception(
                    e, func, args, kwargs, strategy, default_return,
                    custom_handler, catch_types, log_level, include_traceback, error_prefix
                )
        
        # 判断是否为异步函数
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def _handle_exception(
    exception: Exception,
    func: Callable,
    args: tuple,
    kwargs: dict,
    strategy: ErrorHandlingStrategy,
    default_return: Any,
    custom_handler: Optional[Callable],
    catch_types: Optional[List[Type[Exception]]],
    log_level: str,
    include_traceback: bool,
    error_prefix: str
) -> Any:
    """内部异常处理逻辑"""
    
    # 检查是否为指定的异常类型
    if catch_types and not any(isinstance(exception, catch_type) for catch_type in catch_types):
        raise exception
    
    # 构建错误信息
    func_name = f"{func.__module__}.{func.__qualname__}"
    error_msg = f"{error_prefix}{func_name} 执行失败: {type(exception).__name__}: {exception}"
    
    # 获取调用上下文（如果有task_id等参数）
    context = _extract_context(args, kwargs)
    if context:
        error_msg = f"[{context}] {error_msg}"
    
    # 记录日志
    if strategy != ErrorHandlingStrategy.SILENT_RETURN:
        log_func = getattr(logger, log_level.lower(), logger.error)
        
        if include_traceback:
            log_func(error_msg, exc_info=True)
        else:
            log_func(error_msg)
    
    # 根据策略处理异常
    if strategy == ErrorHandlingStrategy.LOG_AND_RAISE:
        raise exception
    elif strategy == ErrorHandlingStrategy.LOG_AND_RETURN:
        return default_return
    elif strategy == ErrorHandlingStrategy.SILENT_RETURN:
        return default_return
    elif strategy == ErrorHandlingStrategy.CUSTOM_HANDLER:
        if custom_handler:
            return custom_handler(exception, func, args, kwargs)
        else:
            logger.warning(f"未提供自定义处理器，使用默认LOG_AND_RAISE策略")
            raise exception
    else:
        raise exception


def _extract_context(args: tuple, kwargs: dict) -> Optional[str]:
    """从函数参数中提取上下文信息（如task_id）"""
    # 尝试从kwargs中获取task_id
    if 'task_id' in kwargs:
        return kwargs['task_id']
    
    # 尝试从args中获取task_id（通常是第一个参数）
    if args:
        first_arg = args[0]
        if isinstance(first_arg, str) and len(first_arg) > 0:
            return first_arg
        # 如果第一个参数是self或cls，检查第二个参数
        if len(args) > 1 and isinstance(args[1], str):
            return args[1]
    
    return None


def create_error_result(
    status: str = "error",
    message: str = "",
    error_code: str = None,
    details: Dict = None
) -> Dict[str, Any]:
    """创建标准化的错误响应"""
    result = {
        "status": status,
        "message": message
    }
    
    if error_code:
        result["error_code"] = error_code
    
    if details:
        result["details"] = details
    
    return result


def api_error_handler(
    default_response: Dict = None,
    log_level: str = "ERROR"
):
    """专门用于API错误处理的装饰器"""
    if default_response is None:
        default_response = create_error_result(message="API调用失败")
    
    def custom_handler(exception: Exception, func: Callable, args: tuple, kwargs: dict) -> Dict:
        if isinstance(exception, APIError):
            return create_error_result(
                message=exception.message,
                error_code=exception.error_code,
                details=exception.details
            )
        else:
            return create_error_result(message=f"未知错误: {exception}")
    
    return handle_service_errors(
        strategy=ErrorHandlingStrategy.CUSTOM_HANDLER,
        custom_handler=custom_handler,
        log_level=log_level
    )


def validation_error_handler(log_level: str = "WARNING"):
    """专门用于数据验证错误处理的装饰器"""
    def custom_handler(exception: Exception, func: Callable, args: tuple, kwargs: dict) -> Dict:
        if isinstance(exception, ValidationError):
            return create_error_result(
                message=f"数据验证失败: {exception.message}",
                error_code=exception.error_code,
                details=exception.details
            )
        else:
            return create_error_result(message=f"验证过程中发生错误: {exception}")
    
    return handle_service_errors(
        strategy=ErrorHandlingStrategy.CUSTOM_HANDLER,
        custom_handler=custom_handler,
        catch_types=[ValidationError, ValueError, TypeError],
        log_level=log_level
    )


# 常用的装饰器快捷方式
def log_and_continue(default_return: Any = None, log_level: str = "ERROR"):
    """记录错误并继续执行（返回默认值）"""
    return handle_service_errors(
        strategy=ErrorHandlingStrategy.LOG_AND_RETURN,
        default_return=default_return,
        log_level=log_level
    )


def log_and_raise(log_level: str = "ERROR", error_prefix: str = ""):
    """记录错误并重新抛出异常"""
    return handle_service_errors(
        strategy=ErrorHandlingStrategy.LOG_AND_RAISE,
        log_level=log_level,
        error_prefix=error_prefix
    )


def silent_fallback(default_return: Any = None):
    """静默处理错误，返回默认值（不记录日志）"""
    return handle_service_errors(
        strategy=ErrorHandlingStrategy.SILENT_RETURN,
        default_return=default_return
    )


# 示例用法
if __name__ == "__main__":
    @log_and_continue(default_return={"status": "error", "message": "默认错误"})
    async def example_service_call(task_id: str):
        """示例服务调用"""
        if task_id == "fail":
            raise APIError("模拟API错误", error_code="API_FAIL")
        return {"status": "success", "data": "success"}
    
    # 测试用例
    async def test():
        result1 = await example_service_call("success")
        print(f"成功结果: {result1}")
        
        result2 = await example_service_call("fail")
        print(f"失败结果: {result2}")
    
    asyncio.run(test())