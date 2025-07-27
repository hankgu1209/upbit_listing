FROM python:3.10-slim

# 安装依赖
RUN pip install --no-cache-dir --upgrade pip

# 拷贝文件
WORKDIR /app
COPY . .

# 安装 Python 库
RUN pip install --no-cache-dir -r requirements.txt

# 设置时区为 UTC
ENV TZ=UTC

# 启动脚本（加 -u 确保日志立即输出）
CMD ["python", "-u", "upbit_listing_bot.py"]
