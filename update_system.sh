#!/bin/bash

# 网盘系统更新脚本
# 用于更新已部署的系统

set -e

echo "开始更新网盘系统..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 备份当前配置
echo "正在备份当前配置..."
cp /opt/netdisk/app.py /opt/netdisk/app.py.backup.$(date +%Y%m%d_%H%M%S)

# 停止服务
echo "正在停止服务..."
systemctl stop netdisk.service

# 更新应用文件
echo "正在更新应用文件..."
cp app.py /opt/netdisk/
cp gunicorn_config.py /opt/netdisk/
cp requirements.txt /opt/netdisk/

# 更新nginx配置
echo "正在更新nginx配置..."
cp nginx.conf /etc/nginx/sites-available/netdisk

# 更新systemd服务配置
echo "正在更新systemd服务配置..."
cp netdisk.service /etc/systemd/system/
systemctl daemon-reload

# 更新Python依赖
echo "正在更新Python依赖..."
cd /opt/netdisk
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 设置权限
echo "正在设置权限..."
chown -R www-data:www-data /opt/netdisk
chmod -R 755 /opt/netdisk

# 测试nginx配置
echo "正在测试nginx配置..."
nginx -t

# 启动服务
echo "正在启动服务..."
systemctl start netdisk.service
systemctl restart nginx

# 检查服务状态
echo "正在检查服务状态..."
sleep 5
systemctl status netdisk.service --no-pager

echo ""
echo "========================================="
echo "系统更新完成！"
echo "========================================="
echo "新功能："
echo "  ✅ 修复大文件夹上传413错误"
echo "  ✅ 修复文件夹下载打包功能"
echo "  ✅ 侧边栏页面功能（最近使用、我的分享、快传）"
echo "  ✅ 修复分享功能问题"
echo "  ✅ 配置域名和HTTPS支持"
echo ""
echo "访问地址: https://duanbowen666.cn"
echo "========================================="
