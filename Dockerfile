
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies and Chrome
RUN apt-get update && apt-get install -y \
    gcc \
    wget \
    gnupg \
    unzip \
    curl \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8001

# Command to run the application
# Assuming run.py is the entry point or app.api.main:app via uvicorn directly if run.py is just a wrapper
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
