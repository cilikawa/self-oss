#!/bin/bash

# HTTPS配置脚本
# 为duanbowen666.cn配置SSL证书

set -e

echo "开始配置HTTPS..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 安装certbot
echo "正在安装certbot..."
apt update
apt install -y certbot python3-certbot-nginx

# 首先停止nginx确保80端口可用
echo "正在停止nginx..."
systemctl stop nginx

# 获取SSL证书
echo "正在获取SSL证书..."
certbot certonly --standalone -d duanbowen666.cn --email admin@duanbowen666.cn --agree-tos --no-eff-email

# 更新nginx配置
echo "正在更新nginx配置..."
cp /tmp/netdisk/nginx.conf /etc/nginx/sites-available/netdisk

# 测试nginx配置
echo "正在测试nginx配置..."
nginx -t

# 启动nginx
echo "正在启动nginx..."
systemctl start nginx

# 设置自动续期
echo "正在设置SSL证书自动续期..."
(crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet --nginx") | crontab -

# 检查SSL证书状态
echo "正在检查SSL证书..."
certbot certificates

echo ""
echo "========================================="
echo "HTTPS配置完成！"
echo "========================================="
echo "网站现在可以通过以下地址访问："
echo "  HTTP:  http://duanbowen666.cn (自动重定向到HTTPS)"
echo "  HTTPS: https://duanbowen666.cn"
echo ""
echo "SSL证书信息："
certbot certificates | grep -A 5 duanbowen666.cn || echo "证书信息获取中..."
echo ""
echo "证书将在到期前自动续期"
echo "========================================="
