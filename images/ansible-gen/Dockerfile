FROM python:3.9

COPY requirements.txt /
RUN pip install -r requirements.txt
RUN wget "https://dl.k8s.io/release/$(wget -O- https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" -O /usr/local/bin/kubectl 
RUN chmod +x /usr/local/bin/kubectl
COPY ansible_gen.py /

CMD ansible_gen.py
