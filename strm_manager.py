import os
import yaml
import json
import logging
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from flask import Blueprint, render_template, request, jsonify, session, current_app, Response, stream_with_context
import time
from wanzitools import socketio  # 从主应用导入 socketio 实例

# 创建蓝图
strm_bp = Blueprint('strm', __name__)

# 获取应用根目录
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# 添加配置文件路径常量
STRM_CONFIG_FILE = 'config/strm_settings.json'
CONFIG_FILE_PATH = 'config.yaml'

class STRMManager:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(APP_ROOT, "config/strm/config.yaml")
            
        self.config_path = config_path
        self.load_config()
        self.setup_logging()
        
        # 确保默认目录存在
        default_paths = self.config.get('default_paths', {})
        for path in [default_paths.get('source'), default_paths.get('output')]:
            if path:
                os.makedirs(path, exist_ok=True)
                
        # 设置默认的URL前缀配置
        self.default_url_prefixes = {
            'webdav': '',
            'alist': '/dav',
            'alist-xiaoya': '/d',
            'direct': ''
        }
        
        # 设置挂载根目录，用于处理URL
        self.mount_root = self.config.get('mount_root', '/mnt/nas')

    def load_config(self):
        """加载配置文件"""
        try:
            # 确保配置目录存在
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f)
            else:
                # 使用默认配置
                self.config = {
                    'libraries': [],
                    'scan_interval': 3600,
                    'default_paths': {
                        'source': '/mnt/nas/vol1/1000/videos',  # 源文件默认目录
                        'output': '/mnt/nas/vol1/1000/strms'    # STRM文件默认目录
                    },
                    'mount_root': '/mnt/nas',  # 添加挂载根目录配置
                    'logging': {
                        'level': 'INFO',
                        'file': os.path.join(APP_ROOT, 'logs/strm.log'),
                        'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        'max_size': '10MB',
                        'backup_count': 5
                    },
                    'file_browser': {
                        'allowed_paths': ['/mnt/nas/vol1/1000/videos', '/mnt/nas/vol1/1000/strms'],  # 修改允许的路径
                        'filters': {
                            'extensions': ['.strm'],
                            'hidden_items': ['.git', '.DS_Store', 'Thumbs.db']
                        }
                    }
                }
                self.save_config()
                
        except Exception as e:
            logging.error(f"加载配置文件失败: {e}")
            # 使用内存中的默认配置
            self.config = {
                'libraries': [],
                'scan_interval': 3600
            }
    
    def save_config(self):
        """保存配置文件"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True)
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")
    
    def setup_logging(self):
        """设置日志"""
        try:
            log_config = self.config.get('logging', {})
            log_file = log_config.get('file', os.path.join(APP_ROOT, 'logs/strm.log'))
            
            # 确保日志目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            logging.basicConfig(
                level=getattr(logging, log_config.get('level', 'INFO')),
                format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
                handlers=[
                    logging.FileHandler(log_file),
                    logging.StreamHandler()
                ]
            )
        except Exception as e:
            logging.error(f"设置日志失败: {e}")
            # 使用基本配置
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler()]
            )
    
    def add_library(self, name: str, path: str, type: str) -> bool:
        """添加STRM库"""
        try:
            if not os.path.exists(path):
                logging.error(f"路径不存在: {path}")
                return False
            
            # 检查是否已存在
            for lib in self.config['libraries']:
                if lib['path'] == path:
                    logging.warning(f"STRM库路径已存在: {path}")
                    return False
            
            library = {
                'name': name,
                'path': path,
                'type': type,
                'added_at': datetime.now().isoformat()
            }
            
            self.config['libraries'].append(library)
            self.save_config()
            logging.info(f"添加STRM库成功: {name} - {path}")
            return True
            
        except Exception as e:
            logging.error(f"添加STRM库失败: {e}")
            return False
    
    def remove_library(self, path: str) -> bool:
        """移除STRM库"""
        try:
            self.config['libraries'] = [
                lib for lib in self.config['libraries'] 
                if lib['path'] != path
            ]
            self.save_config()
            logging.info(f"移除STRM库成功: {path}")
            return True
        except Exception as e:
            logging.error(f"移除STRM库失败: {e}")
            return False
    
    def list_libraries(self) -> List[Dict]:
        """列出所有STRM库"""
        return self.config['libraries']
    
    def scan_library(self, path: str) -> List[Dict]:
        """扫描STRM文件"""
        try:
            strm_files = []
            
            for root, _, files in os.walk(path):
                for file in files:
                    if file.endswith('.strm'):
                        full_path = os.path.join(root, file)
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                url = f.read().strip()
                        except:
                            url = ''
                            
                        strm_files.append({
                            'path': full_path,
                            'name': os.path.splitext(file)[0],
                            'url': url,
                            'size': os.path.getsize(full_path),
                            'modified': datetime.fromtimestamp(
                                os.path.getmtime(full_path)
                            ).isoformat()
                        })
            
            return strm_files
        except Exception as e:
            logging.error(f"扫描STRM库失败: {e}")
            return []
    
    def list_directory(self, path: str) -> List[Dict]:
        """列出目录内容"""
        try:
            # 获取挂载根目录，如果没有配置则使用 /mnt/nas
            mount_root = self.config.get('mount_root', '/mnt/nas')
            mount_root = os.path.abspath(mount_root)

            # 规范化路径
            path = os.path.abspath(path)
            
            # 确保路径不会超出挂载根目录
            if not path.startswith(mount_root) and path != '/':
                path = mount_root

            # 如果目录不存在，返回挂载根目录的内容
            if not os.path.exists(path):
                path = mount_root

            items = []
            try:
                # 列出目录内容
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            # 跳过隐藏文件
                            if entry.name.startswith('.'):
                                continue
                                
                            # 获取文件信息
                            stat = entry.stat()
                            item = {
                                'name': entry.name,
                                'path': os.path.abspath(entry.path),
                                'type': 'directory' if entry.is_dir() else 'file',
                                'size': stat.st_size if entry.is_file() else 0,
                                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                            }
                            items.append(item)
                            
                        except (PermissionError, OSError):
                            # 忽略无权限访问的文件或目录
                            continue
                            
                # 按类型和名称排序
                items.sort(key=lambda x: (x['type'] != 'directory', x['name'].lower()))
                
            except PermissionError:
                # 如果没有权限访问该目录，返回挂载根目录的内容
                path = mount_root
                return self.list_directory(path)
                
            return items
            
        except Exception as e:
            logging.error(f"列出目录内容失败: {e}")
            return []

    def get_strm_list(self, 
                     category: str = 'all',
                     sort: str = 'date',
                     page: int = 1,
                     page_size: int = 20,
                     keyword: str = '',
                     path: str = None) -> Dict:
        """获取STRM列表"""
        try:
            all_strm = []
            
            # 获取所有STRM文件
            if path:
                libraries = [lib for lib in self.config['libraries'] 
                           if lib['path'] == path]
            else:
                libraries = self.config['libraries']
            
            for lib in libraries:
                strm_files = self.scan_library(lib['path'])
                for strm in strm_files:
                    strm['type'] = lib['type']
                    all_strm.append(strm)
            
            # 用过滤
            filtered_strm = all_strm
            
            if category != 'all':
                filtered_strm = [s for s in filtered_strm 
                               if s['type'] == category]
            
            if keyword:
                keyword = keyword.lower()
                filtered_strm = [s for s in filtered_strm 
                               if keyword in s['name'].lower()]
            
            # 应用排序
            if sort == 'name':
                filtered_strm.sort(key=lambda x: x['name'])
            elif sort == 'date':
                filtered_strm.sort(key=lambda x: x['modified'], reverse=True)
            elif sort == 'size':
                filtered_strm.sort(key=lambda x: x['size'], reverse=True)
            
            # 分页
            total = len(filtered_strm)
            start = (page - 1) * page_size
            end = start + page_size
            
            return {
                'items': filtered_strm[start:end],
                'total': total,
                'page': page,
                'pages': (total + page_size - 1) // page_size
            }
            
        except Exception as e:
            logging.error(f"获取STRM列表失败: {e}")
            return {
                'items': [],
                'total': 0,
                'page': page,
                'pages': 0
            }
    
    def generate_strm(self, url: str, path: str, name: str) -> bool:
        """生成STRM文件"""
        try:
            if not url or not path or not name:
                return False
                
            # 确保目录存在
            os.makedirs(path, exist_ok=True)
            
            # 生成文件路径
            file_path = os.path.join(path, f"{name}.strm")
            
            # 写入URL
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(url)
                
            logging.info(f"生成STRM文件成功: {file_path}")
            return True
            
        except Exception as e:
            logging.error(f"生成STRM文件失败: {e}")
            return False
    
    def batch_generate(self, items: List[Dict], path: str) -> Dict:
        """批量生成STRM文件"""
        try:
            results = {
                'success': [],
                'failed': []
            }
            
            for item in items:
                url = item.get('url')
                name = item.get('name')
                
                if self.generate_strm(url, path, name):
                    results['success'].append(name)
                else:
                    results['failed'].append(name)
                    
            return results
            
        except Exception as e:
            logging.error(f"批量生成STRM文件失败: {e}")
            return {
                'success': [],
                'failed': list(items)
            }
    
    def validate_url(self, url: str) -> Dict:
        """验证URL"""
        try:
            # 发送HEAD请求验证URL
            response = requests.head(url, timeout=5)
            
            return {
                'valid': response.status_code == 200,
                'status': response.status_code,
                'content_type': response.headers.get('content-type', ''),
                'content_length': response.headers.get('content-length', 0)
            }
            
        except Exception as e:
            logging.error(f"验证URL失败: {e}")
            return {
                'valid': False,
                'error': str(e)
            }

    def process_url(self, url: str) -> str:
        """处理URL，去除挂载根目录部分"""
        if not url:
            return url
        
        # 如果URL以挂载根目录开头则去除该部分
        if url.startswith(self.mount_root):
            url = url[len(self.mount_root):]
            
        # 确保URL以/开头
        if not url.startswith('/'):
            url = '/' + url
            
        return url

    def get_version(self) -> str:
        """获取软件版本号"""
        try:
            return self.config.get('version', '1.0.0')
        except Exception as e:
            logging.error(f"获取版本号失败: {e}")
            return '1.0.0'

# 添加进度跟踪字典
conversion_progress = {}

def emit_progress(event_data):
    """发送进度更新"""
    try:
        socketio = current_app.extensions['socketio']
        socketio.emit('progress_update', event_data)
    except Exception as e:
        print(f"发送进度更新失败: {e}")

# 路由处理
@strm_bp.route('/')
def index():
    """STRM生成器首页"""
    # 获取保存的设置
    manager = STRMManager()
    settings = manager.config.get('auto_settings', {})
    version = manager.get_version()
    return render_template('strm_manager.html', 
                         title='STRM生成器',
                         description='生成和管理STRM文件',
                         settings=settings,
                         version=version)

@strm_bp.route('/config', methods=['GET'])
def get_config():
    """获取STRM配置"""
    try:
        manager = STRMManager()
        default_paths = manager.config.get('default_paths', {})
        
        return jsonify({
            'status': 'success',
            'config': {
                'enabled': manager.config.get('enabled', False),
                'server_url': manager.config.get('server_url', ''),
                'url_prefix': manager.config.get('url_prefix', ''),
                'source_path': default_paths.get('source', '/mnt/nas'),
                'target_path': default_paths.get('output', '/mnt/nas'),
                'recursive': manager.config.get('recursive', False),
                'scan_interval': manager.config.get('scan_interval', 3600),
                'interval': manager.config.get('interval', 100),
                'mount_mode': manager.config.get('mount_mode', 'alist'),
                'mount_root': manager.config.get('mount_root', ''),
                'alist_username': manager.config.get('alist_username', ''),
                'alist_password': manager.config.get('alist_password', '')
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

@strm_bp.route('/convert/', methods=['POST'])
def convert():
    """转换文���为STRM"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'message': '无效的请求数据'
            }), 400

        task_id = str(int(time.time()))

        # 获取STRM管理器实例
        strm_manager = STRMManager()
        
        # 保存原始路径
        original_source_path = data['source_path']
        original_output_path = data['output_path']
        
        # 处理source_path和output_path，去除挂载根目录部分
        if 'source_path' in data:
            data['source_path'] = strm_manager.process_url(data['source_path'])
            
        if 'output_path' in data:
            data['output_path'] = strm_manager.process_url(data['output_path'])

        # 获取所有视频文件（使用原始source_path）
        video_files = []
        for root, _, files in os.walk(original_source_path):
            for file in files:
                if file.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    video_files.append(os.path.normpath(os.path.join(root, file)))

        total_files = len(video_files)
        if total_files == 0:
            return jsonify({
                'status': 'error',
                'message': '未找到视频文件'
            })

        # 更新总件数
        conversion_progress[task_id] = {
            'status': 'in_progress',
            'total_files': total_files,
            'message': f'找到 {total_files} 个视频文件',
            'processed_files': 0,
            'progress': 0  # 初始进度为0
        }

        def generate():
            nonlocal task_id
            processed_files = 0
            
            # 发送初始状态
            yield f"data: {json.dumps(conversion_progress[task_id], ensure_ascii=False)}\n\n"
            
            try:
                for video_file in video_files:
                    # 更新当前处理文件
                    rel_path = os.path.relpath(video_file, original_source_path)
                    
                    # 发送开始处理文件的进度更新
                    progress = round((processed_files / total_files) * 100, 2)
                    conversion_progress[task_id].update({
                        'status': 'processing',
                        'progress': progress,
                        'current_file': rel_path,
                        'processed_files': processed_files,
                        'total_files': total_files,
                        'message': f'开始处理: {rel_path} ({processed_files + 1}/{total_files})',
                        'completed_file': None
                    })
                    yield f"data: {json.dumps(conversion_progress[task_id], ensure_ascii=False)}\n\n"

                    # 创建STRM文件
                    rel_path_no_ext = os.path.splitext(rel_path)[0]
                    strm_path = os.path.join(original_output_path, f"{rel_path_no_ext}.strm")
                    
                    # 确保STRM文件的目录存在
                    os.makedirs(os.path.dirname(strm_path), exist_ok=True)
                    
                    # 处理视频文件路径
                    if data.get('mount_mode') == 'mount' and data.get('mount_root'):
                        # 标准化路径
                        video_file = os.path.normpath(video_file)
                        mount_root = os.path.normpath(data['mount_root'])
                        
                        # 检查文件是否在挂载根目录下
                        if os.path.commonpath([video_file]) == os.path.commonpath([mount_root]):
                            video_path = os.path.relpath(video_file, mount_root)
                        else:
                            video_path = os.path.relpath(video_file, original_source_path)
                    else:
                        # 根不同的挂载模式处理路径
                        if data.get('mount_mode') in ['alist-xiaoya', 'webdav']:
                            # 对于小雅模式和webdav模式，使用相对路径，去除挂载目录部分
                            mount_root = os.path.normpath(data.get('mount_root', '/mnt/nas'))
                            video_file = os.path.normpath(video_file)
                            if video_file.startswith(mount_root):
                                video_path = os.path.relpath(video_file, mount_root)
                            else:
                                video_path = os.path.relpath(video_file, original_source_path)
                            # 确保路径使用正斜杠且以正斜杠开始
                            video_path = '/' + video_path.replace(os.sep, '/')
                        elif data.get('mount_mode') == 'alist':
                            # 对于alist模式，移除挂载根目录部分
                            video_path = os.path.relpath(video_file, original_source_path)
                        else:
                            # 默认使用相对路径
                            video_path = os.path.relpath(video_file, original_source_path)

                    # 构建URL
                    if data.get('mount_mode') == 'mount':
                        url = f"file://{os.path.join(data.get('mount_root', ''), video_path)}"
                    else:
                        # 服务器地址，确保以 http:// 或 https:// 开头
                        server = data.get('server', '').strip()
                        if not server.startswith(('http://', 'https://')):
                            server = f"http://{server}"
                        server = server.rstrip('/')  # 移除末尾的斜杠

                        # 根据挂载模式获取URL前缀
                        if data.get('mount_mode') == 'alist-xiaoya':
                            url_prefix = '/d'
                        elif data.get('mount_mode') == 'alist':
                            url_prefix = '/dav'
                            # 处理 alist 认证信息
                            if data.get('alist_username') and data.get('alist_password'):
                                # 从服务器地址中提取协议和剩余部分
                                protocol = 'https://' if server.startswith('https://') else 'http://'
                                server_part = server.replace('http://', '').replace('https://', '')
                                # 重新构建带认证信息的服务器地址
                                server = f"{protocol}{data.get('alist_username')}:{data.get('alist_password')}@{server_part}"
                        else:
                            url_prefix = data.get('url_prefix', '').strip()

                        if url_prefix and not url_prefix.startswith('/'):
                            url_prefix = '/' + url_prefix
                        url_prefix = url_prefix.rstrip('/')

                        # 处理视频路径，移除挂载根目录部分
                        mount_root = os.path.normpath(data.get('mount_root', '/mnt/nas'))
                        video_file = os.path.normpath(video_file)
                        if video_file.startswith(mount_root):
                            video_path = os.path.relpath(video_file, mount_root)
                        else:
                            video_path = os.path.relpath(video_file, original_source_path)
                        
                        # 确保路径使用正斜杠且以正斜杠开始
                        video_path = '/' + video_path.replace(os.sep, '/')

                        # 构建完整URL
                        url = f"{server}{url_prefix}{video_path}"

                    # 写入STRM文件
                    with open(strm_path, 'w', encoding='utf-8') as f:
                        f.write(url)

                    # 更新处理进度
                    processed_files += 1
                    current_progress = round((processed_files / total_files) * 100, 2)
                    conversion_progress[task_id].update({
                        'status': 'processing',
                        'progress': current_progress,
                        'processed_files': processed_files,
                        'total_files': total_files,
                        'message': f'已完成: {rel_path} ({processed_files}/{total_files})',
                        'completed_file': rel_path
                    })
                    yield f"data: {json.dumps(conversion_progress[task_id], ensure_ascii=False)}\n\n"

                    # 添加处理间隔
                    if 'generate_interval' in data:
                        time.sleep(data.get('generate_interval', 0))
                    else:
                        time.sleep(data.get('interval', 0))

                # 更新完成状态
                conversion_progress[task_id].update({
                    'status': 'completed',
                    'progress': 100,
                    'processed_files': total_files,
                    'total_files': total_files,
                    'message': '所有文件处理完成',
                    'completed_file': None
                })
                yield f"data: {json.dumps(conversion_progress[task_id], ensure_ascii=False)}\n\n"

            except Exception as e:
                conversion_progress[task_id].update({
                    'status': 'error',
                    'message': str(e)
                })
                yield f"data: {json.dumps(conversion_progress[task_id], ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Content-Type': 'text/event-stream',
                'Connection': 'keep-alive'
            }
        )

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

@strm_bp.route('/progress/<task_id>', methods=['GET'])
def get_conversion_progress(task_id):
    """获取转换进度"""
    if task_id in conversion_progress:
        progress_data = conversion_progress[task_id]
        # 根据已处理文件数计算进度百分比
        if 'processed_files' in progress_data and 'total_files' in progress_data:
            if progress_data['total_files'] > 0:
                progress = round((progress_data['processed_files'] / progress_data['total_files']) * 100, 2)
            else:
                progress = 0
        else:
            progress = progress_data.get('progress', 0)

        return jsonify({
            'status': 'success',
            'progress': progress,
            'message': progress_data.get('message', ''),
            'processed_files': progress_data.get('processed_files', 0),
            'total_files': progress_data.get('total_files', 0),
            'current_file': progress_data.get('current_file', '')
        })
    else:
        return jsonify({
            'status': 'error',
            'message': '无效的任务ID'
        }), 404

@strm_bp.route('/browse/')
def browse():
    """浏目录"""
    try:
        manager = STRMManager()
        path = request.args.get('path', '/')
        
        # 获取挂载根目录
        mount_root = manager.config.get('mount_root', '/mnt/nas')
        mount_root = os.path.abspath(mount_root)
        
        # 规范化当前路径
        path = os.path.abspath(path) if path != '/' else mount_root
        
        # 确保路径不会超出挂载根目录
        if not path.startswith(mount_root) and path != '/':
            path = mount_root

        # 如果目录不存在，返回挂载根目录的内容
        if not os.path.exists(path):
            path = mount_root

        items = []
        try:
            # 列出目录内容
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        # 跳过隐藏文件
                        if entry.name.startswith('.'):
                            continue
                            
                        # 获取文件信息
                        stat = entry.stat()
                        item = {
                            'name': entry.name,
                            'path': os.path.abspath(entry.path),
                            'type': 'directory' if entry.is_dir() else 'file',
                            'size': stat.st_size if entry.is_file() else 0,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        }
                        items.append(item)
                        
                    except (PermissionError, OSError):
                        # 忽略无权限访问的文件或目录
                        continue
                        
            # 按类型和名称排序
            items.sort(key=lambda x: (x['type'] != 'directory', x['name'].lower()))
            
        except PermissionError:
            # 如果没有权限访问该目录，返回挂载根目录的内容
            path = mount_root
            return browse()
            
        return jsonify({
            'status': 'success',
            'items': items,
            'current_path': path,
            'parent_path': os.path.dirname(path) if path != mount_root else None,
            'mount_root': mount_root
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

@strm_bp.route('/settings', methods=['GET'])
def get_settings():
    """获取STRM生成器设置"""
    settings = {
        'source_path': '',
        'target_path': '',
        'server_url': '',
        'url_prefix': '',
        'recursive': True,  # 默认开启递归理子目录
        'interval': 0,
        'mount_mode': 'alist',  # 默认使用 alist 模式
        'alist_username': '',
        'alist_password': ''
    }
    return jsonify({
        'status': 'success',
        'settings': settings
    })

@strm_bp.route('/settings', methods=['POST'])
def save_settings():
    """存STRM生成器设置"""
    try:
        settings = request.json
        return jsonify({
            'status': 'success',
            'message': '设置保存成功'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

@strm_bp.route('/save_manual_settings', methods=['POST'])
def save_manual_settings():
    """保存手动生成设置"""
    try:
        # 获取请求数据
        data = request.get_json()
        
        # 验证必要参数
        source_path = data.get('source_path', '').strip()
        target_path = data.get('target_path', '').strip()
        
        if not source_path or not target_path:
            return jsonify({
                'status': 'error',
                'message': '源文件路径和目标路径不能为空'
            }), 400
        
        # 检查路径是否存在
        if not os.path.exists(source_path):
            return jsonify({
                'status': 'error',
                'message': f'源文件路径不存在: {source_path}'
            }), 400
        
        if not os.path.exists(target_path):
            return jsonify({
                'status': 'error',
                'message': f'目标路径不存在: {target_path}'
            }), 400
        
        # 加载当前配置
        manager = STRMManager()
        current_settings = manager.config.get('manual_settings', {})
        
        # 更新设置
        current_settings.update({
            'source_path': source_path,
            'target_path': target_path,
            'recursive': data.get('recursive', False),
            'interval': max(0, int(data.get('interval', 0))),
            'mount_mode': data.get('mount_mode', 'alist'),
            'mount_root': data.get('mount_root', '/mnt/nas'),  # 新增挂载根目录
            'alist_username': data.get('alist_username', ''),
            'alist_password': data.get('alist_password', '')
        })
        
        # 更新配置文件
        manager.config['manual_settings'] = current_settings
        manager.save_config()
        
        return jsonify({
            'status': 'success',
            'message': '手动生成设置保存成功'
        })
    except Exception as e:
        logging.error(f"保存设置失败: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

@strm_bp.route('/progress_stream/<task_id>')
def progress_stream(task_id):
    def generate():
        while True:
            if task_id in conversion_progress:
                data = conversion_progress[task_id]
                yield f"data: {json.dumps(data)}\n\n"
                
                if data['status'] in ['completed', 'error']:
                    break
            
            time.sleep(0.1)  # 100ms 轮询间隔
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
    )

@strm_bp.route('/save_auto_settings', methods=['POST'])
def save_auto_settings():
    """保存自动生成设置"""
    try:
        data = request.get_json()
        
        # 获取STRM管理器实例
        manager = STRMManager()
        
        # 更新配置
        manager.config['auto_settings'] = {
            'source_path': data.get('source_path', ''),
            'output_path': data.get('output_path', ''),
            'server': data.get('server', ''),
            'url_prefix': data.get('url_prefix', ''),
            'recursive': data.get('recursive', True),
            'interval': data.get('interval', 3600),
            'generate_interval': data.get('generate_interval', 0),
            'enabled': data.get('enabled', False),
            'mount_mode': data.get('mount_mode', 'alist'),
            'mount_root': data.get('mount_root', ''),
            'alist_username': data.get('alist_username', ''),
            'alist_password': data.get('alist_password', '')
        }
        
        # 保存配置
        manager.save_config()
        
        return jsonify({
            'status': 'success',
            'message': '设置保存成功'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })