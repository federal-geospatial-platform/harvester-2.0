#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Usage: hnap2cc-json.py [-f xml_file_input] [-e Error file to generate] [-o Output environment]

Convert HNAP 2.3.1 XML from FGP platform CSW v1.6.2 to OGP Portal input

Accepts streamed HNAP xml input or a supplied HNAP xml filename

    cat hnap.xml | hnap2cc-json.py [-e Error file to generate]
    hnap2cc-json.py [-e Error file to generate] hnap.xml

Options:
    -e Error file to generate
    -f xml_file_input
    -o output environment
"""
import errno
import os
import shutil
from ResourceType import ResourceType
from CL_Formats import CL_Formats

import csv
from lxml import etree
import json

from datetime import datetime
import unicodedata

import urllib2
from urlparse import urlparse

import sys
from io import StringIO, BytesIO
import time
import re
import codecs

import unicodedata

import docopt

import glob
import argparse


MIN_TAG_LENGTH = 1
MAX_TAG_LENGTH = 140

##################################################
# TL err/dbg
error_output = []
error_records = {}

##################################################
# Process the command request

# #Default import location
# input_file     = 'data/majechr_source.xml'
# input_file     = 'data/hnap_import.xml'
input_file = None
records_root = None
SingleXmlInput = None

parser = argparse.ArgumentParser(description='Process provided XML metadata')
parser.add_argument('-e', type=str, help='error file to generate')
parser.add_argument('-f', type=str, help='XML file input')
parser.add_argument('-o', type=str, help='Output environment')
args = parser.parse_args()
OutputEnv = args.o.upper()
if 'PROD' in OutputEnv:
    OutputEnv = "JsonOutput-prod"
elif 'STAG' in OutputEnv:
    OutputEnv = "JsonOutput-stag"
else:
    print "please refer to usage: provide output environment (-o STAGING/PRODUCTION)"
    sys.exit(3)

def ProcDirCreation():
    mydir = os.path.join(
        os.getcwd(), "processed-xml")
    try:
        os.makedirs(mydir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # This was not a "directory exist" error..


# Use stdin if it's populated
if not sys.stdin.isatty():
    input_file = BytesIO(sys.stdin.read())

    records_root = ("/csw:GetRecordsResponse/"
                      "csw:SearchResults/"
                      "gmd:MD_Metadata")
    # a_string = "A string is more than its more parts!"
    # matches = ["more", "wholesome", "milk"]
    # mat = [x for x in matches if x in a_string]
    # if any(x in a_string for x in matches):
    #     print x
    # DEBUG END

# Otherwise, read for a given filename
if not args.f == None:
    input_file = args.f
    with open(args.f, 'rb') as fh:
        input_file = BytesIO(fh.read())
    # input_file = open(args.f, 'rb').read().splitlines()
    records_root = ("/gmd:MD_Metadata")
    SingleXmlInput = True
else:
    with open("harvested_records.xml", 'rb') as fh:
        input_file = BytesIO(fh.read())
    # input_file = open("harvested_records.xml", 'rb').read().splitlines()
    records_root = ("/csw:GetRecordsResponse/"
                      "csw:SearchResults/"
                      "gmd:MD_Metadata")

if input_file is None:
    sys.stdout.write("""
Either stream HNAP in or supply a file
> cat hnap.xml | ./hnap2json.py
> ./hnap2json.py hnap.xml
""")
    sys.exit()

##################################################
# Input can be multiple XML blocks
# Ensure to never try to be clever only taking the
# last XML record or reduce or sort or try to
# combine them.  Each of these updates need to
# happen in the order they were supplied to ensure
# the order of changes.
# We can also not reprocess parts without all the
# subsequent records.  You can't re-process data
# from a particular span of time, any historical
# re-procssing must continue to the current day.
input_data_blocks = []
active_input_block = ''
for line in input_file:
    if not line.strip():
        continue
    if active_input_block == '':
        active_input_block += line
    elif re.search(r'^<\?xml', line):
        input_data_blocks.append(active_input_block)
        active_input_block = line
    else:
        active_input_block += line
input_data_blocks.append(active_input_block)

##################################################
# Extract the schema to convert to
schema_file_ca_en   = 'config/Schema--GC.OGS.TBS-CommonCore-OpenMaps-ca-en.csv'
schema_file_ca_fr = 'config/Schema--GC.OGS.TBS-CommonCore-OpenMaps-ca-fr.csv'
schema_file_en = 'config/Schema--GC.OGS.TBS-CommonCore-OpenMaps-pr-en.csv'
schema_file_fr = 'config/Schema--GC.OGS.TBS-CommonCore-OpenMaps-pr-fr.csv'
schema_file_on = 'config/Schema--GC.OGS.TBS-CommonCore-OpenMaps-on.csv'


schema_ref = {}
schemafile = None
def loadSchemaConfig(file_in):
    global  schemafile
    if schemafile:
        schemafile.close()
    with open(file_in, 'rb') as schemafile:
        reader = csv.reader(schemafile)
        for row in reader:
            if row[0] == 'Property ID':
                continue
            schema_ref[row[0]] = {}
            schema_ref[row[0]]['Property ID'] = row[0]
            schema_ref[row[0]]['CKAN API property'] = row[1]
            schema_ref[row[0]]['Schema Name English'] = unicode(row[2], 'utf-8')
            schema_ref[row[0]]['Schema Name French'] = unicode(row[3], 'utf-8')
            schema_ref[row[0]]['Requirement'] = row[4]
            schema_ref[row[0]]['Occurrences'] = row[5]
            schema_ref[row[0]]['Reference'] = row[6]
            schema_ref[row[0]]['Value Type'] = row[7]
            schema_ref[row[0]]['FGP XPATH'] = unicode(row[8], 'utf-8')
            schema_ref[row[0]]['RegEx Filter'] = unicode(row[9], 'utf-8')
        return schema_ref
    return {}

# records_root = ("/csw:GetRecordsResponse/"
#                 "csw:SearchResults/"
#                 "gmd:MD_Metadata")
#
# records_root = ("gmd:MD_Metadata")

source_hnap = ("csw.open.canada.ca/geonetwork/srv/"
               "csw?service=CSW"
               "&version=2.0.2"
               "&request=GetRecordById"
               "&outputSchema=csw:IsoRecord"
               "&id=")

mappable_protocols = [
    "OGC:WMS",
    "ESRI REST: Map Service",
    "ESRI REST: Map Server",
    "ESRI REST: Feature Service",
    "ESRI REST: Image Service",
    "ESRI REST: Tiled Map Service",
    "WMS de l'OGC",
    "REST de L'ESRI : Service de cartes",
    "REST de L'ESRI : Service d’entités géographiques",
    "REST de L'ESRI : Service d’imagerie",
    "REST de L'ESRI : Service de pavés cartographiques"
]

iso_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def main():
    output_jl = "harvested_records.jl"
    output_err = "harvested_record_errors.csv"
    num_rejects = 0
    num_view_on_map = 0

    OrgNameDict = {
        "Government of Canada",
        "Gouvernement du Canada",
        "Government of Alberta",
        "Gouvernement de l\'Albeta",
        "Government of British Columbia",
        "Gouvernement de la Colombie-Britanique"
        "Government of New Brunswick",
        "Gouvernement du Nouveau-Brunswick",
        "Government of Yukon",
        "Gouvernement du Yukon",
        "Government of Quebec",
        "Gouvernement du Québec",
        "Government and Municipalities of Quebec",
		"Government and Municipalities of Québec",
        "Gouvernement et Municipalités du Québec",
        "Gouvernement et Municipalités du Quebec",
        "Quebec Government and Municipalities",
        "Québec Government and Municipalities",
        "Government of Ontario",
        "Gouvernement de l\'Ontario",
        "Government of Nova Scotia",
        "Gouvernement de la Nouvelle-Ecosse",
        "Government of Manitoba",
        "Gouvernement du Manitoba",
        "Government of Newfoundland and Labrador",
        "Gouvernement de Terre-Neuve et Labrador",
        "Government of Saskatchewan",
        "Gouvernement de la Saskatchewan",
        "Government of Northwest Territories",
        "Gouvernement des Territoires du Nord-Ouest",
        "Government of Nunavut",
        "Gouvernement du Nunavut",
        "Government of Prince Edward Island",
        "Gouvernement de l'Ile-du-Prince-Edouard"
    }

    MunicipalDict = {
        "Ville de Blainville",
        "City of Blainville",
        "Ville de Gatineau",
        "City of Gatineau",
        "Ville de Laval",
        "City of Laval",
        "Ville de Longueuil",
        "City of Longueuil",
        "Ville de Montréal",
        "Ville de Montreal",
        "City of Montreal",
        "City of Montréal",
        "Ville de Quebec",
        "Ville de Québec",
        "City of Quebec",
        "City of Québec",
        "Ville de Repentigny",
        "City of Repentigny",
        "Ville de Rimouski",
        "City of Rimouski",
        "Ville de Rouyn-Noranda",
        "City of Rouyn-Noranda",
        "Ville de Shawinigan",
        "City of Shawinigan",
        "Ville de Sherbrooke",
        "City of Sherbrooke",
        "Ville de Sherbrooke;Sherbrooke Données ouvertes",
        "Ville de Sherbrooke;Données géomatiques",
        "Ville de Montréal;Bixi-Montréal",
        "Ville de Montréal;Bureau du taxi de Montréal",
        "Ville de Sherbrooke;Commercer Sherbrooke",
        "Ville de Sherbrooke;Destination Sherbrooke",
        "Ville de Québec;Le Réseau de transport de la Capitale",
        "Ville de Laval;Société de transport de Laval",
        "Ville de Montréal;Société de transport de Montréal",
        "Ville de Sherbrooke;Société de transport de Sherbrooke",
        "Ville de Montréal;Société des célébrations du 375e anniversaire de Montréal",
        "Ville de Montréal;Stationnement de Montréal",
        "Ville de Sherbrooke;ZAP Sherbrooke",
        "not-found"
        }

    OrgNameDictSecondLang = {
        "Government of Canada" : "Gouvernement du Canada",
        "Gouvernement du Canada" : "Government of Canada",
        "Government of Alberta" : "Gouvernement de l\'Alberta",
        "Gouvernement de l\'Alberta" : "Government of Alberta",
        "Government of British Columbia" : "Gouvernement de la Colombie-Britannique",
        "Gouvernement de la Colombie-Britannique" : "Government of British Columbia",
        "Government of New Brunswick" : "Gouvernement du Nouveau-Brunswick",
        "Gouvernement du Nouveau-Brunswick" : "Government of New Brunswick",
        "Government of Yukon" : "Gouvernement du Yukon",
        "Gouvernement du Yukon" : "Government of Yukon",
        "Government of Québec": "Gouvernement du Québec",
        "Government of Quebec" : "Gouvernement du Québec",
        "Gouvernement du Québec" : "Government of Quebec",
        "Gouvernement du Quebec": "Government of Quebec",
        "Government and Municipalities of Québec" : "Gouvernement et Municipalités du Québec",
        "Gouvernement et Municipalités du Québec" : "Government and Municipalities of Québec",
        "Government and Municipalities of Quebec": "Gouvernement et Municipalités du Québec",
        "Gouvernement et Municipalités du Quebec": "Government and Municipalities of Québec",
        "Quebec Government and Municipalities" : "Gouvernement et Municipalités du Québec",
        "Québec Government and Municipalities" : "Gouvernement et Municipalités du Québec",
        "Government of Ontario" : "Gouvernement de l'Ontario",
        "Gouvernement de l'Ontario" : "Government of Ontario",
        "Government of Nova Scotia" : "Gouvernement de la Nouvelle-Ecosse",
        "Gouvernement de la Nouvelle-Ecosse" : "Government of Nova Scotia",
        "Government of Manitoba" : "Gouvernement du Manitoba",
        "Gouvernement du Manitoba" : "Government of Manitoba",
        "Government of Newfoundland and Labrador" : "Gouvernement de Terre-Neuve et Labrador",
        "Gouvernement de Terre-Neuve et Labrador" : "Government of Newfoundland and Labrador",
        "Government of Saskatchewan" : "Gouvernement de la Saskatchewan",
        "Gouvernement de la Saskatchewan" : "Government of Saskatchewan",
        "Government of Northwest Territories" : "Gouvernement des Territoires du Nord-Ouest",
        "Gouvernement des Territoires du Nord-Ouest" : "Government of Northwest Territories",
        "Government of Nunavut" : "Gouvernement du Nunavut",
        "Gouvernement du Nunavut" : "Government of Nunavut",
        "Government of Prince Edward Island" : "Gouvernement de l'Île-du-Prince-Édouard",
        "Gouvernement de l'Île-du-Prince-Édouard" : "Government of Prince Edward Island"
    }

    licencekey = {
        "Government of Canada" : "64",
        "Gouvernement du Canada" : "64",
        "Government of Alberta" : "64ab",
        "Gouvernement du Canada" : "64ab",
        "Government of British Columbia" : "64bc",
        "Gouvernement de la Colombie-Britannique" : "64bc",
        "Government of New Brunswick" : "64nb",
        "Gouvernement du Nouveau-Brunswick" : "64nb",
        "Government of Yukon" : "64yk",
        "Gouvernement du Yukon" : "64yk",
        "Government of Quebec" : "64qc",
        "Gouvernement du Québec" : "64qc",
        "Gouvernement et Municipalités du Québec" : "64qc",
        "Government and Municipalities of Québec" : "64qc",
        "Government of Québec": "64qc",
        "Gouvernement du Quebec": "64qc",
        "Gouvernement et Municipalités du Quebec": "64qc",
        "Government and Municipalities of Quebec": "64qc",
        "Quebec Government and Municipalities": "64qc",
        "Québec Government and Municipalities": "64qc",
        "Government of Ontario" : "64on",
        "Gouvernement de l'Ontario" : "64on",
        "Government of Nova Scotia" : "64ns",
        "Gouvernement de la Nouvelle-Ecosse" : "64ns",
        "Government of Manitoba" : "64mnb",
        "Gouvernement du Manitoba" : "64mnb",
        "Government of Newfoundland and Labrador" : "64nfl",
        "Gouvernement de Terre-Neuve et Labrador" : "64nfl",
        "Government of Saskatchewan" : "64sa",
        "Gouvernement de la Saskatchewan" : "64sa",
        "Government of Northwest Territories" : "64nwt",
        "Gouvernement des Territoires du Nord-Ouest" : "64nwt",
        "Government of Nunavut" : "64nnvt",
        "Gouvernement du Nunavut" : "64nnvt",
        "Government of Prince Edward Island" : "64pei",
        "Gouvernement de l'Île-du-Prince-Édouard" : "64pei"
    }

    #schema_ref = loadSchemaConfig(schema_file_en)

    # Is there a specified start date
    if arguments['-e']:
        output_err = arguments['-e']

    json_records = []
    for input_block in input_data_blocks:
        if not input_block:
            continue

        # Read the file, should be a streamed input in the future
        ##DEBUG START##
        # root = etree.parse("harvested_records.xml")
        ##DEBUG END##
        root = etree.XML(input_block)
        # Parse the root and iterate over each record
        records = fetchXMLArray(root, records_root)

###############################################
###############################################
        for record in records:
            json_record = {}
            can_be_used_in_RAMP = False
            json_record['display_flags'] = []
            schema_ref = loadSchemaConfig(schema_file_en)
            ##################################################
            # HNAP CORE LANGUAGE
            ##################################################
            # Language is required, the rest can't be processed
            # for errors if the primary language is not certain
            ReadOrgName = None
            strfileIdentifier = fetchXMLValues(record, schema_ref["05"]['FGP XPATH'])

            if sanitySingle('NOID', ['fileIdentifier'], strfileIdentifier) is False:
                    HNAP_fileIdentifier = False
            else:
                HNAP_fileIdentifier = sanityFirst(strfileIdentifier)
            if HNAP_fileIdentifier:
                ReadOrgName = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["16a"])
                if len(ReadOrgName) > 0:
                    ReadOrgName = ReadOrgName[0]
                else:
                    print 'no valid orgnamefound for ' + HNAP_fileIdentifier
                    return 0
            else:
                print 'no valid  file identifier found : ' + HNAP_fileIdentifier
                return 0
            
            fetch_nunicipalname = [x for x in MunicipalDict if unicode(x.lower(), 'UTF-8') in ReadOrgName.lower()]
            
            ReadOrgName = ReadOrgName.split(';')[0]
            QcgovData1 = unicode('québec'.lower(), 'utf-8')
            QcgovData2 = unicode('quebec'.lower(), 'utf-8')
            CangovData = unicode('Canada'.lower(), 'utf-8')
            OngovData = unicode('Ontario'.lower(), 'utf-8')

            if QcgovData1 in ReadOrgName.lower():
                schema_ref = {}
                schema_ref = loadSchemaConfig(schema_file_fr)
            elif QcgovData2 in ReadOrgName.lower():
                schema_ref = {}
                schema_ref = loadSchemaConfig(schema_file_fr)
            elif CangovData in ReadOrgName.lower():
                schema_ref = {}
                schema_ref = loadSchemaConfig(schema_file_ca_en)
            elif OngovData in ReadOrgName.lower():
                schema_ref = {}
                schema_ref = loadSchemaConfig(schema_file_on)
            else:
                schema_ref = {}
                schema_ref = loadSchemaConfig(schema_file_en)

            tmp = fetchXMLValues(record, schema_ref["12"]['FGP XPATH'])
            if sanitySingle('NOID', ['HNAP Priamry Language'], tmp) is False:
                HNAP_primary_language = False
            else:
                HNAP_primary_language = sanityFirst(tmp).split(';')[0].strip()
                if HNAP_primary_language == 'eng':
                    CKAN_primary_lang = 'en'
                    CKAN_secondary_lang = 'fr'
                    HNAP_primary_lang = 'English'
                    HNAP_secondary_lang = 'French'
                else:
                    schema_ref = {}
                    schema_ref = loadSchemaConfig(schema_file_ca_fr)
                    CKAN_secondary_lang = 'fr'
                    CKAN_primary_lang = 'en'
                    HNAP_secondary_lang = 'French'
                    HNAP_primary_lang = 'English'
                    HNAP_primary_language = 'eng'

            ##################################################
            # Catalogue Metadata
            ##################################################

            # CC::OpenMaps-01 Catalogue Type
            json_record[schema_ref["01"]['CKAN API property']] = 'dataset'
            # CC::OpenMaps-02 Collection Type
            json_record[schema_ref["02"]['CKAN API property']] = 'fgp'
            # CC::OpenMaps-03 Metadata Scheme
            #       CKAN defined/provided
            # CC::OpenMaps-04 Metadata Scheme Version
            #       CKAN defined/provided
            # CC::OpenMaps-05 Metadata Record Identifier
            tmp = fetchXMLValues(record, schema_ref["05"]['FGP XPATH'])
            if str(tmp) == "[\'5c252e65-1446-425c-84c3-753ebfdc8b77\']":
                if sanitySingle('NOID', ['fileIdentifier'], tmp) is False:
                    HNAP_fileIdentifier = False
                else:
                    json_record[schema_ref["05"]['CKAN API property']] = \
                        HNAP_fileIdentifier = \
                        sanityFirst(tmp)
            else:
                if sanitySingle('NOID', ['fileIdentifier'], tmp) is False:
                    HNAP_fileIdentifier = False
                else:
                    json_record[schema_ref["05"]['CKAN API property']] = \
                        HNAP_fileIdentifier = \
                        sanityFirst(tmp)

            ##################################################
            # Point of no return
            # fail out if you don't have either a primary language or ID
            ##################################################

            if HNAP_primary_language is False or HNAP_fileIdentifier is False:
                break

            # From here on in continue if you can and collect as many errors as
            # possible for FGP Help desk.  We awant to have a full report of issues
            # to correct, not piecemeal errors.
            # It's faster for them to correct a batch of errors in parallel as
            # opposed to doing them piecemeal.

            # CC::OpenMaps-06 Metadata Contact (English)
            primary_vals = []
            # organizationName
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["06a"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)
            # voice
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["06b"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)
            # electronicMailAddress
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["06c"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)

            json_record[schema_ref["06"]['CKAN API property']] = {}
            json_record[
                schema_ref["06"]['CKAN API property']
            ][CKAN_primary_lang] = ','.join(primary_vals)

            # CC::OpenMaps-07 Metadata Contact (French)
            second_vals = []

            # organizationName
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["07a"])
            if value:
                for single_value in value:
                    second_vals.append(single_value)
            # voice
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["07b"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)
            # electronicMailAddress
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["07c"])
            if value:
                for single_value in value:
                    second_vals.append(single_value)

            json_record[
                schema_ref["06"]['CKAN API property']
            ][CKAN_secondary_lang] = ','.join(second_vals)

            # CC::OpenMaps-08 Source Metadata Record Date Stamp
            tmp = fetchXMLValues(record, schema_ref["08a"]['FGP XPATH'])
            values = list(set(tmp))
            if len(values) < 1:
                tmp = fetchXMLValues(record, schema_ref["08b"]['FGP XPATH'])

            if sanityMandatory(
                    HNAP_fileIdentifier,
                    [schema_ref["08"]['CKAN API property']],
                    tmp
            ):
                if sanitySingle(
                        HNAP_fileIdentifier,
                        [schema_ref["08"]['CKAN API property']],
                        tmp
                ):
                    # Might be a iso datetime
                    date_str = sanityFirst(tmp)
                    if date_str.count('T') == 1:
                        date_str = date_str.split('T')[0]

                    if sanityDate(
                            HNAP_fileIdentifier,
                            [schema_ref["08"]['CKAN API property']],
                            date_str):
                        json_record[schema_ref["08"]['CKAN API property']] = \
                            date_str

            # CC::OpenMaps-09 Metadata Contact (French)

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["09"])
            if value:
                json_record[schema_ref["09"]['CKAN API property']] = value

            # CC::OpenMaps-10 Parent identifier

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["10"])
            if value:
                json_record[schema_ref["10"]['CKAN API property']] = value

            # CC::OpenMaps-11 Hierarchy level

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["11"])
            if value:
                json_record[schema_ref["11"]['CKAN API property']] = value

            # CC::OpenMaps-12 File Identifier

            json_record[schema_ref["12"]['CKAN API property']] = \
                HNAP_fileIdentifier

            # CC::OpenMaps-13 Short Key

            # Disabled as per the current install of RAMP
            # json_record[schema_ref["13"]
            # ['CKAN API property']] = HNAP_fileIdentifier[0:8]

            # CC::OpenMaps-14 Title (English)
            json_record[schema_ref["14"]['CKAN API property']] = {}

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["14a"])
            if value:
                json_record[
                    schema_ref["14"]['CKAN API property']
                ][schema_ref["14a"]['CKAN API property'].split('.')[1]] = value
            # CC::OpenMaps-15 Title (French)
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["14b"])

            # CKAN_secondary_lang = langtrans  ##2lang trans

            if value:
                json_record[
                    schema_ref["14"]['CKAN API property']
                ][schema_ref["14b"]['CKAN API property'].split('.')[1]] = value

            # CC::OpenMaps-16 Publisher - Current Organization Name

            org_strings = []
            org_string = ''
            abstring = ''
            bcstring = ''
            attempt = ''

            value = fetch_FGP_value(
                record, HNAP_fileIdentifier, schema_ref["16a"])
            value[0] = value[0].split(',')[0]
            if not 'government of canada' in value[0].lower():
                value[0] = value[0].split(';')[0]

            if isinstance(value[0], unicode):
                value[0] = value[0]


            fetch_orgname = [x for x in OrgNameDict if unicode(x.lower(),'UTF-8') in value[0].lower()]

            orgname = ""
            org_name = ""
            Primary_org_list = []
            secondary_lang_search_string = ""
            if len(fetch_orgname)>0:
                orgname = fetch_orgname[0]
                if HNAP_primary_lang == 'English':
                    primary_lang_search_string = ""+ orgname+";" # Government of Canada;"
                    secondary_lang_search_string = "" + OrgNameDictSecondLang[orgname]+";" #Gouvernement du Canada;"
                    Primary_org_list = GC_Registry_of_Organization_en
                    secondary_org_list = GC_Registry_of_Organization_fr
                else:
                    Primary_org_list = GC_Registry_of_Organization_fr
                    secondary_org_list = GC_Registry_of_Organization_en
                    primary_lang_search_string =  "" + orgname +";" #Gouvernement du Canada;"
                    secondary_lang_search_string = ""+ OrgNameDictSecondLang[orgname] +";" # Government of Canada;"




            # value = fetch_FGP_value(
            #     record, HNAP_fileIdentifier, schema_ref["16a"])
            # value[0] = value[0].split(',')[0]
            if not value or len(value) < 1:
                attempt += "No primary language value"
            else:
                attempt += "Has primary language value [" + str(len(value)) + "]"
                for single_value in value:
                    orgnamefound = False
                    for org_name in Primary_org_list:
                        try:
                            if re.search(unicode(org_name, "UTF-8"), single_value):
                                org_strings.append(single_value)
                                orgnamefound = True
                                break
                            elif single_value in unicode(org_name, "UTF-8"):
                                org_strings.append(single_value)
                                orgnamefound = True
                                break
                        except:
                            print("An exception occurred")


                    if not orgnamefound:
                        attempt += " but no GoC/GdC prefix [" + single_value + "]"

            value = fetch_FGP_value(
                record, HNAP_fileIdentifier, schema_ref["16b"])
            value[0] = value[0].split(',')[0]
            if not value or len(value) < 1:
                attempt += ", no secondary language value"
            else:
                attempt += ", secondary language [" + str(len(value)) + "]"
                for single_value in value:
                    if re.search(secondary_lang_search_string.lower(), single_value.lower().encode("UTF-8")):
                        org_strings.append(single_value.encode("UTF-8"))
                    else:
                        attempt += " but no GoC/GdC [" + single_value + "]"

            org_strings = list(set(org_strings))

            if len(org_strings) < 1:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["16"]['CKAN API property'],
                        "Bad organizationName, no Government of Canada",
                        attempt
                    ])
            else:
                valid_orgs = []
                curorgname = []

                for org_string in org_strings:
                    provdata = False
                    GOC_Structure = org_string.strip().split(';')  ##revisite
                    #fetch_orgname = [x for x in OrgNameDict if x in GOC_Structure[0].lower()][0] ############  ##############
                    # if GOC_Structure[0].lower() == orgname ##bcstring.lower() or GOC_Structure[0].lower() == abstring.lower():
                    #     del GOC_Structure[0]
                    #     provdata = True
                    #     curorgname = GOC_Structure[0]
                    #
                    # del GOC_Structure[0]

                    # Append to contributor
                    contributor_english = []
                    contributor_french = []

                    # At ths point you have ditched GOC and your checking for good
                    # dept names
                    for GOC_Div in GOC_Structure:
                        # Are they in the CL?
                        GOC_Div = GOC_Structure[0].strip() + '; ' + GOC_Div.strip()
                        termsValue = fetchCLValue( GOC_Div, GC_Registry_of_Applied_Terms)
                        if termsValue:
                            contributor_english.append(termsValue[0])
                            contributor_french.append(termsValue[2])
                            if termsValue[1] == termsValue[3]:
                                valid_orgs.append(termsValue[1].lower())
                            else:
                                valid_orgs.append((termsValue[1] + "-" + termsValue[3]).lower())
                            break

                # Unique the departments, don't need duplicates
                valid_orgs = list(set(valid_orgs))

                if len(valid_orgs) < 1:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["16"]['CKAN API property'],
                            "No valid orgs found",
                            org_string.strip()
                        ])
                else:
                    json_record[schema_ref["16"]['CKAN API property']] = valid_orgs[0]

                # Unique the departments, don't need duplicates
                contributor_english = list(set(contributor_english))
                contributor_french = list(set(contributor_french))

                # Multiple owners, excess pushed to contrib
                if len(valid_orgs) > 1:
                    del valid_orgs[0]
                    if len(contributor_english) > 0:
                        del contributor_english[0]
                    if len(contributor_english) > 0:
                        del contributor_french[0]
                    json_record[schema_ref["22"]['CKAN API property']] = {}
                    json_record[schema_ref["22"]['CKAN API property']]['en'] = []
                    json_record[schema_ref["22"]['CKAN API property']]['fr'] = []
                    for org in valid_orgs:
                        json_record[schema_ref["22"]['CKAN API property']]['en'] = ','.join(contributor_english)
                        json_record[schema_ref["22"]['CKAN API property']]['fr'] = ','.join(contributor_french)

            # CC::OpenMaps-17 Publisher - Organization Name at Publication (English)
            #       CKAN defined/provided
            # CC::OpenMaps-18 Publisher - Organization Name at Publication (French)
            #       CKAN defined/provided
            # CC::OpenMaps-19 Publisher - Organization Section Name (English)
            #       CKAN defined/provided
            # CC::OpenMaps-20 Publisher - Organization Section Name (French)
            #       CKAN defined/provided

            # CC::OpenMaps-21 Creator

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["21"])
            if value:
                json_record[schema_ref["21"]['CKAN API property']] = ','.join(value)

            # CC::OpenMaps-22 Contributor (English)
            #       Intentionally left blank, assuming singular contribution
            # CC::OpenMaps-23 Contributor (French)
            #       Intentionally left blank, assuming singular contribution

            # CC::OpenMaps-24 Position Name (English)
            # CC::OpenMaps-25 Position Name (French)

            json_record[schema_ref["24"]['CKAN API property']] = {}

            schema_ref["24"]['Occurrences'] = 'R'
            primary_data = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["24"])
            if value:
                for single_value in value:
                    primary_data.append(value)

            if len(primary_data) > 0:
                json_record[schema_ref["24"]['CKAN API property']][CKAN_primary_lang] = ','.join(value)

            schema_ref["25"]['Occurrences'] = 'R'
            primary_data = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["25"])
            if value:
                for single_value in value:
                    primary_data.append(value)

            if len(primary_data) > 0:
                json_record[schema_ref["24"]['CKAN API property']][CKAN_secondary_lang] = ','.join(value)

            if len(json_record[schema_ref["24"]['CKAN API property']]) < 1:
                del json_record[schema_ref["24"]['CKAN API property']]

            # CC::OpenMaps-26 Role

            # Single report out, multiple records combined
            schema_ref["26"]['Occurrences'] = 'R'
            primary_data = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["26"])
            if value:
                for single_value in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(single_value, napCI_RoleCode)
                    if not termsValue:
                        reportError(
                            HNAP_fileIdentifier, [
                                schema_ref["26"]['CKAN API property'],
                                'Value not found in ' + schema_ref["26"]['Reference']
                            ])
                    else:
                        primary_data.append(termsValue[0])

            if len(primary_data) > 0:
                json_record[schema_ref["26"]['CKAN API property']] = ','.join(value)

            # CC::OpenMaps-27
            #       Undefined property number
            # CC::OpenMaps-28
            #       Undefined property number

            # CC::OpenMaps-29 Contact Information (English)

            primary_vals = {}
            primary_vals[CKAN_primary_lang] = {}

            # HACK - find out of there is a pointOfContact role provided
            ref = schema_ref["29a"]["FGP XPATH"].split("gmd:CI_ResponsibleParty")[
                      0] + "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"
            tmp = fetchXMLValues(record, ref)
            xpath_sub = ""

            if len(tmp) > 0:
                xpath_sub = "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"

            # deliveryPoint
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29a"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29a"]['Requirement'],
                                                                  "Occurrences": schema_ref["29a"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["29a"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["29a"]['Value Type'],
                                                                  "CKAN API property": schema_ref["29a"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['delivery_point'] = single_value
            # city
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29b"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29b"]['Requirement'],
                                                                  "Occurrences": schema_ref["29b"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["29b"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["29b"]['Value Type'],
                                                                  "CKAN API property": schema_ref["29b"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['city'] = single_value
            # administrativeArea
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29c"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29c"]['Requirement'],
                                                                  "Occurrences": schema_ref["29c"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["29c"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["29c"]['Value Type'],
                                                                  "CKAN API property": schema_ref["29c"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['administrative_area'] = single_value
            # postalCode
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29d"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29d"]['Requirement'],
                                                                  "Occurrences": schema_ref["29d"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["29d"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["29d"]['Value Type'],
                                                                  "CKAN API property": schema_ref["29d"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['postal_code'] = single_value
            # country
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29e"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29e"]['Requirement'],
                                                                  "Occurrences": schema_ref["29e"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["29e"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["29e"]['Value Type'],
                                                                  "CKAN API property": schema_ref["29e"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['country'] = single_value
            # electronicMailAddress
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29f"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29f"]['Requirement'],
                                                                  "Occurrences": schema_ref["29f"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["29f"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["29f"]['Value Type'],
                                                                  "CKAN API property": schema_ref["29f"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['electronic_mail_address'] = single_value

            if len(primary_vals[CKAN_primary_lang]) < 1:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["29"]['CKAN API property'],
                        'Value not found in ' + schema_ref["29"]['Reference']
                    ])

            # CC::OpenMaps-30 Contact Information (French)

            primary_vals[CKAN_secondary_lang] = {}

            # deliveryPoint
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30a"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30a"]['Requirement'],
                                                                  "Occurrences": schema_ref["30a"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["30a"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["30a"]['Value Type'],
                                                                  "CKAN API property": schema_ref["30a"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['point_de_livraison'] = single_value
            # city
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30b"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30b"]['Requirement'],
                                                                  "Occurrences": schema_ref["30b"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["30b"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["30b"]['Value Type'],
                                                                  "CKAN API property": schema_ref["30b"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['ville'] = single_value
            # administrativeArea
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30c"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30c"]['Requirement'],
                                                                  "Occurrences": schema_ref["30c"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["30c"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["30c"]['Value Type'],
                                                                  "CKAN API property": schema_ref["30c"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['zone_administrative'] = single_value
            # postalCode
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30d"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30d"]['Requirement'],
                                                                  "Occurrences": schema_ref["30d"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["30d"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["30d"]['Value Type'],
                                                                  "CKAN API property": schema_ref["30d"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['code_postal'] = single_value
            # country
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30e"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30e"]['Requirement'],
                                                                  "Occurrences": schema_ref["30e"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["30e"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["30e"]['Value Type'],
                                                                  "CKAN API property": schema_ref["30e"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['pays'] = single_value
            # electronicMailAddress
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30f"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30f"]['Requirement'],
                                                                  "Occurrences": schema_ref["30f"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["30f"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["30f"]['Value Type'],
                                                                  "CKAN API property": schema_ref["30f"][
                                                                      'CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['electronic_mail_address'] = single_value

            if len(primary_vals[CKAN_secondary_lang]) < 1:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["30"]['CKAN API property'],
                        'Value not found in ' + schema_ref["30"]['Reference']
                    ])

            json_record[schema_ref["29"]['CKAN API property']] = json.dumps(primary_vals)

            # CC::OpenMaps-31 Contact Email

            # Single report out, multiple records combined
            schema_ref["31"]['Occurrences'] = 'R'
            json_record[schema_ref["31"]['CKAN API property']] = {}

            # HACK - find out of there is a pointOfContact role provided
            ref = schema_ref["31"]["FGP XPATH"].split("gmd:CI_ResponsibleParty")[
                      0] + "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"
            tmp = fetchXMLValues(record, ref)
            xpath_sub = ""

            if len(tmp) > 0:
                xpath_sub = "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"

            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["31"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["31"]['Requirement'],
                                                                  "Occurrences": schema_ref["31"]['Occurrences'],
                                                                  "FGP XPATH": schema_ref["31"]["FGP XPATH"].replace(
                                                                      "gmd:CI_ResponsibleParty", xpath_sub),
                                                                  "Value Type": schema_ref["31"]['Value Type'],
                                                                  "CKAN API property": schema_ref["31"][
                                                                      'CKAN API property']})

            # primary_data = []
            # if value:
            #     for single_value in value:
            #         primary_data.append(single_value)

            # if len(primary_data) > 0:
            #     json_record[schema_ref["31"]['CKAN API property']] = ','.join(value)

            # Check for valid email
            if value:
                value = value[0].split(',')  # revisite
                isprovemail = False
                for email in value:
                    isValidEmail = re.match(r'(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)', email.strip())
                if not isprovemail and isValidEmail == None:

                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["31"]['CKAN API property'],
                            "Invalid Email",
                            value[0]
                        ])
                else:
                    json_record[schema_ref["31"]['CKAN API property']] = value[0]
            else:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["31"]['CKAN API property'],
                        "Invalid Email",
                        ''
                    ])

            # CC::OpenMaps-32 Description (English)

            json_record[schema_ref["32"]['CKAN API property']] = {}
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["32a"])
            value_old = value
            if value:
                # format line breaks
                value = value.replace('\n', '  \n  \n  ')
                value = value.replace('----------------------------------------------------------',
                                      '  \n  \n  ----------------------------------------------------------  \n  \n  ')

                json_record[
                    schema_ref["32"]['CKAN API property']
                ][schema_ref["32a"]['CKAN API property'].split('.')[1]] = value

            # XXX Check that there are values

            # CC::OpenMaps-33 Description (French)

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["32b"])
            value_old = value
            if value:
                # format line breaks
                value = value.replace('\n', '  \n  \n  ')
                value = value.replace('----------------------------------------------------------',
                                      '  \n  \n  ----------------------------------------------------------  \n  \n  ')
                                      
                json_record[
                    schema_ref["32"]['CKAN API property']
                ][schema_ref["32b"]['CKAN API property'].split('.')[1]] = value

            # XXX Check that there are values

            # CC::OpenMaps-34 Keywords (English)

            primary_vals = []
            json_record[schema_ref["34"]['CKAN API property']] = {}
            json_record[schema_ref["34"]['CKAN API property']][schema_ref["34a"]['CKAN API property'].split('.')[1]] = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["34a"])
            if value:
                for single_value in value:
                    p = re.compile('^[A-Z][A-Z] [^>]+ > ')
                    single_value = p.sub('', single_value)
                    single_value = single_value.strip()

                    # ADAPTATION #4
                    # 2016-05-27 - call
                    # Alexandre Bolieux asked I replace commas with something valid.  I'm replacing them with semi-colons
                    # which can act as a seperator character like the comma but get past that reserved character
                    single_value = single_value.replace(',', ';')
                    # END ADAPTATION
                    # remove multiple spaces
                    single_value = re.sub(r'\s+', ' ', single_value)
                    keyword_error = canada_tags(single_value).replace('"', '""')

                    # ADAPTATION #5
                    # 2016-05-27 - call
                    # Alexandre Bolieux asked if I could replace commas with something valid.  I'm
                    # replacing them with semi-colons which can act as a seperator character like
                    # the comma but get past that reserved character
                    if re.search('length is more than maximum 140', keyword_error, re.UNICODE):
                        pass
                    else:
                        # END ADAPTATION
                        if not keyword_error == '':
                            # if not re.search(schema_ref["34"]['RegEx Filter'], single_value,re.UNICODE):
                            reportError(
                                HNAP_fileIdentifier, [
                                    schema_ref["34"]['CKAN API property'] + '-' + CKAN_primary_lang,
                                    "Invalid Keyword",
                                    keyword_error
                                    # "Must be alpha-numeric, space or '-_./>+& ["+single_value+']'
                                ])
                        else:
                            if single_value not in json_record[schema_ref["34"]['CKAN API property']][schema_ref["34a"]['CKAN API property'].split('.')[1]]:
                                json_record[schema_ref["34"]['CKAN API property']][schema_ref["34a"]['CKAN API property'].split('.')[1]].append(
                                    single_value)

            #                        if not len(json_record[schema_ref["34"]['CKAN API property']][CKAN_primary_lang]):
            #                            reportError(
            #                                HNAP_fileIdentifier,[
            #                                    schema_ref["34"]['CKAN API property']+'-'+CKAN_primary_lang,
            #                                    "No keywords"
            #                                ])

            # CC::OpenMaps-35 Keywords (French)

            # json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang] = []
            json_record[schema_ref["34"]['CKAN API property']][schema_ref["34b"]['CKAN API property'].split('.')[1]] = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["34b"])
            if value:
                for single_value in value:
                    p = re.compile('^[A-Z][A-Z] [^>]+ > ')
                    single_value = p.sub('', single_value)
                    # ADAPTATION #4
                    # 2016-05-27 - call
                    # Alexandre Bolieux asked if I could replace commas with something valid.  I'm
                    # replacing them with semi-colons which can act as a seperator character like
                    # the comma but get past that reserved character
                    single_value = single_value.replace(',', ';')
                    # END ADAPTATION
                    single_value = re.sub(r'\s+', ' ', single_value)
                    keyword_error = canada_tags(single_value).replace('"', '""')

                    # ADAPTATION #5
                    # 2016-05-27 - call
                    # Alexandre Bolieux asked I drop keywords that exceed 140 characters
                    if re.search('length is more than maximum 140', keyword_error, re.UNICODE):
                        pass
                    else:
                        # END ADAPTATION
                        if not keyword_error == '':
                            # if not re.search(schema_ref["34"]['RegEx Filter'], single_value,re.UNICODE):
                            reportError(
                                HNAP_fileIdentifier, [
                                    schema_ref["34"]['CKAN API property'] + '-' + CKAN_secondary_lang,
                                    "Invalid Keyword",
                                    keyword_error
                                    # 'Must be alpha-numeric, space or -_./>+& ['+single_value+']'
                                ])
                        else:
                            if single_value not in json_record[schema_ref["34"]['CKAN API property']][schema_ref["34b"]['CKAN API property'].split('.')[1]]:
                                json_record[schema_ref["34"]['CKAN API property']][schema_ref["34b"]['CKAN API property'].split('.')[1]].append(single_value)

                                # json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang].append(single_value)

            #                        if not len(json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang]):
            #                            reportError(
            #                                HNAP_fileIdentifier,[
            #                                    schema_ref["34"]['CKAN API property']+'-'+CKAN_secondary_lang,
            #                                    "No keywords"
            #                                ])

            # CC::OpenMaps-36 Subject

            subject_values = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["36"])
            if value:
                for subject in value:
                    termsValue = fetchCLValue(
                        subject.strip(), CL_Subjects)
                    if termsValue:
                        for single_item in termsValue[3].split(','):
                            subject_values.append(single_item.strip().lower())

                if len(subject_values) < 1:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["36"]['CKAN API property'],
                            'Value not found in ' + schema_ref["36"]['Reference']
                        ])
                else:
                    json_record[schema_ref["36"]['CKAN API property']] = list(set(subject_values))

            # CC::OpenMaps-37 Topic Category

            topicCategory_values = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["37"])
            if value:
                for topicCategory in value:
                    termsValue = fetchCLValue(
                        topicCategory.strip(), napMD_KeywordTypeCode)
                    if termsValue:
                        topicCategory_values.append(termsValue[0])

                if len(topicCategory_values) < 1:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["37"]['CKAN API property'],
                            'Value not found in ' + schema_ref["37"]['Reference']
                        ])
                else:
                    json_record[schema_ref["37"]['CKAN API property']] = topicCategory_values

            # CC::OpenMaps-38 Audience
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-39 Place of Publication (English)
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-40 Place of Publication  (French)
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-41 Spatial

            north = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41n"])
            if north:
                south = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41s"])
                if south:
                    east = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41e"])
                    if east:
                        west = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41w"])
                        if west:
                            # ensure we have proper numbers
                            north = [float(north[0]) if '.' in north[0] else int(north[0])]
                            east = [float(east[0]) if '.' in east[0] else int(east[0])]
                            south = [float(south[0]) if '.' in south[0] else int(south[0])]
                            west = [float(west[0]) if '.' in west[0] else int(west[0])]

                            GeoJSON = {}
                            GeoJSON['type'] = "Polygon"
                            GeoJSON['coordinates'] = [[
                                [west, south],
                                [east, south],
                                [east, north],
                                [west, north],
                                [west, south]
                            ]]

                            # json_record[schema_ref["41"]['CKAN API property']] = json.dumps(GeoJSON)
                            json_record[schema_ref["41"][
                                'CKAN API property']] = '{"type": "Polygon","coordinates": [[[%s,%s],[%s,%s],[%s,%s],[%s,%s],[%s,%s]]]}' % (
                            west[0], south[0], east[0], south[0], east[0], north[0], west[0], north[0], west[0],
                            south[0])

            # CC::OpenMaps-42 Geographic Region Name
            # TBS 2016-04-13: Not in HNAP, we can skip (the only providing the bounding box, not the region name)

            # CC::OpenMaps-43 Time Period Coverage Start Date
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["43"])
            if value:
                if sanityDate(
                        HNAP_fileIdentifier, [
                            schema_ref["43"]['CKAN API property'] + '-start'
                        ],
                        maskDate(value)
                ):
                    json_record[schema_ref["43"]['CKAN API property']] = maskDate(value)

            # CC::OpenMaps-44 Time Period Coverage End Date
            #   ADAPTATION #2
            #     CKAN (or Solr) requires an end date where one doesn't exist.  An open
            #     record should run without an end date.  Since this is not the case a
            #     '9999-99-99' is used in lieu.
            #   ADAPTATION #3
            #     Temporal elements are ISO 8601 date objects but this field may be
            #     left blank (invalid).
            #     The intent is to use a blank field as a maker for an "open" record
            #     were omission of this field would be standard practice.  No
            #     gml:endPosition = no end.
            #     Since changing the source seems to be impossible we adapt by
            #     replacing a blank entry with the equally ugly '9999-99-99' forced
            #     end in CKAN.

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["44"])
            if value:

                check_for_blank = value
                if check_for_blank == '':
                    check_for_blank = '9999-09-09'

                if sanityDate(
                        HNAP_fileIdentifier, [
                            schema_ref["44"]['CKAN API property'] + '-end'
                        ],
                        maskDate(check_for_blank)
                ):
                    json_record[schema_ref["44"]['CKAN API property']] = maskDate(check_for_blank)

            # CC::OpenMaps-45 Maintenance and Update Frequency

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["45"])
            if value:
                # Can you find the CL entry?
                termsValue = fetchCLValue(value, napMD_MaintenanceFrequencyCode)
                if not termsValue:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["45"]['CKAN API property'],
                            'Value not found in ' + schema_ref["45"]['Reference']
                        ])
                else:
                    json_record[schema_ref["45"]['CKAN API property']] = termsValue[2]

            # CC::OpenMaps-46 Date Published
            # CC::OpenMaps-47 Date Modified

            ##################################################
            # These are a little different, we have to do these odd birds manually
            r = record.xpath(
                schema_ref["46"]["FGP XPATH"],
                namespaces={
                    'gmd': 'http://www.isotc211.org/2005/gmd',
                    'gco': 'http://www.isotc211.org/2005/gco'})

            if (len(r)):
                for cn in r:
                    input_types = {}
                    inKey = []
                    inVal = ''
                    # Decypher which side has the code and which has the data,
                    # yea... it changes -sigh-
                    # Keys will always use the ;
                    try:
                        if cn[0][0].text is not None and len(cn[0][0].text.split(';')) > 1:
                            inKey = cn[0][0].text.split(';')
                            inVal = cn[1][0].text.strip()
                        elif cn[1][0].text is not None:
                            inKey = cn[1][0].text.split(';')
                            inVal = cn[0][0].text.strip()
                    except:
                        pass

                    for input_type in inKey:
                        input_type = input_type.strip()
                        if input_type == u'publication':
                            if sanityDate(
                                    HNAP_fileIdentifier, [
                                        schema_ref["46"]['CKAN API property']
                                    ],
                                    maskDate(inVal)):
                                json_record[schema_ref["46"]['CKAN API property']] = maskDate(inVal)
                                break

                        if input_type == u'revision' or input_type == u'révision':
                            if sanityDate(
                                    HNAP_fileIdentifier, [
                                        schema_ref["47"]['CKAN API property']
                                    ],
                                    maskDate(inVal)):
                                json_record[schema_ref["47"]['CKAN API property']] = maskDate(inVal)
                                break

                # Check the field is populated if you have to
                if schema_ref["46"]['Requirement'] == 'M' and schema_ref["46"]['CKAN API property'] not in json_record:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["46"]['CKAN API property'],
                            'Value not found in ' + schema_ref["46"]['Reference']
                        ])

                # Check the field is populated if you have to
                if schema_ref["47"]['Requirement'] == 'M' and schema_ref["47"]['CKAN API property'] not in json_record:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["47"]['CKAN API property'],
                            'Value not found in ' + schema_ref["47"]['Reference']
                        ])

            if 'date_published' not in json_record:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["46"]['CKAN API property'],
                        'mandatory field missing'
                    ])

            # CC::OpenMaps-48 Date Released
            # SYSTEM GENERATED

            # CC::OpenMaps-49 Homepage URL (English)
            # TBS 2016-04-13: Not in HNAP, we can skip
            # CC::OpenMaps-50 Homepage URL (French)
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-51 Series Name (English)
            # TBS 2016-04-13: Not in HNAP, we can skip
            # CC::OpenMaps-52 Series Name (French)
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-53 Series Issue Identification (English)
            # TBS 2016-04-13: Not in HNAP, we can skip
            # CC::OpenMaps-54 Series Issue Identification (French)
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-55 Digital Object Identifier
            # TBS 2016-04-13: Not in HNAP, we can skip

            # CC::OpenMaps-56 Reference System Information

            # Allow for multiple refrence definitions
            # Updated implementation mimics prior behaviour.
            possible_refrences = fetchXMLArray(
                record,
                schema_ref["56"]['FGP XPATH'])

            # print '--------------------------------------'
            # print possible_refrences
            # print '--------------------------------------'

            if len(possible_refrences) == 0:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["56"]['CKAN API property'],
                        'No projection information found'
                    ])
            else:
                first_full_triplet = ''
                for possible_refrence in possible_refrences:
                    vala = valb = valc = ''

                    # code
                    value = fetch_FGP_value(possible_refrence, HNAP_fileIdentifier, schema_ref["56a"])
                    if value:
                        vala = value
                    # codeSpace
                    value = fetch_FGP_value(possible_refrence, HNAP_fileIdentifier, schema_ref["56b"])
                    if value:
                        valb = value
                    # version
                    value = fetch_FGP_value(possible_refrence, HNAP_fileIdentifier, schema_ref["56c"])
                    if value:
                        valc = value

                    # Apply your business logic, this is the same logic as before assuming a single projection
                    # If this is to become multiple projections the property needs to be changed into an array
                    # in the schema and _then_ in CKAN.
                    if vala != '' and valb != '' and valc != '':
                        first_full_triplet = vala + ',' + valb + ',' + valc
                        json_record[schema_ref["56"]['CKAN API property']] = first_full_triplet
                        break

                # if the triplet is not complete then fail over to just the mandatory HNAP requirement
                if first_full_triplet == '':

                    rs_identifier = fetch_FGP_value(possible_refrences[0], HNAP_fileIdentifier, schema_ref["56a"])

                    if len(rs_identifier) > 0:
                        first_full_triplet = rs_identifier + ',' + fetch_FGP_value(possible_refrences[0],
                                                                                   HNAP_fileIdentifier, schema_ref[
                                                                                       "56b"]) + ',' + fetch_FGP_value(
                            possible_refrences[0], HNAP_fileIdentifier, schema_ref["56c"])

                    if first_full_triplet == '':
                        reportError(
                            HNAP_fileIdentifier, [
                                schema_ref["56"]['CKAN API property'],
                                'Complete triplet not found'
                            ])

            # CC::OpenMaps-57 Distributor (English)

            primary_vals = {}
            primary_vals[CKAN_primary_lang] = {}
            primary_vals[CKAN_secondary_lang] = {}

            # organizationName
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57a"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['organization_name'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58a"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['nom_organization'] = single_value

            # phone
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57b"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['phone'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58b"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['telephone'] = single_value

            # address
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57c"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['address'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58c"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['adresse'] = single_value

            # city
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57d"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['city'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58d"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['ville'] = single_value

            # administrativeArea
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57e"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['administrative_area'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58e"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['zone_administrative'] = single_value

            # postalCode
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57f"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['postal_code'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58f"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['code_postal'] = single_value

            # country
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57g"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['country'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58g"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['pays'] = single_value

            # electronicMailAddress  mandatory
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57h"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['electronic_mail_address'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58h"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['electronic_mail_address'] = single_value

            # role mandatory
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57i"])
            if value:
                for single_value in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(single_value, napCI_RoleCode)
                    if not termsValue:
                        reportError(
                            HNAP_fileIdentifier, [
                                schema_ref["57"]['CKAN API property'],
                                'Value not found in ' + schema_ref["57"]['Reference']
                            ])
                    else:
                        primary_vals[CKAN_primary_lang]['role'] = termsValue[0]
                        primary_vals[CKAN_secondary_lang]['role'] = termsValue[1]

            json_record[schema_ref["57"]['CKAN API property']] = json.dumps(primary_vals)

            # json_record[schema_ref["57"]['CKAN API property']] = {}
            # json_record[schema_ref["57"]['CKAN API property']][CKAN_primary_lang] = ','.join(primary_vals)
            # json_record[schema_ref["57"]['CKAN API property']][CKAN_secondary_lang] = ','.join(second_vals)

            # CC::OpenMaps-59 Status

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["59"])
            if value:
                # Can you find the CL entry?
                termsValue = fetchCLValue(value, napMD_ProgressCode)
                if not termsValue:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["59"]['CKAN API property'],
                            'Value not found in ' + schema_ref["59"]['Reference']
                        ])
                else:
                    json_record[schema_ref["59"]['CKAN API property']] = termsValue[0]

            # CC::OpenMaps-60 Association Type

            associationTypes_array = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["60"])

            # Not mandatory, process if you have it
            if value and len(value) > 0:

                # You have to iterate to find a valid one, not necessarily the
                for associationType in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(
                        associationType, napDS_AssociationTypeCode)
                    if not termsValue:
                        termsValue = []
                    else:
                        associationTypes_array.append(termsValue[2])

            if len(associationTypes_array):
                json_record[schema_ref["60"]['CKAN API property']] = ','.join(associationTypes_array)

            # CC::OpenMaps-61 Aggregate Dataset Identifier

            aggregateDataSetIdentifier_array = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["61"])
            # Not mandatory, process if you have it
            if value and len(value) > 0:

                try:
                    for aggregateDataSetIdentifier in value:
                        (primary, secondary) = \
                            aggregateDataSetIdentifier.strip().split(';')
                        aggregateDataSetIdentifier_array.append(primary.strip())
                        aggregateDataSetIdentifier_array.append(secondary.strip())
                except ValueError:
                    errorInfo = [schema_ref["61"]['CKAN API property']]
                    errorInfo.append('primary/secondary identifiers not provided/valid')
                    errorInfo.append(aggregateDataSetIdentifier.strip())
                    reportError(HNAP_fileIdentifier, errorInfo)
                    pass

            json_record[schema_ref["61"]['CKAN API property']] = ','.join(
                aggregateDataSetIdentifier_array)

            # CC::OpenMaps-62 Spatial Representation Type

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["62"])

            json_record[schema_ref["62"]['CKAN API property']] = {}
            spatialRepresentationType_array = []

            if value:
                # You have to itterate to find a valid one,
                # not neccesaraly the first
                for spatialRepresentationType in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(
                        spatialRepresentationType,
                        napMD_SpatialRepresentationTypeCode)
                    if not termsValue:
                        termsValue = []
                    else:
                        spatialRepresentationType_array.append(termsValue[0])

            # json_record[schema_ref["62"]['CKAN API property']] = ','.join(
            # spatialRepresentationType_array)

            json_record[schema_ref["62"]['CKAN API property']] = spatialRepresentationType_array

            # CC::OpenMaps-63 Jurisdiction
            # TBS 2016-04-13: Not in HNAP, but can we default text to ‘Federal’ / ‘Fédéral

            json_record[schema_ref["63"]['CKAN API property']] = schema_ref["63"]['FGP XPATH']

            if org_name.lower().find('government of canada') == -1:
                json_record[schema_ref["63"]['CKAN API property']] = schema_ref["63p"]['FGP XPATH']


            if fetch_nunicipalname:
                json_record[schema_ref["63"]['CKAN API property']] = schema_ref["63m"]['FGP XPATH']

            # CC::OpenMaps-64 Licence
            # TBS (call): use ca-ogl-lgo


            def SetLicence(kindex):
                json_record[schema_ref["64"]['CKAN API property']] = schema_ref[kindex]['FGP XPATH']

            fetch_orgname = [x for x in OrgNameDict if x.lower() in org_name.lower()]
            if len(fetch_orgname) > 0:
                SetLicence(licencekey[fetch_orgname[0]])

            # json_record[schema_ref["64"]['CKAN API property']] = schema_ref["64"]['FGP XPATH']

            # if org_name.lower().find('government of alberta') != -1:
            #     json_record[schema_ref["64"]['CKAN API property']] = schema_ref["64ab"]['FGP XPATH']
            # elif org_name.lower().find('government of british columbia') != -1:
            #     json_record[schema_ref["64"]['CKAN API property']] = schema_ref["64bc"]['FGP XPATH']

            # choice[string](parameters)

            # CC::OpenMaps-65 Unique Identifier
            # System generated

            #### Resources

            # CC::OpenMaps-68 Date Published
            # TBS 2016-04-13: Not in HNAP, we can skip

            json_record['resources'] = []
            record_resources = fetchXMLArray(
                record,
                "gmd:distributionInfo/" +
                "gmd:MD_Distribution/" +
                "gmd:transferOptions/" +
                "gmd:MD_DigitalTransferOptions/" +
                "gmd:onLine/" +
                "gmd:CI_OnlineResource")

            resource_no = 0
            for resource in record_resources:

                resource_no += 1

                json_record_resource = {}
                json_record_resource[schema_ref["66"]['CKAN API property']] = {}

                # CC::OpenMaps-66 Title (English)

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["66a"])
                if value:
                    json_record_resource[schema_ref["66"]['CKAN API property']][schema_ref["66a"]['CKAN API property'].split('.')[1]]  = value

                # CC::OpenMaps-67 Title (English)

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["66b"])
                if value:
                    json_record_resource[schema_ref["66"]['CKAN API property']][schema_ref["66b"]['CKAN API property'].split('.')[1]] = value
                

                # CC::OpenMaps-69 Resource Type
                # CC::OpenMaps-70 Format
                # CC::OpenMaps-73 Language

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["69-70-73"])
                if value:
                    description_text = value.strip()

                    if description_text.count(';') != 2:
                        reportError(
                            HNAP_fileIdentifier, [
                                schema_ref["69-70-73"]['CKAN API property'],
                                'Content, Format or Language missing, must be: contentType;format;lang,lang',
                                description_text
                            ])
                    else:
                        (res_contentType, res_format,
                         res_language) = description_text.split(';')

                        languages_in = res_language.strip().split(',')
                        languages_out = []
                        for language in languages_in:
                            if language.strip() == 'eng':
                                languages_out.append('en')
                            if language.strip() == 'fra':
                                languages_out.append('fr')
                            if language.strip() == 'zxx':  # Non linguistic
                                languages_out.append('zxx')
                        # language_str = ','.join(languages_out)
                        language_str = []
                        for langStr in languages_out:
                            language_str.append(langStr)

                        json_record_resource[schema_ref["69"]['CKAN API property']] = res_contentType.strip().lower()
                        json_record_resource[schema_ref["70"]['CKAN API property']] = res_format.strip()
                        json_record_resource[schema_ref["73"]['CKAN API property']] = language_str

                        # XXX Super duper hack
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'document de soutien':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'supporting document':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'Supporting Documents':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'Supporting Document':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == u'données':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'dataset'

                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Web App':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'HTML'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'IOS Application':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'IPA'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Blackberry Application':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'COD'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Windows Mobile':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'EXE'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Android Application':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'APK'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'GeoJSON':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'GEOJSON'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'dxf':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'DXF'

                else:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["69-70-73"]['CKAN API property'],
                            'format,mandatory field missing'
                        ])
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["69-70-73"]['CKAN API property'],
                            'language,mandatory field missing'
                        ])
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["69-70-73"]['CKAN API property'],
                            'contentType,mandatory field missing'
                        ])

                if json_record_resource[schema_ref["69"]['CKAN API property']].lower() not in ResourceType:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["69-70-73"]['CKAN API property'],
                            'invalid resource type',
                            json_record_resource[schema_ref["69"]['CKAN API property']]
                        ])
                else:
                    json_record_resource[schema_ref["69"]['CKAN API property']] = \
                    ResourceType[json_record_resource[schema_ref["69"]['CKAN API property']].lower()][0]

                if json_record_resource[schema_ref["70"]['CKAN API property']] not in CL_Formats:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["69-70-73"]['CKAN API property'],
                            'invalid resource format',
                            json_record_resource[schema_ref["70"]['CKAN API property']]
                        ])

                # CC::OpenMaps-71 Character Set
                # TBS 2016-04-13: Not in HNAP, we can skip
                # CC::OpenMaps-74 Size
                # TBS 2016-04-13: Not in HNAP, we can skip

                # CC::OpenMaps-74 Download URL

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["74"])
                if value:
                    json_record_resource[schema_ref["74"]['CKAN API property']] = value
                else:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["74"]['CKAN API property'],
                            'URL, mandatory field missing'
                        ])

                # # CC::OpenMaps-75 Title (English)
                # # XXX Need to confirm why this is not included
                # json_record[schema_ref["75"]['CKAN API property']] = {}

                # value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["75"])
                # if value:
                #     json_record[schema_ref["75"]['CKAN API property']][CKAN_primary_lang] = value

                # # CC::OpenMaps-76 Title (French)
                # # XXX Need to confirm why this is not included
                # value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["75b"])
                # if value:
                #     json_record[schema_ref["75"]['CKAN API property']][schema_ref["75b"]['CKAN API property'].split('.')[1]] = value

                # CC::OpenMaps-76 Record Type
                # TBS 2016-04-13: Not in HNAP, we can skip
                # CC::OpenMaps-78 Relationship Type
                # TBS 2016-04-13: Not in HNAP, we can skip
                # CC::OpenMaps-79 Language
                # TBS 2016-04-13: Not in HNAP, we can skip
                # CC::OpenMaps-80 Record URL
                # TBS 2016-04-13: Not in HNAP, we can skip

                # CC::OpenMaps-81 Mappable
                # Stored as a generic Display Flag in preperation for other forms of visualizations

                # if schema_ref["81"]['CKAN API property'] not in json_record:
                #    can_be_used_in_RAMP = False
                #    json_record[schema_ref["81"]['CKAN API property']] = can_be_used_in_RAMP

                # If false check if true now
                if not can_be_used_in_RAMP:
                    value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["81"])
                    if value:
                        protocol_desc = value.strip()
                        if protocol_desc in mappable_protocols:
                            can_be_used_in_RAMP = True

                            # check to see if the URL is HTTPS
                            value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["74"])
                            # if value[:value.find(":")] == 'http':
                            # print "No HTTPS: " + HNAP_fileIdentifier
                            if value:
                                can_be_used_in_RAMP = value[:value.find(":")] == 'https'

                # Append the resource to the Open Maps record
                json_record['resources'].append(json_record_resource)

            # TODO Add parent relation if exists
            # json_record['resources'].append( { "relation_type" : "info" } )

            # json_record[schema_ref["81"]['CKAN API property']] = can_be_used_in_RAMP
            view_on_map = ""
            '''
            strtmp = str(HNAP_fileIdentifier)
            str1 = "9b1d5058-81a9-420c-afb9-69791b06e35a"
            str2 = "6ac8d5f2-6a3d-4313-8785-881b2ac2ad24"
            str3 = "10987662-c496-4ba8-a6b9-21cb5a134da2"
            str4 = "fb362c48-fe21-4e4d-abee-cf7ef92b475d"
            str5 = "15c36c35-bb63-425e-9753-12704d310844"
            str6 = "267e20aa-97e8-43da-8c23-1234376938bc"
            str7 = "308b7792-a075-4b43-a68f-37bf35d76a9f"
            str8 = "848e943b-1a98-43b8-acb3-ac89af17ea41"
            str9 = "9a42d891-fc9c-44b3-8fba-9d9ed96890cf"
            str10= "8ac7fcc1-779c-480c-a31a-3bfca2629cd5"
            str11= "3f78ae16-d59f-494e-bb1f-ffbabb8eff9b"
            str12= "981a18a3-6f0d-4109-b3d2-019589fad7c6" 
            if [strtmp == str1] or [strtmp == str2] or [strtmp == str3] or [strtmp == str4] or\
               [strtmp == str5] or [strtmp == str6] or [strtmp == str7] or [strtmp == str8] or \
               [strtmp == str9] or [strtmp == str10] or [strtmp == str11] or [strtmp == str12] :
                can_be_used_in_RAMP = True
            '''

            if can_be_used_in_RAMP:
                json_record['display_flags'].append('fgp_viewer')
                view_on_map = " [ View on Map ]"
                num_view_on_map += 1

            ##################################################
            #                                                #
            # Accept or Reject                               #
            # Assume IMSO approval                           #
            # Assume publish status                          #
            # Assume active status                           #
            # Append to list of Datasets                     #
            #                                                #
            ##################################################

            if HNAP_fileIdentifier in error_records:
                time.sleep(0.1)  # slow display#
                print "\x1b[0;37;41m Reject: \x1b[0m " + str(HNAP_fileIdentifier) + view_on_map
                num_rejects += 1
            else:
                time.sleep(0.1)  # slow display#
                print "\x1b[0;37;42m Accept: \x1b[0m " + str(HNAP_fileIdentifier) + view_on_map
                json_record['imso_approval'] = 'true'
                json_record['ready_to_publish'] = 'true'
                json_record['state'] = 'active'
                json_record['restrictions'] = 'unrestricted'
                # if error don't do this
                json_records.append(json_record)
                schemafile.close()

            ##################################################
            #                                                #
            # Move onto the next record                      #
            #                                                #
            ##################################################
###############################################
###############################################
    if len(json_records) > 0:
        print "Generating Common Core JSON file for import to CKAN..."

        # Write JSON Lines to files
        print " Generating New JSON"
        output = codecs.open(output_jl, 'w', 'utf-8')

        groupcount = 1
        fileindexcount = 1
        timestr = time.strftime("%Y%m%d-%H%M%S")
        groupoutput = codecs.open(OutputEnv + "/" + timestr + "-" + str(fileindexcount) + ".jl",'w', 'utf-8')
        for json_record in json_records:
            utf_8_output = \
                json.dumps(
                    json_record,
                    # sort_keys=True,
                    # indent=4,
                    ensure_ascii=False,
                    encoding='utf8')
            # print utf_8_output
        
            output.write(utf_8_output + "\n")
            groupoutput.write(utf_8_output + "\n")
            if groupcount%50 == 0:
                groupoutput.close()
                fileindexcount +=1
                timestr = time.strftime("%Y%m%d-%H%M%S")
                groupoutput = codecs.open(OutputEnv + "/" + timestr + "-" + str(fileindexcount)  +".jl",'w', 'utf-8')
            groupcount += 1
        groupoutput.close()    
        output.close()

    

    if len(json_records) > 0:
        print "Done!"
        print ""
        print "* Number of records accepted: " + str(len(json_records))
        print ""
        print "* Number of records rejected: " + str(num_rejects)
        print ""
        print "* Number with view on map:    " + str(num_view_on_map)
        print ""
        print "* Number of errors logged:    " + str(
            len(error_output)) + " [ harvested_record_errors.csv | harvested_record_errors.html ]"
        print ""

    output = codecs.open(output_err, 'w', 'utf-8')
    if len(error_output) > 0:
        output.write('"id","field","description","value"' + u"\n")
    for error in error_output:
        # output.write(unicode(error+"\n", 'utf-8'))
        output.write(error + u"\n")
    output.close()

    ## Move file to Porcessed Dir
    if SingleXmlInput == True:
        ProcDirCreation();
        # shutil.move(sys.argv[2], "processed-xml")



##################################################
# Reporting, Sanity and Access functions
# reportError(HNAP_fileIdentifier, errorInfo)
# sanityMandatory(pre, values)
# sanitySingle(pre, values)
# sanityDate(pre, date_text)
# sanityFirst(values)

# Fire off an error to cmd line
def reportError(HNAP_fileIdentifier, errorInfo):
    errorText = '"' + HNAP_fileIdentifier + '","' + '","'.join(errorInfo) + '"'
    global error_output
    global error_records
    # global OGDMES2ID
    # print len(error_output)
    if not isinstance(errorText, unicode):
        errorText = unicode(errorText, 'utf-8')
    error_output.append(errorText)
    if HNAP_fileIdentifier not in error_records:
        error_records[HNAP_fileIdentifier] = []
    error_records[HNAP_fileIdentifier].append(errorText)
    # print len(error_output)


# Sanity check: make sure the value exists
def sanityMandatory(HNAP_fileIdentifier, errorInfo, values):
    values = list(set(values))
    if values is None or len(values) < 1:
        errorInfo.append('mandatory field missing or not found in controlled list')
        reportError(HNAP_fileIdentifier, errorInfo)
        return False
    return True


# Sanity check: make sure there is only one value
def sanitySingle(HNAP_fileIdentifier, errorInfo, values):
    values = list(set(values))
    if len(values) > 1:
        multiplefreqcode = True
        for value in values:
            if not napMD_MaintenanceFrequencyCode.has_key(value.strip()):
                multiplefreqcode = False
            if sanityDate(HNAP_fileIdentifier, errorInfo, value.strip()):
                multiplefreqcode = True

        if not multiplefreqcode == True:
            errorInfo.append('multiple of a single value')
            errorInfo.append(','.join(values))
            reportError(HNAP_fileIdentifier, errorInfo)
            return False
    return True


# Sanity check: validate the date
def sanityDate(HNAP_fileIdentifier, errorInfo, date_text):
    value = ''
    try:
        value = datetime.strptime(
            date_text,
            '%Y-%m-%d').isoformat().split('T')[0]
    except ValueError:
        errorInfo.append('date is not valid')
        errorInfo.append(date_text)
        reportError(HNAP_fileIdentifier, errorInfo)
        return False
    if value != date_text:
        errorInfo.append('date is not valid')
        errorInfo.append(date_text)
        reportError(HNAP_fileIdentifier, errorInfo)
        return False
    return True


# Sanity value: extract the first value or blank string
def sanityFirst(values):
    if len(values) < 1:
        return ''
    else:
        return values[0]


##################################################
# Project specific data manipulation
# maskDate(date)


def maskDate(date):
    # default_date =\
    if len(date) >= 10:
        return date
    return date + ('xxxx-01-01'[-10 + len(date):])


##################################################
# XML Extract functions
# fetchXMLArray(objectToXpath, xpath)
# fetchXMLValues(objectToXpath, xpath)
# fetchXMLAttribute(objectToXpath, xpath, attribute)
# fetchCLValue(SRCH_key, CL_array)


# Fetch an array which may be subsections
def fetchXMLArray(objectToXpath, xpath):
    return objectToXpath.xpath(xpath, namespaces={
        'gmd': 'http://www.isotc211.org/2005/gmd',
        'gco': 'http://www.isotc211.org/2005/gco',
        'gml': 'http://www.opengis.net/gml/3.2',
        'csw': 'http://www.opengis.net/cat/csw/2.0.2'})


# Extract values from your current position
def fetchXMLValues(objectToXpath, xpath):
    values = []
    r = fetchXMLArray(objectToXpath, xpath)
    if (len(r)):
        for namePart in r:
            if namePart.text is None:
                values.append('')
            else:
                values.append(namePart.text.strip())
    return values


# Fetch an attribute instead of a an element
def fetchXMLAttribute(objectToXpath, xpath, attribute):
    # Easy to miss this, clean and combine
    clean_xpath = xpath.rstrip('/')
    clean_attribute = xpath.lstrip('@')
    # Access to an attribute through lxml is
    # xpath/to/key/@key_attribute
    # e.g.:
    # html/body/@background-color
    return objectToXpath.xpath(xpath + '/@' + attribute, namespaces={
        'gmd': 'http://www.isotc211.org/2005/gmd',
        'gco': 'http://www.isotc211.org/2005/gco',
        'gml': 'http://www.opengis.net/gml/3.2',
        'csw': 'http://www.opengis.net/cat/csw/2.0.2'})


# Fetch the value of a controled list ( at the bottom )
def fetchCLValue(SRCH_key, CL_array):
    p = re.compile(' ')
    SRCH_key = SRCH_key.lower()
    SRCH_key = p.sub('', SRCH_key)

    for CL_key, value in CL_array.items():
        CL_key = CL_key.lower()
        CL_key = p.sub('', CL_key)

        if 'québec' in CL_key:
            CL_key = unicode(CL_key, "UTF-8")
        else:
            CL_key = unicode(CL_key, errors='ignore')

        if isinstance(SRCH_key, unicode):
            if SRCH_key == CL_key:
                return value
        elif unicode(SRCH_key,'UTF-8') == CL_key:
            return value
    return None
# # Fetch the value of a controled list ( at the bottom )
# def fetchCLValue(SRCH_key, CL_array):
#     p = re.compile(' ')
#     SRCH_key = SRCH_key.lower()
#     SRCH_key = p.sub('', SRCH_key)
#     for CL_key, value in CL_array.items():
#         CL_key = CL_key.lower()
#         CL_key = p.sub('', CL_key)
#         CL_key = unicode(CL_key, errors='ignore')
#         if SRCH_key.decode('utf-8') == CL_key:
#             return value
#     return None
# Schema aware fetch for generic items
def fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref):
    if schema_ref['Value Type'] == 'value':
        tmp = fetchXMLValues(
            record,
            schema_ref["FGP XPATH"])
    elif schema_ref['Value Type'] == 'attribute':
        tmp = fetchXMLAttribute(
            record,
            schema_ref["FGP XPATH"],
            "codeListValue")
    else:
        reportError(
            HNAP_fileIdentifier, [
                schema_ref['CKAN API property'],
                'FETCH on undefined Value Type',
                schema_ref['CKAN API property'] + ':' + schema_ref['Value Type']
            ])
        return False

    if schema_ref['Requirement'] == 'M':

        if not sanityMandatory(
                HNAP_fileIdentifier, [
                    schema_ref['CKAN API property']
                ],
                tmp
        ):
            return False
    if schema_ref['Occurrences'] == 'S':
        if not sanitySingle(
                HNAP_fileIdentifier, [
                    schema_ref['CKAN API property']
                ],
                tmp
        ):
            return False
        else:
            return sanityFirst(tmp)

    return tmp


##################################################
# External validators
# canada_tags(value)

# Unceremoniously appropriated/repurposed from Ian Ward's change to CKAN and
# clubbed into a shape I can use here.
# https://github.com/open-data/ckanext-canada/commit/711236e39922d167991dc56a06e53f8328b11c4c
# I should pull these tests in from CKAN but we don't have time to do the smart
# thing quite yet.  Eventually I'll collect these errors from my attempt to
# upload them to CKAN to keep up to date.  This happens when we generate system
# level documentation to match.
def canada_tags(value):
    """
    Accept
    - unicode graphical (printable) characters
    - single internal spaces (no double-spaces)

    Reject
    - commas
    - tags that are too short or too long

    Strip
    - spaces at beginning and end
    """
    value = value.strip()
    lenght = len(value)
    if len(value) <= MIN_TAG_LENGTH:
        return u'Tag "%s" length is less than minimum %s' % (value, MIN_TAG_LENGTH)
    if len(value) > MAX_TAG_LENGTH:
        return u'Tag "%s" length is more than maximum %i' % (value, MAX_TAG_LENGTH)
    if u',' in value:
        return u'Tag "%s" may not contain commas' % (value)
    if u'  ' in value:
        return u'Tag "%s" may not contain consecutive spaces' % (value)

    caution = re.sub(ur'[\w ]*', u'', value)
    for ch in caution:
        category = unicodedata.category(ch)
        if category.startswith('C'):
            return u'Tag "%s" may not contain unprintable character U+%04x' % (value, ord(ch))
        if category.startswith('Z'):
            return u'Tag "%s" may not contain separator charater U+%04x' % (value, ord(ch))

    return ''


##################################################
# FGP specific Controled lists
#
# Citation-Role
# IC_90
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_90
# napCI_RoleCode {}
#
# Status
# IC_106
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_106
# napMD_ProgressCode
#
# Association Type
# IC_92
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_92
# napDS_AssociationTypeCode
#
# spatialRespresentionType
# IC_109
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_109
# napMD_SpatialRepresentationTypeCode
#
# maintenanceAndUpdateFrequency
# IC_102
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_102
# napMD_MaintenanceFrequencyCode
#
# presentationForm
# IC_89
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_89
# presentationForm
#
# Mapping to CKAN required values
# napMD_MaintenanceFrequencyCode
# napMD_KeywordTypeCode
#
# GC_Registry_of_Applied_Terms {}
# OGP_catalogueType


# Citation-Role
# IC_90    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_90
napCI_RoleCode = {
    'RI_408': [u'resource_provider', u'resourceProvider', u'fournisseurRessource'],
    'RI_409': [u'custodian', u'custodian', u'conservateur'],
    'RI_410': [u'owner', u'owner', u'propriétaire'],
    'RI_411': [u'user', u'user', u'utilisateur'],
    'RI_412': [u'distributor', u'distributor', u'distributeur'],
    'RI_413': [u'originator', u'originator', u'créateur'],
    'RI_414': [u'point_of_contact', u'pointOfContact', u'contact'],
    'RI_415': [u'principal_investigator', u'principalInvestigator', u'chercheurPrincipal'],
    'RI_416': [u'processor', u'processor', u'traiteur'],
    'RI_417': [u'publisher', u'publisher', u'éditeur'],
    'RI_418': [u'author', u'author', u'auteur'],
    'RI_419': [u'collaborator', u'collaborator', u'collaborateur'],
    'RI_420': [u'editor', u'editor', u'réviseur'],
    'RI_421': [u'mediator', u'mediator', u'médiateur'],
    'RI_422': [u'rights_holder', u'rightsHolder', u'détenteurDroits']
}

# Status
# IC_106    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_106
napMD_ProgressCode = {
    'RI_593': [u'completed', u'completed', u'complété'],
    'RI_594': [u'historical_archive', u'historicalArchive', u'archiveHistorique'],
    'RI_595': [u'obsolete', u'obsolete', u'périmé'],
    'RI_596': [u'ongoing', u'onGoing', u'enContinue'],
    'RI_597': [u'planned', u'planned', u'planifié'],
    'RI_598': [u'required', u'required', u'requis'],
    'RI_599': [u'under_development', u'underDevelopment', u'enProduction'],
    'RI_600': [u'proposed', u'proposed', u'proposé']
}

# Association Type
# IC_92    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_92
napDS_AssociationTypeCode = {
    'RI_428': [u'crossReference', u'référenceCroisée', u'cross_reference'],
    'RI_429': [u'largerWorkCitation', u'référenceGénérique', u'larger_work_citation'],
    'RI_430': [u'partOfSeamlessDatabase', u'partieDeBaseDeDonnéesContinue', u'part_of_seamless_database'],
    'RI_431': [u'source', u'source', u'source'],
    'RI_432': [u'stereoMate', u'stéréoAssociée', u'stereo_mate'],
    'RI_433': [u'isComposedOf', u'estComposéDe', u'is_composed_of']
}

# spatialRespresentionType
# IC_109    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_109
napMD_SpatialRepresentationTypeCode = {
    'RI_635': [u'vector', u'vector', u'vecteur'],
    'RI_636': [u'grid', u'grid', u'grille'],
    'RI_637': [u'text_table', u'textTable', u'texteTable'],
    'RI_638': [u'tin', u'tin', u'tin'],
    'RI_639': [u'stereo_model', u'stereoModel', u'stéréomodèle'],
    'RI_640': [u'video', u'vidéo']
}

# maintenanceAndUpdateFrequency
# IC_102    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_102
napMD_MaintenanceFrequencyCode = {
    'RI_532': [u'continual', u'continue', u'continual'],
    'RI_533': [u'daily', u'quotidien', u'P1D'],
    'RI_534': [u'weekly', u'hebdomadaire', u'P1W'],
    'RI_535': [u'fortnightly', u'quinzomadaire', u'P2W'],
    'RI_536': [u'monthly', u'mensuel', u'P1M'],
    'RI_537': [u'quarterly', u'trimestriel', u'P3M'],
    'RI_538': [u'biannually', u'semestriel', u'P6M'],
    'RI_539': [u'annually', u'annuel', u'P1Y'],
    'RI_540': [u'asNeeded', u'auBesoin', u'as_needed'],
    'RI_541': [u'irregular', u'irrégulier', u'irregular'],
    'RI_542': [u'notPlanned', u'nonPlanifié', u'not_planned'],
    'RI_543': [u'unknown', u'inconnu', u'unknown'],
    'RI_544': [u'semimonthly', u'bimensuel', u'P2M'],
}

# # In the mapping doc but not used
# presentationForm
# IC_89    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_89
# presentationForm = {
#    'RI_387'    : [u'documentDigital',            u'documentNumérique'],
#    'RI_388'    : [u'documentHardcopy',            u'documentPapier'],
#    'RI_389'    : [u'imageDigital',                u'imageNumérique'],
#    'RI_390'    : [u'imageHardcopy',                u'imagePapier'],
#    'RI_391'    : [u'mapDigital',                u'carteNumérique'],
#    'RI_392'    : [u'mapHardcopy',                u'cartePapier'],
#    'RI_393'    : [u'modelDigital',                u'modèleNumérique'],
#    'RI_394'    : [u'modelHardcopy',                u'maquette'],
#    'RI_395'    : [u'profileDigital',            u'profilNumérique'],
#    'RI_396'    : [u'profileHardcopy',            u'profilPapier'],
#    'RI_397'    : [u'tableDigital',                u'tableNumérique'],
#    'RI_398'    : [u'tableHardcopy',                u'tablePapier'],
#    'RI_399'    : [u'videoDigital',                u'vidéoNumérique'],
#    'RI_400'    : [u'videoHardcopy',                u'vidéoFilm'],
#    'RI_401'    : [u'audioDigital',                u'audioNumérique'],
#    'RI_402'    : [u'audioHardcopy',                u'audioAnalogique'],
#    'RI_403'    : [u'multimediaDigital',            u'multimédiaNumérique'],
#    'RI_404'    : [u'multimediaHardcopy',        u'multimédiaAnalogique'],
#    'RI_405'    : [u'diagramDigital',            u'diagrammeNumérique'],
#    'RI_406'    : [u'diagramHardcopy',            u'diagrammePapier']
# }

napMD_KeywordTypeCode = {
    'farming': [u'farming', u'Farming', u'Agriculture'],
    'biota': [u'biota', u'Biota', u'Biote'],
    'boundaries': [u'boundaries', u'Boundaries', u'Frontières'],
    'climatologyMeteorologyAtmosphere': [u'climatology_meterology_atmosphere',
                                         u'Climatology / Meteorology / Atmosphere',
                                         u'Climatologie / Météorologie / Atmosphère'],
    'economy': [u'economy', u'Economy', u'Économie'],
    'elevation': [u'elevation', u'Elevation', u'Élévation'],
    'environment': [u'environment', u'Environment', u'Environnement'],
    'geoscientificInformation': [u'geoscientific_information', u'Geoscientific Information',
                                 u'Information géoscientifique'],
    'health': [u'health', u'Health', u'Santé'],
    'imageryBaseMapsEarthCover': [u'imagery_base_maps_earth_cover', u'Imagery Base Maps Earth Cover',
                                  u'Imagerie carte de base couverture terrestre'],
    'intelligenceMilitary': [u'intelligence_military', u'Intelligence Military', u'Renseignements militaires'],
    'inlandWaters': [u'inland_waters', u'Inland Waters', u'Eaux intérieures'],
    'location': [u'location', u'Location', u'Localisation'],
    'oceans': [u'oceans', u'Oceans', u'Océans'],
    'planningCadastre': [u'planning_cadastre', u'Planning Cadastre', u'Aménagement cadastre'],
    'society': [u'society', u'Society', u'Société'],
    'structure': [u'structure', u'Structure', u'Structures'],
    'transportation': [u'transport', u'Transportation', u'Transport'],
    'utilitiesCommunication': [u'utilities_communication', u'Utilities Communication', u'Services communication'],
    # French Equivalents
    'agriculture': [u'farming', u'Farming', u'Agriculture'],
    'biote': [u'biota', u'Biota', u'Biote'],
    'frontières': [u'boundaries', u'Boundaries', u'Frontières'],
    'limatologieMétéorologieAtmosphère': [u'climatology_meterology_atmosphere',
                                          u'Climatology / Meteorology / Atmosphere',
                                          u'Climatologie / Météorologie / Atmosphère'],
    'économie': [u'economy', u'Economy', u'Économie'],
    'élévation': [u'elevation', u'Elevation', u'Élévation'],
    'environnement': [u'environment', u'Environment', u'Environnement'],
    'informationGéoscientifique': [u'geoscientific_information', u'Geoscientific Information',
                                   u'Information géoscientifique'],
    'santé': [u'health', u'Health', u'Santé'],
    'imagerieCarteDeBaseCouvertureTerrestre': [u'imagery_base_maps_earth_cover', u'Imagery Base Maps Earth Cover',
                                               u'Imagerie carte de base couverture terrestre'],
    'renseignementsMilitaires': [u'intelligence_military', u'Intelligence Military', u'Renseignements militaires'],
    'eauxIntérieures': [u'inland_waters', u'Inland Waters', u'Eaux intérieures'],
    'localisation': [u'location', u'Location', u'Localisation'],
    'océans': [u'oceans', u'Oceans', u'Océans'],
    'aménagementCadastre': [u'planning_cadastre', u'Planning Cadastre', u'Aménagement cadastre'],
    'société': [u'society', u'Society', u'Société'],
    'structures': [u'structure', u'Structure', u'Structures'],
    'transport': [u'transport', u'Transportation', u'Transport'],
    'servicesCommunication': [u'utilities_communication', u'Utilities Communication', u'Services communication']
}

GC_Registry_of_Organization_en = ["^Government of Canada;", "^Government of Alberta;",
                                "^Government of British Columbia;", "^Government of New Brunswick;",
                                "^Government of Quebec;", "^Government of Yukon;",
                                "^Government and Municipalities of Québec;",
                                "^Government and Municipalities of Quebec;",
                                "^Québec Government and Municipalities;",
                                "^Quebec Government and Municipalities;",
                                "^Government of Ontario", "^Government of Nova Scotia",
                                "^Government of Manitoba", "^Government of Newfoundland and Labrador",
                                "^Government of Saskatchewan", "^Government of Northwest Territories",
                                "^Government of Nunavut", "^Government of Prince Edward Island"                                
                                ]

GC_Registry_of_Organization_fr = ["^Gouvernement du Canada;", "^Gouvernement de l\\'Alberta;",
                                "^Gouvernement de la Colombie-Britannique;", "^Gouvernement du Nouveau-Brunswick;",
                                "^Gouvernement du Québec;", "^Gouvernement du Yukon;",
                                "^Gouvernement et Municipalités du Québec;",
                                "^Gouvernement de l\\'Ontario", "^Gouvernement de la Nouvelle-Ecosse",
                                "^Gouvernement du Manitoba", "^Gouvernement de Terre-Neuve et Labrador",
                                "^Gouvernement de la Saskatchewan", "^Gouvernement Des Territoires du Nord-Ouest",
                                "^Gouvernement du Nunavut", "^Gouvernement de l'Île-du-Prince-Edouard"]

GC_Registry_of_Applied_Terms = {
    'Government of Canada; Canadian Intergovernmental Conference Secretariat': [u'Canadian Intergovernmental Conference Secretariat', u'CICS', u'Secr\xe9tariat des conf\xe9rences intergouvernementales canadiennes', u'SCIC', u'274'],
    'Government of Canada; Tribunal d\'appel des transports du Canada': [u'Transportation Appeal Tribunal of Canada', u'TATC', u"Tribunal d'appel des transports du Canada", u'TATC', u'96'],
    'Government of Canada; Travaux publics et Services gouvernementaux Canada': [u'Public Works and Government Services Canada', u'PWGSC', u'Travaux publics et Services gouvernementaux Canada', u'TPSGC', u'81'],
    'Government of Canada; Commission des champs de bataille nationaux': [u'The National Battlefields Commission', u'NBC', u'Commission des champs de bataille nationaux', u'CCBN', u'262'],
    'Government of Canada; Copyright Board Canada': [u'Copyright Board Canada', u'CB', u"Commission du droit d'auteur Canada", u'CDA', u'116'],
    'Government of Canada; Office of the Commissioner of Lobbying of Canada': [u'Office of the Commissioner of Lobbying of Canada', u'OCL', u'Commissariat au lobbying du Canada', u'CAL', u'205'],
    'Government of Canada; S\xc3\xa9curit\xc3\xa9 publique Canada': [u'Public Safety Canada', u'PS', u'S\xe9curit\xe9 publique Canada', u'SP', u'214'],
    'Government of Canada; L\'Enqu\xc3\xaateur correctionnel Canada': [u'The Correctional Investigator Canada', u'OCI', u"L'Enqu\xeateur correctionnel Canada", u'BEC', u'5555'],
    'Government of Canada; Secr\xc3\xa9tariat du Conseil du Tr\xc3\xa9sor du Canada': [u'Treasury Board of Canada Secretariat', u'TBS', u'Secr\xe9tariat du Conseil du Tr\xe9sor du Canada', u'SCT', u'139'],
    'Government of Canada; Canada Development Investment Corporation': [u'Canada Development Investment Corporation', u'CDEV', u'Corporation de d\xe9veloppement des investissements du Canada', u'CDEV', u'148'],
    'Government of Canada; Immigration, Refugees and Citizenship Canada': [u'Citizenship and Immigration Canada', u'CIC', u'Citoyennet\xe9 et Immigration Canada', u'CIC', u'94'],
    'Government of Canada; Economic Development Agency of Canada for the Regions of Quebec': [u'Economic Development Agency of Canada for the Regions of Quebec', u'CED', u'Agence de d\xe9veloppement \xe9conomique du Canada pour les r\xe9gions du Qu\xe9bec', u'DEC', u'93'],
    'Government of Canada; The National Battlefields Commission': [u'The National Battlefields Commission', u'NBC', u'Commission des champs de bataille nationaux', u'CCBN', u'262'],
    'Government of Canada; Science and Engineering Research Canada': [u'Science and Engineering Research Canada', u'SERC', u'Recherches en sciences et en g\xe9nie Canada', u'RSGC', u'110'],
    'Government of Canada; Patented Medicine Prices Review Board Canada': [u'Patented Medicine Prices Review Board Canada', u'', u"Conseil d'examen du prix des m\xe9dicaments brevet\xe9s Canada", u'', u'15'],
    'Government of Canada; Innovation, Science and Economic Development Canada': [u'Industry Canada', u'IC', u'Industrie Canada', u'IC', u'230'],
    'Government of Canada; Tribunal de la dotation de la fonction publique': [u'Public Service Staffing Tribunal', u'PSST', u'Tribunal de la dotation de la fonction publique', u'TDFP', u'266'],
    'Government of Canada; \xc3\x89lections Canada': [u'Elections Canada', u'elections', u'\xc9lections Canada', u'elections', u'285'],
    'Government of Canada; Treasury Board of Canada Secretariat': [u'Treasury Board of Canada Secretariat', u'TBS', u'Secr\xe9tariat du Conseil du Tr\xe9sor du Canada', u'SCT', u'139'],
    "Government of Canada; Office de commercialisation du poisson d'eau douce": [u'Freshwater Fish Marketing Corporation', u'FFMC', u"Office de commercialisation du poisson d'eau douce", u'OCPED', u'252'],
    'Government of Canada; Public Service Labour Relations Board': [u'Public Service Labour Relations Board', u'PSLRB', u'Commission des relations de travail dans la fonction publique', u'CRTFP', u'102'],
    'Government of Canada; Commission du droit du Canada': [u'Law Commission of Canada', u'', u'Commission du droit du Canada', u'', u'231'],
    'Government of Canada; Infrastructure Canada': [u'Infrastructure Canada', u'INFC', u'Infrastructure Canada', u'INFC', u'278'],
    'Government of Canada; Conseil des produits agricoles du Canada': [u'Farm Products Council of Canada', u'FPCC', u'Conseil des produits agricoles du Canada', u'CPAC', u'200'],
    'Government of Canada; Environnement et Changement climatique Canada': [u'Environment Canada', u'EC', u'Environnement Canada', u'EC', u'99'],
    'Government of Canada; National Energy Board': [u'National Energy Board', u'NEB', u"Office national de l'\xe9nergie", u'ONE', u'239'],
    'Government of Canada; Office of the Chief Electoral Officer': [u'Office of the Chief Electoral Officer', u'elections', u'Bureau du directeur g\xe9n\xe9ral des \xe9lections', u'elections', u'---'],
    'Government of Canada; Services partag\xc3\xa9s Canada': [u'Shared Services Canada', u'SSC', u'Services partag\xe9s Canada', u'SPC', u'92'],
    'Government of Canada; Corporation de d\xc3\xa9veloppement des investissements du Canada': [u'Canada Development Investment Corporation', u'CDEV', u'Corporation de d\xe9veloppement des investissements du Canada', u'CDEV', u'148'],
    'Government of Canada; National Gallery of Canada': [u'National Gallery of Canada', u'NGC', u'Mus\xe9e des beaux-arts du Canada', u'MBAC', u'59'],
    'Government of Canada; Conseil national de recherches Canada': [u'National Research Council Canada', u'NRC', u'Conseil national de recherches Canada', u'CNRC', u'172'],
    'Government of Canada; Canadian Museum of History': [u'Canadian Museum of History', u'CMH', u"Mus\xe9e canadien de l'histoire", u'MCH', u'263'],
    'Government of Canada; Tribunal canadien du commerce ext\xc3\xa9rieur': [u'Canadian International Trade Tribunal', u'CITT', u'Tribunal canadien du commerce ext\xe9rieur', u'TCCE', u'175'],
    'Government of Canada; Military Police Complaints Commission of Canada': [u'Military Police Complaints Commission of Canada', u'MPCC', u"Commission d'examen des plaintes concernant la police militaire du Canada", u'CPPM', u'66'],
    'Government of Canada; Minist\xc3\xa8re des Finances Canada': [u'Department of Finance Canada', u'FIN', u'Minist\xe8re des Finances Canada', u'FIN', u'157'],
    'Government of Canada; Administration de pilotage des Grands Lacs Canada': [u'Great Lakes Pilotage Authority Canada', u'GLPA', u'Administration de pilotage des Grands Lacs Canada', u'APGL', u'261'],
    'Government of Canada; Atlantic Canada Opportunities Agency': [u'Atlantic Canada Opportunities Agency', u'ACOA', u'Agence de promotion \xe9conomique du Canada atlantique', u'APECA', u'276'],
    'Government of Canada; Canadian Centre for Occupational Health and Safety': [u'Canadian Centre for Occupational Health and Safety', u'CCOHS', u"Centre canadien d'hygi\xe8ne et de s\xe9curit\xe9 au travail", u'CCHST', u'35'],
    'Government of Canada; Canada Mortgage and Housing Corporation': [u'Canada Mortgage and Housing Corporation', u'CMHC', u"Soci\xe9t\xe9 canadienne d'hypoth\xe8ques et de logement", u'SCHL', u'87'],
    'Government of Canada; Mus\xc3\xa9e des sciences et de la technologie du Canada': [u'Canada Science and Technology Museum', u'CSTM', u'Mus\xe9e des sciences et de la technologie du Canada', u'MSTC', u'202'],
    'Government of Canada; Services publics et Approvisionnement Canada': [u'Public Works and Government Services Canada', u'PWGSC', u'Travaux publics et Services gouvernementaux Canada', u'TPSGC', u'81'],
    'Government of Canada; Northern Pipeline Agency Canada': [u'Northern Pipeline Agency Canada', u'NPA', u'Administration du pipe-line du Nord Canada', u'APN', u'10'],
    'Government of Canada; Canadian Polar Commission': [u'Canadian Polar Commission', u'POLAR', u'Commission canadienne des affaires polaires', u'POLAIRE', u'143'],
    'Government of Canada; Civilian Review and Complaints Commission for the RCMP': [u'Civilian Review and Complaints Commission for the RCMP', u'CRCC', u'Commission civile d\u2019examen et de traitement des plaintes relatives \xe0 la GRC', u'CCETP', u'136'],
    'Government of Canada; Western Economic Diversification Canada': [u'Western Economic Diversification Canada', u'WD', u"Diversification de l'\xe9conomie de l'Ouest Canada", u'DEO', u'55'],
    'Government of Canada; Soci\xc3\xa9t\xc3\xa9 des ponts f\xc3\xa9d\xc3\xa9raux': [u'Federal Bridge Corporation', u'FBCL', u'Soci\xe9t\xe9 des ponts f\xe9d\xe9raux', u'SPFL', u'254'],
    'Government of Canada; Emploi et D\xc3\xa9veloppement social Canada': [u'Employment and Social Development Canada', u'esdc', u'Emploi et D\xe9veloppement social Canada', u'edsc', u'141'],
    'Government of Canada; Administration du pipe-line du Nord Canada': [u'Northern Pipeline Agency Canada', u'NPA', u'Administration du pipe-line du Nord Canada', u'APN', u'10'],
    'Government of Canada; Financial Transactions and Reports Analysis Centre of Canada': [u'Financial Transactions and Reports Analysis Centre of Canada', u'FINTRAC', u"Centre d'analyse des op\xe9rations et d\xe9clarations financi\xe8res du Canada", u'CANAFE', u'127'],
    "Government of Canada; Commission de l'immigration et du statut de r\xc3\xa9fugi\xc3\xa9 du Canada": [u'Immigration and Refugee Board of Canada', u'IRB', u"Commission de l'immigration et du statut de r\xe9fugi\xe9 du Canada", u'CISR', u'5'],
    'Government of Canada; Commissariat aux langues officielles': [u'Office of the Commissioner of Official Languages', u'OCOL', u'Commissariat aux langues officielles', u'CLO', u'258'],
    "Government of Canada; Commission de l'assurance-emploi du Canada": [u'Canada Employment Insurance Commission', u'CEIC', u"Commission de l'assurance-emploi du Canada", u'CAEC', u'196'],
    'Government of Canada; Commission canadienne de s\xc3\xbbret\xc3\xa9 nucl\xc3\xa9aire': [u'Canadian Nuclear Safety Commission', u'CNSC', u'Commission canadienne de s\xfbret\xe9 nucl\xe9aire', u'CCSN', u'58'],
    'Government of Canada; Agriculture and Agri-Food Canada': [u'Agriculture and Agri-Food Canada', u'AAFC', u'Agriculture et Agroalimentaire Canada', u'AAC', u'235'],
    'Government of Canada; Royal Canadian Mounted Police': [u'Royal Canadian Mounted Police', u'RCMP', u'Gendarmerie royale du Canada', u'GRC', u'131'],
    "Government of Canada; Centre d'analyse des op\xc3\xa9rations et d\xc3\xa9clarations financi\xc3\xa8res du Canada": [u'Financial Transactions and Reports Analysis Centre of Canada', u'FINTRAC', u"Centre d'analyse des op\xe9rations et d\xe9clarations financi\xe8res du Canada", u'CANAFE', u'127'],
    "Government of Canada; Conseil d'examen du prix des m\xc3\xa9dicaments brevet\xc3\xa9s Canada": [u'Patented Medicine Prices Review Board Canada', u'', u"Conseil d'examen du prix des m\xe9dicaments brevet\xe9s Canada", u'', u'15'],
    'Government of Canada; Canadian International Trade Tribunal': [u'Canadian International Trade Tribunal', u'CITT', u'Tribunal canadien du commerce ext\xe9rieur', u'TCCE', u'175'],
    'Government of Canada; Conseil canadien des relations industrielles': [u'Canada Industrial Relations Board', u'CIRB', u'Conseil canadien des relations industrielles', u'CCRI', u'188'],
    'Government of Canada; Innovation, Sciences et D\xc3\xa9veloppement \xc3\xa9conomique Canada': [u'Industry Canada', u'IC', u'Industrie Canada', u'IC', u'230'],
    'Government of Canada; Marine Atlantic Inc.': [u'Marine Atlantic Inc.', u'', u'Marine Atlantique S.C.C.', u'', u'238'],
    'Government of Canada; Laurentian Pilotage Authority Canada': [u'Laurentian Pilotage Authority Canada', u'LPA', u'Administration de pilotage des Laurentides Canada', u'APL', u'213'],
    'Government of Canada; Freshwater Fish Marketing Corporation': [u'Freshwater Fish Marketing Corporation', u'FFMC', u"Office de commercialisation du poisson d'eau douce", u'OCPED', u'252'],
    'Government of Canada; Bureau du secr\xc3\xa9taire du gouverneur g\xc3\xa9n\xc3\xa9ral': [u'Office of the Secretary to the Governor General', u'OSGG', u'Bureau du secr\xe9taire du gouverneur g\xe9n\xe9ral', u'BSGG', u'5557'],
    'Government of Canada; Affaires \xc3\xa9trang\xc3\xa8res et Commerce international Canada': [u'Foreign Affairs and International Trade Canada', u'DFAIT', u'Affaires \xe9trang\xe8res et Commerce international Canada', u'MAECI', u'64'],
    'Government of Canada; Canada Post': [u'Canada Post', u'CPC', u'Postes Canada', u'SCP', u'83'],
    'Government of Canada; Affaires mondiales Canada': [u'Foreign Affairs and International Trade Canada', u'DFAIT', u'Affaires \xe9trang\xe8res et Commerce international Canada', u'MAECI', u'64'],
    'Government of Canada; Soci\xc3\xa9t\xc3\xa9 immobili\xc3\xa8re du Canada Limit\xc3\xa9e': [u'Canada Lands Company Limited', u'', u'Soci\xe9t\xe9 immobili\xe8re du Canada Limit\xe9e', u'', u'82'],
    'Government of Canada; Bureau du v\xc3\xa9rificateur g\xc3\xa9n\xc3\xa9ral du Canada': [u'Office of the Auditor General of Canada', u'OAG', u'Bureau du v\xe9rificateur g\xe9n\xe9ral du Canada', u'BVG', u'125'],
    'Government of Canada; Commission canadienne des affaires polaires': [u'Canadian Polar Commission', u'POLAR', u'Commission canadienne des affaires polaires', u'POLAIRE', u'143'],
    'Government of Canada; Shared Services Canada': [u'Shared Services Canada', u'SSC', u'Services partag\xe9s Canada', u'SPC', u'92'],
    'Government of Canada; Canada School of Public Service': [u'Canada School of Public Service', u'CSPS', u'\xc9cole de la fonction publique du Canada', u'EFPC', u'73'],
    'Government of Canada; Canadian Radio-television and Telecommunications Commission': [u'Canadian Radio-television and Telecommunications Commission', u'CRTC', u'Conseil de la radiodiffusion et des t\xe9l\xe9communications canadiennes', u'CRTC', u'126'],
    'Government of Canada; Federal Bridge Corporation': [u'Federal Bridge Corporation', u'FBCL', u'Soci\xe9t\xe9 des ponts f\xe9d\xe9raux', u'SPFL', u'254'],
    'Government of Canada; Elections Canada': [u'Elections Canada', u'elections', u'\xc9lections Canada', u'elections', u'285'],
    'Government of Canada; Commission civile d\xe2\x80\x99examen et de traitement des plaintes relatives \xc3\xa0 la GRC': [u'Civilian Review and Complaints Commission for the RCMP', u'CRCC', u'Commission civile d\u2019examen et de traitement des plaintes relatives \xe0 la GRC', u'CCETP', u'136'],
    'Government of Canada; Canada Lands Company Limited': [u'Canada Lands Company Limited', u'', u'Soci\xe9t\xe9 immobili\xe8re du Canada Limit\xe9e', u'', u'82'],
    'Government of Canada; Mus\xc3\xa9e canadien pour les droits de la personne': [u'Canadian Museum for Human Rights', u'CMHR', u'Mus\xe9e canadien pour les droits de la personne', u'MCDP', u'267'],
    'Government of Canada; Patrimoine canadien': [u'Canadian Heritage', u'PCH', u'Patrimoine canadien', u'PCH', u'16'],
    'Government of Canada; Correctional Service of Canada': [u'Correctional Service of Canada', u'CSC', u'Service correctionnel du Canada', u'SCC', u'193'],
    'Government of Canada; Canadian Grain Commission': [u'Canadian Grain Commission', u'CGC', u'Commission canadienne des grains', u'CCG', u'169'],
    'Government of Canada; National Capital Commission': [u'National Capital Commission', u'NCC', u'Commission de la capitale nationale', u'CCN', u'22'],
    'Government of Canada; Canada Emission Reduction Incentives Agency': [u'Canada Emission Reduction Incentives Agency', u'', u"Agence canadienne pour l'incitation \xe0 la r\xe9duction des \xe9missions", u'', u'277'],
    'Government of Canada; Agriculture et Agroalimentaire Canada': [u'Agriculture and Agri-Food Canada', u'AAFC', u'Agriculture et Agroalimentaire Canada', u'AAC', u'235'],
    "Government of Canada; Office national de l'\xc3\xa9nergie": [u'National Energy Board', u'NEB', u"Office national de l'\xe9nergie", u'ONE', u'239'],
    'Government of Canada; Agence des services frontaliers du Canada': [u'Canada Border Services Agency', u'CBSA', u'Agence des services frontaliers du Canada', u'ASFC', u'229'],
    'Government of Canada; Canadian Institutes of Health Research': [u'Canadian Institutes of Health Research', u'CIHR', u'Instituts de recherche en sant\xe9 du Canada', u'IRSC', u'236'],
    'Government of Canada; Citoyennet\xc3\xa9 et Immigration Canada': [u'Citizenship and Immigration Canada', u'CIC', u'Citoyennet\xe9 et Immigration Canada', u'CIC', u'94'],
    'Government of Canada; Agence de la sant\xc3\xa9 publique du Canada': [u'Public Health Agency of Canada', u'PHAC', u'Agence de la sant\xe9 publique du Canada', u'ASPC', u'135'],
    "Government of Canada; Soci\xc3\xa9t\xc3\xa9 d'expansion du Cap-Breton": [u'Enterprise Cape Breton Corporation', u'', u"Soci\xe9t\xe9 d'expansion du Cap-Breton", u'', u'203'],
    'Government of Canada; Transports Canada': [u'Transport Canada', u'TC', u'Transports Canada', u'TC', u'217'],
    'Government of Canada; Sant\xc3\xa9 Canada': [u'Health Canada', u'HC', u'Sant\xe9 Canada', u'SC', u'271'],
    'Government of Canada; Service des poursuites p\xc3\xa9nales du Canada': [u'Public Prosecution Service of Canada', u'PPSC', u'Service des poursuites p\xe9nales du Canada', u'SPPC', u'98'],
    'Government of Canada; Canadian Nuclear Safety Commission': [u'Canadian Nuclear Safety Commission', u'CNSC', u'Commission canadienne de s\xfbret\xe9 nucl\xe9aire', u'CCSN', u'58'],
    'Government of Canada; Communications Security Establishment Canada': [u'Communications Security Establishment Canada', u'CSEC', u'Centre de la s\xe9curit\xe9 des t\xe9l\xe9communications Canada', u'CSTC', u'156'],
    'Government of Canada; Canadian Northern Economic Development Agency': [u'Canadian Northern Economic Development Agency', u'CanNor', u'Agence canadienne de d\xe9veloppement \xe9conomique du Nord', u'CanNor', u'4'],
    'Government of Canada; Commission canadienne des grains': [u'Canadian Grain Commission', u'CGC', u'Commission canadienne des grains', u'CCG', u'169'],
    'Government of Canada; Great Lakes Pilotage Authority Canada': [u'Great Lakes Pilotage Authority Canada', u'GLPA', u'Administration de pilotage des Grands Lacs Canada', u'APGL', u'261'],
    "Government of Canada; Registraire de la Cour supr\xc3\xaame du Canada et le secteur de l'administration publique f\xc3\xa9d\xc3\xa9rale nomm\xc3\xa9 en vertu du paragraphe 12(2) de la Loi sur la Cour supr\xc3\xaame": [u'Registrar of the Supreme Court of Canada and that portion of the federal public administration appointed under subsection 12(2) of the Supreme Court Act', u'SCC', u"Registraire de la Cour supr\xeame du Canada et le secteur de l'administration publique f\xe9d\xe9rale nomm\xe9 en vertu du paragraphe 12(2) de la Loi sur la Cour supr\xeame", u'CSC', u'63'],
    'Government of Canada; Recherches en sciences et en g\xc3\xa9nie Canada': [u'Science and Engineering Research Canada', u'SERC', u'Recherches en sciences et en g\xe9nie Canada', u'RSGC', u'110'],
    'Government of Canada; Les Ponts Jacques-Cartier et Champlain Incorpor\xc3\xa9e': [u'Jacques Cartier and Champlain Bridges Incorporated', u'JCCBI', u'Les Ponts Jacques-Cartier et Champlain Incorpor\xe9e', u'PJCCI', u'55559'],
    'Government of Canada; Registry of the Competition Tribunal': [u'Registry of the Competition Tribunal', u'RCT', u'Greffe du Tribunal de la concurrence', u'GTC', u'89'],
    "Government of Canada; Comit\xc3\xa9 externe d'examen des griefs militaires": [u'Military Grievances External Review Committee', u'MGERC', u"Comit\xe9 externe d'examen des griefs militaires", u'CEEGM', u'43'],
    'Government of Canada; Canada Border Services Agency': [u'Canada Border Services Agency', u'CBSA', u'Agence des services frontaliers du Canada', u'ASFC', u'229'],
    "Government of Canada; Agence canadienne d'\xc3\xa9valuation environnementale": [u'Canadian Environmental Assessment Agency', u'CEAA', u"Agence canadienne d'\xe9valuation environnementale", u'ACEE', u'270'],
    'Government of Canada; Administration de pilotage du Pacifique Canada': [u'Pacific Pilotage Authority Canada', u'PPA', u'Administration de pilotage du Pacifique Canada', u'APP', u'165'],
    'Government of Canada; Commission de la capitale nationale': [u'National Capital Commission', u'NCC', u'Commission de la capitale nationale', u'CCN', u'22'],
    'Government of Canada; Statistique Canada': [u'Statistics Canada', u'StatCan', u'Statistique Canada', u'StatCan', u'256'],
    'Government of Canada; Canadian Heritage': [u'Canadian Heritage', u'PCH', u'Patrimoine canadien', u'PCH', u'16'],
    'Government of Canada; Foreign Affairs and International Trade Canada': [u'Foreign Affairs and International Trade Canada', u'DFAIT', u'Affaires \xe9trang\xe8res et Commerce international Canada', u'MAECI', u'64'],
    'Government of Canada; Industrie Canada': [u'Industry Canada', u'IC', u'Industrie Canada', u'IC', u'230'],
    'Government of Canada; Minist\xc3\xa8re de la Justice Canada': [u'Department of Justice Canada', u'JUS', u'Minist\xe8re de la Justice Canada', u'JUS', u'119'],
    'Government of Canada; Commission des lib\xc3\xa9rations conditionnelles du Canada': [u'Parole Board of Canada', u'PBC', u'Commission des lib\xe9rations conditionnelles du Canada', u'CLCC', u'246'],
    'Government of Canada; Comit\xc3\xa9 de surveillance des activit\xc3\xa9s de renseignement de s\xc3\xa9curit\xc3\xa9': [u'Security Intelligence Review Committee', u'SIRC', u'Comit\xe9 de surveillance des activit\xe9s de renseignement de s\xe9curit\xe9', u'CSARS', u'109'],
    'Government of Canada; Relations Couronne-Autochtones et Affaires du Nord Canada': [u'Crown-Indigenous Relations and Northern Affairs Canada', u'AANDC', u'Relations Couronne-Autochtones et Affaires du Nord Canada', u'AADNC', u'249'],
    'Government of Canada; Environment Canada': [u'Environment Canada', u'EC', u'Environnement Canada', u'EC', u'99'],
    'Government of Canada; Public Safety Canada': [u'Public Safety Canada', u'PS', u'S\xe9curit\xe9 publique Canada', u'SP', u'214'],
    'Government of Canada; Destination Canada': [u'Destination Canada', u'  DC', u'Destination Canada', u'  DC', u'178'],
    'Government of Canada; Status of Women Canada': [u'Status of Women Canada', u'SWC', u'Condition f\xe9minine Canada', u'CFC', u'147'],
    'Government of Canada; Tribunal des anciens combattants (r\xc3\xa9vision et appel)': [u'Veterans Review and Appeal Board', u'VRAB', u'Tribunal des anciens combattants (r\xe9vision et appel)', u'TACRA', u'85'],
    'Government of Canada; Monnaie royale canadienne': [u'Royal Canadian Mint', u'', u'Monnaie royale canadienne', u'', u'18'],
    'Government of Canada; Marine Atlantique S.C.C.': [u'Marine Atlantic Inc.', u'', u'Marine Atlantique S.C.C.', u'', u'238'],
    'Government of Canada; Canada Revenue Agency': [u'Canada Revenue Agency', u'CRA', u'Agence du revenu du Canada', u'ARC', u'47'],
    'Government of Canada; Business Development Bank of Canada': [u'Business Development Bank of Canada', u'BDC', u'Banque de d\xe9veloppement du Canada', u'BDC', u'150'],
    'Government of Canada; Office national du film': [u'National Film Board', u'NFB', u'Office national du film', u'ONF', u'167'],
    'Government of Canada; Tribunal de la protection des fonctionnaires divulgateurs Canada': [u'Public Servants Disclosure Protection Tribunal Canada', u'PSDPTC', u'Tribunal de la protection des fonctionnaires divulgateurs Canada', u'TPFDC', u'40'],
    'Government of Canada; Social Sciences and Humanities Research Council of Canada': [u'Social Sciences and Humanities Research Council of Canada', u'SSHRC', u'Conseil de recherches en sciences humaines du Canada', u'CRSH', u'207'],
    'Government of Canada; Banque de d\xc3\xa9veloppement du Canada': [u'Business Development Bank of Canada', u'BDC', u'Banque de d\xe9veloppement du Canada', u'BDC', u'150'],
    'Government of Canada; Standards Council of Canada': [u'Standards Council of Canada', u'SCC-CCN', u'Conseil canadien des normes', u'SCC-CCN', u'107'],
    'Government of Canada; Tribunal des droits de la personne du Canada': [u'Human Rights Tribunal of Canada', u'HRTC', u'Tribunal des droits de la personne du Canada', u'TDPC', u'164'],
    'Government of Canada; National Research Council Canada': [u'National Research Council Canada', u'NRC', u'Conseil national de recherches Canada', u'CNRC', u'172'],
    'Government of Canada; Royal Canadian Mint': [u'Royal Canadian Mint', u'', u'Monnaie royale canadienne', u'', u'18'],
    'Government of Canada; Treasury Board': [u'Treasury Board', u'TB', u'Conseil du Tr\xe9sor', u'CT', u'105'],
    'Government of Canada; Fisheries and Oceans Canada': [u'Fisheries and Oceans Canada', u'DFO', u'P\xeaches et Oc\xe9ans Canada', u'MPO', u'253'],
    'Government of Canada; Condition f\xc3\xa9minine Canada': [u'Status of Women Canada', u'SWC', u'Condition f\xe9minine Canada', u'CFC', u'147'],
    'Government of Canada; Autorit\xc3\xa9 du pont Windsor-D\xc3\xa9troit': [u'Windsor-Detroit Bridge Authority', u'', u'Autorit\xe9 du pont Windsor-D\xe9troit', u'', u'55553'],
    'Government of Canada; Indigenous and Northern Affairs Canada': [u'Aboriginal Affairs and Northern Development Canada', u'AANDC', u'Affaires autochtones et D\xe9veloppement du Nord Canada', u'AADNC', u'249'],
    'Government of Canada; Law Commission of Canada': [u'Law Commission of Canada', u'', u'Commission du droit du Canada', u'', u'231'],
    "Government of Canada; Agence canadienne d'inspection des aliments": [u'Canadian Food Inspection Agency', u'CFIA', u"Agence canadienne d'inspection des aliments", u'ACIA', u'206'],
    'Government of Canada; Canada Employment Insurance Commission': [u'Canada Employment Insurance Commission', u'CEIC', u"Commission de l'assurance-emploi du Canada", u'CAEC', u'196'],
    'Government of Canada; Department of Justice Canada': [u'Department of Justice Canada', u'JUS', u'Minist\xe8re de la Justice Canada', u'JUS', u'119'],
    'Government of Canada; Immigration, R\xc3\xa9fugi\xc3\xa9s et Citoyennet\xc3\xa9 Canada': [u'Citizenship and Immigration Canada', u'CIC', u'Citoyennet\xe9 et Immigration Canada', u'CIC', u'94'],
    'Government of Canada; Agence spatiale canadienne': [u'Canadian Space Agency', u'CSA', u'Agence spatiale canadienne', u'ASC', u'3'],
    'Government of Canada; Canada Industrial Relations Board': [u'Canada Industrial Relations Board', u'CIRB', u'Conseil canadien des relations industrielles', u'CCRI', u'188'],
    'Government of Canada; Canadian Air Transport Security Authority': [u'Canadian Air Transport Security Authority', u'CATSA', u'Administration canadienne de la s\xfbret\xe9 du transport a\xe9rien', u'ACSTA', u'250'],
    'Government of Canada; Public Prosecution Service of Canada': [u'Public Prosecution Service of Canada', u'PPSC', u'Service des poursuites p\xe9nales du Canada', u'SPPC', u'98'],
    'Government of Canada; Public Works and Government Services Canada': [u'Public Works and Government Services Canada', u'PWGSC', u'Travaux publics et Services gouvernementaux Canada', u'TPSGC', u'81'],
    'Government of Canada; Canadian Environmental Assessment Agency': [u'Canadian Environmental Assessment Agency', u'CEAA', u"Agence canadienne d'\xe9valuation environnementale", u'ACEE', u'270'],
    'Government of Canada; Greffe du Tribunal de la concurrence': [u'Registry of the Competition Tribunal', u'RCT', u'Greffe du Tribunal de la concurrence', u'GTC', u'89'],
    'Government of Canada; Public Services and Procurement Canada': [u'Public Works and Government Services Canada', u'PWGSC', u'Travaux publics et Services gouvernementaux Canada', u'TPSGC', u'81'],
    'Government of Canada; Canadian Space Agency': [u'Canadian Space Agency', u'CSA', u'Agence spatiale canadienne', u'ASC', u'3'],
    'Government of Canada; Agence de d\xc3\xa9veloppement \xc3\xa9conomique du Canada pour les r\xc3\xa9gions du Qu\xc3\xa9bec': [u'Economic Development Agency of Canada for the Regions of Quebec', u'CED', u'Agence de d\xe9veloppement \xe9conomique du Canada pour les r\xe9gions du Qu\xe9bec', u'DEC', u'93'],
    'Government of Canada; \xc3\x89nergie atomique du Canada': [u'Limit\xe9e', u'Atomic Energy of Canada Limited', u'', u'\xc9nergie atomique du Canada', u'Limit\xe9e', u'', u'138'],
    'Government of Canada; Defence Construction Canada': [u'Defence Construction Canada', u'DCC', u'Construction de D\xe9fense Canada', u'CDC', u'28'],
    'Government of Canada; Agence de la consommation en mati\xc3\xa8re financi\xc3\xa8re du Canada': [u'Financial Consumer Agency of Canada', u'FCAC', u'Agence de la consommation en mati\xe8re financi\xe8re du Canada', u'ACFC', u'224'],
    'Government of Canada; Anciens Combattants Canada': [u'Veterans Affairs Canada', u'VAC', u'Anciens Combattants Canada', u'ACC', u'189'],
    'Government of Canada; Citizenship and Immigration Canada': [u'Citizenship and Immigration Canada', u'CIC', u'Citoyennet\xe9 et Immigration Canada', u'CIC', u'94'],
    'Government of Canada; Transportation Safety Board of Canada': [u'Transportation Safety Board of Canada', u'TSB', u'Bureau de la s\xe9curit\xe9 des transports du Canada', u'BST', u'215'],
    'Government of Canada; Parcs Canada': [u'Parks Canada', u'PC', u'Parcs Canada', u'PC', u'154'],
    "Government of Canada; Commission d'examen des plaintes concernant la police militaire du Canada": [u'Military Police Complaints Commission of Canada', u'MPCC', u"Commission d'examen des plaintes concernant la police militaire du Canada", u'CPPM', u'66'],
    'Government of Canada; Veterans Review and Appeal Board': [u'Veterans Review and Appeal Board', u'VRAB', u'Tribunal des anciens combattants (r\xe9vision et appel)', u'TACRA', u'85'],
    'Government of Canada; D\xc3\xa9fense nationale': [u'National Defence', u'DND', u'D\xe9fense nationale', u'MDN', u'32'],
    'Government of Canada; National Film Board': [u'National Film Board', u'NFB', u'Office national du film', u'ONF', u'167'],
    'Government of Canada; Secr\xc3\xa9tariat des conf\xc3\xa9rences intergouvernementales canadiennes': [u'Canadian Intergovernmental Conference Secretariat', u'CICS', u'Secr\xe9tariat des conf\xe9rences intergouvernementales canadiennes', u'SCIC', u'274'],
    'Government of Canada; Conseil canadien des normes': [u'Standards Council of Canada', u'SCC-CCN', u'Conseil canadien des normes', u'SCC-CCN', u'107'],
    'Government of Canada; Registrar of the Supreme Court of Canada and that portion of the federal public administration appointed under subsection 12(2) of the Supreme Court Act': [u'Registrar of the Supreme Court of Canada and that portion of the federal public administration appointed under subsection 12(2) of the Supreme Court Act', u'SCC', u"Registraire de la Cour supr\xeame du Canada et le secteur de l'administration publique f\xe9d\xe9rale nomm\xe9 en vertu du paragraphe 12(2) de la Loi sur la Cour supr\xeame", u'CSC', u'63'],
    "Government of Canada; Service canadien d'appui aux tribunaux administratifs": [u'Administrative Tribunals Support Service of Canada', u'ATSSC', u"Service canadien d'appui aux tribunaux administratifs", u'SCDATA', u'8888888'],
    'Government of Canada; Environment and Climate Change Canada': [u'Environment Canada', u'EC', u'Environnement Canada', u'EC', u'99'],
    "Government of Canada; Diversification de l'\xc3\xa9conomie de l'Ouest Canada": [u'Western Economic Diversification Canada', u'WD', u"Diversification de l'\xe9conomie de l'Ouest Canada", u'DEO', u'55'],
    'Government of Canada; Canadian Commercial Corporation': [u'Canadian Commercial Corporation', u'CCC', u'Corporation commerciale canadienne', u'CCC', u'34'],
    'Government of Canada; Administration canadienne de la s\xc3\xbbret\xc3\xa9 du transport a\xc3\xa9rien': [u'Canadian Air Transport Security Authority', u'CATSA', u'Administration canadienne de la s\xfbret\xe9 du transport a\xe9rien', u'ACSTA', u'250'],
    'Government of Canada; Parks Canada': [u'Parks Canada', u'PC', u'Parcs Canada', u'PC', u'154'],
    'Government of Canada; Office of the Public Sector Integrity Commissioner of Canada': [u'Office of the Public Sector Integrity Commissioner of Canada', u'PSIC', u"Commissariat \xe0 l'int\xe9grit\xe9 du secteur public du Canada", u'ISPC', u'210'],
    'Government of Canada; Privy Council Office': [u'Privy Council Office', u'', u'Bureau du Conseil priv\xe9', u'', u'173'],
    'Government of Canada; Bureau du commissaire du Centre de la s\xc3\xa9curit\xc3\xa9 des t\xc3\xa9l\xc3\xa9communications': [u'Office of the Communications Security Establishment Commissioner', u'OCSEC', u'Bureau du commissaire du Centre de la s\xe9curit\xe9 des t\xe9l\xe9communications', u'BCCST', u'279'],
    'Government of Canada; Aboriginal Affairs and Northern Development Canada': [u'Aboriginal Affairs and Northern Development Canada', u'AANDC', u'Affaires autochtones et D\xe9veloppement du Nord Canada', u'AADNC', u'249'],
    'Government of Canada; Gendarmerie royale du Canada': [u'Royal Canadian Mounted Police', u'RCMP', u'Gendarmerie royale du Canada', u'GRC', u'131'],
    'Government of Canada; Transport Canada': [u'Transport Canada', u'TC', u'Transports Canada', u'TC', u'217'],
    'Government of Canada; Environnement Canada': [u'Environment Canada', u'EC', u'Environnement Canada', u'EC', u'99'],
    'Government of Canada; Public Health Agency of Canada': [u'Public Health Agency of Canada', u'PHAC', u'Agence de la sant\xe9 publique du Canada', u'ASPC', u'135'],
    'Government of Canada; Public Service Commission of Canada': [u'Public Service Commission of Canada', u'PSC', u'Commission de la fonction publique du Canada', u'CFP', u'227'],
    'Government of Canada; Office of the Commissioner of Official Languages': [u'Office of the Commissioner of Official Languages', u'OCOL', u'Commissariat aux langues officielles', u'CLO', u'258'],
    'Government of Canada; P\xc3\xaaches et Oc\xc3\xa9ans Canada': [u'Fisheries and Oceans Canada', u'DFO', u'P\xeaches et Oc\xe9ans Canada', u'MPO', u'253'],
    'Government of Canada; Administration de pilotage des Laurentides Canada': [u'Laurentian Pilotage Authority Canada', u'LPA', u'Administration de pilotage des Laurentides Canada', u'APL', u'213'],
    'Government of Canada; Office of the Commissioner for Federal Judicial Affairs Canada': [u'Office of the Commissioner for Federal Judicial Affairs Canada', u'FJA', u'Commissariat \xe0 la magistrature f\xe9d\xe9rale Canada', u'CMF', u'140'],
    'Government of Canada; Commission des relations de travail dans la fonction publique': [u'Public Service Labour Relations Board', u'PSLRB', u'Commission des relations de travail dans la fonction publique', u'CRTFP', u'102'],
    'Government of Canada; Office of the Auditor General of Canada': [u'Office of the Auditor General of Canada', u'OAG', u'Bureau du v\xe9rificateur g\xe9n\xe9ral du Canada', u'BVG', u'125'],
    'Government of Canada; Windsor-Detroit Bridge Authority': [u'Windsor-Detroit Bridge Authority', u'', u'Autorit\xe9 du pont Windsor-D\xe9troit', u'', u'55553'],
    "Government of Canada; Commissariat \xc3\xa0 l'int\xc3\xa9grit\xc3\xa9 du secteur public du Canada": [u'Office of the Public Sector Integrity Commissioner of Canada', u'PSIC', u"Commissariat \xe0 l'int\xe9grit\xe9 du secteur public du Canada", u'ISPC', u'210'],
    'Government of Canada; Mus\xc3\xa9e des beaux-arts du Canada': [u'National Gallery of Canada', u'NGC', u'Mus\xe9e des beaux-arts du Canada', u'MBAC', u'59'],
    'Government of Canada; Military Grievances External Review Committee': [u'Military Grievances External Review Committee', u'MGERC', u"Comit\xe9 externe d'examen des griefs militaires", u'CEEGM', u'43'],
    "Government of Canada; Soci\xc3\xa9t\xc3\xa9 d'assurance-d\xc3\xa9p\xc3\xb4ts du Canada": [u'Canada Deposit Insurance Corporation', u'CDIC', u"Soci\xe9t\xe9 d'assurance-d\xe9p\xf4ts du Canada", u'SADC', u'273'],
    'Government of Canada; Bureau du surintendant des institutions financi\xc3\xa8res Canada': [u'Office of the Superintendent of Financial Institutions Canada', u'OSFI', u'Bureau du surintendant des institutions financi\xe8res Canada', u'BSIF', u'184'],
    'Government of Canada; Jacques Cartier and Champlain Bridges Incorporated': [u'Jacques Cartier and Champlain Bridges Incorporated', u'JCCBI', u'Les Ponts Jacques-Cartier et Champlain Incorpor\xe9e', u'PJCCI', u'55559'],
    'Government of Canada; Natural Resources Canada': [u'Natural Resources Canada', u'NRCan', u'Ressources naturelles Canada', u'RNCan', u'115'],
    'Government of Canada; Bureau de la s\xc3\xa9curit\xc3\xa9 des transports du Canada': [u'Transportation Safety Board of Canada', u'TSB', u'Bureau de la s\xe9curit\xe9 des transports du Canada', u'BST', u'215'],
    'Government of Canada; Service administratif des tribunaux judiciaires': [u'Courts Administration Service', u'CAS', u'Service administratif des tribunaux judiciaires', u'SATJ', u'228'],
    "Government of Canada; Agence canadienne pour l'incitation \xc3\xa0 la r\xc3\xa9duction des \xc3\xa9missions": [u'Canada Emission Reduction Incentives Agency', u'', u"Agence canadienne pour l'incitation \xe0 la r\xe9duction des \xe9missions", u'', u'277'],
    'Government of Canada; Public Service Staffing Tribunal': [u'Public Service Staffing Tribunal', u'PSST', u'Tribunal de la dotation de la fonction publique', u'TDFP', u'266'],
    'Government of Canada; Human Rights Tribunal of Canada': [u'Human Rights Tribunal of Canada', u'HRTC', u'Tribunal des droits de la personne du Canada', u'TDPC', u'164'],
    'Government of Canada; Corporation commerciale canadienne': [u'Canadian Commercial Corporation', u'CCC', u'Corporation commerciale canadienne', u'CCC', u'34'],
    'Government of Canada; Enterprise Cape Breton Corporation': [u'Enterprise Cape Breton Corporation', u'', u"Soci\xe9t\xe9 d'expansion du Cap-Breton", u'', u'203'],
    'Government of Canada; Crown-Indigenous Relations and Northern Affairs Canada': [u'Crown-Indigenous Relations and Northern Affairs Canada', u'AANDC', u'Relations Couronne-Autochtones et Affaires du Nord Canada', u'AADNC', u'249'],
    'Government of Canada; Canadian Museum for Human Rights': [u'Canadian Museum for Human Rights', u'CMHR', u'Mus\xe9e canadien pour les droits de la personne', u'MCDP', u'267'],
    'Government of Canada; RCMP External Review Committee': [u'RCMP External Review Committee', u'ERC', u"Comit\xe9 externe d'examen de la GRC", u'CEE', u'232'],
    'Government of Canada; Veterans Affairs Canada': [u'Veterans Affairs Canada', u'VAC', u'Anciens Combattants Canada', u'ACC', u'189'],
    'Government of Canada; Instituts de recherche en sant\xc3\xa9 du Canada': [u'Canadian Institutes of Health Research', u'CIHR', u'Instituts de recherche en sant\xe9 du Canada', u'IRSC', u'236'],
    'Government of Canada; Bureau du directeur g\xc3\xa9n\xc3\xa9ral des \xc3\xa9lections': [u'Office of the Chief Electoral Officer', u'elections', u'Bureau du directeur g\xe9n\xe9ral des \xe9lections', u'elections', u'---'],
    'Government of Canada; Library and Archives Canada': [u'Library and Archives Canada', u'LAC', u'Biblioth\xe8que et Archives Canada', u'BAC', u'129'],
    'Government of Canada; Postes Canada': [u'Canada Post', u'CPC', u'Postes Canada', u'SCP', u'83'],
    "Government of Canada; Soci\xc3\xa9t\xc3\xa9 canadienne d'hypoth\xc3\xa8ques et de logement": [u'Canada Mortgage and Housing Corporation', u'CMHC', u"Soci\xe9t\xe9 canadienne d'hypoth\xe8ques et de logement", u'SCHL', u'87'],
    'Government of Canada; Health Canada': [u'Health Canada', u'HC', u'Sant\xe9 Canada', u'SC', u'271'],
    'Government of Canada; Indian Residential Schools Truth and Reconciliation Commission': [u'Indian Residential Schools Truth and Reconciliation Commission', u'', u'Commission de v\xe9rit\xe9 et de r\xe9conciliation relative aux pensionnats indiens', u'', u'245'],
    'Government of Canada; Administrative Tribunals Support Service of Canada': [u'Administrative Tribunals Support Service of Canada', u'ATSSC', u"Service canadien d'appui aux tribunaux administratifs", u'SCDATA', u'8888888'],
    'Government of Canada; Global Affairs Canada': [u'Foreign Affairs and International Trade Canada', u'DFAIT', u'Affaires \xe9trang\xe8res et Commerce international Canada', u'MAECI', u'64'],
    'Government of Canada; Financial Consumer Agency of Canada': [u'Financial Consumer Agency of Canada', u'FCAC', u'Agence de la consommation en mati\xe8re financi\xe8re du Canada', u'ACFC', u'224'],
    'Government of Canada; Agence de promotion \xc3\xa9conomique du Canada atlantique': [u'Atlantic Canada Opportunities Agency', u'ACOA', u'Agence de promotion \xe9conomique du Canada atlantique', u'APECA', u'276'],
    'Government of Canada; Canadian Security Intelligence Service': [u'Canadian Security Intelligence Service', u'CSIS', u'Service canadien du renseignement de s\xe9curit\xe9', u'SCRS', u'90'],
    'Government of Canada; Canadian Museum of Nature': [u'Canadian Museum of Nature', u'CMN', u'Mus\xe9e canadien de la nature', u'MCN', u'57'],
    'Government of Canada; Financement agricole Canada': [u'Farm Credit Canada', u'FCC', u'Financement agricole Canada', u'FAC', u'23'],
    'Government of Canada; Commissariats \xc3\xa0 l\xe2\x80\x99information et \xc3\xa0 la protection de la vie priv\xc3\xa9e au Canada': [u'Offices of the Information and Privacy Commissioners of Canada', u'OPC', u'Commissariats \xe0 l\u2019information et \xe0 la protection de la vie priv\xe9e au Canada', u'CPVP', u'226'],
    'Government of Canada; Federal Economic Development Agency for Southern Ontario': [u'Federal Economic Development Agency for Southern Ontario', u'FedDev Ontario', u"Agence f\xe9d\xe9rale de d\xe9veloppement \xe9conomique pour le Sud de l'Ontario", u'FedDev Ontario', u'21'],
    'Government of Canada; National Defence': [u'National Defence', u'DND', u'D\xe9fense nationale', u'MDN', u'32'],
    'Government of Canada; Office of the Secretary to the Governor General': [u'Office of the Secretary to the Governor General', u'OSGG', u'Bureau du secr\xe9taire du gouverneur g\xe9n\xe9ral', u'BSGG', u'5557'],
    'Government of Canada; Courts Administration Service': [u'Courts Administration Service', u'CAS', u'Service administratif des tribunaux judiciaires', u'SATJ', u'228'],
    "Government of Canada; Agence f\xc3\xa9d\xc3\xa9rale de d\xc3\xa9veloppement \xc3\xa9conomique pour le Sud de l'Ontario": [u'Federal Economic Development Agency for Southern Ontario', u'FedDev Ontario', u"Agence f\xe9d\xe9rale de d\xe9veloppement \xe9conomique pour le Sud de l'Ontario", u'FedDev Ontario', u'21'],
    'Government of Canada; Conseil de la radiodiffusion et des t\xc3\xa9l\xc3\xa9communications canadiennes': [u'Canadian Radio-television and Telecommunications Commission', u'CRTC', u'Conseil de la radiodiffusion et des t\xe9l\xe9communications canadiennes', u'CRTC', u'126'],
    "Government of Canada; Centre canadien d'hygi\xc3\xa8ne et de s\xc3\xa9curit\xc3\xa9 au travail": [u'Canadian Centre for Occupational Health and Safety', u'CCOHS', u"Centre canadien d'hygi\xe8ne et de s\xe9curit\xe9 au travail", u'CCHST', u'35'],
    'Government of Canada; Greffe du Tribunal des revendications particuli\xc3\xa8res du Canada': [u'Registry of the Specific Claims Tribunal of Canada', u'SCT', u'Greffe du Tribunal des revendications particuli\xe8res du Canada', u'TRP', u'220'],
    'Government of Canada; Biblioth\xc3\xa8que et Archives Canada': [u'Library and Archives Canada', u'LAC', u'Biblioth\xe8que et Archives Canada', u'BAC', u'129'],
    'Government of Canada; Bureau du Conseil priv\xc3\xa9': [u'Privy Council Office', u'', u'Bureau du Conseil priv\xe9', u'', u'173'],
    'Government of Canada; Agence canadienne de d\xc3\xa9veloppement \xc3\xa9conomique du Nord': [u'Canadian Northern Economic Development Agency', u'CanNor', u'Agence canadienne de d\xe9veloppement \xe9conomique du Nord', u'CanNor', u'4'],
    'Government of Canada; Commission canadienne du lait': [u'Canadian Dairy Commission', u'CDC', u'Commission canadienne du lait', u'CCL', u'151'],
    'Government of Canada; Parole Board of Canada': [u'Parole Board of Canada', u'PBC', u'Commission des lib\xe9rations conditionnelles du Canada', u'CLCC', u'246'],
    'Government of Canada; Agence du revenu du Canada': [u'Canada Revenue Agency', u'CRA', u'Agence du revenu du Canada', u'ARC', u'47'],
    'Government of Canada; Exportation et d\xc3\xa9veloppement Canada': [u'Export Development Canada', u'EDC', u'Exportation et d\xe9veloppement Canada', u'EDC', u'62'],
    'Government of Canada; Library of Parliament': [u'Library of Parliament', u'LP', u'Biblioth\xe8que du Parlement', u'BP', u'55555'],
    'Government of Canada; Farm Products Council of Canada': [u'Farm Products Council of Canada', u'FPCC', u'Conseil des produits agricoles du Canada', u'CPAC', u'200'],
    'Government of Canada; Construction de D\xc3\xa9fense Canada': [u'Defence Construction Canada', u'DCC', u'Construction de D\xe9fense Canada', u'CDC', u'28'],
    'Government of Canada; Registry of the Specific Claims Tribunal of Canada': [u'Registry of the Specific Claims Tribunal of Canada', u'SCT', u'Greffe du Tribunal des revendications particuli\xe8res du Canada', u'TRP', u'220'],
    "Government of Canada; Mus\xc3\xa9e canadien de l'histoire": [u'Canadian Museum of History', u'CMH', u"Mus\xe9e canadien de l'histoire", u'MCH', u'263'],
    'Government of Canada; Atlantic Pilotage Authority Canada': [u'Atlantic Pilotage Authority Canada', u'APA', u"Administration de pilotage de l'Atlantique Canada", u'APA', u'221'],
    'Government of Canada; Office des transports du Canada': [u'Canadian Transportation Agency', u'CTA', u'Office des transports du Canada', u'OTC', u'124'],
    'Government of Canada; Canadian Museum of Immigration at Pier 21': [u'Canadian Museum of Immigration at Pier 21', u'CMIP', u"Mus\xe9e canadien de l'immigration du Quai 21", u'MCIQ', u'2'],
    'Government of Canada; Department of Finance Canada': [u'Department of Finance Canada', u'FIN', u'Minist\xe8re des Finances Canada', u'FIN', u'157'],
    'Government of Canada; Commission de la fonction publique du Canada': [u'Public Service Commission of Canada', u'PSC', u'Commission de la fonction publique du Canada', u'CFP', u'227'],
    'Government of Canada; Conseil de recherches en sciences humaines du Canada': [u'Social Sciences and Humanities Research Council of Canada', u'SSHRC', u'Conseil de recherches en sciences humaines du Canada', u'CRSH', u'207'],
    'Government of Canada; Canadian Human Rights Commission': [u'Canadian Human Rights Commission', u'CHRC', u'Commission canadienne des droits de la personne', u'CCDP', u'113'],
    'Government of Canada; Affaires autochtones et D\xc3\xa9veloppement du Nord Canada': [u'Aboriginal Affairs and Northern Development Canada', u'AANDC', u'Affaires autochtones et D\xe9veloppement du Nord Canada', u'AADNC', u'249'],
    'Government of Canada; Service correctionnel du Canada': [u'Correctional Service of Canada', u'CSC', u'Service correctionnel du Canada', u'SCC', u'193'],
    'Government of Canada; Public Servants Disclosure Protection Tribunal Canada': [u'Public Servants Disclosure Protection Tribunal Canada', u'PSDPTC', u'Tribunal de la protection des fonctionnaires divulgateurs Canada', u'TPFDC', u'40'],
    'Government of Canada; Mus\xc3\xa9e canadien de la nature': [u'Canadian Museum of Nature', u'CMN', u'Mus\xe9e canadien de la nature', u'MCN', u'57'],
    'Government of Canada; Blue Water Bridge Canada': [u'Blue Water Bridge Canada', u'bwbc', u'Pont Bleu Water', u'pbwc', u'333'],
    'Government of Canada; Canada Science and Technology Museum': [u'Canada Science and Technology Museum', u'CSTM', u'Mus\xe9e des sciences et de la technologie du Canada', u'MSTC', u'202'],
    'Government of Canada; Export Development Canada': [u'Export Development Canada', u'EDC', u'Exportation et d\xe9veloppement Canada', u'EDC', u'62'],
    'Government of Canada; Biblioth\xc3\xa8que du Parlement': [u'Library of Parliament', u'LP', u'Biblioth\xe8que du Parlement', u'BP', u'55555'],
    'Government of Canada; Pacific Pilotage Authority Canada': [u'Pacific Pilotage Authority Canada', u'PPA', u'Administration de pilotage du Pacifique Canada', u'APP', u'165'],
    'Government of Canada; Canadian Transportation Agency': [u'Canadian Transportation Agency', u'CTA', u'Office des transports du Canada', u'OTC', u'124'],
    'Government of Canada; Atomic Energy of Canada Limited': [u'Atomic Energy of Canada Limited', u'', u'\xc9nergie atomique du Canada', u'Limit\xe9e', u'', u'138'],
    'Government of Canada; Affaires autochtones et du Nord Canada': [u'Aboriginal Affairs and Northern Development Canada', u'AANDC', u'Affaires autochtones et D\xe9veloppement du Nord Canada', u'AADNC', u'249'],
    'Government of Canada; Ridley Terminals Inc.': [u'Ridley Terminals Inc.', u'', u'Ridley Terminals Inc.', u'', u'142'],
    "Government of Canada; Administration de pilotage de l'Atlantique Canada": [u'Atlantic Pilotage Authority Canada', u'APA', u"Administration de pilotage de l'Atlantique Canada", u'APA', u'221'],
    'Government of Canada; The Correctional Investigator Canada': [u'The Correctional Investigator Canada', u'OCI', u"L'Enqu\xeateur correctionnel Canada", u'BEC', u'5555'],
    'Government of Canada; Employment and Social Development Canada': [u'Employment and Social Development Canada', u'esdc', u'Emploi et D\xe9veloppement social Canada', u'edsc', u'141'],
    'Government of Canada; Service canadien du renseignement de s\xc3\xa9curit\xc3\xa9': [u'Canadian Security Intelligence Service', u'CSIS', u'Service canadien du renseignement de s\xe9curit\xe9', u'SCRS', u'90'],
    'Government of Canada; VIA Rail Canada Inc.': [u'VIA Rail Canada Inc.', u'', u'VIA Rail Canada Inc.', u'', u'55555'],
    'Government of Canada; Conseil du Tr\xc3\xa9sor': [u'Treasury Board', u'TB', u'Conseil du Tr\xe9sor', u'CT', u'105'],
    'Government of Canada; Commissariat \xc3\xa0 la magistrature f\xc3\xa9d\xc3\xa9rale Canada': [u'Office of the Commissioner for Federal Judicial Affairs Canada', u'FJA', u'Commissariat \xe0 la magistrature f\xe9d\xe9rale Canada', u'CMF', u'140'],
    'Government of Canada; Farm Credit Canada': [u'Farm Credit Canada', u'FCC', u'Financement agricole Canada', u'FAC', u'23'],
    'Government of Canada; Office of the Communications Security Establishment Commissioner': [u'Office of the Communications Security Establishment Commissioner', u'OCSEC', u'Bureau du commissaire du Centre de la s\xe9curit\xe9 des t\xe9l\xe9communications', u'BCCST', u'279'],
    'Government of Canada; Commission canadienne des droits de la personne': [u'Canadian Human Rights Commission', u'CHRC', u'Commission canadienne des droits de la personne', u'CCDP', u'113'],
    'Government of Canada; Centre de la s\xc3\xa9curit\xc3\xa9 des t\xc3\xa9l\xc3\xa9communications Canada': [u'Communications Security Establishment Canada', u'CSEC', u'Centre de la s\xe9curit\xe9 des t\xe9l\xe9communications Canada', u'CSTC', u'156'],
    "Government of Canada; Commission du droit d'auteur Canada": [u'Copyright Board Canada', u'CB', u"Commission du droit d'auteur Canada", u'CDA', u'116'],
    'Government of Canada; Ressources naturelles Canada': [u'Natural Resources Canada', u'NRCan', u'Ressources naturelles Canada', u'RNCan', u'115'],
    'Government of Canada; Office of the Superintendent of Financial Institutions Canada': [u'Office of the Superintendent of Financial Institutions Canada', u'OSFI', u'Bureau du surintendant des institutions financi\xe8res Canada', u'BSIF', u'184'],
    "Government of Canada; Comit\xc3\xa9 externe d'examen de la GRC": [u'RCMP External Review Committee', u'ERC', u"Comit\xe9 externe d'examen de la GRC", u'CEE', u'232'],
    'Government of Canada; Statistics Canada': [u'Statistics Canada', u'StatCan', u'Statistique Canada', u'StatCan', u'256'],
    'Government of Canada; Canadian Food Inspection Agency': [u'Canadian Food Inspection Agency', u'CFIA', u"Agence canadienne d'inspection des aliments", u'ACIA', u'206'],
    'Government of Canada; Canada Deposit Insurance Corporation': [u'Canada Deposit Insurance Corporation', u'CDIC', u"Soci\xe9t\xe9 d'assurance-d\xe9p\xf4ts du Canada", u'SADC', u'273'],
    'Government of Canada; \xc3\x89cole de la fonction publique du Canada': [u'Canada School of Public Service', u'CSPS', u'\xc9cole de la fonction publique du Canada', u'EFPC', u'73'],
    'Government of Canada; Immigration and Refugee Board of Canada': [u'Immigration and Refugee Board of Canada', u'IRB', u"Commission de l'immigration et du statut de r\xe9fugi\xe9 du Canada", u'CISR', u'5'],
    'Government of Canada; Commissariat au lobbying du Canada': [u'Office of the Commissioner of Lobbying of Canada', u'OCL', u'Commissariat au lobbying du Canada', u'CAL', u'205'],
    'Government of Canada; Commission de v\xc3\xa9rit\xc3\xa9 et de r\xc3\xa9conciliation relative aux pensionnats indiens': [u'Indian Residential Schools Truth and Reconciliation Commission', u'', u'Commission de v\xe9rit\xe9 et de r\xe9conciliation relative aux pensionnats indiens', u'', u'245'],
    'Government of Canada; Canadian Dairy Commission': [u'Canadian Dairy Commission', u'CDC', u'Commission canadienne du lait', u'CCL', u'151'],
    "Government of Canada; Mus\xc3\xa9e canadien de l'immigration du Quai 21": [u'Canadian Museum of Immigration at Pier 21', u'CMIP', u"Mus\xe9e canadien de l'immigration du Quai 21", u'MCIQ', u'2'],
    'Government of Canada; Industry Canada': [u'Industry Canada', u'IC', u'Industrie Canada', u'IC', u'230'],
    'Government of Canada; Transportation Appeal Tribunal of Canada': [u'Transportation Appeal Tribunal of Canada', u'TATC', u"Tribunal d'appel des transports du Canada", u'TATC', u'96'],
    'Government of Canada; Offices of the Information and Privacy Commissioners of Canada': [u'Offices of the Information and Privacy Commissioners of Canada', u'OPC', u'Commissariats \xe0 l\u2019information et \xe0 la protection de la vie priv\xe9e au Canada', u'CPVP', u'226'],
    'Government of Canada; Security Intelligence Review Committee': [u'Security Intelligence Review Committee', u'SIRC', u'Comit\xe9 de surveillance des activit\xe9s de renseignement de s\xe9curit\xe9', u'CSARS', u'109'],
    'Government of Canada; Impact Assessment Agency of Canada': [u'Impact Assessment Agency of Canada', u'IAAC', u"Agence d'Évaluation d'Impact du Canada", u'AEIC', u'209'],
    ############################################
    ## Alberta Gov Department
    ############################################
    'Government of Alberta; Alberta Geological Survey': ['Alberta Geological Survey', 'ab', 'Commission géologique de l\'Alberta', 'ab', '666600'],
    'Government of Alberta; Alberta Environment and Parks': ['Alberta Environment and Parks', 'ab', 'Environnement et parcs de l\'Alberta', 'ab', '666601'],
    'Government of Alberta; Alberta Parks': ['Alberta Parks', 'ab', 'Parcs de l\'Alberta', 'ab', '666602'],
    'Government of Alberta; Land Use Secretariat': ['Land Use Secretariat', 'ab', '; Secrétariat de l\'utilisation des terres', 'ab', '666603'],
    'Government of Alberta; Government Data': ['Government Data', 'ab', '; Données gouvernementales', 'ab', '666604'],
    'Government of Alberta; Alberta Justice and Solicitor General': ['Alberta Justice and Solicitor General', 'ab', '; Justice et Solliciteur général de l\'Alberta', 'ab', '666605'],
    'Government of Alberta; Alberta Agriculture and Forestry': ['Alberta Agriculture and Forestry', 'ab', '; Agriculture et foresterie de l\'Alberta', 'ab', '666606'],
    'Government of Alberta; Treasury Board and Finance': ['Treasury Board and Finance', 'ab', '; Conseil du Trésor et Finances', 'ab', '666607'],
    'Government of Alberta; Alberta Health': ['Alberta Health', 'ab', '; Alberta Health', 'ab', '666608'],
    'Government of Alberta; Alberta Energy': ["Alberta Energy", 'ab', '; Alberta Energy', 'ab', '666609'],
    'Government of Alberta; Government of Alberta': ["Government of Alberta", 'ab', "; Gouvernement de l'Alberta", 'ab', '666609'],
    #############################################
    ## Government of British Columbia Department
    #############################################
    'Government of British Columbia; Agriculture and Forestry': ['Agriculture and Forestry', 'bc', 'Agriculture et Foret', 'cb', '777700'],
    'Government of British Columbia; Natural Resources': ['Natural Resources', 'bc', 'Ressources Naturelles', 'cb', '777701'],
    'Government of British Columbia; BC-Natural Resources': ['Natural Resources', 'bc', 'Ressources Naturelles', 'cb', '777702'],
    'Government of British Columbia; Education': ['Education', 'bc', 'Éducation', 'cb', '777703'],
    'Government of British Columbia; Transportation': ['Transportation', 'bc', 'Transport', 'cb', '777704'],
    'Government of British Columbia; Service': ['Service', 'bc', 'Service', 'cb', '777705'],
    'Government of British Columbia; Justice': ['Justice', 'bc', 'Justice', 'cb', '777706'],
    'Government of British Columbia; Economy': ['Economy', 'bc', 'Économie', 'cb', '777707'],
    'Government of British Columbia; Health and Safety': ['Health and Safety', 'bc', 'Santé et sécurité', 'cb', '777709'],
    'Government of British Columbia; Social Services': ['Social Services', 'bc', 'Services sociaux', 'cb', '777710'],
    'Government of British Columbia; Government of British Columbia': ['Government of British Columbia', 'bc', 'Gouvernement de la Colombie-Britanique', 'cb', '777710'],

    #############################################
    ## Government of Ontario
    #############################################
    'Government of Ontario; Government of Ontario': ['Government of Ontario', 'on', 'Gouvernement de l\'Ontario', 'on', '888833'],

    #############################################
    ## Government of Quebec/Québec
    #############################################
    'Government of Quebec; Quebec Geological Survey': ['Quebec Geological Survey', 'qc', 'Commission géologique du Québec', 'qc', '888800'],
    'Government and Municipalities of Québec; City of Montreal': ['City of Montreal', 'qc', 'Ville de Montréal', 'qc', '888001'],
    'Government and Municipalities of Québec; City of Longueuil': ['City of Longueuil', 'qc', 'Ville de Longueuil', 'qc', '888002'],
    'Government and Municipalities of Québec': ['Government and Municipalities of Québec', 'qc', 'Gouvernement et municipalités du Québec', 'qc', '888000'],
    'Government and Municipalities of Québec; Government and Municipalities of Québec': ['Government and Municipalities of Québec', 'qc', 'Gouvernement et municipalités du Québec', 'qc', '888044'],
    'Gouvernement et municipalités du Québec; Gouvernement et municipalités du Québec': ['Gouvernement et municipalités du Québec', 'qc', 'Gouvernement et municipalités du Québec', 'qc', '888044'],
    'Quebec Government and Municipalities; Quebec Government and Municipalities': ['Government and Municipalities of Québec', 'qc', 'Gouvernement et municipalités du Québec', 'qc', '888044'],
    'Québec Government and Municipalities; Québec Government and Municipalities': ['Government and Municipalities of Québec', 'qc', 'Gouvernement et municipalités du Québec', 'qc', '888044'],
    #############################################
    ## Government of Brunswick
    #############################################
    'Government of New Brunswick; New Brunswick Geological Survey': ['New Brunswick Geological Survey', 'nb', 'Commission géologique du Nouveau-Brunswick', 'nb', '999900'],

    #############################################
    ## Government of Yukon
    #############################################
    'Government of Yukon; Yukon Geological Survey': ['Yukon Geological Survey', 'yk', 'Commission géologique du Yukon', 'yk', '555500']

}

# Imported now - update by running schema-sync.py
# ResourceType = {
#     'abstract'                               :[u'abstract'],
#     'sommaire'                               :[u'abstract'],
#     'agreement'                              :[u'agreement'],
#     'entente'                                :[u'agreement'],
#     'contractual material'                   :[u'contractual_material'],
#     'contenu contractuel'                    :[u'contractual_material'],
#     'intergovernmental agreement'            :[u'intergovernmental_agreement'],
#     'entente intergouvernementale'           :[u'intergovernmental_agreement'],
#     'lease'                                  :[u'lease'],
#     'bail'                                   :[u'lease'],
#     'memorandum of understanding'            :[u'memorandum_of_understanding'],
#     'protocole d’entente'                    :[u'memorandum_of_understanding'],
#     'nondisclosure agreement'                :[u'nondisclosure_agreement'],
#     'accord de non divulgation'              :[u'nondisclosure_agreement'],
#     'service-level agreement'                :[u'service-level_agreement'],
#     'entente de niveau de service'           :[u'service-level_agreement'],
#     'affidavit'                              :[u'affidavit'],
#     'application'                            :[u'application'],
#     'demande'                                :[u'application'],
#     'api'                                    :[u'api'],
#     'architectural or technical design'      :[u'architectural_or_technical_design'],
#     'conception architecturale ou technique' :[u'architectural_or_technical_design'],
#     'article'                                :[u'article'],
#     'assessment'                             :[u'assessment'],
#     'évaluation'                             :[u'assessment'],
#     'audit'                                  :[u'audit'],
#     'environmental assessment'               :[u'environmental_assessment'],
#     'évaluation environnementale'            :[u'environmental_assessment'],
#     'examination'                            :[u'examination'],
#     'examen'                                 :[u'examination'],
#     'gap assessment'                         :[u'gap_assessment'],
#     'évaluation des écarts'                  :[u'gap_assessment'],
#     'lessons learned'                        :[u'lessons_learned'],
#     'leçons apprises'                        :[u'lessons_learned'],
#     'performance indicator'                  :[u'performance_indicator'],
#     'indicateur de rendement'                :[u'performance_indicator'],
#     'risk assessment'                        :[u'risk_assessment'],
#     'évaluation des risques'                 :[u'risk_assessment'],
#     'biography'                              :[u'biography'],
#     'biographie'                             :[u'biography'],
#     'briefing material'                      :[u'briefing_material'],
#     'matériel de breffage'                   :[u'briefing_material'],
#     'backgrounder'                           :[u'backgrounder'],
#     'précis d’information'                   :[u'backgrounder'],
#     'business case'                          :[u'business_case'],
#     'analyse de rentabilisation'             :[u'business_case'],
#     'claim'                                  :[u'claim'],
#     'réclamation'                            :[u'claim'],
#     'comments'                               :[u'comments'],
#     'commentaires'                           :[u'comments'],
#     'conference proceedings'                 :[u'conference_proceedings'],
#     'actes de la conférence'                 :[u'conference_proceedings'],
#     'consultation'                           :[u'consultation'],
#     'consultation'                           :[u'consultation'],
#     'contact information'                    :[u'contact_information'],
#     'coordonnées'                            :[u'contact_information'],
#     'correspondence'                         :[u'correspondence'],
#     'correspondance'                         :[u'correspondence'],
#     'ministerial correspondence'             :[u'ministerial_correspondence'],
#     'correspondance ministérielle'           :[u'ministerial_correspondence'],
#     'memorandum'                             :[u'memorandum'],
#     'note de service'                        :[u'memorandum'],
#     'dataset'                                :[u'dataset'],
#     'jeu de données'                         :[u'dataset'],
#     'delegation of authority'                :[u'delegation_of_authority'],
#     'délégation des pouvoirs'                :[u'delegation_of_authority'],
#     'educational material'                   :[u'educational_material'],
#     'matériel pédagogique'                   :[u'educational_material'],
#     'employment opportunity'                 :[u'employment_opportunity'],
#     'possibilité d’emploi'                   :[u'employment_opportunity'],
#     'event'                                  :[u'event'],
#     'événement'                              :[u'event'],
#     'fact sheet'                             :[u'fact_sheet'],
#     'feuille de renseignements'              :[u'fact_sheet'],
#     'financial material'                     :[u'financial_material'],
#     'document financier'                     :[u'financial_material'],
#     'budget'                                 :[u'budget'],
#     'funding proposal'                       :[u'funding_proposal'],
#     'proposition de financement'             :[u'funding_proposal'],
#     'invoice'                                :[u'invoice'],
#     'facture'                                :[u'invoice'],
#     'financial statement'                    :[u'financial_statement'],
#     'états financiers'                       :[u'financial_statement'],
#     'form'                                   :[u'form'],
#     'formulaire'                             :[u'form'],
#     'framework'                              :[u'framework'],
#     'cadre'                                  :[u'framework'],
#     'geospatial material'                    :[u'geospatial_material'],
#     'matériel géospatial'                    :[u'geospatial_material'],
#     'guide'                                  :[u'guide'],
#     'guide'                                  :[u'guide'],
#     'best practices'                         :[u'best_practices'],
#     'pratiques exemplaires'                  :[u'best_practices'],
#     'intellectual property statement'        :[u'intellectual_property_statement'],
#     'Énoncé sur la propriété intellectuelle' :[u'intellectual_property_statement'],
#     'legal complaint'                        :[u'legal_complaint'],
#     'plainte légale'                         :[u'legal_complaint'],
#     'legal opinion'                          :[u'legal_opinion'],
#     'avis juridique'                         :[u'legal_opinion'],
#     'legislation and regulations'            :[u'legislation_and_regulations'],
#     'lois et règlements'                     :[u'legislation_and_regulations'],
#     'licenses and permits'                   :[u'licenses_and_permits'],
#     'licences et permis'                     :[u'licenses_and_permits'],
#     'literary material'                      :[u'literary_material'],
#     'ouvrages littéraires'                   :[u'literary_material'],
#     'media release'                          :[u'media_release'],
#     'communiqué de presse'                   :[u'media_release'],
#     'statement'                              :[u'statement'],
#     'énoncé'                                 :[u'statement'],
#     'meeting material'                       :[u'meeting_material'],
#     'documentation de la réunion'            :[u'meeting_material'],
#     'agenda'                                 :[u'agenda'],
#     'programme'                              :[u'agenda'],
#     'minutes'                                :[u'minutes'],
#     'procès-verbaux'                         :[u'minutes'],
#     'memorandum to Cabinet'                  :[u'memorandum_to_cabinet'],
#     'mémoire au Cabinet'                     :[u'memorandum_to_cabinet'],
#     'multimedia resource'                    :[u'multimedia_resource'],
#     'ressource multimédia'                   :[u'multimedia_resource'],
#     'notice'                                 :[u'notice'],
#     'avis'                                   :[u'notice'],
#     'organizational description'             :[u'organizational_description'],
#     'description organisationnelle'          :[u'organizational_description'],
#     'plan'                                   :[u'plan'],
#     'business plan'                          :[u'business_plan'],
#     'plan d’activités'                       :[u'business_plan'],
#     'strategic plan'                         :[u'strategic_plan'],
#     'plan stratégique'                       :[u'strategic_plan'],
#     'policy'                                 :[u'policy'],
#     'politique'                              :[u'policy'],
#     'white paper'                            :[u'white_paper'],
#     'livre blanc'                            :[u'white_paper'],
#     'presentation'                           :[u'presentation'],
#     'présentation'                           :[u'presentation'],
#     'procedure'                              :[u'procedure'],
#     'procédure'                              :[u'procedure'],
#     'profile'                                :[u'profile'],
#     'profil'                                 :[u'profile'],
#     'project material'                       :[u'project_material'],
#     'documents du projet'                    :[u'project_material'],
#     'project charter'                        :[u'project_charter'],
#     'charte de projet'                       :[u'project_charter'],
#     'project plan'                           :[u'project_plan'],
#     'plan du projet'                         :[u'project_plan'],
#     'project proposal'                       :[u'project_proposal'],
#     'proposition de projet'                  :[u'project_proposal'],
#     'promotional material'                   :[u'promotional_material'],
#     'documents promotionnels'                :[u'promotional_material'],
#     'publication'                            :[u'publication'],
#     'Q & A'                                  :[u'faq'],
#     'FAQ'                                    :[u'faq'],
#     'Q et R'                                 :[u'faq'],
#     'foire aux questions'                    :[u'faq'],
#     'record of decision'                     :[u'record_of_decision'],
#     'compte rendu des décisions'             :[u'record_of_decision'],
#     'report'                                 :[u'report'],
#     'rapport'                                :[u'report'],
#     'annual report'                          :[u'annual_report'],
#     'rapport annuel'                         :[u'annual_report'],
#     'interim report'                         :[u'interim_report'],
#     'rapport d’étape'                        :[u'interim_report'],
#     'research proposal'                      :[u'research_proposal'],
#     'projet de recherche'                    :[u'research_proposal'],
#     'resource list'                          :[u'resource_list'],
#     'liste de référence'                     :[u'resource_list'],
#     'routing slip'                           :[u'routing_slip'],
#     'bordereau d’acheminement'               :[u'routing_slip'],
#     'Social media resource'                  :[u'blog_entry'],
#     'blog entry'                             :[u'blog_entry'],
#     'ressources des médias sociaux'          :[u'blog_entry'],
#     'entrée de blogue'                       :[u'blog_entry'],
#     'sound recording'                        :[u'sound_recording'],
#     'enregistrement sonore'                  :[u'sound_recording'],
#     'specification'                          :[u'specification'],
#     'spécification'                          :[u'specification'],
#     'statistics'                             :[u'statistics'],
#     'statistiques'                           :[u'statistics'],
#     'still image'                            :[u'still_image'],
#     'image fixe'                             :[u'still_image'],
#     'submission'                             :[u'submission'],
#     'présentation'                           :[u'submission'],
#     'survey'                                 :[u'survey'],
#     'sondage'                                :[u'survey'],
#     'terminology'                            :[u'terminology'],
#     'terminologie'                           :[u'terminology'],
#     'terms of reference'                     :[u'terms_of_reference'],
#     'mandat'                                 :[u'terms_of_reference'],
#     'tool'                                   :[u'tool'],
#     'outil'                                  :[u'tool'],
#     'training material'                      :[u'training_material'],
#     'matériel didactique'                    :[u'training_material'],
#     'transcript'                             :[u'transcript'],
#     'transcription'                          :[u'transcript'],
#     'web service'                            :[u'web_service'],
#     'service web'                            :[u'web_service'],
#     'website'                                :[u'website'],
#     'site Web'                               :[u'website'],
#     'workflow'                               :[u'workflow'],
#     'flux des travaux'                       :[u'workflow'],

#     'abstract'                               :[u'abstract'],
#     'affidavit'                              :[u'affidavit'],
#     'agenda'                                 :[u'agenda'],
#     'agreement'                              :[u'agreement'],
#     'annual_report'                          :[u'annual_report'],
#     'api'                                    :[u'api'],
#     'application'                            :[u'application'],
#     'architectural_or_technical_design'      :[u'architectural_or_technical_design'],
#     'article'                                :[u'article'],
#     'assessment'                             :[u'assessment'],
#     'audit'                                  :[u'audit'],
#     'backgrounder'                           :[u'backgrounder'],
#     'best_practices'                         :[u'best_practices'],
#     'biography'                              :[u'biography'],
#     'blog_entry'                             :[u'blog_entry'],
#     'briefing_material'                      :[u'briefing_material'],
#     'budget'                                 :[u'budget'],
#     'business_case'                          :[u'business_case'],
#     'business_plan'                          :[u'business_plan'],
#     'claim'                                  :[u'claim'],
#     'comments'                               :[u'comments'],
#     'conference_proceedings'                 :[u'conference_proceedings'],
#     'consultation'                           :[u'consultation'],
#     'contact_information'                    :[u'contact_information'],
#     'contractual_material'                   :[u'contractual_material'],
#     'correspondence'                         :[u'correspondence'],
#     'dataset'                                :[u'dataset'],
#     'delegation_of_authority'                :[u'delegation_of_authority'],
#     'educational_material'                   :[u'educational_material'],
#     'employment_opportunity'                 :[u'employment_opportunity'],
#     'environmental_assessment'               :[u'environmental_assessment'],
#     'event'                                  :[u'event'],
#     'examination'                            :[u'examination'],
#     'fact_sheet'                             :[u'fact_sheet'],
#     'faq'                                    :[u'faq'],
#     'financial_material'                     :[u'financial_material'],
#     'financial_statement'                    :[u'financial_statement'],
#     'form'                                   :[u'form'],
#     'framework'                              :[u'framework'],
#     'funding_proposal'                       :[u'funding_proposal'],
#     'gap_assessment'                         :[u'gap_assessment'],
#     'geospatial_material'                    :[u'geospatial_material'],
#     'guide'                                  :[u'guide'],
#     'intellectual_property_statement'        :[u'intellectual_property_statement'],
#     'intergovernmental_agreement'            :[u'intergovernmental_agreement'],
#     'interim_report'                         :[u'interim_report'],
#     'invoice'                                :[u'invoice'],
#     'lease'                                  :[u'lease'],
#     'legal_complaint'                        :[u'legal_complaint'],
#     'legal_opinion'                          :[u'legal_opinion'],
#     'legislation_and_regulations'            :[u'legislation_and_regulations'],
#     'lessons_learned'                        :[u'lessons_learned'],
#     'licenses_and_permits'                   :[u'licenses_and_permits'],
#     'literary_material'                      :[u'literary_material'],
#     'media_release'                          :[u'media_release'],
#     'meeting_material'                       :[u'meeting_material'],
#     'memorandum'                             :[u'memorandum'],
#     'memorandum_of_understanding'            :[u'memorandum_of_understanding'],
#     'memorandum_to_cabinet'                  :[u'memorandum_to_cabinet'],
#     'ministerial_correspondence'             :[u'ministerial_correspondence'],
#     'minutes'                                :[u'minutes'],
#     'multimedia_resource'                    :[u'multimedia_resource'],
#     'nondisclosure_agreement'                :[u'nondisclosure_agreement'],
#     'notice'                                 :[u'notice'],
#     'organizational_description'             :[u'organizational_description'],
#     'performance_indicator'                  :[u'performance_indicator'],
#     'plan'                                   :[u'plan'],
#     'policy'                                 :[u'policy'],
#     'presentation'                           :[u'presentation'],
#     'procedure'                              :[u'procedure'],
#     'profile'                                :[u'profile'],
#     'project_charter'                        :[u'project_charter'],
#     'project_material'                       :[u'project_material'],
#     'project_plan'                           :[u'project_plan'],
#     'project_proposal'                       :[u'project_proposal'],
#     'promotional_material'                   :[u'promotional_material'],
#     'publication'                            :[u'publication'],
#     'record_of_decision'                     :[u'record_of_decision'],
#     'report'                                 :[u'report'],
#     'research_proposal'                      :[u'research_proposal'],
#     'resource_list'                          :[u'resource_list'],
#     'risk_assessment'                        :[u'risk_assessment'],
#     'routing_slip'                           :[u'routing_slip'],
#     'service-level_agreement'                :[u'service-level_agreement'],
#     'sound_recording'                        :[u'sound_recording'],
#     'specification'                          :[u'specification'],
#     'statement'                              :[u'statement'],
#     'statistics'                             :[u'statistics'],
#     'still_image'                            :[u'still_image'],
#     'strategic_plan'                         :[u'strategic_plan'],
#     'submission'                             :[u'submission'],
#     'survey'                                 :[u'survey'],
#     'terminology'                            :[u'terminology'],
#     'terms_of_reference'                     :[u'terms_of_reference'],
#     'tool'                                   :[u'tool'],
#     'training_material'                      :[u'training_material'],
#     'transcript'                             :[u'transcript'],
#     'web_service'                            :[u'web_service'],
#     'website'                                :[u'website'],
#     'white_paper'                            :[u'white_paper'],
#     'workflow'                               :[u'workflow'],

# }

# Imported now - update by running schema-sync.py
# These should be synced with http://www.gcpedia.gc.ca/wiki/Federal_Geospatial_Platform/Policies_and_Standards/Catalogue/Release/Appendix_B_Guidelines_and_Best_Practices/Guide_to_Harmonized_ISO_19115:2003_NAP/Format
# CL_Formats = [
#     'AAC',
#     'AIFF',
#     'Android'
#     'APK', #deprecated
#     'ASCII Grid',
#     'AVI',
#     'Blackberry',
#     'BMP',
#     'BWF',
#     'CCT',
#     'CDED ASCII',
#     'CDF',
#     'CDR',
#     'COD', #deprecated
#     'CSV',
#     'DBD',
#     'DBF',
#     'DICOM',
#     'DNG',
#     'DOC',
#     'DOCX',
#     'DXF',
#     'E00',
#     'ECW',
#     'EDI', #deprecated
#     'EMF',
#     'EPS',
#     'EPUB2',
#     'EPUB3',
#     'ESRI REST',
#     'EXE',
#     'FGDB/GDB',
#     'Flat raster binary',
#     'GeoJSON',
#     'GEOJSON', #deprecated
#     'GeoPackage',
#     'GeoPDF',
#     'GeoRSS',
#     'GeoTIF',
#     'GPKG', #deprecated
#     'GIF',
#     'GML',
#     'GRIB1',
#     'GRIB2',
#     'HDF',
#     'HTML',
#     'IATI',
#     'IOS',
#     'IPA', #deprecated
#     'JAR',
#     'JFIF',
#     'JP2',
#     'JPEG 2000',
#     'JPEG',
#     'JPG',
#     'JSON',
#     'JSONL', #deprecated
#     'JSON Lines',
#     'JSON-LD',
#     'KML',
#     'KMZ',
#     'LAS',
#     'LYR',
#     'MapInfo', #deprecated
#     'MFX',
#     'MOV',
#     'MP3',
#     'MPEG',
#     'MPEG-1',
#     'MXD',
#     'NetCDF',
#     'NT', #deprecated
#     'ODP',
#     'ODS',
#     'ODT',
#     'other',
#     'PDF',
#     'PDF/A-1',
#     'PDF/A-2',
#     'PNG',
#     'PPT',
#     'RDF',
#     'RDFa',
#     'RSS',
#     'RTF',
#     'SAR',
#     'SAV',
#     'SEGY',
#     'SHP',
#     'SQL',
#     'SQLITE3', #deprecated
#     'SQLITE',
#     'SVG',
#     'TAB',
#     'TFW', #deprecated
#     'TIFF',
#     'TRiG',
#     'TRiX',
#     'TTL', #deprecated
#     'TXT',
#     'VPF',
#     'WAV',
#     'Web App',
#     'WCS',
#     'WFS',
#     'WMS',
#     'WMTS',
#     'WMV',
#     'WPS',
#     'XLS',
#     'XLSM',
#     'XML',
#     'ZIP'
# ]

CL_Subjects = {
    'farming': [
        'Farming',
        'Agriculture',
        'Agriculture',
        'agriculture'],
    'biota': [
        'Biota',
        'Biote',
        'Nature and Environment, Science and Technology',
        'nature_and_environment,science_and_technology'],
    'boundaries': [
        'Boundaries',
        'Frontières',
        'Government and Politics',
        'government_and_politics'],
    'climatologyMeteorologyAtmosphere': [
        'Climatology / Meteorology / Atmosphere',
        'Climatologie / Météorologie / Atmosphère',
        'Nature and Environment, Science and Technology',
        'nature_and_environment,science_and_technology'],
    'economy': [
        'Economy',
        'Économie',
        'Economics and Industry',
        'economics_and_industry'],
    'elevation': [
        'Elevation',
        'Élévation',
        'Form Descriptors',
        'form_descriptors'],
    'environment': [
        'Environment',
        'Environnement',
        'Nature and Environment',
        'nature_and_environment'],
    'geoscientificInformation': [
        'Geoscientific Information',
        'Information géoscientifique',
        'Nature and Environment, Science and Technology, Form Descriptors',
        'nature_and_environment,science_and_technology,form_descriptors'],
    'health': [
        'Health',
        'Santé',
        'Health and Safety',
        'health_and_safety'],
    'imageryBaseMapsEarthCover': [
        'Imagery Base Maps Earth Cover',
        'Imagerie carte de base couverture terrestre',
        'Form Descriptors',
        'form_descriptors'],
    'intelligenceMilitary': [
        'Intelligence Military',
        'Renseignements militaires',
        'Military',
        'military'],
    'inlandWaters': [
        'Inland Waters',
        'Eaux intérieures',
        'Nature and Environment',
        'nature_and_environment'],
    'location': [
        'Location',
        'Localisation',
        'Form Descriptors',
        'form_descriptors'],
    'oceans': [
        'Oceans',
        'Océans',
        'Nature and Environment',
        'nature_and_environment'],
    'planningCadastre': [
        'Planning Cadastre',
        'Aménagement cadastre',
        'Nature and Environment, Form Descriptors, Economics and Industry',
        'nature_and_environment,form_descriptors,economics_and_industry'],
    'society': [
        'Society',
        'Société',
        'Society and Culture',
        'society_and_culture'],
    'structure': [
        'Structure',
        'Structures',
        'Economics and Industry',
        'economics_and_industry'],
    'transportation': [
        'Transportation',
        'Transport',
        'Transport',
        'transport'],
    'utilitiesCommunication': [
        'Utilities Communication',
        'Services communication',
        'Economics and Industry, Information and Communications',
        'economics_and_industry,information_and_communications']
}

OGP_catalogueType = {
    'Data': [u'Data', u'Données'],
    'Geo Data': [u'Geo Data', u'Géo'],
    'FGP Data': [u'FGP Data', u'FGP Data'],
    'Données': [u'Data', u'Données'],
    'Géo': [u'Geo Data', u'Géo'],
    'FGP Data': [u'FGP Data', u'FGP Data']
}

if __name__ == "__main__":
    arguments = docopt.docopt(__doc__)
    sys.exit(main())
