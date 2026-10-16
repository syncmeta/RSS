FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt
CMD ["python", "chatgpt_plan.py", "serve", "--credentials", "/data/credentials.json", "--host", "0.0.0.0"]
