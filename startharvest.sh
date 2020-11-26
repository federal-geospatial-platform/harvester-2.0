#!/bin/bash
# -*- coding: utf-8 -*-
"""Usage: hharvest [-e environment STAGING/PRODUCTION] [-d xml-file-directory] [-b skip send request to csw ] [-p skip push to Open-Canada ] [-f start date time ] [-t end date time ]

Options:
    -e environment to run the script
    -d provide xml file directory for individual xml file
    -b to skip sending request for new metadata download to the server
    -p to skip pushing to OpenCanada through CKAN
    -f from date as starting date 
    -t to date as ending date of the time range
"""

DIRECTORY=$(cd `dirname $0` && pwd)
echo $DIRECTORY
# Lockfile
# 86400 — one day
# 10800 - three hours

# Jump into the Open Maps harvester directory
# cd /home/odatsrv/_harvester_OpenMaps

unset Dirfiles
unset ProductEnv
unset ReqBypass
unset OGSHARVESTRUNSTART
unset OGSHARVESTRUNEND
unset ProvTerr

CkanPush=true

while getopts e:d:b:p:f:t:x: flag
do
    case "${flag}" in
        e) ProductEnv=${OPTARG^^};;
        d) Dirfiles=${OPTARG};;
        b) ReqBypass=${OPTARG};;
        p) CkanPush=${OPTARG};;
        f) OGSHARVESTRUNSTART=${OPTARG^^};;
        t) OGSHARVESTRUNEND=${OPTARG^^};;
        x) ProvTerr=${OPTARG^^};;
    esac
done


set -e
trap_with_arg() {
    func="$1" ; shift
    for sig ; do
        trap "$func $sig" "$sig"
    done
}

func_trap() {
    $(rm -f run.lock)
    echo PROCESS ENDED: $1
}

trap_with_arg func_trap INT TERM EXIT HUP KILL TERM STOP QUIT

# echo "environment: $ProductEnv";
# echo "file-directory: $Dirfiles";
# echo "ckan-push: $CkanPush";
# exit 2
if [ -e "run.lock" ]; then
    if [ "$(( $(date +"%s") - $(stat -c "%Y" run.lock) ))" -lt "10800" ]; then
        echo "Aborting: Lock file 'run.lock' found"
        exit 0
    fi
fi

function InitializeInput(){

    date +"%Y-%m-%dT%H:%M:%S" > run.lock

    #ProductEnv=$(python globals.py --outenv true)

    if [ -z "$ProductEnv" ]; then
        echo "No environment argument supplied"
        echo "Please check usage"
        rm run.lock
        exit 1
    fi

    if [[ $ProductEnv == *"PROD"* ]]; then
        ProductEnv='PRODUCTION'
        JsonOutPutDir="JsonOutput-prod/*.jl" 
    elif [[ $ProductEnv == *"STAG"* ]]; then
        ProductEnv='STAGING' 
        JsonOutPutDir="JsonOutput-stag/*.jl"
    fi

    echo "------------env--start-----------"
    echo $ProductEnv
    echo "------------env--end-----------"
    # Need to enable python27
    # /usr/bin/scl enable python27

    # Jump into the Open Maps harvester directory
    # cd /home/odatsrv/_harvester_OpenMaps

    # Last run info
    if [ ! -e "run.last" ]; then
        echo "1970-01-01T00:00:01" > run.last
    fi
    OGS_HARVEST_LAST_RUN=$(cat run.last)
    # /bin/date --date "2 minutes ago" +"%Y-%m-%dT%H:%M:%SZ" > run.last

    # Now updating run.last after successful CKAN load
    # date +"%Y-%m-%dT%H:%M:%SZ" > run.last

    #echo "Run starting from:"
    #echo $OGS_HARVEST_LAST_RUN
    #OGS_HARVEST_RUN_START=$(cat run.last)

    F=0
    if [ -z "$OGSHARVESTRUNSTART" ]; then
        OGSHARVESTRUNSTART=$(cat run.last)
        lastrunstr="harvesting last run : ${OGSHARVESTRUNSTART}" 
        OGSHARVESTRUNSTART=$(date -u -d @$(date -d $OGSHARVESTRUNSTART +%s) +"%Y-%m-%dT%H:%M:%S") 
        echo $lastrunstr+"; UTC : ${OGSHARVESTRUNSTART}"

    else 
        lastrunstr="harvesting start time : ${OGSHARVESTRUNSTART}"
        OGSHARVESTRUNSTART=$(date -u -d @$(date -d $OGSHARVESTRUNSTART +%s) +"%Y-%m-%dT%H:%M:%S") 
        echo $lastrunstr+"; UTC : ${OGSHARVESTRUNSTART}"

    fi

    if [ -z "$OGSHARVESTRUNEND" ]; then
        OGSHARVESTRUNEND=$(date +"%Y-%m-%dT%H:%M:%S")
        lastrunstr="harvesting until now : ${OGSHARVESTRUNEND}" 
        OGSHARVESTRUNEND=$(date -u -d @$(date -d $OGSHARVESTRUNEND +%s) +"%Y-%m-%dT%H:%M:%S") 
        echo $lastrunstr+"; UTC : ${OGSHARVESTRUNEND}"
    else
        OGSHARVESTRUNEND=$(date -u -d @$(date -d $OGSHARVESTRUNEND +%s) +"%Y-%m-%dT%H:%M:%S") 
        lastrunstr="harvesting until now : ${OGSHARVESTRUNEND}" 
        echo $lastrunstr+"; UTC : ${OGSHARVESTRUNEND}"
    fi
}


#rm run.lock
# exit 33  
# while read F  ; do
#     OGS_HARVEST_RUN_START=$F
# done <"run.last"
# OGS_HARVEST_RUN_END=$F

# /bin/date --date "2 minutes ago" +"%Y-%m-%dT%H:%M:%SZ" > run.last

# Now updating run.last after successful CKAN load
# date +"%Y-%m-%dT%H:%M:%SZ" > run.last



function RetreiveMetadataXML(){
# AND THEN the virtual environment
# . /var/www/html/venv/staging-portal/bin/activate
    echo $ReqBypass
    if [ -z "$ReqBypass" ]; then
        if [ -z "$Dirfiles" ]; then
            # Collect the latest data
            # /home/odatsrv/_harvester_OpenMaps/harvest_hnap.py -f $OGS_HARVEST_LAST_RUN > harvested_records.xml
            ####send request#### 
            # 
            > harvested_records.xml
            > harvested_records.jl
            if [ -z "$ProvTerr" ]; then
                ./harvest_hnap.py -f $OGSHARVESTRUNSTART -t $OGSHARVESTRUNEND -e $ProductEnv > harvested_records.xml & pid=$!
            else
                ./harvest_hnap.py -f $OGSHARVESTRUNSTART -t $OGSHARVESTRUNEND -e $ProductEnv -p $ProvTerr > harvested_records.xml & pid=$!
            fi
            # Show progress as this can take several minutes
            spin='-\|/'
            i=0
            while kill -0 $pid 2>/dev/null
            do
                i=$(( (i+1) %4 ))
                printf "\r${spin:$i:1}"
                sleep .1
            done
            printf "\r"
            
            # Create the common core JSON file
            /bin/cat harvested_records.xml | ./hnap2cc-json.py -o $ProductEnv
        else
            echo "Processing single Xml files from ${Dirfiles} directory"
            FILES=$Dirfiles/*xml
            firstpass=true   
            for f in $FILES
            do
                if [ "$firstpass" = "true" ]; then
                    firstpass=false
                    > "harvested_records.jl"
                fi
                echo "Processing $f file..."
                # take action on each file. $f store current file name
                ./hnap2cc-json.py -f $f -o $ProductEnv
            done
        fi
    else
        # Create the common core JSON file
        /bin/cat harvested_records.xml | ./hnap2cc-json.py -o $ProductEnv
    fi
}


function UploadToOpenCanada(){
    # Convert csv errors to html
    ./csv2html.py -f harvested_record_errors.csv

    #myfilesize=`stat -c %s harvested_records.jl` # for Linux

    myfilesize=`stat -c %s harvested_records.jl` # for Linux
    # myfilesize=`stat -f %z harvested_records.jl` # for OSX

    if [ $myfilesize = 0 ]; then
        echo "No new/updated records since last harvest, skipping load into CKAN"
    else
        echo "Found new/updated records, loading into CKAN..."
        #CKAN_API_KEY=''  # pord-key
        CKAN_API_KEY_PROD='' # <= provide CKAN Key to run this script
        CKAN_API_KEY_STAG='' # <= provide CKAN Key to run this script
        
        # cd /var/www/html/open_gov/staging-portal/ckan
        # ckanapi load datasets -I ~/_harvester_OpenMaps/harvested_records.jl -c production.ini

        if [ "$CkanPush" = "true" ]; then
        ## STAGING
            if [ "$ProductEnv" = "STAGING" ]; then
                echo "Loading to CKAN STAGING"
                ## ckanapi load datasets -I harvested_records.jl -r https://staging.open.canada.ca/data -a CKAN_API_KEY && date +"%Y-%m-%dT%H:%M:%SZ" > run.last
                files=($JsonOutPutDir)

                if [ ${#files[@]} -gt 0 ] && [ "$files" != "$JsonOutPutDir" ]; then
                    for filez in $JsonOutPutDir
                    do
                        # take action on each file. $f store current file name
                        echo processing $filez json file
                        ckanapi load datasets -I $filez -r https://staging.open.canada.ca/data -a $CKAN_API_KEY_STAG # && date +"%Y-%m-%dT%H:%M:%S" > run.last
                        if [ -f $filez ]; then
                            rm $filez
                        fi
                    done
                fi
                # ckanapi load datasets -I harvested_records.jl -r https://staging.open.canada.ca/data -a $CKAN_API_KEY_STAG # && date +"%Y-%m-%dT%H:%M:%SZ" > run.last
            else
                if [ "$ProductEnv" = "PRODUCTION" ]; then 
                    ## PRODUCTION
                    files=($JsonOutPutDir)

                    if [ ${#files[@]} -gt 0 ] && [ "$files" != "$JsonOutPutDir" ]; then
                        for filez in $JsonOutPutDir
                        do
                            # take action on each file. $f store current file name
                            ckanapi load datasets -I $filez -r https://open.canada.ca/data -a $CKAN_API_KEY_PROD #&& date +"%Y-%m-%dT%H:%M:%SZ" > run.last
                            if [ -f $filez ]; then
                                rm $filez
                            fi
                        done
                    fi
                    # ckanapi load datasets -I harvested_records.jl -r https://open.canada.ca/data -a $CKAN_API_KEY_PROD #&& date +"%Y-%m-%dT%H:%M:%SZ" > run.last
                fi
            fi
        else 
            for filez in $JsonOutPutDir
            do
                if [ -f $filez ]; then
                    echo "removing $filez"
                    rm $filez

                fi
            done
        fi

    fi
}


InitializeInput
#UploadToOpenCanada
RetreiveMetadataXML
UploadToOpenCanada