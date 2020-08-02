FROM hashicorp/terraform:0.13.0-rc1
ADD toolbox.vm.lab.platform-essential.com.crt /usr/local/share/ca-certificates/mycert.crt
ADD kubectl /usr/local/bin/kubectl
RUN update-ca-certificates
CMD [ "terraform" ]
