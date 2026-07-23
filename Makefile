.PHONY: setup test scrape backfill evaluate train predict serve refresh demo frontend docker

setup:
	pip install -e . && pip install pytest httpx

test:
	python -m pytest tests/ -q

scrape:            ## top-up recent results (polite crawler)
	python -m vpredict.scraping.crawl

backfill:          ## deep history walk (resumable; interrupt-safe)
	python -m vpredict.scraping.crawl --backfill

evaluate:          ## the single source of every reported number
	python scripts/evaluate.py

train:
	python scripts/train.py

predict:
	python scripts/predict_upcoming.py --crawl

serve:
	uvicorn vpredict.serving.api:app --reload --port 8000

refresh:
	python scripts/refresh.py

demo:              ## watermarked synthetic end-to-end run
	python scripts/demo.py && python scripts/evaluate.py --data data/demo/matches.jsonl

frontend:
	cd frontend && npm install --no-audit --no-fund && npm run build

docker:
	docker build -t vpredict .
