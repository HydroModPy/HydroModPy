# Dockerfile for image to run LoopAggregation example
FROM jupyter/scipy-notebook:latest

USER root

# System packages
RUN apt-get update && \
DEBIAN_FRONTEND=noninteractive \
TZ=Europe \
apt-get install libgfortran5 python3 python3-pip libgdal-dev python3-gdal libgl1-mesa-glx libxt6 bsdmainutils spyder -y
USER ${NB_UID}



# Python packages
RUN pip3 install flopy vtk



# Add modflow project in the docker
COPY . ~/LoopAggregation/

# Default folder
WORKDIR ~/LoopAggregation
