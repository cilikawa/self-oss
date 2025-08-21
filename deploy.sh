#!/bin/bash

# 网盘系统自动部署脚本
# 适用于Ubuntu服务器

set -e  # 遇到错误立即退出

echo "开始部署个人网盘系统..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 更新系统
echo "正在更新系统..."
apt update && apt upgrade -y

# 安装必要的软件包
echo "正在安装必要的软件包..."
apt install -y python3 python3-pip python3-venv nginx supervisor ufw

# 创建应用目录
echo "正在创建应用目录..."
mkdir -p /opt/netdisk
mkdir -p /var/log/netdisk
mkdir -p /opt/netdisk/uploads

# 创建www-data用户（如果不存在）
if ! id "www-data" &>/dev/null; then
    useradd -r -s /bin/false www-data
fi

# 复制应用文件
echo "正在复制应用文件..."
cp app.py /opt/netdisk/
cp requirements.txt /opt/netdisk/
cp gunicorn_config.py /opt/netdisk/

# 设置权限
chown -R www-data:www-data /opt/netdisk
chown -R www-data:www-data /var/log/netdisk
chmod -R 755 /opt/netdisk
chmod -R 755 /var/log/netdisk

# 创建Python虚拟环境
echo "正在创建Python虚拟环境..."
cd /opt/netdisk
python3 -m venv venv
source venv/bin/activate

# 安装Python依赖
echo "正在安装Python依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 配置systemd服务
echo "正在配置systemd服务..."
cp netdisk.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable netdisk.service

# 配置Nginx
echo "正在配置Nginx..."
cp nginx.conf /etc/nginx/sites-available/netdisk
ln -sf /etc/nginx/sites-available/netdisk /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 测试Nginx配置
nginx -t

# 配置防火墙
echo "正在配置防火墙..."
ufw --force enable
ufw allow ssh
ufw allow 'Nginx Full'

# 启动服务
echo "正在启动服务..."
systemctl start netdisk.service
systemctl restart nginx

# 检查服务状态
echo "正在检查服务状态..."
sleep 5
systemctl status netdisk.service --no-pager
systemctl status nginx --no-pager

# 获取服务器IP
SERVER_IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')

echo ""
echo "========================================="
echo "部署完成！"
echo "========================================="
echo "访问地址: http://$SERVER_IP"
echo ""
echo "服务管理命令："
echo "  启动服务: systemctl start netdisk.service"
echo "  停止服务: systemctl stop netdisk.service"
echo "  重启服务: systemctl restart netdisk.service"
echo "  查看状态: systemctl status netdisk.service"
echo "  查看日志: journalctl -u netdisk.service -f"
echo ""
echo "上传目录: /opt/netdisk/uploads"
echo "日志目录: /var/log/netdisk"
echo ""
echo "如需配置域名或HTTPS，请编辑 /etc/nginx/sites-available/netdisk"
echo "========================================="
