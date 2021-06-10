FROM python:3.7
RUN pip install kopf==1.30.3 kubernetes==11.0.0
ADD terraform-operator.py /
CMD [ "kopf", "run", "/terraform-operator.py", "--log-format", "full" ]
