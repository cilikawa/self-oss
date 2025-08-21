#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网盘系统 - Flask后端服务器
支持文件上传、下载、文件夹上传等功能
"""

import os
import shutil
import json
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_file, render_template_string, session, redirect, url_for
from flask_cors import CORS
from functools import wraps

app = Flask(__name__)
CORS(app)

# 配置
UPLOAD_FOLDER = 'uploads'
QUICK_TRANSFER_FOLDER = 'quick_transfer'
SHARES_FOLDER = 'shares'
MAX_CONTENT_LENGTH = 20 * 1024 * 1024 * 1024  # 20GB 最大文件大小
ALLOWED_EXTENSIONS = set()  # 允许所有文件类型
TOTAL_STORAGE = 500 * 1024 * 1024 * 1024  # 500GB 总存储空间

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'

# 确保目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QUICK_TRANSFER_FOLDER, exist_ok=True)
os.makedirs(SHARES_FOLDER, exist_ok=True)

# 存储分享信息的字典
shares_data = {}

# 存储最近使用的文件
recent_files = []

# 用户数据（生产环境应使用数据库）
users = {
    'root': {
        'password': hashlib.sha256('qaz341212'.encode()).hexdigest(),
        'username': 'root'
    }
}

# 登录失败记录 {IP: {'count': 失败次数, 'last_attempt': 最后尝试时间}}
failed_logins = {}

def allowed_file(filename):
    """检查文件是否允许上传（目前允许所有文件）"""
    return True

def get_client_ip():
    """获取客户端IP地址"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr

def is_ip_blocked(ip):
    """检查IP是否被封禁"""
    if ip not in failed_logins:
        return False
    
    login_data = failed_logins[ip]
    last_attempt = datetime.fromisoformat(login_data['last_attempt'])
    
    # 如果是新的一天，重置计数
    if datetime.now().date() > last_attempt.date():
        failed_logins[ip] = {'count': 0, 'last_attempt': datetime.now().isoformat()}
        return False
    
    return login_data['count'] >= 10

def record_failed_login(ip):
    """记录登录失败"""
    if ip not in failed_logins:
        failed_logins[ip] = {'count': 0, 'last_attempt': datetime.now().isoformat()}
    
    failed_logins[ip]['count'] += 1
    failed_logins[ip]['last_attempt'] = datetime.now().isoformat()

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'success': False, 'message': '请先登录', 'redirect': '/login'})
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_file_info(filepath):
    """获取文件信息"""
    stat = os.stat(filepath)
    return {
        'name': os.path.basename(filepath),
        'size': stat.st_size,
        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'is_dir': os.path.isdir(filepath)
    }

def get_directory_size(path):
    """计算目录总大小"""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, IOError):
                    continue
    except (OSError, IOError):
        pass
    return total_size

def clean_expired_quick_transfers():
    """清理过期的快传文件（1小时后删除）"""
    try:
        current_time = datetime.now()
        for item in os.listdir(QUICK_TRANSFER_FOLDER):
            item_path = os.path.join(QUICK_TRANSFER_FOLDER, item)
            if os.path.isfile(item_path):
                # 检查文件修改时间
                mtime = datetime.fromtimestamp(os.path.getmtime(item_path))
                if current_time - mtime > timedelta(hours=1):
                    try:
                        os.remove(item_path)
                    except OSError:
                        pass
            elif os.path.isdir(item_path):
                # 检查目录修改时间
                mtime = datetime.fromtimestamp(os.path.getmtime(item_path))
                if current_time - mtime > timedelta(hours=1):
                    try:
                        shutil.rmtree(item_path)
                    except OSError:
                        pass
    except OSError:
        pass

def add_to_recent_files(filename, file_path, action='upload'):
    """添加到最近使用文件列表"""
    global recent_files
    try:
        file_info = {
            'name': filename,
            'path': file_path,
            'action': action,
            'timestamp': datetime.now().isoformat(),
            'size': os.path.getsize(os.path.join(UPLOAD_FOLDER, file_path, filename)) if os.path.exists(os.path.join(UPLOAD_FOLDER, file_path, filename)) else 0
        }
        
        # 移除重复项
        recent_files = [f for f in recent_files if not (f['name'] == filename and f['path'] == file_path)]
        
        # 添加到开头
        recent_files.insert(0, file_info)
        
        # 只保留最近50个
        recent_files = recent_files[:50]
    except Exception:
        pass

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        client_ip = get_client_ip()
        
        # 检查IP是否被封禁
        if is_ip_blocked(client_ip):
            return jsonify({
                'success': False, 
                'message': '登录失败次数过多，今天无法再次尝试登录'
            })
        
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'})
        
        # 验证用户
        if username in users and users[username]['password'] == hashlib.sha256(password.encode()).hexdigest():
            session['user_id'] = username
            session['username'] = users[username]['username']
            return jsonify({'success': True, 'message': '登录成功'})
        else:
            record_failed_login(client_ip)
            remaining = 10 - failed_logins[client_ip]['count']
            return jsonify({
                'success': False, 
                'message': f'用户名或密码错误，还可尝试 {remaining} 次'
            })
    
    # GET请求返回登录页面
    login_html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - bowen网盘系统</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
        }
        .login-container { 
            background: white; 
            padding: 48px; 
            border-radius: 16px; 
            box-shadow: 0 20px 40px rgba(0,0,0,0.1); 
            width: 100%; 
            max-width: 400px; 
        }
        .login-header { text-align: center; margin-bottom: 32px; }
        .login-header h1 { 
            font-size: 28px; 
            color: #1a202c; 
            margin-bottom: 8px; 
        }
        .login-header p { color: #718096; }
        .form-group { margin-bottom: 20px; }
        .form-label { 
            display: block; 
            margin-bottom: 8px; 
            font-weight: 500; 
            color: #374151; 
        }
        .form-input { 
            width: 100%; 
            padding: 12px 16px; 
            border: 1px solid #e2e8f0; 
            border-radius: 8px; 
            font-size: 16px; 
            transition: border-color 0.2s; 
        }
        .form-input:focus { 
            outline: none; 
            border-color: #3182ce; 
            box-shadow: 0 0 0 3px rgba(49, 130, 206, 0.1); 
        }
        .login-btn { 
            width: 100%; 
            padding: 12px; 
            background: #3182ce; 
            color: white; 
            border: none; 
            border-radius: 8px; 
            font-size: 16px; 
            font-weight: 500; 
            cursor: pointer; 
            transition: background 0.2s; 
        }
        .login-btn:hover { background: #2c5aa0; }
        .login-btn:disabled { background: #a0aec0; cursor: not-allowed; }
        .message { 
            padding: 12px; 
            border-radius: 6px; 
            margin-bottom: 20px; 
            display: none; 
        }
        .message.error { 
            background: #fed7d7; 
            color: #721c24; 
            border: 1px solid #f5c6cb; 
        }
        .message.success { 
            background: #d4edda; 
            color: #155724; 
            border: 1px solid #c3e6cb; 
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1><i class="fas fa-cloud" style="color: #3182ce;"></i> 网盘系统</h1>
            <p>请登录以访问您的文件</p>
        </div>
        
        <div id="message" class="message"></div>
        
        <form id="loginForm">
            <div class="form-group">
                <label class="form-label">用户名</label>
                <input type="text" class="form-input" id="username" required>
            </div>
            <div class="form-group">
                <label class="form-label">密码</label>
                <input type="password" class="form-input" id="password" required>
            </div>
            <button type="submit" class="login-btn" id="loginBtn">登录</button>
        </form>
    </div>

    <script>
        document.getElementById('loginForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const loginBtn = document.getElementById('loginBtn');
            const message = document.getElementById('message');
            
            loginBtn.disabled = true;
            loginBtn.textContent = '登录中...';
            
            fetch('/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    message.textContent = data.message;
                    message.className = 'message success';
                    message.style.display = 'block';
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1000);
                } else {
                    message.textContent = data.message;
                    message.className = 'message error';
                    message.style.display = 'block';
                }
            })
            .catch(() => {
                message.textContent = '登录失败，请重试';
                message.className = 'message error';
                message.style.display = 'block';
            })
            .finally(() => {
                loginBtn.disabled = false;
                loginBtn.textContent = '登录';
            });
        });
    </script>
</body>
</html>
    """
    return render_template_string(login_html)

@app.route('/logout')
def logout():
    """退出登录"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """主页面"""
    html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>个人网盘系统</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: #f5f7fa;
            min-height: 100vh;
            color: #2d3748;
        }
        
        .app-container {
            display: flex;
            height: 100vh;
            background: #ffffff;
        }
        
        .sidebar {
            width: 280px;
            background: #ffffff;
            border-right: 1px solid #e2e8f0;
            display: flex;
            flex-direction: column;
            z-index: 100;
            transition: width 0.3s ease;
        }
        
        .sidebar.collapsed {
            width: 60px;
        }
        
        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .logo {
            font-size: 24px;
            font-weight: 700;
            color: #1a202c;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: opacity 0.3s ease;
        }
        
        .logo i {
            color: #3182ce;
        }
        
        .sidebar-toggle {
            background: none;
            border: none;
            color: #718096;
            cursor: pointer;
            padding: 8px;
            border-radius: 4px;
            transition: all 0.2s;
        }
        
        .sidebar-toggle:hover {
            background: #f7fafc;
            color: #3182ce;
        }
        
        .sidebar.collapsed .logo span {
            opacity: 0;
            width: 0;
            overflow: hidden;
        }
        
        .sidebar.collapsed .sidebar-toggle i {
            transform: rotate(180deg);
        }
        
        .sidebar-nav {
            flex: 1;
            padding: 24px 0;
        }
        
        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 24px;
            color: #4a5568;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s;
            border: none;
            background: none;
            width: 100%;
            text-align: left;
            font-size: 14px;
        }
        
        .nav-item:hover, .nav-item.active {
            background: #ebf8ff;
            color: #3182ce;
        }
        
        .nav-item i {
            width: 16px;
            text-align: center;
            min-width: 16px;
        }
        
        .sidebar.collapsed .nav-item span {
            opacity: 0;
            width: 0;
            overflow: hidden;
        }
        
        .sidebar.collapsed .nav-item {
            justify-content: center;
            padding: 12px;
        }
        
        .storage-info {
            padding: 24px;
            border-top: 1px solid #e2e8f0;
        }
        
        .storage-progress {
            margin-top: 12px;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #3182ce, #2b6cb0);
            transition: width 0.3s ease;
        }
        
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }
        
        .header {
            background: #ffffff;
            border-bottom: 1px solid #e2e8f0;
            padding: 24px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 16px;
        }
        
        .header-left {
            display: flex;
            align-items: center;
            gap: 16px;
            flex: 1;
            min-width: 300px;
        }
        
        .breadcrumb {
            display: flex;
            align-items: center;
            gap: 8px;
            color: #718096;
            font-size: 14px;
        }
        
        .breadcrumb a {
            color: #3182ce;
            text-decoration: none;
        }
        
        .breadcrumb a:hover {
            text-decoration: underline;
        }
        
        .search-box {
            position: relative;
            max-width: 400px;
            flex: 1;
        }
        
        .search-input {
            width: 100%;
            padding: 12px 16px 12px 44px;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        
        .search-input:focus {
            border-color: #3182ce;
            box-shadow: 0 0 0 3px rgba(49, 130, 206, 0.1);
        }
        
        .search-icon {
            position: absolute;
            left: 16px;
            top: 50%;
            transform: translateY(-50%);
            color: #a0aec0;
        }
        
        .header-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .user-info {
            display: flex;
            align-items: center;
            gap: 12px;
            padding-left: 12px;
            border-left: 1px solid #e2e8f0;
        }
        
        .username {
            color: #4a5568;
            font-weight: 500;
        }
        
        .btn {
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            text-decoration: none;
        }
        
        .btn-primary {
            background: #3182ce;
            color: white;
        }
        
        .btn-primary:hover {
            background: #2c5aa0;
        }
        
        .btn-secondary {
            background: #edf2f7;
            color: #4a5568;
        }
        
        .btn-secondary:hover {
            background: #e2e8f0;
        }
        
        .btn-success {
            background: #38a169;
            color: white;
        }
        
        .btn-success:hover {
            background: #2f855a;
        }
        
        .btn-danger {
            background: #e53e3e;
            color: white;
        }
        
        .btn-danger:hover {
            background: #c53030;
        }
        
        .content-area {
            flex: 1;
            padding: 32px;
            overflow-y: auto;
        }
        
        .upload-zone {
            border: 2px dashed #cbd5e0;
            border-radius: 12px;
            padding: 48px 24px;
            text-align: center;
            margin-bottom: 32px;
            transition: all 0.2s;
            cursor: pointer;
        }
        
        .upload-zone:hover, .upload-zone.dragover {
            border-color: #3182ce;
            background: #ebf8ff;
        }
        
        .upload-icon {
            font-size: 48px;
            color: #a0aec0;
            margin-bottom: 16px;
        }
        
        .upload-text {
            font-size: 18px;
            color: #4a5568;
            margin-bottom: 8px;
        }
        
        .upload-subtext {
            font-size: 14px;
            color: #718096;
            margin-bottom: 24px;
        }
        
        .upload-buttons {
            display: flex;
            justify-content: center;
            gap: 16px;
            flex-wrap: wrap;
        }
        
        .hidden {
            display: none;
        }
        
        .loading {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #718096;
            padding: 40px;
            justify-content: center;
        }
        
        .loading-spinner {
            width: 20px;
            height: 20px;
            border: 2px solid #e2e8f0;
            border-top: 2px solid #3182ce;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .fade-in {
            animation: fadeIn 0.3s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            padding: 16px;
            background: #f7fafc;
            border-radius: 8px;
        }
        
        .toolbar-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .toolbar-right {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .view-toggle {
            display: flex;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            overflow: hidden;
        }
        
        .view-toggle button {
            padding: 8px 12px;
            border: none;
            background: white;
            color: #4a5568;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .view-toggle button:hover,
        .view-toggle button.active {
            background: #3182ce;
            color: white;
        }
        
        .file-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }
        
        .file-list {
            background: white;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            overflow: hidden;
        }
        
        .file-item {
            display: flex;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #f1f5f9;
            transition: all 0.2s;
            cursor: pointer;
        }
        
        .file-item:hover {
            background: #f8fafc;
        }
        
        .file-item:last-child {
            border-bottom: none;
        }
        
        .file-item.selected {
            background: #ebf8ff;
            border-color: #bfdbfe;
        }
        
        .file-card {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            transition: all 0.2s;
            cursor: pointer;
        }
        
        .file-card:hover {
            border-color: #3182ce;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }
        
        .file-card.selected {
            border-color: #3182ce;
            background: #ebf8ff;
        }
        
        .file-checkbox {
            margin-right: 12px;
        }
        
        .file-icon {
            width: 40px;
            height: 40px;
            margin-right: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            border-radius: 6px;
        }
        
        .file-icon.folder {
            color: #3182ce;
        }
        
        .file-icon.image {
            color: #38a169;
        }
        
        .file-icon.document {
            color: #d69e2e;
        }
        
        .file-icon.archive {
            color: #805ad5;
        }
        
        .file-icon.default {
            color: #718096;
        }
        
        .file-info {
            flex: 1;
            min-width: 0;
        }
        
        .file-name {
            font-weight: 500;
            margin-bottom: 4px;
            color: #1a202c;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .file-meta {
            font-size: 13px;
            color: #718096;
        }
        
        .file-actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        
        .dropdown {
            position: relative;
        }
        
        .dropdown-menu {
            position: absolute;
            top: 100%;
            right: 0;
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
            z-index: 9999;
            min-width: 150px;
            display: none;
        }
        
        .dropdown-menu.show {
            display: block;
        }
        
        .dropdown-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 12px 16px;
            color: #4a5568;
            text-decoration: none;
            transition: background 0.2s;
            border: none;
            background: none;
            width: 100%;
            text-align: left;
            cursor: pointer;
        }
        
        .dropdown-item:hover {
            background: #f7fafc;
        }
        
        .dropdown-item.danger:hover {
            background: #fed7d7;
            color: #e53e3e;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }
        
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
        }
        
        .modal-content {
            background: white;
            border-radius: 8px;
            padding: 24px;
            max-width: 500px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }
        
        .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        
        .modal-title {
            font-size: 18px;
            font-weight: 600;
            color: #1a202c;
        }
        
        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            color: #a0aec0;
            cursor: pointer;
            padding: 0;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .modal-body {
            margin-bottom: 20px;
        }
        
        .modal-footer {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
        }
        
        .form-group {
            margin-bottom: 16px;
        }
        
        .form-label {
            display: block;
            margin-bottom: 6px;
            font-weight: 500;
            color: #374151;
        }
        
        .form-input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        
        .form-input:focus {
            border-color: #3182ce;
            box-shadow: 0 0 0 3px rgba(49, 130, 206, 0.1);
        }
        
        .toast {
            position: fixed;
            top: 20px;
            right: 20px;
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 16px 20px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
            z-index: 3000;
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 300px;
            transform: translateX(400px);
            transition: transform 0.3s ease;
        }
        
        .toast.show {
            transform: translateX(0);
        }
        
        .toast.success {
            border-left: 4px solid #38a169;
        }
        
        .toast.error {
            border-left: 4px solid #e53e3e;
        }
        
        .toast.info {
            border-left: 4px solid #3182ce;
        }
        
        .toast-icon {
            font-size: 18px;
        }
        
        .toast.success .toast-icon {
            color: #38a169;
        }
        
        .toast.error .toast-icon {
            color: #e53e3e;
        }
        
        .toast.info .toast-icon {
            color: #3182ce;
        }
        
        .toast-message {
            flex: 1;
            color: #1a202c;
        }
        
        .toast-close {
            background: none;
            border: none;
            color: #a0aec0;
            cursor: pointer;
            padding: 0;
            font-size: 16px;
        }
        
        .transfer-panel {
            position: fixed;
            right: -400px;
            top: 0;
            width: 400px;
            height: 100vh;
            background: white;
            border-left: 1px solid #e2e8f0;
            z-index: 1500;
            transition: right 0.3s ease;
            display: flex;
            flex-direction: column;
        }
        
        .transfer-panel.show {
            right: 0;
        }
        
        .transfer-header {
            padding: 20px;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .transfer-body {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        
        .transfer-item {
            padding: 12px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            margin-bottom: 12px;
        }
        
        .transfer-name {
            font-weight: 500;
            margin-bottom: 8px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .transfer-progress {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 14px;
            color: #718096;
        }
        
        .transfer-progress-bar {
            flex: 1;
            height: 6px;
            background: #e2e8f0;
            border-radius: 3px;
            overflow: hidden;
        }
        
        .transfer-progress-fill {
            height: 100%;
            background: #3182ce;
            transition: width 0.3s ease;
        }
        
        @media (max-width: 1024px) {
            .sidebar {
                position: fixed;
                left: -280px;
                transition: left 0.3s ease;
                height: 100vh;
                box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
            }
            
            .sidebar.show {
                left: 0;
            }
            
            .main-content {
                margin-left: 0;
            }
            
            .transfer-panel {
                width: 100vw;
                right: -100vw;
            }
        }
        
        @media (max-width: 768px) {
            .header {
                padding: 16px 20px;
                flex-direction: column;
                align-items: stretch;
            }
            
            .header-left {
                min-width: auto;
                margin-bottom: 16px;
            }
            
            .content-area {
                padding: 20px;
            }
            
            .upload-zone {
                padding: 32px 16px;
            }
            
            .file-grid {
                grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            }
            
            .toolbar {
                flex-direction: column;
                align-items: stretch;
                gap: 16px;
            }
            
            .toolbar-left,
            .toolbar-right {
                justify-content: center;
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <!-- 侧边栏 -->
        <div class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <div class="logo">
                    <i class="fas fa-cloud"></i>
                    <span>网盘系统</span>
                </div>
                <button class="sidebar-toggle" id="sidebarCollapseBtn">
                    <i class="fas fa-angle-left"></i>
                </button>
            </div>
            
            <nav class="sidebar-nav">
                <button class="nav-item active" data-page="files">
                    <i class="fas fa-folder"></i>
                    <span>我的文件</span>
                </button>
                <button class="nav-item" data-page="recent">
                    <i class="fas fa-clock"></i>
                    <span>最近使用</span>
                </button>
                <button class="nav-item" data-page="shared">
                    <i class="fas fa-share-alt"></i>
                    <span>我的分享</span>
                </button>
                <button class="nav-item" data-page="quick-transfer">
                    <i class="fas fa-bolt"></i>
                    <span>快传</span>
                </button>
                <button class="nav-item" id="transferBtn">
                    <i class="fas fa-exchange-alt"></i>
                    <span>传输列表</span>
                </button>
            </nav>
            
            <div class="storage-info">
                <div style="font-size: 14px; color: #4a5568; margin-bottom: 8px;">存储空间</div>
                <div id="storageText" style="font-size: 13px; color: #718096;">正在加载...</div>
                <div class="storage-progress">
                    <div class="progress-bar">
                        <div class="progress-fill" id="storageProgress" style="width: 0%;"></div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- 主内容区 -->
        <div class="main-content">
            <!-- 顶部工具栏 -->
            <div class="header">
                <div class="header-left">
                    <button class="btn btn-secondary" id="sidebarToggle" style="display: none;">
                        <i class="fas fa-bars"></i>
                    </button>
                    <div class="breadcrumb" id="breadcrumb">
                        <a href="#" onclick="loadFiles('')">根目录</a>
                    </div>
                </div>
                
                <div class="search-box">
                    <i class="fas fa-search search-icon"></i>
                    <input type="text" class="search-input" id="searchInput" placeholder="搜索文件和文件夹...">
                </div>
                
                <div class="header-actions">
                    <button class="btn btn-primary" id="uploadFileBtn">
                        <i class="fas fa-file-upload"></i>
                        上传文件
                    </button>
                    <button class="btn btn-primary" id="uploadFolderBtn">
                        <i class="fas fa-folder-plus"></i>
                        上传文件夹
                    </button>
                    <button class="btn btn-secondary" id="shareBtn" disabled>
                        <i class="fas fa-share"></i>
                        分享
                    </button>
                    
                    <!-- 用户信息 -->
                    <div class="user-info">
                        <span class="username">{{ session.username }}</span>
                        <button class="btn btn-secondary" onclick="window.location.href='/logout'">
                            <i class="fas fa-sign-out-alt"></i>
                            退出
                        </button>
                    </div>
                </div>
            </div>
            
            <!-- 内容区域 -->
            <div class="content-area">
                <!-- 上传区域 -->
                <div class="upload-zone" id="uploadZone">
                    <div class="upload-icon">
                        <i class="fas fa-cloud-upload-alt"></i>
                    </div>
                    <div class="upload-text">拖拽文件到此处上传</div>
                    <div class="upload-subtext">或者点击下方按钮选择文件</div>
                    <div class="upload-buttons">
                        <button class="btn btn-primary" onclick="document.getElementById('fileInput').click()">
                            <i class="fas fa-file"></i>
                            选择文件
                        </button>
                        <button class="btn btn-secondary" onclick="document.getElementById('folderInput').click()">
                            <i class="fas fa-folder"></i>
                            选择文件夹
                        </button>
                    </div>
                    
                    <input type="file" id="fileInput" class="hidden" multiple>
                    <input type="file" id="folderInput" class="hidden" webkitdirectory>
                </div>
                
                <!-- 工具栏 -->
                <div class="toolbar">
                    <div class="toolbar-left">
                        <button class="btn btn-secondary" id="selectAllBtn">
                            <i class="fas fa-check-square"></i>
                            全选
                        </button>
                        <button class="btn btn-secondary" id="downloadBtn" disabled>
                            <i class="fas fa-download"></i>
                            下载
                        </button>
                        <button class="btn btn-danger" id="deleteBtn" disabled>
                            <i class="fas fa-trash"></i>
                            删除
                        </button>
                    </div>
                    
                    <div class="toolbar-right">
                        <div class="view-toggle">
                            <button class="active" data-view="list">
                                <i class="fas fa-list"></i>
                            </button>
                            <button data-view="grid">
                                <i class="fas fa-th"></i>
                            </button>
                        </div>
                    </div>
                </div>
                
                <!-- 文件列表 -->
                <div id="fileContainer">
                    <div class="file-list" id="fileList">
                        <!-- 文件列表将通过JavaScript动态加载 -->
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- 传输面板 -->
    <div class="transfer-panel" id="transferPanel">
        <div class="transfer-header">
            <h3>传输列表</h3>
            <button class="btn btn-secondary" id="closeTransferBtn">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="transfer-body" id="transferList">
            <div style="text-align: center; padding: 40px; color: #718096;">
                <i class="fas fa-exchange-alt" style="font-size: 48px; margin-bottom: 16px;"></i>
                <div>暂无传输任务</div>
            </div>
        </div>
    </div>

    <script>
        let currentPath = '';
        let selectedFiles = new Set();
        let currentView = 'list';
        let transferTasks = [];
        let storageInfo = { used: 0, total: 100 * 1024 * 1024 * 1024 }; // 默认100GB
        
        // 页面加载时初始化
        document.addEventListener('DOMContentLoaded', function() {
            loadFiles('');
            loadStorageInfo();
            setupEventListeners();
            
            // 定时刷新传输列表和存储信息
            setInterval(updateTransferProgress, 1000);
            setInterval(loadStorageInfo, 30000);
        });
        
        function setupEventListeners() {
            // 文件选择事件
            document.getElementById('fileInput').addEventListener('change', handleFileSelect);
            document.getElementById('folderInput').addEventListener('change', handleFileSelect);
            
            // 拖拽上传
            const uploadZone = document.getElementById('uploadZone');
            uploadZone.addEventListener('dragover', handleDragOver);
            uploadZone.addEventListener('dragleave', handleDragLeave);
            uploadZone.addEventListener('drop', handleDrop);
            
            // 头部按钮事件
            document.getElementById('uploadFileBtn').addEventListener('click', () => {
                document.getElementById('fileInput').click();
            });
            document.getElementById('uploadFolderBtn').addEventListener('click', () => {
                document.getElementById('folderInput').click();
            });
            document.getElementById('shareBtn').addEventListener('click', shareSelectedFiles);
            
            // 工具栏事件
            document.getElementById('selectAllBtn').addEventListener('click', toggleSelectAll);
            document.getElementById('downloadBtn').addEventListener('click', downloadSelected);
            document.getElementById('deleteBtn').addEventListener('click', deleteSelected);
            
            // 视图切换
            document.querySelectorAll('.view-toggle button').forEach(btn => {
                btn.addEventListener('click', () => switchView(btn.dataset.view));
            });
            
            // 搜索功能
            document.getElementById('searchInput').addEventListener('input', handleSearch);
            
            // 传输面板
            document.getElementById('transferBtn').addEventListener('click', toggleTransferPanel);
            document.getElementById('closeTransferBtn').addEventListener('click', closeTransferPanel);
            
            // 侧边栏切换
            document.getElementById('sidebarToggle').addEventListener('click', toggleSidebar);
            document.getElementById('sidebarCollapseBtn').addEventListener('click', toggleSidebarCollapse);
            
            // 导航按钮
            document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
                btn.addEventListener('click', (e) => switchPage(e.target.closest('.nav-item').dataset.page));
            });
            
            // 响应式处理
            handleResize();
            window.addEventListener('resize', handleResize);
        }
        
        function handleDragOver(e) {
            e.preventDefault();
            document.getElementById('uploadZone').classList.add('dragover');
        }
        
        function handleDragLeave(e) {
            e.preventDefault();
            document.getElementById('uploadZone').classList.remove('dragover');
        }
        
        function handleDrop(e) {
            e.preventDefault();
            document.getElementById('uploadZone').classList.remove('dragover');
            
            const files = Array.from(e.dataTransfer.files);
            if (files.length > 0) {
                uploadFiles(files);
            }
        }
        
        function handleFileSelect(e) {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                uploadFiles(files);
            }
        }
        
        function uploadFiles(files) {
            if (files.length === 0) return;
            
            // 检查存储空间
            const totalSize = files.reduce((sum, file) => sum + file.size, 0);
            if (storageInfo.used + totalSize > storageInfo.total) {
                showToast('存储空间不足，无法上传', 'error');
                return;
            }
            
            const formData = new FormData();
            const taskId = 'upload_' + Date.now();
            
            // 添加文件到FormData
            files.forEach(file => {
                formData.append('files', file);
                if (file.webkitRelativePath) {
                    formData.append('paths', file.webkitRelativePath);
                }
            });
            
            formData.append('path', currentPath);
            
            // 创建传输任务
            const task = {
                id: taskId,
                type: 'upload',
                name: files.length === 1 ? files[0].name : `${files.length}个文件`,
                progress: 0,
                status: 'uploading',
                size: totalSize
            };
            
            transferTasks.push(task);
            updateTransferList();
            
            // 自动显示传输面板
            document.getElementById('transferPanel').classList.add('show');
            
            // 创建XMLHttpRequest
            const xhr = new XMLHttpRequest();
            
            xhr.upload.addEventListener('progress', function(e) {
                if (e.lengthComputable) {
                    const progress = (e.loaded / e.total) * 100;
                    task.progress = Math.round(progress);
                    updateTransferList();
                }
            });
            
            xhr.addEventListener('load', function() {
                if (xhr.status === 200) {
                    const response = JSON.parse(xhr.responseText);
                    if (response.success) {
                        task.status = 'completed';
                        task.progress = 100;
                        showToast('文件上传成功！', 'success');
                        loadFiles(currentPath);
                        loadStorageInfo();
                    } else {
                        task.status = 'error';
                        showToast('上传失败: ' + response.message, 'error');
                    }
                } else {
                    task.status = 'error';
                    showToast('上传失败，请重试', 'error');
                }
                
                updateTransferList();
                
                // 清空文件选择
                document.getElementById('fileInput').value = '';
                document.getElementById('folderInput').value = '';
                
                // 3秒后移除已完成的任务
                setTimeout(() => {
                    const index = transferTasks.findIndex(t => t.id === taskId);
                    if (index !== -1) {
                        transferTasks.splice(index, 1);
                        updateTransferList();
                    }
                }, 3000);
            });
            
            xhr.addEventListener('error', function() {
                task.status = 'error';
                updateTransferList();
                showToast('上传失败，请检查网络连接', 'error');
            });
            
            xhr.open('POST', '/upload');
            xhr.send(formData);
        }
        
        function loadFiles(path) {
            currentPath = path;
            
            fetch(`/files?path=${encodeURIComponent(path)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        displayFiles(data.files);
                        updateBreadcrumb(path);
                    } else {
                        showMessage('加载文件列表失败: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    showMessage('加载文件列表失败，请重试', 'error');
                    console.error('Error:', error);
                });
        }
        
        function displayFiles(files) {
            const container = document.getElementById('fileContainer');
            
            if (files.length === 0) {
                container.innerHTML = '<div style="text-align: center; padding: 60px; color: #718096;"><i class="fas fa-folder-open" style="font-size: 48px; margin-bottom: 16px; display: block;"></i>此文件夹为空</div>';
                return;
            }
            
            if (currentView === 'grid') {
                displayFilesGrid(files);
            } else {
                displayFilesList(files);
            }
            
            updateSelectionButtons();
        }
        
        function displayFilesList(files) {
            const container = document.getElementById('fileContainer');
            const fileList = document.createElement('div');
            fileList.className = 'file-list';
            fileList.id = 'fileList';
            
            files.forEach(file => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                fileItem.dataset.filename = file.name;
                fileItem.dataset.isdir = file.is_dir;
                
                const icon = getFileIcon(file);
                const sizeText = file.is_dir ? '文件夹' : formatFileSize(file.size);
                
                fileItem.innerHTML = `
                    <input type="checkbox" class="file-checkbox" onchange="toggleFileSelection('${file.name}')">
                    <div class="file-icon ${getFileIconClass(file)}">${icon}</div>
                    <div class="file-info">
                        <div class="file-name">${escapeHtml(file.name)}</div>
                        <div class="file-meta">${sizeText} • ${file.modified}</div>
                    </div>
                    <div class="file-actions">
                        <div class="dropdown">
                            <button class="btn btn-secondary" onclick="toggleDropdown(this)">
                                <i class="fas fa-ellipsis-v"></i>
                            </button>
                            <div class="dropdown-menu">
                                ${file.is_dir ? 
                                    `<button class="dropdown-item" onclick="openFolder('${escapeHtml(file.name)}')">
                                        <i class="fas fa-folder-open"></i> 打开
                                    </button>` : 
                                    `<a href="/download?path=${encodeURIComponent(currentPath)}&filename=${encodeURIComponent(file.name)}" class="dropdown-item">
                                        <i class="fas fa-download"></i> 下载
                                    </a>`
                                }
                                <button class="dropdown-item" onclick="showRenameModal('${escapeHtml(file.name)}')">
                                    <i class="fas fa-edit"></i> 重命名
                                </button>
                                <button class="dropdown-item" onclick="showFileDetails('${escapeHtml(file.name)}')">
                                    <i class="fas fa-info-circle"></i> 详情
                                </button>
                                <button class="dropdown-item danger" onclick="deleteFile('${escapeHtml(file.name)}', ${file.is_dir})">
                                    <i class="fas fa-trash"></i> 删除
                                </button>
                            </div>
                        </div>
                    </div>
                `;
                
                // 双击打开文件夹
                if (file.is_dir) {
                    fileItem.addEventListener('dblclick', () => openFolder(file.name));
                }
                
                fileList.appendChild(fileItem);
            });
            
            container.innerHTML = '';
            container.appendChild(fileList);
        }
        
        function displayFilesGrid(files) {
            const container = document.getElementById('fileContainer');
            const fileGrid = document.createElement('div');
            fileGrid.className = 'file-grid';
            fileGrid.id = 'fileGrid';
            
            files.forEach(file => {
                const fileCard = document.createElement('div');
                fileCard.className = 'file-card';
                fileCard.dataset.filename = file.name;
                fileCard.dataset.isdir = file.is_dir;
                
                const icon = getFileIcon(file);
                const sizeText = file.is_dir ? '文件夹' : formatFileSize(file.size);
                
                fileCard.innerHTML = `
                    <input type="checkbox" class="file-checkbox" onchange="toggleFileSelection('${file.name}')" style="position: absolute; top: 8px; right: 8px;">
                    <div class="file-icon ${getFileIconClass(file)}" style="font-size: 32px; margin-bottom: 12px;">${icon}</div>
                    <div class="file-name" style="margin-bottom: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(file.name)}</div>
                    <div class="file-meta" style="font-size: 12px; color: #718096;">${sizeText}</div>
                `;
                
                // 双击打开文件夹或下载文件
                fileCard.addEventListener('dblclick', () => {
                    if (file.is_dir) {
                        openFolder(file.name);
                    } else {
                        window.location.href = `/download?path=${encodeURIComponent(currentPath)}&filename=${encodeURIComponent(file.name)}`;
                    }
                });
                
                // 右键菜单
                fileCard.addEventListener('contextmenu', (e) => {
                    e.preventDefault();
                    showContextMenu(e, file);
                });
                
                fileGrid.appendChild(fileCard);
            });
            
            container.innerHTML = '';
            container.appendChild(fileGrid);
        }
        
        function openFolder(folderName) {
            const newPath = currentPath ? currentPath + '/' + folderName : folderName;
            loadFiles(newPath);
        }
        
        function deleteFile(filename, isDir) {
            if (!confirm(`确定要删除${isDir ? '文件夹' : '文件'} "${filename}" 吗？`)) {
                return;
            }
            
            fetch('/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    path: currentPath,
                    filename: filename
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showMessage('删除成功！', 'success');
                    loadFiles(currentPath);
                } else {
                    showMessage('删除失败: ' + data.message, 'error');
                }
            })
            .catch(error => {
                showMessage('删除失败，请重试', 'error');
                console.error('Error:', error);
            });
        }
        
        function updateBreadcrumb(path) {
            const breadcrumb = document.getElementById('breadcrumb');
            breadcrumb.innerHTML = '<a href="#" onclick="loadFiles(\\'\\')">根目录</a>';
            
            if (path) {
                const parts = path.split('/');
                let currentPath = '';
                
                parts.forEach((part, index) => {
                    currentPath += (index > 0 ? '/' : '') + part;
                    breadcrumb.innerHTML += ` / <a href="#" onclick="loadFiles('${currentPath}')">${part}</a>`;
                });
            }
        }
        
        function formatFileSize(bytes) {
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            if (bytes === 0) return '0 B';
            
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i];
        }
        
        // 辅助函数
        function getFileIcon(file) {
            if (file.is_dir) return '<i class="fas fa-folder"></i>';
            
            const ext = file.name.split('.').pop().toLowerCase();
            const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'];
            const docExts = ['doc', 'docx', 'pdf', 'txt', 'rtf'];
            const archiveExts = ['zip', 'rar', '7z', 'tar', 'gz'];
            const videoExts = ['mp4', 'avi', 'mkv', 'mov', 'wmv'];
            const audioExts = ['mp3', 'wav', 'flac', 'aac'];
            
            if (imageExts.includes(ext)) return '<i class="fas fa-image"></i>';
            if (docExts.includes(ext)) return '<i class="fas fa-file-alt"></i>';
            if (archiveExts.includes(ext)) return '<i class="fas fa-file-archive"></i>';
            if (videoExts.includes(ext)) return '<i class="fas fa-file-video"></i>';
            if (audioExts.includes(ext)) return '<i class="fas fa-file-audio"></i>';
            
            return '<i class="fas fa-file"></i>';
        }
        
        function getFileIconClass(file) {
            if (file.is_dir) return 'folder';
            
            const ext = file.name.split('.').pop().toLowerCase();
            const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'];
            const docExts = ['doc', 'docx', 'pdf', 'txt', 'rtf'];
            const archiveExts = ['zip', 'rar', '7z', 'tar', 'gz'];
            
            if (imageExts.includes(ext)) return 'image';
            if (docExts.includes(ext)) return 'document';
            if (archiveExts.includes(ext)) return 'archive';
            
            return 'default';
        }
        
        function escapeHtml(text) {
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        }
        
        function showToast(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = `toast ${type} show`;
            
            const iconMap = {
                success: 'fas fa-check-circle',
                error: 'fas fa-exclamation-circle',
                info: 'fas fa-info-circle'
            };
            
            toast.innerHTML = `
                <i class="toast-icon ${iconMap[type] || iconMap.info}"></i>
                <div class="toast-message">${message}</div>
                <button class="toast-close" onclick="this.parentElement.remove()">
                    <i class="fas fa-times"></i>
                </button>
            `;
            
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.remove();
            }, 5000);
        }
        
        // 文件选择功能
        function toggleFileSelection(filename) {
            if (selectedFiles.has(filename)) {
                selectedFiles.delete(filename);
            } else {
                selectedFiles.add(filename);
            }
            updateSelectionButtons();
            updateFileSelectionUI();
        }
        
        function toggleSelectAll() {
            const checkboxes = document.querySelectorAll('.file-checkbox');
            const allSelected = checkboxes.length > 0 && Array.from(checkboxes).every(cb => cb.checked);
            
            if (allSelected) {
                selectedFiles.clear();
                checkboxes.forEach(cb => cb.checked = false);
            } else {
                checkboxes.forEach(cb => {
                    cb.checked = true;
                    const filename = cb.closest('[data-filename]').dataset.filename;
                    selectedFiles.add(filename);
                });
            }
            
            updateSelectionButtons();
            updateFileSelectionUI();
        }
        
        function updateSelectionButtons() {
            const hasSelection = selectedFiles.size > 0;
            document.getElementById('downloadBtn').disabled = !hasSelection;
            document.getElementById('deleteBtn').disabled = !hasSelection;
            document.getElementById('shareBtn').disabled = !hasSelection;
            
            const selectAllBtn = document.getElementById('selectAllBtn');
            const checkboxes = document.querySelectorAll('.file-checkbox');
            const allSelected = checkboxes.length > 0 && Array.from(checkboxes).every(cb => cb.checked);
            
            selectAllBtn.innerHTML = allSelected ? 
                '<i class="fas fa-square"></i> 取消全选' : 
                '<i class="fas fa-check-square"></i> 全选';
        }
        
        function updateFileSelectionUI() {
            document.querySelectorAll('[data-filename]').forEach(item => {
                const filename = item.dataset.filename;
                const checkbox = item.querySelector('.file-checkbox');
                checkbox.checked = selectedFiles.has(filename);
                
                if (selectedFiles.has(filename)) {
                    item.classList.add('selected');
                } else {
                    item.classList.remove('selected');
                }
            });
        }
        
        // 搜索功能
        function handleSearch() {
            const query = document.getElementById('searchInput').value.toLowerCase();
            const items = document.querySelectorAll('[data-filename]');
            
            items.forEach(item => {
                const filename = item.dataset.filename.toLowerCase();
                if (filename.includes(query)) {
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            });
        }
        
        // 视图切换
        function switchView(view) {
            currentView = view;
            document.querySelectorAll('.view-toggle button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-view="${view}"]`).classList.add('active');
            
            // 重新加载当前文件列表
            loadFiles(currentPath);
        }
        
        // 传输面板
        function toggleTransferPanel() {
            const panel = document.getElementById('transferPanel');
            panel.classList.toggle('show');
        }
        
        function closeTransferPanel() {
            document.getElementById('transferPanel').classList.remove('show');
        }
        
        function updateTransferList() {
            const container = document.getElementById('transferList');
            
            if (transferTasks.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #718096;">
                        <i class="fas fa-exchange-alt" style="font-size: 48px; margin-bottom: 16px;"></i>
                        <div>暂无传输任务</div>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = transferTasks.map(task => `
                <div class="transfer-item">
                    <div class="transfer-name">${escapeHtml(task.name)}</div>
                    <div class="transfer-progress">
                        <div class="transfer-progress-bar">
                            <div class="transfer-progress-fill" style="width: ${task.progress}%"></div>
                        </div>
                        <span>${task.progress}%</span>
                    </div>
                    <div style="font-size: 12px; color: #718096; margin-top: 4px;">
                        ${task.status === 'uploading' ? '上传中' : 
                          task.status === 'downloading' ? '下载中' : 
                          task.status === 'completed' ? '已完成' : '错误'}
                    </div>
                </div>
            `).join('');
        }
        
        function updateTransferProgress() {
            // 这里可以添加实时进度更新逻辑
        }
        
        // 存储信息
        function loadStorageInfo() {
            fetch('/storage-info')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        storageInfo = data.storage;
                        updateStorageDisplay();
                    }
                })
                .catch(console.error);
        }
        
        function updateStorageDisplay() {
            const usedPercent = (storageInfo.used / storageInfo.total) * 100;
            const usedText = formatFileSize(storageInfo.used);
            const totalText = formatFileSize(storageInfo.total);
            
            document.getElementById('storageProgress').style.width = usedPercent + '%';
            document.getElementById('storageText').textContent = `${usedText} / ${totalText}`;
            
            // 存储空间不足警告
            if (usedPercent > 90) {
                document.getElementById('storageText').style.color = '#e53e3e';
            } else if (usedPercent > 80) {
                document.getElementById('storageText').style.color = '#d69e2e';
            } else {
                document.getElementById('storageText').style.color = '#718096';
            }
        }
        
        // 下拉菜单
        function toggleDropdown(button) {
            // 关闭其他下拉菜单
            document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
                if (menu !== button.nextElementSibling) {
                    menu.classList.remove('show');
                }
            });
            
            // 切换当前下拉菜单
            button.nextElementSibling.classList.toggle('show');
        }
        
        // 点击其他地方关闭下拉菜单
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.dropdown')) {
                document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
                    menu.classList.remove('show');
                });
            }
        });
        
        // 批量操作
        function downloadSelected() {
            if (selectedFiles.size === 0) return;
            
            selectedFiles.forEach(filename => {
                const url = `/download?path=${encodeURIComponent(currentPath)}&filename=${encodeURIComponent(filename)}`;
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            });
        }
        
        function deleteSelected() {
            if (selectedFiles.size === 0) return;
            
            if (!confirm(`确定要删除选中的 ${selectedFiles.size} 个项目吗？`)) {
                return;
            }
            
            const promises = Array.from(selectedFiles).map(filename => {
                return fetch('/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        path: currentPath,
                        filename: filename
                    })
                });
            });
            
            Promise.all(promises).then(() => {
                selectedFiles.clear();
                loadFiles(currentPath);
                showToast('删除成功！', 'success');
            }).catch(() => {
                showToast('删除失败，请重试', 'error');
            });
        }
        
        // 文件分享
        function shareSelectedFiles() {
            if (selectedFiles.size === 0) return;
            
            const files = Array.from(selectedFiles);
            fetch('/create-share', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    path: currentPath,
                    files: files
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const shareUrl = `${window.location.origin}/share/${data.share_id}`;
                    showShareModal(shareUrl);
                } else {
                    showToast('创建分享链接失败', 'error');
                }
            })
            .catch(() => {
                showToast('创建分享链接失败', 'error');
            });
        }
        
        function showShareModal(shareUrl) {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 class="modal-title">分享链接</h3>
                        <button class="modal-close" onclick="this.closest('.modal').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label class="form-label">分享链接：</label>
                            <input type="text" class="form-input" value="${shareUrl}" readonly>
                        </div>
                        <p style="color: #718096; font-size: 14px; margin-top: 12px;">
                            此链接允许他人下载选中的文件，链接永久有效。
                        </p>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-primary" onclick="copyToClipboard('${shareUrl}')">复制链接</button>
                        <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">关闭</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }
        
        function copyToClipboard(text) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(() => {
                    showToast('链接已复制到剪贴板', 'success');
                }).catch(() => {
                    fallbackCopyTextToClipboard(text);
                });
            } else {
                fallbackCopyTextToClipboard(text);
            }
        }
        
        function fallbackCopyTextToClipboard(text) {
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            
            try {
                const successful = document.execCommand('copy');
                if (successful) {
                    showToast('链接已复制到剪贴板', 'success');
                } else {
                    showToast('复制失败，请手动复制', 'error');
                }
            } catch (err) {
                showToast('复制失败，请手动复制', 'error');
            }
            
            document.body.removeChild(textArea);
        }
        
        // 响应式处理
        function handleResize() {
            const sidebarToggle = document.getElementById('sidebarToggle');
            if (window.innerWidth <= 1024) {
                sidebarToggle.style.display = 'block';
            } else {
                sidebarToggle.style.display = 'none';
                document.getElementById('sidebar').classList.remove('show');
            }
        }
        
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('show');
        }
        
        function toggleSidebarCollapse() {
            document.getElementById('sidebar').classList.toggle('collapsed');
        }
        
        // 页面切换
        function switchPage(page) {
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
            });
            document.querySelector(`[data-page="${page}"]`).classList.add('active');
            
            // 显示加载状态
            showLoading();
            
            // 延迟执行以显示加载动画
            setTimeout(() => {
                switch(page) {
                    case 'files':
                        showFilesPage();
                        break;
                    case 'recent':
                        showRecentPage();
                        break;
                    case 'shared':
                        showSharedPage();
                        break;
                    case 'quick-transfer':
                        showQuickTransferPage();
                        break;
                    default:
                        showFilesPage();
                }
            }, 100);
        }
        
        function showLoading(container = null) {
            const target = container || document.getElementById('fileContainer');
            target.innerHTML = `
                <div class="loading">
                    <div class="loading-spinner"></div>
                    <span>加载中...</span>
                </div>
            `;
        }
        
        function showFilesPage() {
            const container = document.getElementById('fileContainer');
            // 隐藏上传区域，只显示工具栏
            document.querySelector('.upload-zone').style.display = 'none';
            document.querySelector('.toolbar').style.display = 'flex';
            loadFiles(currentPath);
        }
        
        function showRecentPage() {
            const container = document.getElementById('fileContainer');
            // 隐藏上传区域和工具栏
            document.querySelector('.upload-zone').style.display = 'none';
            document.querySelector('.toolbar').style.display = 'none';
            
            fetch('/recent-files')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        displayRecentFiles(data.files);
                    } else {
                        container.innerHTML = '<div style="text-align: center; padding: 60px; color: #718096;">加载最近文件失败</div>';
                    }
                })
                .catch(() => {
                    container.innerHTML = '<div style="text-align: center; padding: 60px; color: #718096;">加载最近文件失败</div>';
                });
        }
        
        function displayRecentFiles(files) {
            const container = document.getElementById('fileContainer');
            
            if (files.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 60px; color: #718096;">
                        <i class="fas fa-clock" style="font-size: 48px; margin-bottom: 16px; display: block;"></i>
                        暂无最近使用的文件
                    </div>
                `;
                return;
            }
            
            const fileList = document.createElement('div');
            fileList.className = 'file-list';
            
            files.forEach(file => {
                const timeAgo = getTimeAgo(file.timestamp);
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                
                fileItem.innerHTML = `
                    <div class="file-icon default">
                        <i class="fas fa-file"></i>
                    </div>
                    <div class="file-info">
                        <div class="file-name">${escapeHtml(file.name)}</div>
                        <div class="file-meta">${formatFileSize(file.size)} • ${timeAgo} • ${file.action === 'upload' ? '上传' : '下载'}</div>
                    </div>
                    <div class="file-actions">
                        <a href="/download?path=${encodeURIComponent(file.path)}&filename=${encodeURIComponent(file.name)}" class="btn btn-secondary">
                            <i class="fas fa-download"></i> 下载
                        </a>
                    </div>
                `;
                
                fileList.appendChild(fileItem);
            });
            
            container.innerHTML = '';
            container.appendChild(fileList);
        }
        
        function showSharedPage() {
            const container = document.getElementById('fileContainer');
            document.querySelector('.upload-zone').style.display = 'none';
            document.querySelector('.toolbar').style.display = 'none';
            
            fetch('/my-shares')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        displaySharedFiles(data.shares);
                    } else {
                        container.innerHTML = '<div style="text-align: center; padding: 60px; color: #718096;">加载分享失败</div>';
                    }
                })
                .catch(() => {
                    container.innerHTML = '<div style="text-align: center; padding: 60px; color: #718096;">加载分享失败</div>';
                });
        }
        
        function displaySharedFiles(shares) {
            const container = document.getElementById('fileContainer');
            
            if (shares.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 60px; color: #718096;">
                        <i class="fas fa-share-alt" style="font-size: 48px; margin-bottom: 16px; display: block;"></i>
                        暂无分享的文件
                    </div>
                `;
                return;
            }
            
            const shareList = document.createElement('div');
            shareList.className = 'file-list';
            
            shares.forEach(share => {
                const timeAgo = getTimeAgo(share.created_at);
                const shareItem = document.createElement('div');
                shareItem.className = 'file-item';
                
                shareItem.innerHTML = `
                    <div class="file-icon folder">
                        <i class="fas fa-share-alt"></i>
                    </div>
                    <div class="file-info">
                        <div class="file-name">${share.files.join(', ')}</div>
                        <div class="file-meta">${share.files.length}个文件 • ${timeAgo}</div>
                    </div>
                    <div class="file-actions">
                        <button class="btn btn-secondary" onclick="copyShareLink('${window.location.origin}${share.url}')">
                            <i class="fas fa-copy"></i> 复制链接
                        </button>
                        <button class="btn btn-danger" onclick="revokeShare('${share.id}')">
                            <i class="fas fa-times"></i> 撤销
                        </button>
                    </div>
                `;
                
                shareList.appendChild(shareItem);
            });
            
            container.innerHTML = '';
            container.appendChild(shareList);
        }
        
        function showQuickTransferPage() {
            const container = document.getElementById('fileContainer');
            document.querySelector('.upload-zone').style.display = 'none';
            document.querySelector('.toolbar').style.display = 'none';
            
            // 显示快传界面
            container.innerHTML = `
                <div style="display: flex; gap: 32px; height: 70vh;">
                    <!-- 左侧：上传区域 -->
                    <div style="flex: 1; background: white; border-radius: 12px; border: 1px solid #e2e8f0; padding: 32px;">
                        <h3 style="margin-bottom: 24px; color: #1a202c;">
                            <i class="fas fa-upload" style="color: #3182ce; margin-right: 12px;"></i>
                            发送文件
                        </h3>
                        
                        <div class="upload-zone" id="quickUploadZone" style="margin-bottom: 24px;">
                            <div class="upload-icon">
                                <i class="fas fa-bolt"></i>
                            </div>
                            <div class="upload-text">拖拽文件到此处快传</div>
                            <div class="upload-subtext">文件将在1小时后自动删除</div>
                            <div class="upload-buttons">
                                <button class="btn btn-primary" onclick="document.getElementById('quickFileInput').click()">
                                    <i class="fas fa-file"></i> 选择文件
                                </button>
                                <button class="btn btn-secondary" onclick="document.getElementById('quickFolderInput').click()">
                                    <i class="fas fa-folder"></i> 选择文件夹
                                </button>
                            </div>
                            
                            <input type="file" id="quickFileInput" class="hidden" multiple>
                            <input type="file" id="quickFolderInput" class="hidden" webkitdirectory>
                        </div>
                        
                        <div style="border-top: 1px solid #e2e8f0; padding-top: 16px;">
                            <label style="display: block; margin-bottom: 8px; font-weight: 500;">发送者名称：</label>
                            <input type="text" id="uploaderName" class="form-input" placeholder="请输入您的名称" value="匿名用户">
                        </div>
                    </div>
                    
                    <!-- 右侧：文件列表 -->
                    <div style="flex: 1; background: white; border-radius: 12px; border: 1px solid #e2e8f0; padding: 32px;">
                        <h3 style="margin-bottom: 24px; color: #1a202c;">
                            <i class="fas fa-download" style="color: #38a169; margin-right: 12px;"></i>
                            接收文件
                        </h3>
                        <div id="quickTransferList">
                            <div style="text-align: center; padding: 40px; color: #718096;">
                                正在加载...
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            // 设置快传上传事件
            setupQuickTransferEvents();
            loadQuickTransferFiles();
        }
        
        // 辅助函数
        function getTimeAgo(timestamp) {
            const now = new Date();
            const time = new Date(timestamp);
            const diff = now - time;
            
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);
            
            if (days > 0) return `${days}天前`;
            if (hours > 0) return `${hours}小时前`;
            if (minutes > 0) return `${minutes}分钟前`;
            return '刚刚';
        }
        
        function copyShareLink(url) {
            navigator.clipboard.writeText(url).then(() => {
                showToast('分享链接已复制', 'success');
            }).catch(() => {
                // 备用方法
                const textArea = document.createElement('textarea');
                textArea.value = url;
                document.body.appendChild(textArea);
                textArea.select();
                try {
                    document.execCommand('copy');
                    showToast('分享链接已复制', 'success');
                } catch (err) {
                    showToast('复制失败，请手动复制', 'error');
                }
                document.body.removeChild(textArea);
            });
        }
        
        function revokeShare(shareId) {
            if (!confirm('确定要撤销这个分享吗？')) return;
            
            fetch('/revoke-share', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ share_id: shareId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast('分享已撤销', 'success');
                    showSharedPage(); // 刷新页面
                } else {
                    showToast('撤销失败', 'error');
                }
            })
            .catch(() => {
                showToast('撤销失败', 'error');
            });
        }
        
        function setupQuickTransferEvents() {
            const quickUploadZone = document.getElementById('quickUploadZone');
            const quickFileInput = document.getElementById('quickFileInput');
            const quickFolderInput = document.getElementById('quickFolderInput');
            
            if (quickUploadZone) {
                quickUploadZone.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    quickUploadZone.classList.add('dragover');
                });
                
                quickUploadZone.addEventListener('dragleave', (e) => {
                    e.preventDefault();
                    quickUploadZone.classList.remove('dragover');
                });
                
                quickUploadZone.addEventListener('drop', (e) => {
                    e.preventDefault();
                    quickUploadZone.classList.remove('dragover');
                    
                    const files = Array.from(e.dataTransfer.files);
                    if (files.length > 0) {
                        uploadQuickTransferFiles(files);
                    }
                });
            }
            
            if (quickFileInput) {
                quickFileInput.addEventListener('change', (e) => {
                    const files = Array.from(e.target.files);
                    if (files.length > 0) {
                        uploadQuickTransferFiles(files);
                    }
                });
            }
            
            if (quickFolderInput) {
                quickFolderInput.addEventListener('change', (e) => {
                    const files = Array.from(e.target.files);
                    if (files.length > 0) {
                        uploadQuickTransferFiles(files);
                    }
                });
            }
        }
        
        function uploadQuickTransferFiles(files) {
            const formData = new FormData();
            const uploaderName = document.getElementById('uploaderName').value || '匿名用户';
            
            files.forEach(file => {
                formData.append('files', file);
                if (file.webkitRelativePath) {
                    formData.append('paths', file.webkitRelativePath);
                }
            });
            
            formData.append('uploader', uploaderName);
            
            fetch('/quick-transfer-upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast(data.message, 'success');
                    loadQuickTransferFiles();
                    
                    // 清空输入
                    document.getElementById('quickFileInput').value = '';
                    document.getElementById('quickFolderInput').value = '';
                } else {
                    showToast('快传失败: ' + data.message, 'error');
                }
            })
            .catch(() => {
                showToast('快传失败，请重试', 'error');
            });
        }
        
        function loadQuickTransferFiles() {
            fetch('/quick-transfer-files')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        displayQuickTransferFiles(data.files);
                    } else {
                        document.getElementById('quickTransferList').innerHTML = 
                            '<div style="text-align: center; padding: 40px; color: #718096;">加载失败</div>';
                    }
                })
                .catch(() => {
                    document.getElementById('quickTransferList').innerHTML = 
                        '<div style="text-align: center; padding: 40px; color: #718096;">加载失败</div>';
                });
        }
        
        function displayQuickTransferFiles(files) {
            const container = document.getElementById('quickTransferList');
            
            if (files.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #718096;">
                        <i class="fas fa-inbox" style="font-size: 48px; margin-bottom: 16px; display: block;"></i>
                        暂无快传文件
                    </div>
                `;
                return;
            }
            
            container.innerHTML = files.map(file => `
                <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div style="flex: 1;">
                            <div style="font-weight: 500; margin-bottom: 4px;">${escapeHtml(file.name)}</div>
                            <div style="font-size: 13px; color: #718096;">
                                ${formatFileSize(file.size)} • ${file.uploader} • ${getTimeAgo(file.upload_time)}
                            </div>
                            <div style="font-size: 12px; color: #d69e2e; margin-top: 4px;">
                                ${file.expires_in.includes('-') ? '已过期' : '剩余时间: ' + file.expires_in}
                            </div>
                        </div>
                        <button class="btn btn-primary" onclick="downloadQuickFile('${escapeHtml(file.name)}')">
                            <i class="fas fa-download"></i> 下载
                        </button>
                    </div>
                </div>
            `).join('');
        }
        
        function downloadQuickFile(filename) {
            window.location.href = `/quick-transfer-download?filename=${encodeURIComponent(filename)}`;
        }
        
        // 重命名功能
        function showRenameModal(filename) {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 class="modal-title">重命名</h3>
                        <button class="modal-close" onclick="this.closest('.modal').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label class="form-label">新名称：</label>
                            <input type="text" class="form-input" id="newNameInput" value="${escapeHtml(filename)}">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-primary" onclick="performRename('${escapeHtml(filename)}')">确定</button>
                        <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            
            // 聚焦到输入框并选中文件名（不包括扩展名）
            const input = document.getElementById('newNameInput');
            input.focus();
            const lastDotIndex = filename.lastIndexOf('.');
            if (lastDotIndex > 0) {
                input.setSelectionRange(0, lastDotIndex);
            } else {
                input.select();
            }
        }
        
        function performRename(oldName) {
            const newName = document.getElementById('newNameInput').value.trim();
            if (!newName || newName === oldName) {
                document.querySelector('.modal').remove();
                return;
            }
            
            fetch('/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    path: currentPath,
                    old_name: oldName,
                    new_name: newName
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast('重命名成功！', 'success');
                    loadFiles(currentPath);
                } else {
                    showToast('重命名失败: ' + data.message, 'error');
                }
                document.querySelector('.modal').remove();
            })
            .catch(() => {
                showToast('重命名失败，请重试', 'error');
                document.querySelector('.modal').remove();
            });
        }
        
        // 文件详情
        function showFileDetails(filename) {
            fetch(`/files?path=${encodeURIComponent(currentPath)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const file = data.files.find(f => f.name === filename);
                        if (file) {
                            showFileDetailsModal(file);
                        }
                    }
                })
                .catch(console.error);
        }
        
        function showFileDetailsModal(file) {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 class="modal-title">文件详情</h3>
                        <button class="modal-close" onclick="this.closest('.modal').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <div style="text-align: center; margin-bottom: 24px;">
                            <div class="file-icon ${getFileIconClass(file)}" style="font-size: 64px; margin-bottom: 16px;">
                                ${getFileIcon(file)}
                            </div>
                            <h4>${escapeHtml(file.name)}</h4>
                        </div>
                        <div style="display: grid; gap: 12px;">
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: #718096;">类型：</span>
                                <span>${file.is_dir ? '文件夹' : '文件'}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: #718096;">大小：</span>
                                <span>${file.is_dir ? '文件夹' : formatFileSize(file.size)}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: #718096;">修改时间：</span>
                                <span>${file.modified}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: #718096;">路径：</span>
                                <span style="word-break: break-all;">${currentPath ? currentPath + '/' + file.name : file.name}</span>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">关闭</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }
    </script>
</body>
</html>
    """
    return render_template_string(html_template, session=session)

@app.route('/upload', methods=['POST'])
@login_required
def upload_files():
    """处理文件上传"""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'message': '没有找到文件'})
        
        files = request.files.getlist('files')
        paths = request.form.getlist('paths')  # 文件夹上传时的相对路径
        target_path = request.form.get('path', '')
        
        if not files or files[0].filename == '':
            return jsonify({'success': False, 'message': '没有选择文件'})
        
        uploaded_files = []
        
        for i, file in enumerate(files):
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                
                # 如果有相对路径信息，使用相对路径
                if i < len(paths) and paths[i]:
                    relative_path = paths[i]
                    # 确保路径安全
                    relative_path = relative_path.replace('..', '').strip('/')
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], target_path, relative_path)
                else:
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], target_path, filename)
                
                # 创建目录（如果不存在）
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                # 保存文件
                file.save(file_path)
                uploaded_files.append(filename)
                
                # 添加到最近使用文件
                add_to_recent_files(filename, target_path)
        
        return jsonify({
            'success': True, 
            'message': f'成功上传 {len(uploaded_files)} 个文件',
            'files': uploaded_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'上传失败: {str(e)}'})

@app.route('/files')
@login_required
def list_files():
    """获取文件列表"""
    try:
        path = request.args.get('path', '')
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
        
        # 安全检查，防止路径遍历攻击
        full_path = os.path.abspath(full_path)
        upload_path = os.path.abspath(app.config['UPLOAD_FOLDER'])
        
        if not full_path.startswith(upload_path):
            return jsonify({'success': False, 'message': '无效的路径'})
        
        if not os.path.exists(full_path):
            os.makedirs(full_path, exist_ok=True)
        
        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            try:
                file_info = get_file_info(item_path)
                files.append(file_info)
            except (OSError, IOError):
                continue  # 跳过无法访问的文件
        
        # 排序：文件夹在前，然后按名称排序
        files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        
        return jsonify({'success': True, 'files': files})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取文件列表失败: {str(e)}'})

@app.route('/download')
@login_required
def download_file():
    """下载文件或文件夹"""
    try:
        path = request.args.get('path', '')
        filename = request.args.get('filename', '')
        
        if not filename:
            return jsonify({'success': False, 'message': '文件名不能为空'})
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], path, filename)
        
        # 安全检查
        file_path = os.path.abspath(file_path)
        upload_path = os.path.abspath(app.config['UPLOAD_FOLDER'])
        
        if not file_path.startswith(upload_path):
            return jsonify({'success': False, 'message': '无效的文件路径'})
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '文件不存在'})
        
        if os.path.isdir(file_path):
            # 如果是文件夹，创建zip压缩包
            import zipfile
            import tempfile
            
            temp_dir = tempfile.mkdtemp()
            zip_path = os.path.join(temp_dir, f'{filename}.zip')
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(file_path):
                    for file in files:
                        file_full_path = os.path.join(root, file)
                        # 计算相对路径，保持文件夹结构
                        arcname = os.path.relpath(file_full_path, file_path)
                        zipf.write(file_full_path, arcname)
            
            # 发送文件后删除临时文件
            def remove_temp_file(response):
                try:
                    os.remove(zip_path)
                    os.rmdir(temp_dir)
                except:
                    pass
                return response
            
            response = send_file(zip_path, as_attachment=True, download_name=f'{filename}.zip')
            response.call_on_close(lambda: remove_temp_file)
            return response
        else:
            return send_file(file_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'下载失败: {str(e)}'})

@app.route('/delete', methods=['POST'])
@login_required
def delete_file():
    """删除文件或文件夹"""
    try:
        data = request.get_json()
        path = data.get('path', '')
        filename = data.get('filename', '')
        
        if not filename:
            return jsonify({'success': False, 'message': '文件名不能为空'})
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], path, filename)
        
        # 安全检查
        file_path = os.path.abspath(file_path)
        upload_path = os.path.abspath(app.config['UPLOAD_FOLDER'])
        
        if not file_path.startswith(upload_path):
            return jsonify({'success': False, 'message': '无效的文件路径'})
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '文件不存在'})
        
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
        else:
            os.remove(file_path)
        
        return jsonify({'success': True, 'message': '删除成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

@app.route('/storage-info')
@login_required
def storage_info():
    """获取存储空间信息"""
    try:
        # 清理过期的快传文件
        clean_expired_quick_transfers()
        
        used_space = get_directory_size(UPLOAD_FOLDER) + get_directory_size(QUICK_TRANSFER_FOLDER)
        
        return jsonify({
            'success': True,
            'storage': {
                'used': used_space,
                'total': TOTAL_STORAGE,
                'available': TOTAL_STORAGE - used_space
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取存储信息失败: {str(e)}'})

@app.route('/create-share', methods=['POST'])
@login_required
def create_share():
    """创建分享链接"""
    try:
        data = request.get_json()
        path = data.get('path', '')
        files = data.get('files', [])
        
        if not files:
            return jsonify({'success': False, 'message': '没有选择文件'})
        
        # 生成分享ID
        share_id = str(uuid.uuid4())
        
        # 存储分享信息
        shares_data[share_id] = {
            'path': path,
            'files': files,
            'created_at': datetime.now().isoformat(),
            'created_by': session.get('username', '未知用户')
        }
        
        return jsonify({
            'success': True,
            'share_id': share_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'创建分享失败: {str(e)}'})

@app.route('/share/<share_id>')
def view_share(share_id):
    """查看分享页面"""
    if share_id not in shares_data:
        return render_template_string("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>分享不存在 - 网盘系统</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .error { text-align: center; background: white; padding: 60px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h1 { color: #e53e3e; margin-bottom: 16px; }
        p { color: #718096; }
    </style>
</head>
<body>
    <div class="error">
        <h1>😕 分享链接不存在或已过期</h1>
        <p>请确认链接是否正确，或联系分享者重新生成链接</p>
    </div>
</body>
</html>
        """), 404
    
    share_info = shares_data[share_id]
    
    def generate_file_list_html():
        html = ""
        for filename in share_info['files']:
            file_path = os.path.join(UPLOAD_FOLDER, share_info['path'], filename)
            if os.path.exists(file_path):
                is_dir = os.path.isdir(file_path)
                icon = '<i class="fas fa-folder"></i>' if is_dir else '<i class="fas fa-file"></i>'
                
                if is_dir:
                    size_text = '文件夹'
                else:
                    size_bytes = os.path.getsize(file_path)
                    if size_bytes < 1024:
                        size_text = f'{size_bytes} B'
                    elif size_bytes < 1024 * 1024:
                        size_text = f'{size_bytes / 1024:.1f} KB'
                    elif size_bytes < 1024 * 1024 * 1024:
                        size_text = f'{size_bytes / (1024 * 1024):.1f} MB'
                    else:
                        size_text = f'{size_bytes / (1024 * 1024 * 1024):.1f} GB'
                
                # HTML转义文件名
                safe_filename = filename.replace("'", "\\'").replace('"', '\\"')
                
                html += f"""
                <div class="file-item">
                    <div class="file-icon">{icon}</div>
                    <div class="file-info">
                        <div class="file-name">{filename}</div>
                        <div class="file-meta">{size_text}</div>
                    </div>
                    <button class="download-btn" onclick="downloadFile('{safe_filename}')">
                        <i class="fas fa-download"></i> 下载
                    </button>
                </div>
                """
        return html
    
    def generate_download_all_js():
        js_lines = []
        for filename in share_info['files']:
            safe_filename = filename.replace("'", "\\'").replace('"', '\\"')
            js_lines.append(f"setTimeout(() => downloadFile('{safe_filename}'), {len(js_lines) * 500});")
        return '\n'.join(js_lines)
    
    html_template = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>文件分享 - 网盘系统</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif; background: #f5f7fa; min-height: 100vh; color: #2d3748; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 40px 20px; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .header h1 {{ font-size: 32px; margin-bottom: 16px; color: #1a202c; }}
        .header p {{ color: #718096; }}
        .file-list {{ background: white; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; }}
        .file-item {{ display: flex; align-items: center; padding: 20px; border-bottom: 1px solid #f1f5f9; }}
        .file-item:last-child {{ border-bottom: none; }}
        .file-icon {{ width: 48px; height: 48px; margin-right: 16px; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #3182ce; }}
        .file-info {{ flex: 1; }}
        .file-name {{ font-weight: 500; margin-bottom: 4px; color: #1a202c; word-break: break-all; }}
        .file-meta {{ font-size: 14px; color: #718096; }}
        .download-btn {{ background: #3182ce; color: white; border: none; padding: 12px 20px; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; transition: background 0.2s; }}
        .download-btn:hover {{ background: #2c5aa0; }}
        .download-all {{ text-align: center; padding: 24px; border-bottom: 1px solid #f1f5f9; }}
        .toast {{ position: fixed; top: 20px; right: 20px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1); z-index: 3000; display: none; }}
        .toast.success {{ border-left: 4px solid #38a169; }}
        .toast.error {{ border-left: 4px solid #e53e3e; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-share-alt"></i> 文件分享</h1>
            <p>{share_info.get('created_by', '未知用户')} 向你分享了以下文件</p>
        </div>
        
        <div class="file-list">
            <div class="download-all">
                <button class="download-btn" onclick="downloadAll()">
                    <i class="fas fa-download"></i> 下载全部
                </button>
            </div>
            {generate_file_list_html()}
        </div>
    </div>
    
    <div class="toast" id="toast"></div>
    
    <script>
        function downloadFile(filename) {{
            const url = `/share/{share_id}/download?filename=${{encodeURIComponent(filename)}}`;
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            
            showToast('开始下载: ' + filename, 'success');
        }}
        
        function downloadAll() {{
            showToast('开始批量下载...', 'success');
            {generate_download_all_js()}
        }}
        
        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = `toast ${{type}}`;
            toast.style.display = 'block';
            
            setTimeout(() => {{
                toast.style.display = 'none';
            }}, 3000);
        }}
    </script>
</body>
</html>
    """
    
    return render_template_string(html_template)

@app.route('/share/<share_id>/download')
def download_shared_file(share_id):
    """下载分享的文件"""
    if share_id not in shares_data:
        return "分享链接不存在或已过期", 404
    
    share_info = shares_data[share_id]
    filename = request.args.get('filename', '')
    
    if filename not in share_info['files']:
        return "文件不在分享列表中", 403
    
    try:
        file_path = os.path.join(UPLOAD_FOLDER, share_info['path'], filename)
        
        if not os.path.exists(file_path):
            return "文件不存在", 404
        
        if os.path.isdir(file_path):
            # 如果是文件夹，创建zip压缩包
            import zipfile
            import tempfile
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            with zipfile.ZipFile(temp_file.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(file_path):
                    for file in files:
                        file_full_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_full_path, file_path)
                        zipf.write(file_full_path, arcname)
            
            return send_file(temp_file.name, as_attachment=True, download_name=f'{filename}.zip')
        else:
            return send_file(file_path, as_attachment=True, download_name=filename)
            
    except Exception as e:
        return f"下载失败: {str(e)}", 500

@app.route('/rename', methods=['POST'])
def rename_file():
    """重命名文件或文件夹"""
    try:
        data = request.get_json()
        path = data.get('path', '')
        old_name = data.get('old_name', '')
        new_name = data.get('new_name', '')
        
        if not old_name or not new_name:
            return jsonify({'success': False, 'message': '文件名不能为空'})
        
        old_path = os.path.join(UPLOAD_FOLDER, path, old_name)
        new_path = os.path.join(UPLOAD_FOLDER, path, secure_filename(new_name))
        
        # 安全检查
        old_path = os.path.abspath(old_path)
        new_path = os.path.abspath(new_path)
        upload_path = os.path.abspath(UPLOAD_FOLDER)
        
        if not old_path.startswith(upload_path) or not new_path.startswith(upload_path):
            return jsonify({'success': False, 'message': '无效的文件路径'})
        
        if not os.path.exists(old_path):
            return jsonify({'success': False, 'message': '文件不存在'})
        
        if os.path.exists(new_path):
            return jsonify({'success': False, 'message': '目标文件名已存在'})
        
        os.rename(old_path, new_path)
        
        return jsonify({'success': True, 'message': '重命名成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'重命名失败: {str(e)}'})

@app.route('/recent-files')
@login_required
def get_recent_files():
    """获取最近使用的文件"""
    try:
        return jsonify({
            'success': True,
            'files': recent_files[:20]  # 只返回最近20个
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取最近文件失败: {str(e)}'})

@app.route('/my-shares')
@login_required
def get_my_shares():
    """获取我的分享"""
    try:
        shares_list = []
        for share_id, share_info in shares_data.items():
            shares_list.append({
                'id': share_id,
                'files': share_info['files'],
                'path': share_info['path'],
                'created_at': share_info['created_at'],
                'url': f'/share/{share_id}'
            })
        
        # 按创建时间倒序排列
        shares_list.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            'success': True,
            'shares': shares_list
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取分享列表失败: {str(e)}'})

@app.route('/revoke-share', methods=['POST'])
def revoke_share():
    """撤销分享"""
    try:
        data = request.get_json()
        share_id = data.get('share_id', '')
        
        if share_id in shares_data:
            del shares_data[share_id]
            return jsonify({'success': True, 'message': '分享已撤销'})
        else:
            return jsonify({'success': False, 'message': '分享不存在'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'撤销分享失败: {str(e)}'})

@app.route('/quick-transfer-upload', methods=['POST'])
def quick_transfer_upload():
    """快传文件上传"""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'message': '没有找到文件'})
        
        files = request.files.getlist('files')
        paths = request.form.getlist('paths')
        uploader_name = request.form.get('uploader', '匿名用户')
        
        if not files or files[0].filename == '':
            return jsonify({'success': False, 'message': '没有选择文件'})
        
        uploaded_files = []
        upload_time = datetime.now()
        
        for i, file in enumerate(files):
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                
                # 快传文件保存到单独目录
                if i < len(paths) and paths[i]:
                    relative_path = paths[i]
                    relative_path = relative_path.replace('..', '').strip('/')
                    file_path = os.path.join(QUICK_TRANSFER_FOLDER, relative_path)
                else:
                    file_path = os.path.join(QUICK_TRANSFER_FOLDER, filename)
                
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                file.save(file_path)
                
                uploaded_files.append({
                    'name': filename,
                    'path': file_path,
                    'uploader': uploader_name,
                    'upload_time': upload_time.isoformat(),
                    'size': os.path.getsize(file_path)
                })
        
        return jsonify({
            'success': True,
            'message': f'快传成功上传 {len(uploaded_files)} 个文件，1小时后自动删除',
            'files': uploaded_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'快传上传失败: {str(e)}'})

@app.route('/quick-transfer-files')
def get_quick_transfer_files():
    """获取快传文件列表"""
    try:
        # 先清理过期文件
        clean_expired_quick_transfers()
        
        files = []
        for item in os.listdir(QUICK_TRANSFER_FOLDER):
            item_path = os.path.join(QUICK_TRANSFER_FOLDER, item)
            try:
                stat = os.stat(item_path)
                upload_time = datetime.fromtimestamp(stat.st_mtime)
                
                files.append({
                    'name': item,
                    'size': stat.st_size,
                    'upload_time': upload_time.isoformat(),
                    'uploader': '未知用户',  # 这里可以扩展存储上传者信息
                    'expires_in': str(timedelta(hours=1) - (datetime.now() - upload_time))
                })
            except (OSError, IOError):
                continue
        
        # 按上传时间倒序
        files.sort(key=lambda x: x['upload_time'], reverse=True)
        
        return jsonify({
            'success': True,
            'files': files
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取快传文件失败: {str(e)}'})

@app.route('/quick-transfer-download')
def download_quick_transfer_file():
    """下载快传文件"""
    try:
        filename = request.args.get('filename', '')
        
        if not filename:
            return jsonify({'success': False, 'message': '文件名不能为空'})
        
        file_path = os.path.join(QUICK_TRANSFER_FOLDER, filename)
        
        # 安全检查
        file_path = os.path.abspath(file_path)
        quick_transfer_path = os.path.abspath(QUICK_TRANSFER_FOLDER)
        
        if not file_path.startswith(quick_transfer_path):
            return jsonify({'success': False, 'message': '无效的文件路径'})
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '文件不存在或已过期'})
        
        return send_file(file_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'下载失败: {str(e)}'})

if __name__ == '__main__':
    # 开发环境配置
    app.run(host='0.0.0.0', port=5000, debug=False)
