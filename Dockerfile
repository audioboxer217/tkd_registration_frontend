FROM python:3.8

WORKDIR /app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

VOLUME [ "/data" ]

ENV MAPS_API_KEY='SetViaEnvFile'

CMD ["python", "app.py"]
