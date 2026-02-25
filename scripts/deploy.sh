#!/bin/bash

# EngHub 生产部署脚本
# 适用于 6GB 内存的服务器

set -e

echo "=== EngHub 部署脚本 ==="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查环境
check_env() {
    echo -e "${YELLOW}检查环境...${NC}"
    
    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}错误: Docker 未安装${NC}"
        exit 1
    fi
    
    # 检查 Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}错误: Docker Compose 未安装${NC}"
        exit 1
    fi
    
    # 检查内存 (6GB推荐)
    MEMORY=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$MEMORY" -lt 4096 ]; then
        echo -e "${YELLOW}警告: 内存小于 4GB (${MEMORY}MB)，建议升级到 6GB${NC}"
    elif [ "$MEMORY" -lt 6144 ]; then
        echo -e "${YELLOW}提示: 当前内存 ${MEMORY}MB，建议 6GB 以获得最佳性能${NC}"
    else
        echo -e "${GREEN}内存检查通过: ${MEMORY}MB${NC}"
    fi
    
    # 检查磁盘 (推荐20GB)
    DISK=$(df -m . | awk 'NR==2 {print $4}')
    if [ "$DISK" -lt 10240 ]; then
        echo -e "${YELLOW}警告: 可用磁盘空间小于 10GB (${DISK}MB)${NC}"
    else
        echo -e "${GREEN}磁盘空间检查通过: ${DISK}MB${NC}"
    fi
    
    echo -e "${GREEN}环境检查完成${NC}"
}

# 创建目录结构
setup_dirs() {
    echo -e "${YELLOW}创建目录结构...${NC}"
    
    mkdir -p /opt/enghub/{data/postgres,data/redis,logs}
    
    echo -e "${GREEN}目录创建完成${NC}"
}

# 拉取最新代码
pull_code() {
    echo -e "${YELLOW}拉取最新代码...${NC}"
    
    if [ -d "/opt/enghub/.git" ]; then
        cd /opt/enghub
        git pull origin main
    else
        echo -e "${RED}错误: 不是Git仓库，请先克隆代码${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}代码更新完成${NC}"
}

# 部署应用
deploy() {
    echo -e "${YELLOW}开始部署...${NC}"
    
    cd /opt/enghub
    
    # 停止旧容器
    echo "停止旧容器..."
    docker-compose -f docker/docker-compose.minimal.yml down || true
    
    # 拉取最新镜像
    echo "拉取最新镜像..."
    docker-compose -f docker/docker-compose.minimal.yml pull
    
    # 启动服务
    echo "启动服务..."
    docker-compose -f docker/docker-compose.minimal.yml up -d
    
    # 等待服务启动
    echo "等待服务启动..."
    sleep 10
    
    # 检查服务状态
    echo "检查服务状态..."
    docker-compose -f docker/docker-compose.minimal.yml ps
    
    # 清理旧镜像
    echo "清理旧镜像..."
    docker system prune -f
    
    echo -e "${GREEN}部署完成!${NC}"
}

# 显示状态
show_status() {
    echo -e "${YELLOW}=== 服务状态 ===${NC}"
    docker-compose -f /opt/enghub/docker/docker-compose.minimal.yml ps
    
    echo ""
    echo -e "${GREEN}访问地址:${NC}"
    echo "  前端: http://$(hostname -I | awk '{print $1}')"
    echo "  后端API: http://$(hostname -I | awk '{print $1}'):8000"
    echo "  API文档: http://$(hostname -I | awk '{print $1}'):8000/docs"
}

# 主函数
main() {
    case "${1:-deploy}" in
        check)
            check_env
            ;;
        deploy)
            check_env
            setup_dirs
            deploy
            show_status
            ;;
        status)
            show_status
            ;;
        logs)
            docker-compose -f /opt/enghub/docker/docker-compose.minimal.yml logs -f
            ;;
        *)
            echo "用法: $0 [check|deploy|status|logs]"
            exit 1
            ;;
    esac
}

main "$@"
