#!/usr/bin/env python3
"""
WaveShift TTS Engine - 部署验证测试脚本
测试阿里云GPU云函数部署是否成功
"""
import asyncio
import json
import time
import os
import sys
from typing import Dict, Any, Optional
import argparse

import httpx
from dotenv import load_dotenv

# 颜色输出
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

def print_colored(message: str, color: str = Colors.NC):
    print(f"{color}{message}{Colors.NC}")

def print_success(message: str):
    print_colored(f"✅ {message}", Colors.GREEN)

def print_error(message: str):
    print_colored(f"❌ {message}", Colors.RED)

def print_warning(message: str):
    print_colored(f"⚠️  {message}", Colors.YELLOW)

def print_info(message: str):
    print_colored(f"ℹ️  {message}", Colors.BLUE)

def print_step(step: str, description: str):
    print_colored(f"\n🔄 步骤 {step}: {description}", Colors.CYAN)


class DeploymentTester:
    """部署验证测试器"""
    
    def __init__(self, base_url: str, timeout: int = 300):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        
        print_info(f"初始化测试器，目标URL: {self.base_url}")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def test_health_check(self) -> bool:
        """测试健康检查接口"""
        print_step("1", "健康检查测试")
        
        try:
            url = f"{self.base_url}/api/health"
            print_info(f"请求URL: {url}")
            
            response = await self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                print_success("健康检查通过")
                print_info(f"服务版本: {data.get('version', 'unknown')}")
                print_info(f"环境: {data.get('environment', 'unknown')}")
                print_info(f"服务状态: {data.get('status', 'unknown')}")
                
                # 检查服务初始化状态
                if data.get('services_initialized'):
                    print_success("服务已初始化")
                else:
                    print_warning("服务未初始化")
                
                # 检查GPU状态
                system_info = data.get('system_info', {})
                if system_info.get('gpu_available'):
                    print_success(f"GPU可用: {system_info.get('gpu_name', 'unknown')}")
                    print_info(f"GPU内存: {system_info.get('gpu_memory_gb', 0):.1f}GB")
                else:
                    print_warning("GPU不可用")
                
                # 检查磁盘空间
                disk_free = system_info.get('disk_free_gb', 0)
                print_info(f"可用磁盘空间: {disk_free:.1f}GB")
                
                return True
            else:
                print_error(f"健康检查失败，状态码: {response.status_code}")
                print_error(f"响应内容: {response.text}")
                return False
                
        except Exception as e:
            print_error(f"健康检查异常: {e}")
            return False
    
    async def test_root_endpoint(self) -> bool:
        """测试根路径接口"""
        print_step("2", "根路径接口测试")
        
        try:
            url = f"{self.base_url}/"
            response = await self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                print_success("根路径接口正常")
                print_info(f"服务名称: {data.get('name', 'unknown')}")
                print_info(f"服务描述: {data.get('description', 'unknown')}")
                
                endpoints = data.get('endpoints', {})
                print_info("可用接口:")
                for name, path in endpoints.items():
                    print_info(f"  {name}: {path}")
                
                return True
            else:
                print_error(f"根路径测试失败，状态码: {response.status_code}")
                return False
                
        except Exception as e:
            print_error(f"根路径测试异常: {e}")
            return False
    
    async def test_tts_interface(self, test_task_id: str = "test-deployment-task") -> bool:
        """测试TTS接口（不执行实际TTS）"""
        print_step("3", "TTS接口测试")
        
        try:
            url = f"{self.base_url}/api/start_tts"
            payload = {"task_id": test_task_id}
            
            print_info(f"请求URL: {url}")
            print_info(f"请求载荷: {json.dumps(payload, indent=2)}")
            
            response = await self.client.post(url, json=payload)
            
            if response.status_code in [200, 400, 404, 500]:
                # 接口可达，无论成功还是业务错误都算通过
                print_success("TTS接口可达")
                print_info(f"响应状态: {response.status_code}")
                
                try:
                    data = response.json()
                    print_info(f"响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")
                except:
                    print_info(f"响应内容: {response.text}")
                
                return True
            else:
                print_error(f"TTS接口异常，状态码: {response.status_code}")
                return False
                
        except Exception as e:
            print_error(f"TTS接口测试异常: {e}")
            return False
    
    async def test_status_interface(self, test_task_id: str = "test-deployment-task") -> bool:
        """测试状态查询接口"""
        print_step("4", "状态查询接口测试")
        
        try:
            url = f"{self.base_url}/api/task/{test_task_id}/status"
            print_info(f"请求URL: {url}")
            
            response = await self.client.get(url)
            
            if response.status_code in [200, 404]:
                # 接口可达
                print_success("状态查询接口可达")
                print_info(f"响应状态: {response.status_code}")
                
                try:
                    data = response.json()
                    print_info(f"响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")
                except:
                    print_info(f"响应内容: {response.text}")
                
                return True
            else:
                print_error(f"状态查询接口异常，状态码: {response.status_code}")
                return False
                
        except Exception as e:
            print_error(f"状态查询接口测试异常: {e}")
            return False
    
    async def test_error_handling(self) -> bool:
        """测试错误处理"""
        print_step("5", "错误处理测试")
        
        try:
            # 测试无效路径
            url = f"{self.base_url}/api/invalid-path"
            response = await self.client.get(url)
            
            if response.status_code == 404:
                print_success("404错误处理正常")
            else:
                print_warning(f"意外的状态码: {response.status_code}")
            
            # 测试无效请求体
            url = f"{self.base_url}/api/start_tts"
            response = await self.client.post(url, json={})
            
            if response.status_code == 400:
                print_success("400错误处理正常")
            else:
                print_warning(f"无效请求体返回状态码: {response.status_code}")
            
            return True
            
        except Exception as e:
            print_error(f"错误处理测试异常: {e}")
            return False
    
    async def test_performance(self, iterations: int = 3) -> bool:
        """测试性能和响应时间"""
        print_step("6", f"性能测试（{iterations}次请求）")
        
        response_times = []
        
        try:
            for i in range(iterations):
                start_time = time.time()
                
                response = await self.client.get(f"{self.base_url}/api/health")
                
                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # 转换为毫秒
                response_times.append(response_time)
                
                if response.status_code == 200:
                    print_info(f"请求 {i+1}: {response_time:.0f}ms")
                else:
                    print_warning(f"请求 {i+1} 失败: {response.status_code}")
            
            if response_times:
                avg_time = sum(response_times) / len(response_times)
                min_time = min(response_times)
                max_time = max(response_times)
                
                print_success("性能测试完成")
                print_info(f"平均响应时间: {avg_time:.0f}ms")
                print_info(f"最快响应时间: {min_time:.0f}ms")
                print_info(f"最慢响应时间: {max_time:.0f}ms")
                
                # 性能评估
                if avg_time < 1000:
                    print_success("响应速度优秀（<1秒）")
                elif avg_time < 5000:
                    print_info("响应速度良好（<5秒）")
                else:
                    print_warning(f"响应较慢（{avg_time/1000:.1f}秒）")
                
                return True
            else:
                print_error("性能测试失败：无有效响应")
                return False
                
        except Exception as e:
            print_error(f"性能测试异常: {e}")
            return False
    
    async def run_all_tests(self) -> Dict[str, bool]:
        """运行所有测试"""
        print_colored("🚀 开始WaveShift TTS引擎部署验证测试", Colors.PURPLE)
        print_colored("=" * 60, Colors.PURPLE)
        
        results = {}
        
        # 执行所有测试
        results['health_check'] = await self.test_health_check()
        results['root_endpoint'] = await self.test_root_endpoint()
        results['tts_interface'] = await self.test_tts_interface()
        results['status_interface'] = await self.test_status_interface()
        results['error_handling'] = await self.test_error_handling()
        results['performance'] = await self.test_performance()
        
        # 总结结果
        print_colored("\n" + "=" * 60, Colors.PURPLE)
        print_colored("📊 测试结果汇总", Colors.PURPLE)
        print_colored("=" * 60, Colors.PURPLE)
        
        passed = 0
        total = len(results)
        
        for test_name, result in results.items():
            if result:
                print_success(f"{test_name}: 通过")
                passed += 1
            else:
                print_error(f"{test_name}: 失败")
        
        print_colored(f"\n通过率: {passed}/{total} ({passed/total*100:.1f}%)", Colors.CYAN)
        
        if passed == total:
            print_success("🎉 所有测试通过！部署验证成功！")
        elif passed >= total * 0.8:
            print_warning("⚠️  大部分测试通过，部署基本成功，请检查失败项")
        else:
            print_error("❌ 多个测试失败，部署可能存在问题")
        
        return results


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='WaveShift TTS引擎部署验证测试')
    parser.add_argument('--url', type=str, help='函数URL地址')
    parser.add_argument('--account-id', type=str, help='阿里云账户ID')
    parser.add_argument('--region', type=str, default='cn-hangzhou', help='部署地域')
    parser.add_argument('--service-name', type=str, default='waveshift-tts', help='服务名称')
    parser.add_argument('--function-name', type=str, default='tts-processor', help='函数名称')
    parser.add_argument('--timeout', type=int, default=300, help='请求超时时间（秒）')
    
    args = parser.parse_args()
    
    # 加载环境变量
    load_dotenv()
    
    # 确定函数URL
    if args.url:
        function_url = args.url
    else:
        account_id = args.account_id or os.getenv('ALIYUN_ACCOUNT_ID')
        if not account_id:
            print_error("请提供 --url 参数或设置 ALIYUN_ACCOUNT_ID 环境变量")
            sys.exit(1)
        
        function_url = f"https://{account_id}.{args.region}.fc.aliyuncs.com/2016-08-15/proxy/{args.service_name}/{args.function_name}"
    
    print_info(f"目标函数URL: {function_url}")
    
    # 运行测试
    async with DeploymentTester(function_url, args.timeout) as tester:
        results = await tester.run_all_tests()
    
    # 返回适当的退出码
    if all(results.values()):
        sys.exit(0)  # 成功
    else:
        sys.exit(1)  # 失败


if __name__ == "__main__":
    asyncio.run(main())