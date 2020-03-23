# -*- coding: latin-1 -*-
import os
import sys, getopt
import datetime

CKANKEY = None
PRODURL = None
STAGINGURL = None
LOCALBINPATH = None
RESOURCEFILEPATH = None
DEVURL = None
S3BUCKETNAME = None
S3RESOURCEFILENAME = None
#OPERATION_ENV = 'production' 
### or ### 
OPERATION_ENV = 'staging'
LOGFILEPATH = "/tmp/harvester/logs"
FORCEREMOVELOCKFILE = None
FORCEHARVESTSTART = False
PUSHDATA = "TRUE"

def main(argv):
   inputfile = ''
   outputfile = ''
   try:
      opts, args = getopt.getopt(argv,"hi:o:",["outenv="])
   except getopt.GetoptError:
      print 'test.py -o <outputEnvcc>'
      sys.exit(2)
   for opt, arg in opts:
      if opt == '-h':
         print 'usage: globals.py --outenv=1/true'
         sys.exit()
      elif opt in ("-o", "--outenv"):
            if(arg=='1' or arg.upper()=='TRUE'):
                print OPERATION_ENV.upper()

if __name__ == "__main__":
   main(sys.argv[1:])


