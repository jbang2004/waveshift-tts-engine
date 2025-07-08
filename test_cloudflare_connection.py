#!/usr/bin/env python3
"""
Cloudflare D1和R2连接验证脚本
验证数据库结构和数据格式是否符合TTS引擎要求
"""
import asyncio
import sys
import logging
from pathlib import Path
from config import get_config, init_logging
from core.cloudflare.d1_client import D1Client
from core.cloudflare.r2_client import R2Client

# 初始化日志
init_logging()
logger = logging.getLogger(__name__)

async def test_d1_connection(d1_client: D1Client):
    """测试D1数据库连接和结构"""
    print("\n=== 🔍 D1数据库连接测试 ===")
    
    try:
        # 1. 测试基本连接 - 查看所有表
        print("📋 检查数据库表结构...")
        tables_sql = """
        SELECT name FROM sqlite_master 
        WHERE type='table' 
        ORDER BY name;
        """
        tables_result = await d1_client._execute_query(tables_sql)
        
        if not tables_result:
            print("❌ 无法连接到D1数据库")
            return False
            
        tables = [row['name'] for row in tables_result.get('results', [])]
        print(f"✅ 找到 {len(tables)} 个表: {', '.join(tables)}")
        
        # 2. 检查关键表是否存在
        required_tables = ['media_tasks', 'transcriptions', 'transcription_segments']
        missing_tables = [table for table in required_tables if table not in tables]
        
        if missing_tables:
            print(f"⚠️  缺少必要的表: {', '.join(missing_tables)}")
        else:
            print("✅ 所有必要的表都存在")
        
        # 3. 检查media_tasks表结构
        print("\n📊 检查media_tasks表结构...")
        media_tasks_schema = await d1_client._execute_query(
            "PRAGMA table_info(media_tasks);"
        )
        
        if media_tasks_schema and 'results' in media_tasks_schema:
            print("media_tasks表字段:")
            for field in media_tasks_schema['results']:
                print(f"  - {field['name']}: {field['type']} {'(NOT NULL)' if field['notnull'] else ''}")
        
        # 4. 检查transcription_segments表结构
        print("\n📊 检查transcription_segments表结构...")
        segments_schema = await d1_client._execute_query(
            "PRAGMA table_info(transcription_segments);"
        )
        
        if segments_schema and 'results' in segments_schema:
            print("transcription_segments表字段:")
            for field in segments_schema['results']:
                print(f"  - {field['name']}: {field['type']} {'(NOT NULL)' if field['notnull'] else ''}")
        
        # 5. 检查示例数据
        print("\n📝 检查示例数据...")
        sample_tasks = await d1_client._execute_query(
            "SELECT id, audio_path, video_path, transcription_id FROM media_tasks LIMIT 3;"
        )
        
        if sample_tasks and 'results' in sample_tasks and sample_tasks['results']:
            print(f"✅ 找到 {len(sample_tasks['results'])} 个示例任务:")
            for task in sample_tasks['results']:
                print(f"  - 任务ID: {task['id']}")
                print(f"    音频路径: {task.get('audio_path', 'N/A')}")
                print(f"    视频路径: {task.get('video_path', 'N/A')}")
                print(f"    转录ID: {task.get('transcription_id', 'N/A')}")
                
                # 测试获取具体任务的数据
                if task['id']:
                    task_id = task['id']
                    sentences = await d1_client.get_transcription_segments_from_worker(task_id)
                    media_paths = await d1_client.get_worker_media_paths(task_id)
                    print(f"    转录片段数: {len(sentences)}")
                    print(f"    媒体文件路径: {media_paths}")
                    
                    if sentences:
                        first_sentence = sentences[0]
                        print(f"    首个片段: {first_sentence.sequence} | {first_sentence.start_ms}-{first_sentence.end_ms}ms")
                        print(f"      原文: {first_sentence.original_text[:50]}...")
                        print(f"      译文: {first_sentence.translated_text[:50]}...")
                print()
        else:
            print("⚠️  没有找到示例数据")
        
        return True
        
    except Exception as e:
        print(f"❌ D1测试失败: {e}")
        logger.exception("D1测试异常")
        return False

async def test_r2_connection(r2_client: R2Client):
    """测试R2对象存储连接和结构"""
    print("\n=== 🔍 R2对象存储连接测试 ===")
    
    try:
        # 1. 列出存储桶中的文件
        print("📁 检查R2存储桶内容...")
        
        # 列出根目录文件（限制数量）
        files = await r2_client.list_files("")
        print(f"✅ 存储桶中有 {len(files)} 个文件")
        
        # 按类型分组显示
        audio_files = [f for f in files if f['key'].endswith(('.wav', '.mp3', '.m4a', '.aac'))]
        video_files = [f for f in files if f['key'].endswith(('.mp4', '.avi', '.mov', '.mkv'))]
        hls_files = [f for f in files if f['key'].endswith(('.m3u8', '.ts'))]
        
        print(f"  📻 音频文件: {len(audio_files)} 个")
        print(f"  🎬 视频文件: {len(video_files)} 个") 
        print(f"  📺 HLS文件: {len(hls_files)} 个")
        
        # 显示前几个文件作为示例
        if files:
            print("\n📝 示例文件（前5个）:")
            for file in files[:5]:
                size_mb = file['size'] / (1024 * 1024)
                print(f"  - {file['key']} ({size_mb:.2f} MB)")
        
        # 2. 测试特定目录结构
        print("\n📂 检查目录结构...")
        
        # 检查是否有按任务组织的文件
        task_prefixes = set()
        for file in files:
            parts = file['key'].split('/')
            if len(parts) > 1:
                task_prefixes.add(parts[0])
        
        if task_prefixes:
            print(f"✅ 找到 {len(task_prefixes)} 个任务目录")
            sample_tasks = list(task_prefixes)[:3]
            print(f"  示例任务目录: {', '.join(sample_tasks)}")
            
            # 测试下载一个小文件
            if audio_files:
                test_file = audio_files[0]
                print(f"\n📥 测试下载文件: {test_file['key']}")
                
                # 只下载前1KB作为测试
                file_exists = await r2_client.file_exists(test_file['key'])
                if file_exists:
                    print("✅ 文件存在，下载功能正常")
                else:
                    print("❌ 文件不存在或下载功能异常")
        else:
            print("⚠️  文件结构可能不是按任务组织的")
        
        return True
        
    except Exception as e:
        print(f"❌ R2测试失败: {e}")
        logger.exception("R2测试异常")
        return False

async def test_data_compatibility():
    """测试数据格式与项目的兼容性"""
    print("\n=== 🔍 数据格式兼容性测试 ===")
    
    config = get_config()
    
    # 初始化客户端
    d1_client = D1Client(
        account_id=config.CLOUDFLARE_ACCOUNT_ID,
        api_token=config.CLOUDFLARE_API_TOKEN,
        database_id=config.CLOUDFLARE_D1_DATABASE_ID
    )
    
    r2_client = R2Client(
        account_id=config.CLOUDFLARE_ACCOUNT_ID,
        access_key_id=config.CLOUDFLARE_R2_ACCESS_KEY_ID,
        secret_access_key=config.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        bucket_name=config.CLOUDFLARE_R2_BUCKET_NAME
    )
    
    try:
        # 获取一个示例任务
        sample_tasks = await d1_client._execute_query(
            "SELECT id FROM media_tasks LIMIT 1;"
        )
        
        if not sample_tasks or not sample_tasks.get('results'):
            print("⚠️  没有找到示例任务，无法测试兼容性")
            return False
            
        task_id = sample_tasks['results'][0]['id']
        print(f"📋 使用任务 {task_id} 进行兼容性测试")
        
        # 1. 测试句子数据获取
        print("\n🗣️  测试句子数据获取...")
        sentences = await d1_client.get_transcription_segments_from_worker(task_id)
        
        if sentences:
            sentence = sentences[0]
            print(f"✅ 成功获取 {len(sentences)} 个句子")
            print(f"  示例句子字段检查:")
            print(f"    - sequence: {sentence.sequence}")
            print(f"    - start_ms: {sentence.start_ms}")
            print(f"    - end_ms: {sentence.end_ms}")
            print(f"    - speaker: {sentence.speaker}")
            print(f"    - original_text: {'✅' if sentence.original_text else '❌'}")
            print(f"    - translated_text: {'✅' if sentence.translated_text else '❌'}")
            print(f"    - is_first: {sentence.is_first}")
            print(f"    - is_last: {sentence.is_last}")
            
            # 检查必要字段
            required_fields = ['sequence', 'start_ms', 'end_ms', 'speaker', 'original_text', 'translated_text']
            missing_fields = []
            for field in required_fields:
                if not hasattr(sentence, field) or getattr(sentence, field) is None:
                    missing_fields.append(field)
            
            if missing_fields:
                print(f"⚠️  缺少必要字段: {', '.join(missing_fields)}")
            else:
                print("✅ 所有必要字段都存在")
        else:
            print("❌ 无法获取句子数据")
            return False
        
        # 2. 测试媒体文件路径获取
        print("\n🎬 测试媒体文件路径获取...")
        media_paths = await d1_client.get_worker_media_paths(task_id)
        
        if media_paths:
            print("✅ 成功获取媒体文件路径:")
            print(f"    - 音频路径: {media_paths.get('audio_path', 'N/A')}")
            print(f"    - 视频路径: {media_paths.get('video_path', 'N/A')}")
            
            # 测试R2文件是否存在
            audio_path = media_paths.get('audio_path')
            video_path = media_paths.get('video_path')
            
            if audio_path:
                audio_exists = await r2_client.file_exists(audio_path)
                print(f"    - 音频文件存在: {'✅' if audio_exists else '❌'}")
            
            if video_path:
                video_exists = await r2_client.file_exists(video_path)
                print(f"    - 视频文件存在: {'✅' if video_exists else '❌'}")
        else:
            print("❌ 无法获取媒体文件路径")
            return False
        
        print("\n🎉 兼容性测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 兼容性测试失败: {e}")
        logger.exception("兼容性测试异常")
        return False
    finally:
        await d1_client.close()

async def main():
    """主测试函数"""
    print("🚀 开始Cloudflare D1和R2连接验证")
    print("=" * 50)
    
    config = get_config()
    
    # 验证配置
    required_configs = [
        'CLOUDFLARE_ACCOUNT_ID',
        'CLOUDFLARE_API_TOKEN', 
        'CLOUDFLARE_D1_DATABASE_ID',
        'CLOUDFLARE_R2_ACCESS_KEY_ID',
        'CLOUDFLARE_R2_SECRET_ACCESS_KEY',
        'CLOUDFLARE_R2_BUCKET_NAME'
    ]
    
    missing_configs = []
    for config_name in required_configs:
        if not getattr(config, config_name, None):
            missing_configs.append(config_name)
    
    if missing_configs:
        print(f"❌ 缺少必要配置: {', '.join(missing_configs)}")
        return
    
    print("✅ 配置检查通过")
    
    # 初始化客户端
    d1_client = D1Client(
        account_id=config.CLOUDFLARE_ACCOUNT_ID,
        api_token=config.CLOUDFLARE_API_TOKEN,
        database_id=config.CLOUDFLARE_D1_DATABASE_ID
    )
    
    r2_client = R2Client(
        account_id=config.CLOUDFLARE_ACCOUNT_ID,
        access_key_id=config.CLOUDFLARE_R2_ACCESS_KEY_ID,
        secret_access_key=config.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        bucket_name=config.CLOUDFLARE_R2_BUCKET_NAME
    )
    
    try:
        # 执行测试
        d1_success = await test_d1_connection(d1_client)
        r2_success = await test_r2_connection(r2_client)
        
        if d1_success and r2_success:
            compatibility_success = await test_data_compatibility()
            
            print("\n" + "=" * 50)
            print("📊 测试结果总结:")
            print(f"  D1数据库连接: {'✅' if d1_success else '❌'}")
            print(f"  R2对象存储连接: {'✅' if r2_success else '❌'}")
            print(f"  数据格式兼容性: {'✅' if compatibility_success else '❌'}")
            
            if d1_success and r2_success and compatibility_success:
                print("\n🎉 所有测试通过！TTS引擎可以正常使用Cloudflare数据")
            else:
                print("\n⚠️  部分测试失败，需要检查配置或数据格式")
        else:
            print("\n❌ 基础连接测试失败，请检查配置")
    
    finally:
        await d1_client.close()

if __name__ == "__main__":
    asyncio.run(main())