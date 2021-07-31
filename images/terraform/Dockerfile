FROM hashicorp/terraform:0.13.0-rc1
RUN wget "https://dl.k8s.io/release/$(wget -O- https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" -O /usr/local/bin/kubectl 
RUN chmod +x /usr/local/bin/kubectl
CMD [ "terraform" ]
