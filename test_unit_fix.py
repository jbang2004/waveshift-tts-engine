#!/usr/bin/env python3
"""
测试单位修复
"""
from core.sentence_tools import Sentence

def test_duration_units():
    """测试时间单位一致性"""
    # 创建测试句子
    sentence = Sentence(
        original_text="测试句子",
        translated_text="Test sentence", 
        sequence=1,
        speaker="speaker1",
        start_ms=1000.0,  # 1秒
        end_ms=3000.0,    # 3秒，总时长2秒
        task_id="test"
    )
    
    print("=== 句子初始化后的时间值 ===")
    print(f"start_ms: {sentence.start_ms}")
    print(f"end_ms: {sentence.end_ms}")
    print(f"target_duration: {sentence.target_duration} (应该是毫秒)")
    print(f"duration: {sentence.duration}")
    print(f"speech_duration: {sentence.speech_duration}")
    print(f"silence_duration: {sentence.silence_duration}")
    
    # 模拟TTS处理后的duration（毫秒）
    sentence.duration = 2100.0  # 2.1秒的音频
    
    print("\n=== TTS处理后 ===")
    print(f"duration: {sentence.duration} (TTS生成的音频时长，毫秒)")
    print(f"target_duration: {sentence.target_duration} (目标时长，毫秒)")
    
    # 计算diff（现在应该是毫秒 - 毫秒）
    diff = sentence.duration - sentence.target_duration
    print(f"diff: {diff} (应该是100毫秒，而不是1998+)")
    
    # 模拟align_batch中的速度计算
    adjusted_duration = sentence.duration - diff * 0.5  # 假设调整一半
    speed = sentence.duration / max(adjusted_duration, 0.001)
    
    print(f"adjusted_duration: {adjusted_duration}")
    print(f"speed: {speed} (应该是合理值，不是1300+)")
    
    # 验证单位一致性
    assert sentence.target_duration == 2000.0, f"target_duration should be 2000ms, got {sentence.target_duration}"
    assert abs(diff - 100.0) < 0.1, f"diff should be around 100ms, got {diff}"
    assert 0.5 < speed < 2.0, f"speed should be reasonable, got {speed}"
    
    print("\n✅ 单位修复验证通过！")

if __name__ == "__main__":
    test_duration_units()