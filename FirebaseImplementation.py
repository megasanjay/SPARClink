#--------------------------------------------------------------
# FirebaseImplementation.py
# This script implements a firebase database with all the data
#
# Author: Sachira Kuruppu
# Date  : 22/07/2021
#--------------------------------------------------------------

from collections import UserString
import time
from pyasn1_modules.rfc2459 import Time
import pyrebase
from dotenv import dotenv_values

from ExternalAPIs.NIH_NCBI import NIH_NCBI
import SPARC.metadata_extraction as SPARC

#******************* Update with firebase API key*******************#
firebaseConfig = {
    'apiKey': "AIzaSyBZGI1EbzcsoPnplzgBGWYZBF0CHwR4BnY",
    'authDomain': "sparclink-f151d.firebaseapp.com",
    'databaseURL': "https://sparclink-f151d-default-rtdb.firebaseio.com",
    'projectId': "sparclink-f151d",
    'storageBucket': "sparclink-f151d.appspot.com",
    'messagingSenderId': "168500342210",
    'appId': "1:168500342210:web:8675fcd3db2f527916ba5b",
    'measurementId': "G-N1K2EXBDZG"
}
#*******************************************************************#

ENV_CONFIG = dotenv_values('.env')

firebase = pyrebase.initialize_app(firebaseConfig)
auth     = firebase.auth()

email    = input('Enter email: ')
passw    = input('Enter password: ')
user     = auth.sign_in_with_email_and_password(email, passw)

db = firebase.database()
NN = NIH_NCBI()

disallowed_chars = {ord(c):None for c in "$#[]/. "}
Timestamp = time.time()

#--------------------------------------------------------------
# uploadDatasets:
# Retrieve datasets from SPARC pennsieve and associated papers,
# and upload to firebase. It returns a list of award ids to look for awards
#--------------------------------------------------------------
def uploadDatasets(skip=0):
    print('Processing datasets...')

    global user
    global Timestamp

    award_list = {}

    # Get all the datasets from Sparc Portal
    sparc_dataset_list = []
    sparc_dataset_list = SPARC.get_list_of_datasets_with_metadata(sparc_dataset_list)

    curr_dataset = 0
    for dataset in sparc_dataset_list:
        curr_dataset += 1
        if (curr_dataset < skip):
            continue

        print("--- Processing dataset: {0} ({1}/{2})".format(dataset['datasetDOI'], curr_dataset, len(sparc_dataset_list)))

        # update the user token if its been more than 30 min
        dt = time.time() - Timestamp
        if (dt > 1800):
            refreshed_user       = auth.refresh(user['refreshToken'])
            user['idToken']      = refreshed_user['idToken']
            user['refreshToken'] = refreshed_user['refreshToken']
            Timestamp = time.time()

        # Insert the dataset to the database
        dataset_key = dataset['datasetDOI'].translate(disallowed_chars)

        dataset_record = {
            'doi': dataset['datasetDOI'],
            'name': dataset['name'],
            'description': dataset['description'],
            'award': dataset['properties']['award_id'],
            'protocols': [
                p.translate(disallowed_chars)
                if (p.find('org') == -1)
                else p.split('.org/')[1].translate(disallowed_chars)
                for p in dataset['protocolsDOI']
            ],
        }

        dataset_record['tags']          = dataset['tags']

        db.child(user['localId']).child('Datasets').update({dataset_key: dataset_record}, user['idToken'])

        # Add originating article if available
        originating_articles = {}
        for doi in dataset['originatingArticleDOI']:
            if (doi.find('org') != -1):
                doi = doi.split('.org/')[1]
            originating_articles |= NN.getPublicationWithSearchTerm('{0}[doi]'.format(doi))

        # Add protocols used by the dataset
        uploadDatasetProtocols(dataset['protocolsDOI'])

        # Find papers associated with the dataset. i.e. papers that mention the dataset doi. Upload.
        dataset_pub_records = NN.getPublicationWithSearchTerm('"{0}"'.format(dataset_record['doi'].split('.org/')[1]))
        dataset_pub_records.update(originating_articles)

        for i, k in enumerate(dataset_pub_records, start=1):
            print("---- Uploading paper : {0} / {1}".format(i, len(dataset_pub_records)))

            paper_key = k.translate(disallowed_chars)
            dataset_pub_records[k]['datasets'] = [dataset_key]
            dataset_pub_records[k]['citations']= 0
            dataset_pub_records[k]['direct']   = True # indicate that this paper is directly associated with SPARC

            uploadPaperOrUpdate(paper_key, 'datasets', dataset_pub_records[k])

        award_list[dataset_key] = dataset_record['award']

    return award_list

#--------------------------------------------------------------
# uploadAwards:
# Retrieve information about a given list of awards from NIH reporter, 
# find associated papers, and upload to firebase.
#--------------------------------------------------------------
def uploadAwards(award_list):
    print('Processing awards...')

    global user
    global Timestamp

    for curr_dataset, dataset_key in enumerate(award_list, start=1):
        # update the user token if its been more than 30 min
        dt = time.time() - Timestamp
        if (dt > 1800):
            refreshed_user       = auth.refresh(user['refreshToken'])
            user['idToken']      = refreshed_user['idToken']
            user['refreshToken'] = refreshed_user['refreshToken']
            Timestamp = time.time()

        award_num = award_list[dataset_key]

        print("--- Processing award of dataset: {0} ({1}/{2})".format(dataset_key, curr_dataset, len(award_list)))
        award_record = NN.generateRecord(NN.getProjectFundingDetails([ award_num ]))
        db.child(user['localId']).child('Awards').update({award_num: award_record}, user['idToken'])

        # Collect papers associated with the award
        award_pub = {}
        for k in award_record:
            sub_award = award_record[k]
            pubs = NN.getPublications(sub_award['appl_id'])
            award_pub |= pubs

        for i, (k, v) in enumerate(award_pub.items(), start=1):
            print("---- Uploading paper: {0} / {1}".format(i, len(award_pub)))

            paper_key = k.translate(disallowed_chars)
            award_pub[k]['awards']   = [award_num]
            award_pub[k]['citations']= 0
            award_pub[k]['direct']   = True # indicate that the paper is directly associated with SPARC

            uploadPaperOrUpdate(paper_key, 'awards', v)

    return

#--------------------------------------------------------------
# uploadDatasetProtocols:
# Upload the protocols given in the dataset. This is done here because 
# the protocols may not be from SPARC. If it is a SPARC protocol, 
# it will be updated in the protocol step.
#--------------------------------------------------------------
def uploadDatasetProtocols(dataset_protocol_list):
    # Add protocols.
    for protocol_doi in dataset_protocol_list:
        protocol_key = ''
        if (protocol_doi.find('org') != -1):
            protocol_doi_only = protocol_doi.split('.org/')[1]

        protocol_key = protocol_doi_only.translate(disallowed_chars)
        protocol_record = db.child(user['localId']).child('Protocols').child(protocol_key).get(user['idToken']).val()

        if protocol_record is None:
            # protocol doesn't exist
            db.child(user['localId']).child('Protocols').update({protocol_key: {'url': protocol_doi, 'doi': protocol_doi_only}}, user['idToken'])

        # Add papers associated with the protocol
        protocol_pub_records = NN.getPublicationWithSearchTerm('"{0}"'.format(protocol_doi_only))

        for i, k in enumerate(protocol_pub_records, start=1):
            print("---- Uploading protocol papers : {0} / {1}".format(i, len(protocol_pub_records)))

            paper_key = k.translate(disallowed_chars)
            protocol_pub_records[k]['protocols'] = [protocol_key]
            protocol_pub_records[k]['citations']= 0
            protocol_pub_records[k]['direct']   = True # indicate that this paper is directly associated with SPARC

            uploadPaperOrUpdate(paper_key, 'protocols', protocol_pub_records[k])
            


#--------------------------------------------------------------
# uploadProtocols:
# Retrieve protocol information from SPARC protocols.io, and upload to firebase
#--------------------------------------------------------------
def uploadProtocols():
    global user
    global Timestamp

    print('Processing protocols...')

    sparc_protocol_list = SPARC.parsing_protocols(ENV_CONFIG['PROTOCOLS_IO_KEY'])

    curr_protocol = 0
    for protocol in sparc_protocol_list:
        curr_protocol += 1

        # update the user token if its been more than 30 min
        dt = time.time() - Timestamp
        if (dt > 1800):
            refreshed_user       = auth.refresh(user['refreshToken'])
            user['idToken']      = refreshed_user['idToken']
            user['refreshToken'] = refreshed_user['refreshToken']
            Timestamp = time.time()

        # Ignore if the protocol doesn't have a doi
        if 'doi' not in protocol:
            continue

        if (protocol['doi'].find('org') != -1):
            protocol['doi'] = protocol['doi'].split('./org')[1]

        protocol_key = protocol['doi'].translate(disallowed_chars)

        print("--- Processing protocol {0} / {1}".format(curr_protocol, len(sparc_protocol_list)))

        protocol_record = {
            'title': protocol['title'],
            'authors': protocol['authors'],
            'url': protocol['url'],
            'doi': protocol['doi'],
        }

        db.child(user['localId']).child('Protocols').update({protocol_key: protocol_record}, user['idToken'])

        # Find papers associated with the protocol

        protocol_pub_records   = NN.getPublicationWithSearchTerm('"{0}"'.format(protocol_record['doi']))
        protocol_pub_records_2 = NN.getPublicationWithSearchTerm('"{0}"'.format(protocol_record['url']))
        protocol_pub_records.update(protocol_pub_records_2)

        for i, k in enumerate(protocol_pub_records, start=1):
            print("---- Uploading paper : {0} / {1}".format(i, len(protocol_pub_records)))

            paper_key = k.translate(disallowed_chars)
            protocol_pub_records[k]['protocols'] = [protocol_key]
            protocol_pub_records[k]['citations']= 0
            protocol_pub_records[k]['direct']   = True # indicate that this paper is directly associated with SPARC

            uploadPaperOrUpdate(paper_key, 'protocols', protocol_pub_records[k])

    return

#--------------------------------------------------------------
# uploadCitations:
# Find the citations for each direct paper in firebase, and uplaod them.
#--------------------------------------------------------------
def uploadCitations(skip=0):
    global user
    global Timestamp

    print('Processing citations...')

    papers = db.child(user['localId']).child('Papers').get(user['idToken']).val()

    curr_paper = 0
    for paper_key in papers:
        curr_paper += 1

        if (curr_paper < skip):
            continue

        # update the user token if its been more than 30 min
        dt = time.time() - Timestamp
        if (dt > 1800):
            refreshed_user       = auth.refresh(user['refreshToken'])
            user['idToken']      = refreshed_user['idToken']
            user['refreshToken'] = refreshed_user['refreshToken']
            Timestamp = time.time()

        paper = papers[paper_key]

        # Ignore if the paper is not directly connected to SPARC
        if ('direct' not in paper or paper['direct'] != True):
            continue

        print("--- Processing paper ({0}/{1})".format(curr_paper, len(papers)))

        citedby = {}
        if ('pm_id' in paper):
            citedby = NN.getCitedBy('pm_id', paper['pm_id'])
        elif ('pmc_id' in paper):
            citedby = NN.getCitedBy('pm_id', paper['pmc_id'])

        db.child(user['localId']).child('Papers').child(paper_key).update({'citations': len(citedby)}, user['idToken'])

        for i, kk in enumerate(citedby, start=1):
            print("---- Uploading citation {0}/{1}".format(i, len(citedby)))

            citedby[kk]['papers']   = [paper_key]
            citedby[kk]['direct']   = False
            uploadPaperOrUpdate(kk.translate(disallowed_chars), 'papers', citedby[kk])

    return

#-----------------------------------------------------------------------------------
# uploadPaperOrUpdate:
# Upload the given paper record 'newPaper' to the database if does not exist. If it
# exists, update the field (list) stipulated by 'update_key' (which can be datasets,
# awards, or papers) by appending the values in 'newPaper'.
#-----------------------------------------------------------------------------------
def uploadPaperOrUpdate (paper_key, update_key, newPaper):
    # See if the db already has this paper
    pub_data = db.child(user['localId']).child('Papers').child(paper_key).get(user['idToken']).val()
    if pub_data is None:
        # The db does not have this paper
        db.child(user['localId']).child('Papers').update({paper_key: newPaper}, user['idToken'])
    else:
        # The db has this paper. Only update the datasets field
        if (update_key in pub_data):
            update_field = pub_data[update_key]
            update_field += newPaper[update_key]
        else:
            update_field = newPaper[update_key]
        
        update_field = set(update_field) # remove duplicates
        db.child(user['localId']).child('Papers').child(paper_key).update({update_key: list(update_field)}, user['idToken'])
    return


def main():
    print('-------------------------------------')
    print('Firebase Implementation v1.1')
    print('-------------------------------------\n')
    print('Enter the portion of the code to run.')
    print('[1] Datasets + Awards')
    print('[2] Protocols')
    print('[3] Citations')
    print('[4] Datasets + Awards + Protocols + Citations')

    x = input(': ')
    if (x == '1'):
        award_list = uploadDatasets()
        uploadAwards(award_list)
    elif (x == '2'):
        uploadProtocols()
    elif (x == '3'):
        uploadCitations()
    else:
        award_list = uploadDatasets()
        uploadAwards(award_list)
        uploadProtocols()
        uploadCitations()
    return

if __name__ == '__main__':
    main()