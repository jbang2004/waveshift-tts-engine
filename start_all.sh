#!/bin/bash

# WaveShift TTS Engine 启动脚本
set -e

echo "=== 启动 WaveShift TTS Engine ==="

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi

# 检查必要的环境变量
if [ -z "$CLOUDFLARE_ACCOUNT_ID" ] || [ -z "$CLOUDFLARE_API_TOKEN" ] || [ -z "$CLOUDFLARE_R2_BUCKET_NAME" ]; then
    echo "警告: 未设置 Cloudflare 相关环境变量"
    echo "请确保 .env 文件存在并包含必要的配置"
fi

# 启动服务
echo "启动 TTS 引擎服务..."
cd "$(dirname "$0")"
python3 launcher.py

echo "=== TTS 引擎服务启动完成 ==="