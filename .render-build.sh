#!/usr/bin/env bash
set -e  

apt-get update -qq
apt-get install -y openjdk-17-jdk > /dev/null

pip install --upgrade pip
pip install -r requirements.txt

# optional cleanup 
apt-get clean
rm -rf /var/lib/apt/lists/*

