# 多阶段构建：优化云函数镜像大小
# 基于NVIDIA CUDA 11.8构建，支持GPU推理

# ================================
# 构建阶段：安装Python依赖
# ================================
FROM nvidia/cuda:11.8-devel-ubuntu20.04 as builder

# 设置非交互模式
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    python3.9 \
    python3.9-dev \
    python3.9-distutils \
    python3-pip \
    build-essential \
    wget \
    curl \
    git \
    ffmpeg \
    libsndfile1-dev \
    libsox-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置Python 3.9为默认python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.9 1

# 升级pip
RUN python3 -m pip install --upgrade pip setuptools wheel

# 复制requirements文件
COPY requirements.txt /tmp/requirements.txt

# 创建优化的requirements（移除开发依赖）
RUN echo "# 云函数优化版依赖" > /tmp/fc_requirements.txt && \
    grep -v "^#" /tmp/requirements.txt | \
    grep -v "^$" | \
    # 排除一些大型或不必要的包
    grep -v "jupyter" | \
    grep -v "notebook" | \
    grep -v "tensorboard" >> /tmp/fc_requirements.txt

# 安装Python依赖（使用清华源加速）
RUN pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --no-cache-dir \
    --timeout 300 \
    -r /tmp/fc_requirements.txt

# 安装PyTorch（使用官方源确保CUDA兼容性）
RUN pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# ================================
# 运行阶段：最小化运行时镜像
# ================================
FROM nvidia/cuda:11.8-runtime-ubuntu20.04 as runtime

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CUDA_VISIBLE_DEVICES=0
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# 设置函数计算环境标识
ENV FC_FUNC_CODE_PATH=/code
ENV FC_RUNTIME_API=true

# 安装运行时依赖（最小化）
RUN apt-get update && apt-get install -y \
    python3.9 \
    python3.9-distutils \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    libsox3 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置Python默认版本
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.9 1

# 从构建阶段复制Python依赖
COPY --from=builder /usr/local/lib/python3.9/dist-packages /usr/local/lib/python3.9/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 设置工作目录
WORKDIR /code

# 复制应用代码
COPY . /code/

# 创建必要的目录
RUN mkdir -p /tmp/tasks /tmp/public /tmp/logs && \
    chmod 755 /tmp/tasks /tmp/public /tmp/logs

# 验证关键文件存在
RUN test -f /code/handler.py || (echo "错误: handler.py 不存在" && exit 1)
RUN test -f /code/models/IndexTTS/checkpoints/config.yaml || (echo "错误: IndexTTS配置文件不存在" && exit 1)

# 预编译Python字节码（减少启动时间）
RUN python3 -m compileall /code

# 测试导入关键模块
RUN python3 -c "import torch; print(f'PyTorch版本: {torch.__version__}'); print(f'CUDA可用: {torch.cuda.is_available()}')" && \
    python3 -c "import numpy, scipy, soundfile; print('核心依赖导入成功')" && \
    python3 -c "from handler import handler; print('函数入口导入成功')"

# 清理缓存
RUN find /code -name "*.pyc" -delete && \
    find /code -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# 设置权限
RUN chmod +x /code/handler.py

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "from handler import handler; print('健康检查通过')" || exit 1

# 设置函数入口点
# 阿里云函数计算将调用 handler.handler 函数
CMD ["python3", "-c", "from handler import handler; print('容器启动成功，等待函数调用...')"]

# 镜像元数据
LABEL maintainer="WaveShift TTS Team"
LABEL version="2.0.0-fc"
LABEL description="WaveShift TTS Engine for Alibaba Cloud Function Compute with GPU"
LABEL cuda.version="11.8"
LABEL python.version="3.9"