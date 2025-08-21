#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单网盘系统 - Flask后端服务器
支持文件上传、下载、文件夹上传等功能
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# 配置
UPLOAD_FOLDER = 'uploads'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16GB 最大文件大小
ALLOWED_EXTENSIONS = set()  # 允许所有文件类型

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """检查文件是否允许上传（目前允许所有文件）"""
    return True

def get_file_info(filepath):
    """获取文件信息"""
    stat = os.stat(filepath)
    return {
        'name': os.path.basename(filepath),
        'size': stat.st_size,
        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'is_dir': os.path.isdir(filepath)
    }

@app.route('/')
def index():
    """主页面"""
    html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>个人网盘</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 300;
        }
        
        .content {
            padding: 30px;
        }
        
        .upload-section {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 30px;
            border: 2px dashed #dee2e6;
            transition: all 0.3s ease;
        }
        
        .upload-section:hover {
            border-color: #4facfe;
            background: #f0f8ff;
        }
        
        .upload-area {
            text-align: center;
            cursor: pointer;
        }
        
        .upload-icon {
            font-size: 4em;
            color: #6c757d;
            margin-bottom: 20px;
        }
        
        .upload-text {
            font-size: 1.2em;
            color: #495057;
            margin-bottom: 20px;
        }
        
        .file-input-container {
            margin: 10px 0;
        }
        
        .file-input {
            display: none;
        }
        
        .file-input-label {
            display: inline-block;
            padding: 12px 30px;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 5px;
            font-weight: 500;
        }
        
        .file-input-label:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(79, 172, 254, 0.3);
        }
        
        .progress-container {
            margin-top: 20px;
            display: none;
        }
        
        .progress-bar {
            width: 100%;
            height: 20px;
            background-color: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4facfe, #00f2fe);
            width: 0%;
            transition: width 0.3s ease;
        }
        
        .file-list {
            background: white;
            border-radius: 10px;
            border: 1px solid #dee2e6;
        }
        
        .file-item {
            display: flex;
            align-items: center;
            padding: 15px 20px;
            border-bottom: 1px solid #f1f3f4;
            transition: background-color 0.2s ease;
        }
        
        .file-item:hover {
            background-color: #f8f9fa;
        }
        
        .file-item:last-child {
            border-bottom: none;
        }
        
        .file-icon {
            width: 40px;
            height: 40px;
            margin-right: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
        }
        
        .file-info {
            flex: 1;
        }
        
        .file-name {
            font-weight: 500;
            margin-bottom: 5px;
            color: #343a40;
        }
        
        .file-meta {
            font-size: 0.9em;
            color: #6c757d;
        }
        
        .file-actions {
            display: flex;
            gap: 10px;
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
        
        .btn-download {
            background: #28a745;
            color: white;
        }
        
        .btn-download:hover {
            background: #218838;
            transform: translateY(-1px);
        }
        
        .btn-delete {
            background: #dc3545;
            color: white;
        }
        
        .btn-delete:hover {
            background: #c82333;
            transform: translateY(-1px);
        }
        
        .message {
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
            display: none;
        }
        
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .breadcrumb {
            padding: 15px 0;
            margin-bottom: 20px;
            border-bottom: 1px solid #dee2e6;
        }
        
        .breadcrumb a {
            color: #4facfe;
            text-decoration: none;
            margin-right: 10px;
        }
        
        .breadcrumb a:hover {
            text-decoration: underline;
        }
        
        @media (max-width: 768px) {
            .container {
                margin: 10px;
                border-radius: 10px;
            }
            
            .content {
                padding: 20px;
            }
            
            .file-item {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .file-actions {
                margin-top: 10px;
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌐 个人网盘系统</h1>
            <p>安全、便捷的文件存储解决方案</p>
        </div>
        
        <div class="content">
            <!-- 上传区域 -->
            <div class="upload-section">
                <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                    <div class="upload-icon">📤</div>
                    <div class="upload-text">点击或拖拽文件到此处上传</div>
                    <div class="file-input-container">
                        <input type="file" id="fileInput" class="file-input" multiple>
                        <label for="fileInput" class="file-input-label">选择文件</label>
                        <input type="file" id="folderInput" class="file-input" webkitdirectory>
                        <label for="folderInput" class="file-input-label">选择文件夹</label>
                    </div>
                </div>
                
                <div class="progress-container" id="progressContainer">
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill"></div>
                    </div>
                    <div id="progressText" style="text-align: center; margin-top: 10px;"></div>
                </div>
            </div>
            
            <!-- 消息提示 -->
            <div id="message" class="message"></div>
            
            <!-- 路径导航 -->
            <div class="breadcrumb" id="breadcrumb">
                <a href="#" onclick="loadFiles('')">根目录</a>
            </div>
            
            <!-- 文件列表 -->
            <div class="file-list" id="fileList">
                <!-- 文件列表将通过JavaScript动态加载 -->
            </div>
        </div>
    </div>

    <script>
        let currentPath = '';
        
        // 页面加载时获取文件列表
        document.addEventListener('DOMContentLoaded', function() {
            loadFiles('');
            setupEventListeners();
        });
        
        function setupEventListeners() {
            // 文件选择事件
            document.getElementById('fileInput').addEventListener('change', handleFileSelect);
            document.getElementById('folderInput').addEventListener('change', handleFileSelect);
            
            // 拖拽上传
            const uploadArea = document.querySelector('.upload-area');
            uploadArea.addEventListener('dragover', handleDragOver);
            uploadArea.addEventListener('drop', handleDrop);
        }
        
        function handleDragOver(e) {
            e.preventDefault();
            e.currentTarget.style.background = '#e3f2fd';
        }
        
        function handleDrop(e) {
            e.preventDefault();
            e.currentTarget.style.background = '#f8f9fa';
            
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
            const formData = new FormData();
            
            // 添加文件到FormData
            files.forEach(file => {
                formData.append('files', file);
                // 如果是文件夹上传，保留相对路径
                if (file.webkitRelativePath) {
                    formData.append('paths', file.webkitRelativePath);
                }
            });
            
            formData.append('path', currentPath);
            
            // 显示进度条
            const progressContainer = document.getElementById('progressContainer');
            const progressFill = document.getElementById('progressFill');
            const progressText = document.getElementById('progressText');
            
            progressContainer.style.display = 'block';
            progressFill.style.width = '0%';
            progressText.textContent = '准备上传...';
            
            // 创建XMLHttpRequest以支持进度显示
            const xhr = new XMLHttpRequest();
            
            xhr.upload.addEventListener('progress', function(e) {
                if (e.lengthComputable) {
                    const percentComplete = (e.loaded / e.total) * 100;
                    progressFill.style.width = percentComplete + '%';
                    progressText.textContent = `上传进度: ${Math.round(percentComplete)}%`;
                }
            });
            
            xhr.addEventListener('load', function() {
                progressContainer.style.display = 'none';
                
                if (xhr.status === 200) {
                    const response = JSON.parse(xhr.responseText);
                    if (response.success) {
                        showMessage('文件上传成功！', 'success');
                        loadFiles(currentPath);
                    } else {
                        showMessage('上传失败: ' + response.message, 'error');
                    }
                } else {
                    showMessage('上传失败，请重试', 'error');
                }
                
                // 清空文件选择
                document.getElementById('fileInput').value = '';
                document.getElementById('folderInput').value = '';
            });
            
            xhr.addEventListener('error', function() {
                progressContainer.style.display = 'none';
                showMessage('上传失败，请检查网络连接', 'error');
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
            const fileList = document.getElementById('fileList');
            fileList.innerHTML = '';
            
            if (files.length === 0) {
                fileList.innerHTML = '<div style="text-align: center; padding: 40px; color: #6c757d;">📂 此文件夹为空</div>';
                return;
            }
            
            files.forEach(file => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                
                const icon = file.is_dir ? '📁' : '📄';
                const sizeText = file.is_dir ? '文件夹' : formatFileSize(file.size);
                
                fileItem.innerHTML = `
                    <div class="file-icon">${icon}</div>
                    <div class="file-info">
                        <div class="file-name">${file.name}</div>
                        <div class="file-meta">${sizeText} • ${file.modified}</div>
                    </div>
                    <div class="file-actions">
                        ${file.is_dir ? 
                            `<button class="btn btn-download" onclick="openFolder('${file.name}')">打开</button>` : 
                            `<a href="/download?path=${encodeURIComponent(currentPath)}&filename=${encodeURIComponent(file.name)}" class="btn btn-download">下载</a>`
                        }
                        <button class="btn btn-delete" onclick="deleteFile('${file.name}', ${file.is_dir})">删除</button>
                    </div>
                `;
                
                fileList.appendChild(fileItem);
            });
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
        
        function showMessage(text, type) {
            const message = document.getElementById('message');
            message.textContent = text;
            message.className = `message ${type}`;
            message.style.display = 'block';
            
            setTimeout(() => {
                message.style.display = 'none';
            }, 5000);
        }
    </script>
</body>
</html>
    """
    return render_template_string(html_template)

@app.route('/upload', methods=['POST'])
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
        
        return jsonify({
            'success': True, 
            'message': f'成功上传 {len(uploaded_files)} 个文件',
            'files': uploaded_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'上传失败: {str(e)}'})

@app.route('/files')
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
def download_file():
    """下载文件"""
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
        
        if not os.path.exists(file_path) or os.path.isdir(file_path):
            return jsonify({'success': False, 'message': '文件不存在'})
        
        return send_file(file_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'下载失败: {str(e)}'})

@app.route('/delete', methods=['POST'])
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

if __name__ == '__main__':
    # 开发环境配置
    app.run(host='0.0.0.0', port=5000, debug=False)
