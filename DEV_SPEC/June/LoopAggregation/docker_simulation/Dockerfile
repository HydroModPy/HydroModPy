FROM ubuntu:18.04

# System packages
RUN apt-get update && \
apt-get install libgfortran5 python3 python3-pip libgdal-dev python3-gdal libgl1-mesa-glx libxt6 bsdmainutils -y

# Python packages
RUN pip3 install pandas flopy matplotlib scipy vtk

# Add modflow project in the docker
COPY ./modflow /modflow/
COPY simulate.sh /modflow/

# Default folder
WORKDIR /modflow

ENV COMMAND "2"
ENV SITE 2
ENV APPROX 0
ENV RATE 3652
ENV CHR 0
ENV REF ""
ENV REP 0
ENV PERM 86.4
ENV STEADY 0

# Script to launch when the docker is run (the script need x permission)
# `setting_model.py` contains the command of the simulation to launch
ENTRYPOINT python3 settings_model.py -site $SITE -approx $APPROX -chr $CHR -rate $RATE ${REF} -rep $REP -perm $PERM -sd $STEADY
