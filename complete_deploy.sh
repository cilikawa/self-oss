#!/bin/bash

# 网盘系统完整部署脚本
# 适用于全新的Ubuntu服务器

set -e  # 遇到错误立即退出

echo "开始部署bowen网盘系统..."
echo "========================================="

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
apt install -y python3 python3-pip python3-venv nginx ufw curl

# 创建应用目录
echo "正在创建应用目录..."
mkdir -p /opt/netdisk
mkdir -p /var/log/netdisk
mkdir -p /opt/netdisk/uploads
mkdir -p /opt/netdisk/quick_transfer
mkdir -p /opt/netdisk/shares

# 创建www-data用户（如果不存在）
if ! id "www-data" &>/dev/null; then
    useradd -r -s /bin/false www-data
fi

# 复制应用文件
echo "正在复制应用文件..."
if [ ! -f "app.py" ]; then
    echo "错误：app.py 文件不存在，请确保在正确的目录运行脚本"
    exit 1
fi

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
cp /tmp/netdisk/netdisk.service /etc/systemd/system/ 2>/dev/null || cat > /etc/systemd/system/netdisk.service << 'EOF'
[Unit]
Description=Personal Network Disk Service
After=network.target

[Service]
Type=exec
User=www-data
Group=www-data
WorkingDirectory=/opt/netdisk
Environment=PATH=/opt/netdisk/venv/bin
ExecStart=/opt/netdisk/venv/bin/gunicorn -c gunicorn_config.py app:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable netdisk.service

# 配置Nginx（HTTP配置，后续可升级为HTTPS）
echo "正在配置Nginx..."
cat > /etc/nginx/sites-available/netdisk << 'EOF'
server {
    listen 80;
    server_name duanbowen666.cn www.duanbowen666.cn _;
    
    # 文件上传大小限制
    client_max_body_size 20G;
    client_body_timeout 300s;
    client_header_timeout 300s;
    
    # 超时设置
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
    proxy_buffering off;
    proxy_request_buffering off;
    
    # 根路径代理到Flask应用
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 静态文件优化
    location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # 安全头
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}
EOF

# 启用站点
ln -sf /etc/nginx/sites-available/netdisk /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 测试Nginx配置
echo "正在测试Nginx配置..."
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

if systemctl is-active --quiet netdisk.service; then
    echo "✅ netdisk服务运行正常"
else
    echo "❌ netdisk服务启动失败"
    systemctl status netdisk.service --no-pager
fi

if systemctl is-active --quiet nginx; then
    echo "✅ nginx服务运行正常"
else
    echo "❌ nginx服务启动失败"
    systemctl status nginx --no-pager
fi

# 获取服务器IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "========================================="
echo "bowen网盘系统部署完成！"
echo "========================================="
echo "访问地址："
echo "  HTTP:  http://duanbowen666.cn"
echo "  HTTP:  http://$SERVER_IP"
echo ""
echo "登录信息："
echo "  用户名: root"
echo "  密码:   qaz341212"
echo ""
echo "服务管理命令："
echo "  启动服务: systemctl start netdisk.service"
echo "  停止服务: systemctl stop netdisk.service"
echo "  重启服务: systemctl restart netdisk.service"
echo "  查看状态: systemctl status netdisk.service"
echo "  查看日志: journalctl -u netdisk.service -f"
echo ""
echo "目录位置："
echo "  上传目录: /opt/netdisk/uploads"
echo "  日志目录: /var/log/netdisk"
echo "  应用目录: /opt/netdisk"
echo ""
echo "后续配置HTTPS："
echo "  确保域名解析生效后运行: ./setup_https.sh"
echo "========================================="
