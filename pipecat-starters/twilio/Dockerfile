FROM dailyco/pipecat-base:latest

COPY ./requirements.txt requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends cmake build-essential && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY ./bot.py bot.py
COPY ./docs ./docs
