# Gunicorn配置文件

# 绑定地址和端口
bind = "0.0.0.0:5000"

# 工作进程数量
workers = 4

# 工作类型
worker_class = "sync"

# 超时设置
timeout = 120
keepalive = 2

# 最大请求数
max_requests = 1000
max_requests_jitter = 100

# 进程名称
proc_name = "netdisk_app"

# 日志配置
accesslog = "/var/log/netdisk/access.log"
errorlog = "/var/log/netdisk/error.log"
loglevel = "info"

# 用户和组
user = "www-data"
group = "www-data"

# 预加载应用
preload_app = True

# 工作目录
chdir = "/opt/netdisk"
