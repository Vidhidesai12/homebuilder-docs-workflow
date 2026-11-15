FROM python:3.13-slim
WORKDIR /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY evals ./evals
COPY tests/smoke_live.py ./tests/smoke_live.py
COPY data/ground_truth ./data/ground_truth
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
