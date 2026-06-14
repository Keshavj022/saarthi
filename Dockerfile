FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        libxerces-c3.2 \
        libproj25 \
        libgdal32 \
        libgomp1 \
        libatomic1 \
        libgl1 \
        libglu1-mesa \
        libxrender1 \
        libxext6 \
        libx11-6 \
        libxcb1 \
        libsm6 \
        libice6 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements-hf.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-hf.txt

COPY --chown=user . .

EXPOSE 7860
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "7860"]
