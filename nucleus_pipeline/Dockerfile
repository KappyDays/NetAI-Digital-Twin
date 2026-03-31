FROM python:3.11-slim

WORKDIR /app

# Install base dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install omniverseclient for Nucleus access
RUN pip install --no-cache-dir omniverseclient --extra-index-url https://pypi.nvidia.com || \
    echo "WARNING: omniverseclient install failed. --nucleus-path will not work."

COPY . .

ENTRYPOINT ["python", "main.py"]
