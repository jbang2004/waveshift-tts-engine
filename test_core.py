#!/usr/bin/env python3
"""
WaveShift TTS Engine - 核心逻辑测试
只测试基本的导入和配置，不依赖外部包
"""
import os
import sys

# 设置函数计算环境
os.environ['FC_FUNC_CODE_PATH'] = '/code'
os.environ['FC_RUNTIME_API'] = 'true'

def test_config():
    """测试配置系统"""
    try:
        from config import get_config, is_fc_environment
        
        # 检查环境检测
        if is_fc_environment():
            print("✅ 函数计算环境检测正确")
        else:
            print("❌ 环境检测失败")
            return False
            
        # 检查配置加载
        config = get_config()
        if config:
            print("✅ 配置加载成功")
            print(f"   环境: {config.environment}")
            return True
        else:
            print("❌ 配置加载失败")
            return False
            
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        return False

def test_launcher_basic():
    """测试launcher基本功能"""
    try:
        from launcher import is_fc_environment
        
        if is_fc_environment():
            print("✅ launcher环境检测正确")
            return True
        else:
            print("❌ launcher环境检测失败")
            return False
            
    except Exception as e:
        print(f"❌ launcher测试失败: {e}")
        return False

def test_handler_structure():
    """测试handler文件结构"""
    try:
        # 检查handler.py是否存在
        if os.path.exists('handler.py'):
            print("✅ handler.py文件存在")
        else:
            print("❌ handler.py文件不存在")
            return False
            
        # 检查内容结构
        with open('handler.py', 'r') as f:
            content = f.read()
            
        if 'def handler(event, context):' in content:
            print("✅ handler函数定义正确")
        else:
            print("❌ handler函数定义错误")
            return False
            
        if 'async def handle_request' in content:
            print("✅ 异步请求处理函数存在")
        else:
            print("❌ 异步请求处理函数缺失")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ handler结构测试失败: {e}")
        return False

def test_dockerfile():
    """测试Dockerfile配置"""
    try:
        if os.path.exists('Dockerfile'):
            print("✅ Dockerfile存在")
        else:
            print("❌ Dockerfile不存在")
            return False
            
        with open('Dockerfile', 'r') as f:
            content = f.read()
            
        if 'handler.py' in content:
            print("✅ Dockerfile引用了正确的handler")
        else:
            print("❌ Dockerfile引用错误")
            return False
            
        if 'fc_handler' in content:
            print("❌ Dockerfile仍然引用旧的fc_handler")
            return False
            
        print("✅ Dockerfile配置正确")
        return True
        
    except Exception as e:
        print(f"❌ Dockerfile测试失败: {e}")
        return False

def main():
    """运行所有测试"""
    print("🧪 WaveShift TTS引擎核心逻辑测试")
    print("=" * 50)
    
    tests = [
        ("配置系统", test_config),
        ("Launcher基础功能", test_launcher_basic),
        ("Handler结构", test_handler_structure),
        ("Dockerfile配置", test_dockerfile),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🔄 执行测试: {test_name}")
        print("-" * 30)
        
        try:
            if test_func():
                passed += 1
            else:
                print(f"❌ {test_name} 失败")
        except Exception as e:
            print(f"❌ {test_name} 异常: {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 核心逻辑测试全部通过！")
        print("💡 最小化修改方案架构正确！")
        return True
    else:
        print(f"⚠️ {total - passed} 个测试失败")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)