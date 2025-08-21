#!/bin/bash

# 网盘系统部署修复脚本
# 用于修复部署过程中的问题

set -e

echo "正在修复部署问题..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 找到netdisk.service文件并复制
if [ -f "netdisk.service" ]; then
    echo "找到netdisk.service文件，正在复制..."
    cp netdisk.service /etc/systemd/system/
elif [ -f "/tmp/netdisk/netdisk.service" ]; then
    echo "从部署目录复制netdisk.service文件..."
    cp /tmp/netdisk/netdisk.service /etc/systemd/system/
else
    echo "创建netdisk.service文件..."
    cat > /etc/systemd/system/netdisk.service << 'EOF'
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
fi

# 重载systemd并启用服务
echo "正在配置systemd服务..."
systemctl daemon-reload
systemctl enable netdisk.service

# 配置Nginx
echo "正在配置Nginx..."
if [ -f "nginx.conf" ]; then
    cp nginx.conf /etc/nginx/sites-available/netdisk
elif [ -f "/tmp/netdisk/nginx.conf" ]; then
    cp /tmp/netdisk/nginx.conf /etc/nginx/sites-available/netdisk
else
    echo "创建Nginx配置文件..."
    cat > /etc/nginx/sites-available/netdisk << 'EOF'
server {
    listen 80;
    server_name _;  # 接受所有域名访问
    
    # 文件上传大小限制
    client_max_body_size 10G;
    
    # 超时设置
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
    
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
fi

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
systemctl status netdisk.service --no-pager
systemctl status nginx --no-pager

# 获取服务器IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "========================================="
echo "部署修复完成！"
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
