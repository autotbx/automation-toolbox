FROM python:3
RUN pip install kopf==0.27 kubernetes==11.0.0
ADD terraform-operator.py /
CMD [ "kopf", "run", "/terraform-operator.py" ]
