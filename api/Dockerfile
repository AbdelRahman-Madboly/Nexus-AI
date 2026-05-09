FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from the api folder and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire api folder contents into /app/api/
# so that "from api.config import ..." works correctly
COPY . /app/api/

# Run uvicorn from /app, referencing api.main:app
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]