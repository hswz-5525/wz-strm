# 使用Alpine Linux作为基础镜像
FROM python:3.9-alpine

# 设置工作目录
WORKDIR /app

# 设置Alpine国内镜像源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

# 安装系统依赖
RUN apk update && \
    apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev

# 配置pip国内镜像源
RUN pip install --upgrade pip && \
    pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip config set global.timeout 1000 && \
    pip config set global.retries 5

# 只复制 requirements.txt 文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install -r requirements.txt

# 创建必要的目录
RUN mkdir -p config/strm logs static templates

# 复制项目文件
COPY templates templates/
COPY static static/
COPY *.py .

# 暴露端口
EXPOSE 5525

# 启动命令
CMD ["python", "wanzitools.py"]