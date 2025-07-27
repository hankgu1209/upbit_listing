FROM python:3.10-slim

# 安装依赖
RUN pip install --no-cache-dir --upgrade pip

# 拷贝文件
WORKDIR /app
COPY . .

# 安装Python库
RUN pip install --no-cache-dir -r requirements.txt

# 设置时区为UTC（可选）
ENV TZ=UTC

# 启动脚本
CMD ["python", "upbit_listing_bot.py"]
