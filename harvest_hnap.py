#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Usage: harvest.py [-f from_iso_date_time (e.g. 1970-01-01T00:00:00Z)] [-t to_iso_date_time (e.g. 1970-01-02T00:00:00Z)] [-e environment_input (e.g. staging/production or stag/prod)] [-p province_or_territory_name (e.g. Ontario/On Quebec/Qc)]

Extract HNAP XML from FGP platform

Options:
    -f ISO datetime object that defines when to start harvesting (from date)
    -t ISO datetme object that defines when to end harvesting (to date)
    -e ISO string to define the harvester running environment staging/production
    -p ISO string to define the province were to request data from
"""

# CSW metadata extraction
# Output of this script is parsed by another into OGDMES-CKAN JSON.

# CMAJ: Shamlessly pillaged Ross Thompson's test script
# CMAJ: EC's (Mark Shaw, D. Sampson) XML Filters
# CMAJ: Tom Kralidis attempted to modernise our use of OWSLib
# CMAJ: Assembled by Chris Majewski @ StatCan

# CSW issues go to        : fgp-pgf@nrcan-rncan.gc.ca
# Metadata issues go to   : fgp-pgf@nrcan-rncan.gc.ca
# Open Data issues got to : open-ouvert@tbs-sct.gc.ca

# Called by OWSlib but may be requried if if a proxy is required
# No harm calling it early
import urllib2
# Requirement - OWSLib
# This script was writen to use OD's for of OWSLib
# > git clone https://github.com/open-data/OWSLib
# > cd /location/you/cloned/into
# > sudo python setup.py install
from owslib.csw import CatalogueServiceWeb
# Importing from a harvester.ini file
import os.path
# Pagination changes
import sys
import re
from lxml import etree
import docopt


def main():
    ## Connection variables
    env = 'STAGING'
    bgetprovdata = False
    strprovname = 0
    OrgNameSearchString = {
        "CANADA" :"Government_of_Canada",
        "CAN"    : "Government_of_Canada",
        "ALBERTA":"Government_of_Alberta",
        "AB":"Government_of_Alberta",
        "BRITISH":"Government_of_British_Columbia",
        "BC" : "Government_of_British_Columbia",
        "NEW-BRUNSWICK":"Government_of_New_Brunswick",
        "NB" : "Government_of_New_Brunswick",
        "YUKON":"Government_of_Yukon",
        "YK" : "Government_of_Yukon",
        "QUEBEC":"Government_and_Municipalities_of_Québec",
        "QC" : "Government_and_Municipalities_of_Québec",
        "PQ" : "Government_and_Municipalities_of_Québec",
        "ONTARIO":"Government_of_Ontario",
        "ON" : "Government_of_Ontario",
        "NOVA-SCOTIA":"Government_of_Nova_Scotia",
        "NS" : "Government_of_Nova_Scotia",
        "MANITOBA":"Government_of_Manitoba",
        "MB" : "Government_of_Manitoba",
        "NEWFOUNDLAND":"Government_of_Newfoundland_and_Labrador",
        "TN" : "Government_of_Newfoundland_and_Labrador",
        "Saskatchewan":"Government_of_Saskatchewan",
        "SK" : "Government_of_Saskatchewan",
        "NORTH-WEST": "Government_of_Northwest_Territories",
        "NW" : "Government_of_Northwest_Territories",
        "NUNAVUT":"Government_of_Nunavut",
        "NV" : "Government_of_Nunavut",
        "PRINCE-EDWARD-ISLAND":"Government_of_Prince_Edward_Island",
        "PEI" : "Government_of_Prince_Edward_Island",
        "IPE" : "Government_of_Prince_Edward_Island"
    }
    
    if arguments['-e']:
        env = arguments['-e']
    
    if arguments['-p']:
        provinput = arguments['-p'].upper()
        strprovname = OrgNameSearchString[provinput]
        bgetprovdata = True


    if env.upper() =='STAGING':
        csw_url = 'maps-staging.canada.ca/geonetwork/srv/csw' #Staging URL
    elif env.upper() =='PRODUCTION':
        csw_url = 'csw.open.canada.ca/geonetwork/srv/csw' #Prod URL 
    else :
        csw_url = 'maps-dev.canada.ca/geonetwork/srv/csw' #Dev URL

    csw_user = None
    csw_passwd = None

    proxy_protocol = None
    proxy_url = None
    proxy_user = None
    proxy_passwd = None
    records_per_request = 10

    # Or read from a .ini file
    harvester_file = 'config/harvester.ini'
    if os.path.isfile(harvester_file):
        from ConfigParser import ConfigParser

        ini_config = ConfigParser()

        ini_config.read(harvester_file)

        csw_url = ini_config.get(
            'csw', 'url')

        # Get configuration options
        if ini_config.has_option('csw', 'username'):
            csw_user = ini_config.get(
                'csw', 'username')

            csw_passwd = ini_config.get(
                'csw', 'password')

        if ini_config.has_option('proxy', 'protocol'):
            proxy_protocol = ini_config.get(
                'proxy', 'protocol')

        if ini_config.has_option('proxy', 'url'):
            proxy_url = ini_config.get(
                'proxy', 'url')

        if ini_config.has_option('proxy', 'username'):
            proxy_user = ini_config.get(
                'proxy', 'username')
            proxy_passwd = ini_config.get(
                'proxy', 'password')

        if ini_config.has_option('processing', 'records_per_request'):
            records_per_request = int(ini_config.get(
                'processing', 'records_per_request'))

        if ini_config.has_option('processing', 'start_date'):
            start_date = ini_config.get('processing', 'start_date')

    # If your supplying a proxy
    if proxy_url:
        # And your using authentication
        if proxy_user and proxy_passwd:
            password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(
                None, proxy_url, proxy_user, proxy_passwd)
            proxy_auth_handler = urllib2.ProxyBasicAuthHandler(password_mgr)
        # or even if your not
        else:
            proxy_auth_handler = urllib2.ProxyHandler(
                {proxy_protocol: proxy_url})

        opener = urllib2.build_opener(proxy_auth_handler)
        urllib2.install_opener(opener)

    # Fetch the data
    # csw = CatalogueServiceWeb(
    #   'https://csw_user:csw_pass@csw_url/geonetwork/srv/csw')
    if csw_user and csw_passwd:
        csw = CatalogueServiceWeb(
            'https://'+csw_url,
            username=csw_user,
            password=csw_passwd,
            timeout=20)
    else:
        csw = CatalogueServiceWeb('https://'+csw_url, timeout=20)

    request_template = """<?xml version="1.0"?>
<csw:GetRecords
    xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
    service="CSW"
    version="2.0.2"
    resultType="results_with_summary"
    outputSchema="csw:IsoRecord"
    maxRecords="%d"
    startPosition="%d"
>
    <csw:Query
        typeNames="gmd:MD_Metadata">
        <csw:ElementSetName>full</csw:ElementSetName>
        <csw:Constraint
            version="1.1.0">
            <Filter
                xmlns="http://www.opengis.net/ogc"
                xmlns:gml="http://www.opengis.net/gml">
                <PropertyIsGreaterThanOrEqualTo>
                    <PropertyName>_changeDate</PropertyName>
                    <Literal>%s</Literal>
                </PropertyIsGreaterThanOrEqualTo>
            </Filter>
        </csw:Constraint>
    </csw:Query>
</csw:GetRecords>
"""

    request_template_startenddate = """<?xml version="1.0"?>
<csw:GetRecords
    xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
    service="CSW"
    version="2.0.2"
    resultType="results_with_summary"
    outputSchema="csw:IsoRecord"
    maxRecords="%d"
    startPosition="%d"
>
    <csw:Query
        typeNames="gmd:MD_Metadata">
        <csw:ElementSetName>full</csw:ElementSetName>
        <csw:Constraint
            version="1.1.0">
            <Filter
                xmlns="http://www.opengis.net/ogc"
                xmlns:gml="http://www.opengis.net/gml">
                <PropertyIsGreaterThanOrEqualTo>
                    <PropertyName>changeDate</PropertyName>
                    <Literal>%s</Literal>
                </PropertyIsGreaterThanOrEqualTo>
            </Filter>
            <Filter
                xmlns="http://www.opengis.net/ogc"
                xmlns:gml="http://www.opengis.net/gml">
                <PropertyIsLessThanOrEqualTo>
                    <PropertyName>changeDate</PropertyName>
                    <Literal>%s</Literal>
                </PropertyIsLessThanOrEqualTo>                
            </Filter>            
        </csw:Constraint>
    </csw:Query>
</csw:GetRecords>
"""
    if bgetprovdata :
        request_template = """<?xml version="1.0"?>
<csw:GetRecords
    xmlns:csw="http://www.opengis.net/cat/csw/2.0.2" 
    service="CSW" 
    version="2.0.2" 
    resultType="results" 
    outputSchema="csw:IsoRecord" 
    maxRecords="%d" 
    startPosition="%d"
>
    <csw:Query
        typeNames="gmd:MD_Metadata">
        <csw:ElementSetName>full</csw:ElementSetName>
        <csw:Constraint
            version="1.1.0">
            <Filter
                xmlns="http://www.opengis.net/ogc" 
                xmlns:gml="http://www.opengis.net/gml">
                <PropertyIsLike matchCase="false" wildCard="%%" singleChar="_" escapeChar="\">
                    <PropertyName>OrganisationName</PropertyName>
                    <Literal>%s%%</Literal>
                </PropertyIsLike>
            </Filter>
        </csw:Constraint>
    </csw:Query>
</csw:GetRecords>
"""



    # Is there a specified start date
    if arguments['-f']:
        start_date = arguments['-f']

    # Is there a specified end date
    if arguments['-t']:
        end_date = arguments['-t']    
    
    
 
    active_page = 0
    next_record = 1
    request_another = True

    while request_another:

        request_another = False

        # Filter records into latest updates
        #
        # Sorry Tom K., we'll be more modern ASAWC.
        # For now it's good ol' Kitchen Sink
        #
        # from owslib.fes import PropertyIsGreaterThanOrEqualTo
        # modified = PropertyIsGreaterThanOrEqualTo(
        #   'apiso:Modified',
        #   '2015-04-04'
        # )
        # csw.getrecords2(constraints=[modified])
        #
        # Kitchen Sink is the valid HNAP, we need HNAP for R1 to debug issues
        # This filter was supplied by EC, the CSW service technical lead
        if bgetprovdata:
            current_request = request_template % (
            records_per_request,
            next_record,
            strprovname
            )
        else:
            current_request = request_template % (
            records_per_request,
            next_record,
            start_date )
        # # Is there a specified end date
        # if arguments['-t']:
        #     end_date = arguments['-t']   
        #     current_request = request_template_startenddate % (
        #         records_per_request,
        #         next_record,
        #         start_date,
        #         end_date
        #     )
        
        # (active_page*records_per_request)+1
        csw.getrecords2(format='xml', xml=current_request)
        active_page += 1

        # Identify if we need to continue this.
        records_root = ("/csw:GetRecordsResponse")

        # Read the file, should be a streamed input in the future
        root = etree.XML(csw.response)
        # Parse the root and itterate over each record
        records = fetchXMLArray(root, records_root)

        timestamp = fetchXMLAttribute(
            records[0], "csw:SearchStatus",
            "timestamp")[0]
        number_of_records_matched = int(fetchXMLAttribute(
            records[0], "csw:SearchResults",
            "numberOfRecordsMatched")[0]
        )
        number_of_records_returned = int(fetchXMLAttribute(
            records[0], "csw:SearchResults",
            "numberOfRecordsReturned")[0]
        )
        next_record = int(fetchXMLAttribute(
            records[0], "csw:SearchResults",
            "nextRecord")[0]
        )

        if next_record > number_of_records_matched or next_record == 0:
            pass
        else:
            request_another = True

        # When we move to Tom K's filter we can use results in an R2 unified
        # harvester
        # print csw.results
        # for rec in csw.records:
        #    print '* '+csw.records[rec].title
        # Till then we need to collect and dump the response from the CSW

        # No use minimizing the XML to try to create a XML Lines file as the
        # data has carriage returns.
        # parser = etree.XMLParser(remove_blank_text=True)
        # elem = etree.XML(csw.response, parser=parser)
        # print etree.tostring(elem)

        # Output the harvested page
        print csw.response


##################################################
# XML Extract functions
# fetchXMLArray(objectToXpath, xpath)
# fetchXMLAttribute(objectToXpath, xpath, attribute)


def fetchXMLArray(objectToXpath, xpath):
# Fetch an array which may be subsections
    return objectToXpath.xpath(xpath, namespaces={
        'gmd': 'http://www.isotc211.org/2005/gmd',
        'gco': 'http://www.isotc211.org/2005/gco',
        'gml': 'http://www.opengis.net/gml/3.2',
        'csw': 'http://www.opengis.net/cat/csw/2.0.2'})


def fetchXMLAttribute(objectToXpath, xpath, attribute):
# Fetch an attribute instead of a an element
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

if __name__ == "__main__":
    #options, arguments = docopt(__doc__)  # parse arguments based on docstring above
    arguments = docopt.docopt(__doc__)
    sys.exit(main())