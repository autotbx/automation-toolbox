FROM 'python:3.7'
COPY requirements.txt /
RUN pip install -r requirements.txt
RUN mkdir /ui
COPY ui.py /ui/
COPY utils.py /ui/
COPY templates /ui/templates
COPY static /ui/static

WORKDIR /ui
CMD python3 -u ui.py
CMD ["gunicorn", "--workers","4", "--bind", "0.0.0.0:5000", "ui:app", "--access-logfile", "-", "--error-logfile", "-"]

