FROM python:3.12-slim

WORKDIR /app

# system deps for Pillow/qrcode are already in slim wheels; keep image lean
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GUESTIQ_DATA=/app/data
EXPOSE 9921

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "9921"]
