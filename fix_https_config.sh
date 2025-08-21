#!/bin/bash

# 修复HTTPS配置脚本
# SSL证书已获取，现在配置nginx

set -e

echo "SSL证书已获取，正在配置HTTPS..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 创建完整的nginx配置
echo "正在创建nginx HTTPS配置..."
cat > /etc/nginx/sites-available/netdisk << 'EOF'
# HTTP重定向到HTTPS
server {
    listen 80;
    server_name duanbowen666.cn www.duanbowen666.cn;
    return 301 https://duanbowen666.cn$request_uri;
}

# HTTPS配置
server {
    listen 443 ssl http2;
    server_name duanbowen666.cn www.duanbowen666.cn;
    
    ssl_certificate /etc/letsencrypt/live/duanbowen666.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/duanbowen666.cn/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
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
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
}
EOF

# 测试nginx配置
echo "正在测试nginx配置..."
nginx -t

# 重启nginx
echo "正在重启nginx..."
systemctl restart nginx

# 确保netdisk服务运行
echo "正在检查netdisk服务..."
systemctl start netdisk.service

# 设置SSL证书自动续期
echo "正在设置SSL证书自动续期..."
(crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet --nginx") | crontab -

# 检查服务状态
echo "正在检查服务状态..."
sleep 3
systemctl status nginx --no-pager
systemctl status netdisk.service --no-pager

# 检查SSL证书
echo "正在检查SSL证书..."
certbot certificates

echo ""
echo "========================================="
echo "HTTPS配置完成！"
echo "========================================="
echo "网站现在可以通过以下地址访问："
echo "  HTTP:  http://duanbowen666.cn (自动重定向到HTTPS)"
echo "  HTTPS: https://duanbowen666.cn"
echo "  HTTPS: https://www.duanbowen666.cn"
echo ""
echo "SSL证书信息："
echo "  证书路径: /etc/letsencrypt/live/duanbowen666.cn/fullchain.pem"
echo "  私钥路径: /etc/letsencrypt/live/duanbowen666.cn/privkey.pem"
echo "  过期时间: 2025-11-19"
echo "  自动续期: 已设置"
echo ""
echo "测试HTTPS访问："
echo "  curl -I https://duanbowen666.cn"
echo "========================================="
EOF
