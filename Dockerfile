FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# ffmpeg: YouTube 챕터 스크린샷용 (없으면 해당 기능만 비활성 — 이미지는 완전체 제공)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m liby && mkdir -p /data && chown -R liby:liby /data /app
USER liby

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
