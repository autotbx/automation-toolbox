FROM python:3.9

COPY requirements.txt /
RUN pip install -r requirements.txt
COPY ansible_gen.py /

CMD ansible_gen.py
