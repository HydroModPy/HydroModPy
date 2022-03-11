#!/bin/sh

CPU=20
CPU_EXP=5
MEMORY='15g'
PATH_DOCKER_SOCK='/var/run/docker.sock'
PWD_DIR=$(pwd)
DIR='/mnt/srv/tempdd/jbenvegn/modflops' #$(dirname "$PWD_DIR")/results ##$(pwd)/results
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
TOPO=$8



if [ $CPU -ge $CPU_EXP ]
then

  PATH_DOCKER_SOCK=$PATH_DOCKER_SOCK':/var/run/docker.sock'
  
  echo "DIR variable"
  echo $DIR
  cd $DIR;

  echo "--------------------------------------"
  echo " (1 / 4) docker login..."
  echo " --------------------------------------"
  cat doc.txt | docker login registry.gitlab.inria.fr -u jbenvegn --password-stdin;

  echo "--------------------------------------"
  echo " (2 / 4) pull modflops-simulation-docker-h from gitlab registery"
  echo " --------------------------------------"
  docker pull registry.gitlab.inria.fr/jbenvegn/modflops/modflops-simulation-docker-h;


  echo "--------------------------------------"
  echo " (3 / 4) run modflops-main-docker..."
  echo "--------------------------------------"
  if [ $REF == '1' ]
  then
    REF="-ref"
  else
    REF=""
  fi
  if [ $TOPO == '1' ]
  then
    TOPO="-topo"
  else
    TOPO=""
  fi
  docker run --rm -v $FOLDER:/modflow/outputs --cpus=1 -e LANG=C.UTF-8 -e RATE=$RATE -e APPROX=$APPROX -e CHR=$CHR -e SITE=$SITE -e REF=$REF -e PERM=$PERM -e STEADY=$STEADY -e TOPO=$TOPO registry.gitlab.inria.fr/jbenvegn/modflops/modflops-simulation-docker-h;

  echo " (4 / 4) simulations over, check results/ to see data produced.."
  echo "--------------------------------------"
else
  echo "--> Error: cpu allowed to each simulation higher than cpu allowed to all the program"
fi
