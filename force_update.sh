#!/bin/bash

# 更新网盘系统脚本
# 确保所有更改都生效

set -e

echo "开始强制更新网盘系统..."

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 停止服务
echo "正在停止服务..."
systemctl stop netdisk.service
systemctl stop nginx

# 备份当前文件
echo "正在备份当前文件..."
cp /opt/netdisk/app.py /opt/netdisk/app.py.backup.$(date +%Y%m%d_%H%M%S)

# 检查更新文件是否存在
if [ ! -f "app.py" ]; then
    echo "错误：app.py 文件不存在于当前目录"
    echo "请确保在包含 app.py 的目录中运行此脚本"
    exit 1
fi

# 复制新文件
echo "正在复制新的应用文件..."
cp app.py /opt/netdisk/
chown www-data:www-data /opt/netdisk/app.py
chmod 644 /opt/netdisk/app.py

# 验证文件是否更新成功
echo "正在验证文件更新..."
if grep -q "bowen网盘系统" /opt/netdisk/app.py; then
    echo "✅ 文件更新成功！检测到 'bowen网盘系统' 标题"
else
    echo "❌ 文件可能未正确更新"
fi

# 重新加载systemd配置
echo "正在重新加载配置..."
systemctl daemon-reload

# 启动服务
echo "正在启动服务..."
systemctl start nginx
systemctl start netdisk.service

# 等待服务启动
echo "等待服务启动..."
sleep 5

# 检查服务状态
echo "正在检查服务状态..."
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

# 显示当前运行的进程
echo "当前运行的网盘进程："
ps aux | grep -E "(gunicorn|app\.py)" | grep -v grep

echo ""
echo "========================================="
echo "更新完成！"
echo "========================================="
echo "访问地址: https://duanbowen666.cn"
echo ""
echo "如果问题仍然存在，请检查："
echo "1. 浏览器缓存：按 Ctrl+F5 强制刷新"
echo "2. 服务日志：journalctl -u netdisk.service -f"
echo "3. 应用日志：tail -f /var/log/netdisk/error.log"
echo "========================================="
