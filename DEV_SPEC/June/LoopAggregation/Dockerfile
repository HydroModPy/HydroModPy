# Dockerfile for image to run LoopAggregation example
FROM ubuntu:18.04

# System packages
RUN apt-get update && \
apt-get install libgfortran5 python3 python3-pip libgdal-dev python3-gdal libgl1-mesa-glx libxt6 bsdmainutils -y

# Python packages
RUN pip3 install pandas flopy matplotlib scipy vtk


# Add modflow project in the docker
COPY ./modflow /modflow/
