FROM python:3.9

COPY requirements.txt /
COPY ansible_wrapper.py /
RUN pip install -r requirements.txt

CMD ansible_wrapper.py