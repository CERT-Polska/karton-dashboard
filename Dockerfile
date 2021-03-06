FROM python:3.7

WORKDIR /app/service
COPY ./MANIFEST.in ./MANIFEST.in
COPY ./requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY ./karton ./karton
COPY ./setup.py ./setup.py
RUN pip install .
CMD karton-dashboard run --host 0.0.0.0
