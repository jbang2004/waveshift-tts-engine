#!/usr/bin/env python3
"""
测试TTS音频保存功能
"""
import asyncio
import os
from core.sentence_tools import Sentence
from core.my_index_tts import MyIndexTTSDeployment
from config import get_config

async def test_tts_save():
    """测试TTS音频保存功能"""
    # 获取配置
    config = get_config()
    print(f"SAVE_TTS_AUDIO配置: {config.SAVE_TTS_AUDIO}")
    
    # 创建测试句子
    task_id = "test_task_001"
    sentences = [
        Sentence(
            original_text="Hello world",
            translated_text="你好世界",
            sequence=1,
            speaker="speaker1",
            start_ms=0,
            end_ms=2000,
            task_id=task_id,
            audio="/home/jbang/codebase/waveshift-tts-engine/models/IndexTTS/tests/sample_prompt.wav"
        ),
        Sentence(
            original_text="This is a test",
            translated_text="这是一个测试",
            sequence=2,
            speaker="speaker1",
            start_ms=2000,
            end_ms=4000,
            task_id=task_id,
            audio="/home/jbang/codebase/waveshift-tts-engine/models/IndexTTS/tests/sample_prompt.wav"
        )
    ]
    
    # 创建TTS服务
    tts_service = MyIndexTTSDeployment(config)
    
    # 生成音频
    print(f"\n开始为 {len(sentences)} 个句子生成TTS音频...")
    
    try:
        batch_count = 0
        async for batch in tts_service.generate_audio_stream(sentences):
            batch_count += 1
            print(f"\n批次 {batch_count} 完成，包含 {len(batch)} 个句子:")
            
            for sentence in batch:
                if hasattr(sentence, 'tts_audio_path') and sentence.tts_audio_path:
                    print(f"  - 句子 {sentence.sequence}: {sentence.translated_text}")
                    print(f"    音频保存到: {sentence.tts_audio_path}")
                    print(f"    时长: {sentence.duration:.1f}ms")
                else:
                    print(f"  - 句子 {sentence.sequence}: 没有生成音频或未保存")
        
        # 检查生成的文件
        print("\n检查生成的音频文件:")
        from utils.path_manager import PathManager
        path_manager = PathManager(task_id)
        tts_output_dir = path_manager.temp.tts_output_dir
        
        if tts_output_dir.exists():
            files = list(tts_output_dir.glob("*.wav"))
            print(f"找到 {len(files)} 个音频文件:")
            for file in sorted(files):
                size = file.stat().st_size / 1024  # KB
                print(f"  - {file.name} ({size:.1f} KB)")
        else:
            print("TTS输出目录不存在")
            
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 确保环境变量设置正确
    os.environ["SAVE_TTS_AUDIO"] = "true"
    
    print("TTS音频保存功能测试")
    print("=" * 50)
    
    # 运行测试
    asyncio.run(test_tts_save())