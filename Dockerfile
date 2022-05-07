FROM debian:buster-slim

ENV TERM linux
ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && \
  apt-get install -y git python3 python3-dev python3-pip curl build-essential && \
  c_rehash && \
  apt-get autoremove -y && \
  apt-get clean && \
  useradd --no-log-init mycroft -m

RUN mkdir -p /home/mycroft/.config/mycroft /home/mycroft/.cache/mycroft /home/mycroft/.local/mycroft
RUN chown mycroft:mycroft -R /home/mycroft/.config/mycroft /home/mycroft/.cache/mycroft /home/mycroft/.local/mycroft

COPY . /tmp/ovos-core
RUN pip3 install /tmp/ovos-core

# this is meant as a base image for other containers with a minimal ovos-core install
