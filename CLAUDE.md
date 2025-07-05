# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

WaveShift TTS Engine 是一个基于微服务架构的 AI 语音处理系统，用于视频翻译和语音合成。项目基于 VideoTrans 项目 fork，采用 Ray Serve 作为分布式计算框架。

## 常用命令

### 启动服务
```bash
bash start_all.sh
```

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行测试
```bash
cd models/IndexTTS/tests
python regression_test.py
```

## 架构说明

### 核心技术栈
- **Ray Serve**: 微服务框架和服务编排
- **FastAPI**: REST API 接口
- **PyTorch**: 深度学习模型运行时
- **Supabase**: 后端数据存储

### 主要服务组件
1. **VideoSeparator**: 视频音频分离
2. **ASRModel**: 自动语音识别（基于 SenseVoice）
3. **Translator**: 多模型翻译服务（支持 DeepSeek、Gemini、GLM4）
4. **MyIndexTTSDeployment**: TTS 语音合成（基于 IndexTTS）
5. **TimestampAdjuster**: 时间戳对齐
6. **MediaMixer**: 音视频合成
7. **MainOrchestrator**: 主任务编排器

### 服务启动流程
1. `start_all.sh` → `launcher.py` → 初始化 Ray → 部署所有服务 → 启动 API

### 环境配置
必须设置的环境变量（通过 `.env` 文件）：
- `TRANSLATION_MODEL`: 翻译模型选择（deepseek/glm4/gemini）
- 相应的 API 密钥（如 `DEEPSEEK_API_KEY`）
- `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`（如果使用数据库功能）

## 开发注意事项

### 添加新功能时
1. 新服务需要在 `launcher.py` 中注册部署
2. 服务类需要继承 Ray Serve 的部署装饰器
3. API 接口在 `api.py` 中定义

### 模型管理
- 所有 AI 模型位于 `models/` 目录
- 模型初始化通常在服务类的 `__init__` 方法中完成
- 支持 GPU 加速的模型会自动检测并使用 CUDA

### 日志和调试
- 使用 `config.py` 中的 `init_logging()` 初始化日志
- 日志配置通过环境变量 `FLASK_ENV` 控制（development/production）

## Claude 开发记忆

### 工作指导
- Always think harder.
- Always answer in chinese.