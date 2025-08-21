#!/bin/bash

# 修复Nginx配置脚本
# 先使用HTTP配置，然后可以配置HTTPS

set -e

echo "正在修复Nginx配置..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 停止nginx
echo "正在停止nginx..."
systemctl stop nginx

# 使用HTTP配置
echo "正在应用HTTP配置..."
cp nginx_http_only.conf /etc/nginx/sites-available/netdisk

# 测试nginx配置
echo "正在测试nginx配置..."
nginx -t

# 启动nginx
echo "正在启动nginx..."
systemctl start nginx

# 启动netdisk服务
echo "正在启动netdisk服务..."
systemctl start netdisk.service

# 检查服务状态
echo "正在检查服务状态..."
sleep 3
systemctl status nginx --no-pager
systemctl status netdisk.service --no-pager

echo ""
echo "========================================="
echo "Nginx配置修复完成！"
echo "========================================="
echo "当前可以通过HTTP访问："
echo "  http://duanbowen666.cn"
echo "  http://www.duanbowen666.cn"
echo ""
echo "如需配置HTTPS，请确保域名解析生效后运行："
echo "  ./setup_https.sh"
echo "========================================="
