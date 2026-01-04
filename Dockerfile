### tool Hydromodpy
FROM python:3.11
RUN apt update
ENV PYTHONUNBUFFERED=1
WORKDIR /scripts

RUN python -m pip install -U --upgrade pip
COPY requirements-docker-light.txt .
RUN pip install --no-cache-dir -r requirements-docker-light.txt
RUN pip install --no-cache-dir --no-deps hydromodpy

# copy all python programme
COPY *.py .
# add data
COPY data .
RUN chmod 677 /scripts/

CMD ["python","scripts.py"]
