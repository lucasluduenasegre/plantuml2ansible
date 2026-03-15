#! /bin/bash
grep -oP "ip:\s*\K\S+" /vagrant/vagrant-hosts.yml | sort -u | while read -r ip; do ssh-keyscan -H $ip >> ~/.ssh/known_hosts; done