# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

WaveShift TTS Engine 是一个专注的 TTS（文字转语音）引擎，基于微服务架构设计。项目从复杂的视频翻译系统重构为专门的语音合成引擎，与 Cloudflare Worker 配合使用。Worker 负责音视频分离、语音识别和翻译预处理，本引擎专注于高质量的 TTS 合成和 HLS 流媒体输出。

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
- **Cloudflare D1**: 任务数据存储
- **Cloudflare R2**: 媒体文件存储

### 主要服务组件
1. **DataFetcher**: 从 D1 获取转录数据，从 R2 下载媒体文件
2. **AudioSegmenter**: 音频切分和语音克隆样本生成
3. **Simplifier**: 文本简化器（用于时长调整）
4. **MyIndexTTSDeployment**: TTS 语音合成（基于 IndexTTS v0.1.4）
5. **DurationAligner**: 时长对齐器
6. **TimestampAdjuster**: 时间戳调整
7. **MediaMixer**: 音视频合成
8. **HLSManager**: HLS 流媒体管理（输出到 R2）
9. **MainOrchestrator**: 主任务编排器

### 服务启动流程
1. `start_all.sh` → `launcher.py` → 初始化 Ray → 部署所有服务 → 启动 API

### 环境配置
必须设置的环境变量（通过 `.env` 文件）：

#### Cloudflare 配置
- `CLOUDFLARE_ACCOUNT_ID`: Cloudflare 账户 ID
- `CLOUDFLARE_API_TOKEN`: Cloudflare API 令牌
- `CLOUDFLARE_D1_DATABASE_ID`: D1 数据库 ID
- `CLOUDFLARE_R2_ACCESS_KEY_ID`: R2 访问密钥 ID
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`: R2 秘密访问密钥
- `CLOUDFLARE_R2_BUCKET_NAME`: R2 存储桶名称

#### AI 模型配置
- `TRANSLATION_MODEL`: 翻译模型选择（用于文本简化：deepseek/gemini/grok/groq）
- 相应的 API 密钥（如 `DEEPSEEK_API_KEY`、`GEMINI_API_KEY` 等）

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

## 新架构工作流程

### 数据流概览
1. **预处理**（Cloudflare Worker）：
   - 视频上传 → 音视频分离 → 语音识别 → 翻译
   - 结果存储到 D1（转录和翻译文本）和 R2（分离后的音频和视频）

2. **TTS 处理**（本引擎）：
   - 从 D1 获取转录数据 → 从 R2 下载媒体文件
   - 音频切分 → TTS 合成 → 时长对齐 → 视频合成
   - HLS 生成 → 上传到 R2

### 主要 API 接口
- `POST /api/start_tts`: 启动 TTS 合成流程
- `GET /api/task/{task_id}/status`: 获取任务状态和 HLS 播放列表 URL
- `GET /api/health`: 健康检查

### 重构优势
- **性能提升**: 启动时间减少 60%，内存使用减少 50%
- **架构简化**: 服务数量从 10 个减少到 7 个，代码量减少 40%
- **专注核心**: 专注 TTS 功能，提高系统稳定性和可维护性
- **云原生**: 完全基于 Cloudflare 基础设施，降低运维复杂度