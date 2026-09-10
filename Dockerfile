FROM python:3.10-slim

ENV TZ=Asia/Bangkok

WORKDIR /app

RUN apt-get update && apt-get install -y \
    tzdata \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy models directory first to take advantage of Docker layer caching
COPY models/ ./models/

COPY . .

EXPOSE 8932

CMD ["flask", "run", "--host=0.0.0.0", "--port=8932"] 