from flask import Flask, render_template, redirect, url_for, request, session
import yaml
from datetime import datetime
import importlib
import os
from flask_socketio import SocketIO

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # 用于session

# 初始化 Socket.IO
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    engineio_logger=True,
    logger=True,
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1e8,
    async_handlers=True
)

# 添加Socket.IO事件处理
@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')

def init_app():
    """初始化应用"""
    from strm_manager import strm_bp

    # 注册蓝图
    app.register_blueprint(strm_bp, url_prefix='/strm')

def format_datetime(timestamp):
    """将时间戳转换为可读的日期时间格式"""
    if not timestamp:
        return ''
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return ''

def get_version():
    """获取版本号"""
    try:
        with open('version.txt', 'r') as f:
            return f.read().strip()
    except:
        return 'unknown'

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.ico'))

@app.route('/')
def index():
    """主页面，显示功能导航"""
    # 获取所有模块的配置
    modules = [
        {
            'name': 'STRM管理',
            'route': '/strm',
            'icon': 'fas fa-file-video',
            'description': '管理STRM文件，支持生成、更新和删除操作'
        }
    ]
    return render_template('home.html', modules=modules)

# 添加静态文件调试信息
@app.before_request
def debug_static():
    if app.debug:
        static_folder = app.static_folder
        qrcode_path = os.path.join(static_folder, 'images', 'qrcode.jpg')
        app.logger.debug(f"Static folder: {static_folder}")
        app.logger.debug(f"QR code path: {qrcode_path}")
        app.logger.debug(f"QR code exists: {os.path.exists(qrcode_path)}")

if __name__ == '__main__':
    init_app()
    socketio.run(app, host='0.0.0.0', port=5525, debug=True)