#!/bin/bash

# WaveShift TTS Engine - 阿里云GPU云函数部署脚本
# 自动化构建镜像并部署到阿里云函数计算

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查必需的命令
check_requirements() {
    print_info "检查部署环境..."
    
    local missing_commands=()
    
    # 检查Docker
    if ! command -v docker &> /dev/null; then
        missing_commands+=("docker")
    fi
    
    # 检查阿里云CLI
    if ! command -v aliyun &> /dev/null; then
        missing_commands+=("aliyun")
    fi
    
    # 检查fun工具（可选）
    if ! command -v fun &> /dev/null; then
        print_warning "Fun工具未安装，将使用阿里云CLI部署"
    fi
    
    if [ ${#missing_commands[@]} -ne 0 ]; then
        print_error "缺少必需的命令: ${missing_commands[*]}"
        print_info "请安装缺少的工具后重试"
        exit 1
    fi
    
    print_success "环境检查通过"
}

# 加载配置
load_config() {
    print_info "加载部署配置..."
    
    # 设置默认值
    REGION=${REGION:-"cn-hangzhou"}
    NAMESPACE=${NAMESPACE:-"waveshift"}
    IMAGE_NAME=${IMAGE_NAME:-"waveshift-tts"}
    IMAGE_TAG=${IMAGE_TAG:-"latest"}
    SERVICE_NAME=${SERVICE_NAME:-"waveshift-tts"}
    FUNCTION_NAME=${FUNCTION_NAME:-"tts-processor"}
    
    # 构建完整的镜像URI
    ACR_ENDPOINT="registry.${REGION}.aliyuncs.com"
    IMAGE_URI="${ACR_ENDPOINT}/${NAMESPACE}/${IMAGE_NAME}:${IMAGE_TAG}"
    
    print_info "配置信息:"
    print_info "  地域: ${REGION}"
    print_info "  命名空间: ${NAMESPACE}"
    print_info "  镜像名称: ${IMAGE_NAME}"
    print_info "  镜像标签: ${IMAGE_TAG}"
    print_info "  镜像URI: ${IMAGE_URI}"
}

# 检查环境变量
check_env_vars() {
    print_info "检查环境变量..."
    
    local required_vars=(
        "CLOUDFLARE_ACCOUNT_ID"
        "CLOUDFLARE_API_TOKEN"
        "CLOUDFLARE_D1_DATABASE_ID"
        "CLOUDFLARE_R2_ACCESS_KEY_ID"
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY"
        "CLOUDFLARE_R2_BUCKET_NAME"
    )
    
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            missing_vars+=("$var")
        fi
    done
    
    if [ ${#missing_vars[@]} -ne 0 ]; then
        print_error "缺少必需的环境变量: ${missing_vars[*]}"
        print_info "请设置环境变量或在.env文件中配置"
        exit 1
    fi
    
    print_success "环境变量检查通过"
}

# 构建Docker镜像
build_image() {
    print_info "开始构建Docker镜像..."
    
    # 检查Dockerfile是否存在
    if [ ! -f "Dockerfile" ]; then
        print_error "Dockerfile不存在"
        exit 1
    fi
    
    # 检查模型文件
    if [ ! -f "models/IndexTTS/checkpoints/config.yaml" ]; then
        print_error "IndexTTS模型文件不存在，请确保模型文件已正确放置"
        exit 1
    fi
    
    # 构建镜像
    print_info "构建镜像: ${IMAGE_URI}"
    docker build -t "${IMAGE_URI}" \
        --platform linux/amd64 \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        .
    
    if [ $? -eq 0 ]; then
        print_success "镜像构建成功"
    else
        print_error "镜像构建失败"
        exit 1
    fi
}

# 推送镜像到ACR
push_image() {
    print_info "推送镜像到阿里云容器镜像服务..."
    
    # 登录ACR
    print_info "登录ACR..."
    docker login --username="${ALIYUN_ACCESS_KEY_ID}" \
                 --password="${ALIYUN_ACCESS_KEY_SECRET}" \
                 "${ACR_ENDPOINT}"
    
    if [ $? -ne 0 ]; then
        print_error "ACR登录失败，请检查阿里云访问密钥"
        exit 1
    fi
    
    # 推送镜像
    print_info "推送镜像: ${IMAGE_URI}"
    docker push "${IMAGE_URI}"
    
    if [ $? -eq 0 ]; then
        print_success "镜像推送成功"
    else
        print_error "镜像推送失败"
        exit 1
    fi
}

# 部署函数
deploy_function() {
    print_info "部署GPU云函数..."
    
    # 检查服务是否存在
    print_info "检查函数计算服务..."
    if aliyun fc GetService --region "${REGION}" --serviceName "${SERVICE_NAME}" &> /dev/null; then
        print_info "服务已存在，将更新函数"
    else
        print_info "创建新的函数计算服务..."
        aliyun fc CreateService \
            --region "${REGION}" \
            --serviceName "${SERVICE_NAME}" \
            --description "WaveShift TTS引擎GPU函数服务" \
            --internetAccess true
    fi
    
    # 部署/更新函数
    print_info "部署TTS处理函数..."
    
    # 构建函数配置
    local function_config=$(cat <<EOF
{
    "functionName": "${FUNCTION_NAME}",
    "description": "GPU加速的TTS语音合成处理函数",
    "runtime": "custom-container",
    "handler": "fc_handler.handler",
    "timeout": 7200,
    "memorySize": 4096,
    "instanceType": "fc.gpu.tesla.1",
    "gpuMemorySize": 8192,
    "instanceConcurrency": 1,
    "customContainerConfig": {
        "image": "${IMAGE_URI}",
        "command": ["python3", "fc_handler.py"]
    },
    "environmentVariables": {
        "CLOUDFLARE_ACCOUNT_ID": "${CLOUDFLARE_ACCOUNT_ID}",
        "CLOUDFLARE_API_TOKEN": "${CLOUDFLARE_API_TOKEN}",
        "CLOUDFLARE_D1_DATABASE_ID": "${CLOUDFLARE_D1_DATABASE_ID}",
        "CLOUDFLARE_R2_ACCESS_KEY_ID": "${CLOUDFLARE_R2_ACCESS_KEY_ID}",
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "${CLOUDFLARE_R2_SECRET_ACCESS_KEY}",
        "CLOUDFLARE_R2_BUCKET_NAME": "${CLOUDFLARE_R2_BUCKET_NAME}",
        "TRANSLATION_MODEL": "${TRANSLATION_MODEL:-deepseek}",
        "DEEPSEEK_API_KEY": "${DEEPSEEK_API_KEY:-}",
        "ENABLE_VOCAL_SEPARATION": "true",
        "SAVE_TTS_AUDIO": "false",
        "CLEANUP_TEMP_FILES": "true",
        "FC_FUNC_CODE_PATH": "/code",
        "FC_RUNTIME_API": "true"
    }
}
EOF
)
    
    # 检查函数是否存在
    if aliyun fc GetFunction --region "${REGION}" --serviceName "${SERVICE_NAME}" --functionName "${FUNCTION_NAME}" &> /dev/null; then
        print_info "更新现有函数..."
        echo "${function_config}" | aliyun fc UpdateFunction \
            --region "${REGION}" \
            --serviceName "${SERVICE_NAME}" \
            --functionName "${FUNCTION_NAME}" \
            --cli-input-json file:///dev/stdin
    else
        print_info "创建新函数..."
        echo "${function_config}" | aliyun fc CreateFunction \
            --region "${REGION}" \
            --serviceName "${SERVICE_NAME}" \
            --cli-input-json file:///dev/stdin
    fi
    
    if [ $? -eq 0 ]; then
        print_success "函数部署成功"
    else
        print_error "函数部署失败"
        exit 1
    fi
}

# 配置HTTP触发器
setup_trigger() {
    print_info "配置HTTP触发器..."
    
    local trigger_config=$(cat <<EOF
{
    "triggerName": "http-trigger",
    "triggerType": "HTTP",
    "triggerConfig": {
        "authType": "ANONYMOUS",
        "methods": ["GET", "POST"]
    }
}
EOF
)
    
    # 检查触发器是否存在
    if aliyun fc GetTrigger --region "${REGION}" --serviceName "${SERVICE_NAME}" --functionName "${FUNCTION_NAME}" --triggerName "http-trigger" &> /dev/null; then
        print_info "HTTP触发器已存在"
    else
        print_info "创建HTTP触发器..."
        echo "${trigger_config}" | aliyun fc CreateTrigger \
            --region "${REGION}" \
            --serviceName "${SERVICE_NAME}" \
            --functionName "${FUNCTION_NAME}" \
            --cli-input-json file:///dev/stdin
        
        if [ $? -eq 0 ]; then
            print_success "HTTP触发器创建成功"
        else
            print_error "HTTP触发器创建失败"
            exit 1
        fi
    fi
}

# 启用极速模式
enable_speed_mode() {
    print_info "启用极速模式（预留实例）..."
    
    local provision_config=$(cat <<EOF
{
    "target": 1,
    "scheduledActions": [
        {
            "name": "scale-up-morning",
            "scheduleExpression": "cron(0 8 * * *)",
            "target": 2
        },
        {
            "name": "scale-down-night", 
            "scheduleExpression": "cron(0 2 * * *)",
            "target": 0
        }
    ]
}
EOF
)
    
    echo "${provision_config}" | aliyun fc PutProvisionConfig \
        --region "${REGION}" \
        --serviceName "${SERVICE_NAME}" \
        --functionName "${FUNCTION_NAME}" \
        --qualifier "LATEST" \
        --cli-input-json file:///dev/stdin
    
    if [ $? -eq 0 ]; then
        print_success "极速模式启用成功"
    else
        print_warning "极速模式启用失败，可能需要手动配置"
    fi
}

# 测试部署
test_deployment() {
    print_info "测试部署..."
    
    # 获取函数URL
    local account_id=$(aliyun sts GetCallerIdentity --query 'AccountId' --output text)
    local function_url="https://${account_id}.${REGION}.fc.aliyuncs.com/2016-08-15/proxy/${SERVICE_NAME}/${FUNCTION_NAME}"
    
    print_info "函数URL: ${function_url}"
    
    # 测试健康检查
    print_info "测试健康检查接口..."
    local health_response=$(curl -s -w "%{http_code}" "${function_url}/api/health" -o /tmp/health_response.json)
    
    if [ "${health_response}" = "200" ]; then
        print_success "健康检查通过"
        cat /tmp/health_response.json | python3 -m json.tool 2>/dev/null || cat /tmp/health_response.json
    else
        print_warning "健康检查失败，HTTP状态码: ${health_response}"
        cat /tmp/health_response.json 2>/dev/null || echo "无响应内容"
    fi
    
    rm -f /tmp/health_response.json
}

# 显示部署信息
show_deployment_info() {
    print_success "部署完成！"
    
    local account_id=$(aliyun sts GetCallerIdentity --query 'AccountId' --output text)
    local function_url="https://${account_id}.${REGION}.fc.aliyuncs.com/2016-08-15/proxy/${SERVICE_NAME}/${FUNCTION_NAME}"
    
    echo
    print_info "部署信息:"
    print_info "  服务名称: ${SERVICE_NAME}"
    print_info "  函数名称: ${FUNCTION_NAME}"
    print_info "  地域: ${REGION}"
    print_info "  镜像: ${IMAGE_URI}"
    echo
    print_info "API接口:"
    print_info "  TTS处理: POST ${function_url}/api/start_tts"
    print_info "  任务状态: GET ${function_url}/api/task/{task_id}/status"
    print_info "  健康检查: GET ${function_url}/api/health"
    echo
    print_info "使用示例:"
    print_info "  curl -X POST '${function_url}/api/start_tts' \\"
    print_info "       -H 'Content-Type: application/json' \\"
    print_info "       -d '{\"task_id\": \"your-task-id\"}'"
    echo
}

# 主函数
main() {
    print_info "开始部署WaveShift TTS引擎到阿里云GPU云函数..."
    
    # 检查参数
    if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        echo "用法: $0 [选项]"
        echo "选项:"
        echo "  --build-only     仅构建镜像，不部署"
        echo "  --deploy-only    仅部署函数，不构建镜像"
        echo "  --skip-push      跳过镜像推送（用于本地测试）"
        echo "  --help, -h       显示帮助信息"
        exit 0
    fi
    
    # 加载环境变量
    if [ -f ".env" ]; then
        export $(cat .env | xargs)
    fi
    
    check_requirements
    load_config
    check_env_vars
    
    # 根据参数执行不同的流程
    if [ "$1" = "--build-only" ]; then
        build_image
        print_success "镜像构建完成"
        exit 0
    elif [ "$1" = "--deploy-only" ]; then
        deploy_function
        setup_trigger
        enable_speed_mode
        test_deployment
        show_deployment_info
        exit 0
    else
        # 完整部署流程
        build_image
        
        if [ "$1" != "--skip-push" ]; then
            push_image
        fi
        
        deploy_function
        setup_trigger
        enable_speed_mode
        test_deployment
        show_deployment_info
    fi
}

# 运行主函数
main "$@"