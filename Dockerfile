FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agrisense ./agrisense
COPY wsgi.py .
RUN useradd -r -u 10001 app && mkdir -p /app/instance && chown app /app/instance
USER app
EXPOSE 8000
CMD ["gunicorn", "-w", "3", "-k", "gthread", "--threads", "4", "-b", "0.0.0.0:8000", "--access-logfile", "-", "wsgi:app"]
