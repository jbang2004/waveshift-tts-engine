# TTS音频保存功能使用说明

## 功能概述

WaveShift TTS Engine 现在支持保存TTS生成的音频文件，方便您试听每个句子的合成效果。

## 如何启用

### 方法1：环境变量

在 `.env` 文件中添加或修改：
```bash
SAVE_TTS_AUDIO=true
```

### 方法2：系统环境变量

在运行程序前设置：
```bash
export SAVE_TTS_AUDIO=true
```

## 文件保存位置

TTS生成的音频文件将保存在临时目录下的 `tts_output` 子目录中：

```
/tmp/tts_{task_id}_*/
└── tts_output/
    ├── sentence_0001_speaker1.wav
    ├── sentence_0002_speaker1.wav
    ├── sentence_0003_speaker2.wav
    └── ...
```

## 文件命名规则

- 格式：`sentence_{序号}_{说话人}.wav`
- 序号：4位数字，按句子在文本中的顺序
- 说话人：自动清理特殊字符（空格替换为下划线）

## 音频格式

- 文件格式：WAV
- 采样率：24000 Hz（根据 TARGET_SR 配置）
- 位深度：32位浮点
- 编码：FLOAT子类型

## 查看生成的音频

### 1. 在处理过程中

查看日志输出，会显示每个音频文件的保存路径：
```
INFO | TTS音频已保存: sentence_0001_speaker1.wav (时长: 1523.5ms)
```

### 2. 任务处理后

在任务完成前，可以到临时目录查看和复制音频文件：
```bash
# 查找最新的TTS任务目录
ls -la /tmp/tts_*

# 查看TTS输出
ls -la /tmp/tts_{task_id}_*/tts_output/

# 复制音频文件到其他位置（如需长期保存）
cp /tmp/tts_{task_id}_*/tts_output/*.wav ~/my_tts_samples/
```

## 注意事项

1. **临时文件**：音频文件保存在临时目录中，任务完成后会自动清理
2. **磁盘空间**：每个句子的音频文件大小通常为几十到几百KB
3. **性能影响**：保存音频会略微增加处理时间，但影响很小
4. **默认启用**：如果不设置环境变量，默认会保存TTS音频

## 禁用功能

如果不需要保存TTS音频，可以设置：
```bash
SAVE_TTS_AUDIO=false
```

## 测试功能

可以运行测试脚本验证功能：
```bash
python test_tts_save.py
```

注意：测试脚本需要有效的音频提示文件路径才能正常运行。

## 与现有功能的兼容性

- 不影响音频切片功能（audio_prompts）
- 不影响最终视频输出
- 不影响HLS流媒体生成
- 完全向后兼容