FROM python:3.7

WORKDIR /usr/src/app
COPY src/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY "README.md" "/usr/src/app/README.md"
COPY "src/" "src/"

WORKDIR /usr/src/app/src
CMD ["flask", "run", "--host", "0.0.0.0"]
