#!/bin/sh

CPU=1
CPU_EXP=1
MEMORY='2g'
PATH_DOCKER_SOCK='/var/run/docker.sock'
PWD_DIR=$(pwd)
DIR='/mnt/srv/tempdd/jbenvegn/modflops'    #$(dirname "$PWD_DIR")/results ##$(pwd)/results
ID_USER=$(id -u $USER)
#DATE=$(date +'%H:%M_%d-%m-%Y')
FOLDER='/mnt/srv/tempdd/jbenvegn/results'
SITE=$1
CHR=$2
APPROX=$3
RATE=$4
REF=$5
PERM=$6
STEADY=$7
REP=$8


if [ $CPU -ge $CPU_EXP ]
then

  PATH_DOCKER_SOCK=$PATH_DOCKER_SOCK':/var/run/docker.sock'

  echo "--------------------------------------"
  echo 'cpu allowed to each simulation: '$CPU_EXP
  echo 'memory allowed to each simulation: '$MEMORY
  echo "--------------------------------------"
  echo $DIR;
  cd $DIR;

  echo "--------------------------------------"
  echo " (1 / 4) docker login..."
  echo " --------------------------------------"
  cat doc.txt | docker login registry.gitlab.inria.fr -u jbenvegn --password-stdin;

  echo "--------------------------------------"
  echo " (2 / 4) pull modflops-simulation-docker-h from gitlab registery"
  echo " --------------------------------------"
  docker pull registry.gitlab.inria.fr/jbenvegn/modflops/modflops-simulation-docker;


  echo "--------------------------------------"
  echo " (3 / 4) run modflops-main-docker..."
  echo "--------------------------------------"

  if [ $REF == '1' ]
  then
    REF="-ref"
  else
    REF=""
  fi
  echo $FOLDER
  docker run -e LANG=C.UTF-8 --rm -v $FOLDER:/modflow/outputs --memory $MEMORY --cpus=1 -e SITE=$SITE -e APPROX=$APPROX -e RATE=$RATE -e CHR=$CHR -e REF=$REF -e REP=$REP -e STEADY=$STEADY -e PERM=$PERM registry.gitlab.inria.fr/jbenvegn/modflops/modflops-simulation-docker;

  echo " (4 / 4) simulations over, check results/ to see data produced.."
  echo "--------------------------------------"
else
  echo "--> Error: cpu allowed to each simulation higher than cpu allowed to all the program"
fi

