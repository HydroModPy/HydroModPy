
FROM ubuntu:18.04

# System packages
RUN apt-get -y update
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Moscow
RUN apt-get install -y libgfortran5 python3 python3-pip libgdal-dev python3-gdal libgl1-mesa-glx libxt6 bsdmainutils


# Python packages
ENV PYTHON_VERSION 3.7.3
RUN pip3 install pandas flopy matplotlib scipy
RUN pip3 install vtk

# Add modflow project in the docker
COPY ./modflow /modflow/


# Default folder
WORKDIR /modflow

ENV SITE 2
ENV APPROX 0
ENV RATE 3652
ENV CHR 0
ENV REF ""
ENV PERM 86.4
ENV STEADY 0
ENV TOPO ""

# Compute H indicator value
ENTRYPOINT python3 ErrorComput.py -site $SITE -approx $APPROX -chr $CHR -rate $RATE ${REF} -perm $PERM -sd $STEADY ${TOPO}

