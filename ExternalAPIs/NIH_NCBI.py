#-----------------------------------------------------------------------------
# NIH_NCBI.py:
# API to acquire data from NIH reporter and NCBI eutils
#
# Author: Sachira Kuruppu
# Date  : 16/07/2021
#-----------------------------------------------------------------------------

import time
import json
import requests
import urllib.parse as urlparser
from requests.structures import CaseInsensitiveDict

class NIH_NCBI:

    __NIH_timestamp = None  # can post only 1 request per second
    __NCBI_timestamp = None # can post only 3 requests per second

    #----------------------------------------------------
    # __maintainRequestFrequency:
    # This function maintains the request frequency specified by the API providers by
    # pausing the execution.
    #----------------------------------------------------
    def __maintainRequestFrequency (self, timestamp, request_per_second):
        seconds_per_request = 1 / request_per_second
        if (timestamp != None):
            dt = time.time() - timestamp
            if (dt < seconds_per_request):
                time.sleep(seconds_per_request - dt)
        return time.time()

    #----------------------------------------------------
    # _generateFundingDetailsPayload:
    # Given a project number, this private function generates a POST payload to be 
    # sent to the NIH reporter.
    #----------------------------------------------------
    def _generateFundingDetailsPayload(self, project_no):
        data = {'criteria': {'project_nums': project_no}}
        return json.dumps(data)
    
    #----------------------------------------------------
    # _generateNCBIpublicationRecord:
    # Generate a publication record from the json data retrieved from NCBI eutils
    #----------------------------------------------------
    def _generateNCBIpublicationRecord(self, jsonPub):
        data = {
            'title': jsonPub['title'],
            'journal': jsonPub['source'],
            'year': jsonPub['pubdate'].split(' ')[0],
        }


        author_list = ''
        for author in jsonPub['authors']:
            author_list = author['name'] + ', '
        data['author_list'] = author_list

        for id in jsonPub['articleids']:
            data[id['idtype']] = id['value']

        return data

    #----------------------------------------------------
    # _getPublicationFromPubmed:
    # Retrieve information about a publication using pm_id from NCBI eutils
    #----------------------------------------------------
    def _getPublicationFromPubmed(self, pm_id):
        self.__NCBI_timestamp = self.__maintainRequestFrequency(self.__NCBI_timestamp, 1)
        resp = requests.get(
            f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id={str(pm_id)}'
        )


        record = {}
        if (resp.status_code == 200):
            jsonData = json.loads(resp.content)

            if (len(jsonData['result']['uids']) > 0):
                record = self._generateNCBIpublicationRecord(jsonData['result'][str(pm_id)])

        return record

    #----------------------------------------------------
    # _getPublicationFromPMC:
    # Retrieve information about a publication from PMC using the pmc_id from NCBI eutils
    #----------------------------------------------------
    def _getPublicationFromPMC(self, pmc_id):
        self.__NCBI_timestamp = self.__maintainRequestFrequency(self.__NCBI_timestamp, 1)
        resp = requests.get(
            f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pmc&retmode=json&id={str(pmc_id)}'
        )


        record = {}
        if (resp.status_code == 200):
            jsonData = json.loads(resp.content)

            if (len(jsonData['result']['uids']) > 0):
                record = self._generateNCBIpublicationRecord(jsonData['result'][str(pmc_id)])

        return record
    
    #----------------------------------------------------
    # getCitedBy:
    # Get the articles that cite a given publication specified by pmc_id or
    # pm_id. 'idtype' specifies 'pm_id' or 'pmc_id'. 'id' gives the respective
    # id.
    #----------------------------------------------------
    def getCitedBy(self, id_type, id):
        urls = []
        if id_type == 'pm_id':
            urls.extend(
                (
                    f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&linkname=pubmed_pubmed_citedin&retmode=json&id={str(id)}',
                    f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&linkname=pubmed_pmc_refs&retmode=json&id={str(id)}',
                )
            )

        elif id_type == 'pmc_id':
            urls.append(
                f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&linkname=pmc_pmc_citedby&retmode=json&id={str(id)}'
            )


        record = {}

        for url in urls:
            self.__NCBI_timestamp = self.__maintainRequestFrequency(self.__NCBI_timestamp, 1)
            resp = requests.get(url)

            if (resp.status_code != 200):
                return {}

            jsonData = json.loads(resp.content)
            linksets = jsonData['linksets'][0]

            if ('linksetdbs' not in linksets):
                continue

            cited_by = linksets['linksetdbs'][0]

            for cited_id in cited_by['links']:
                pub = {}
                if (cited_by['dbto'] == 'pubmed'):
                    pub = self._getPublicationFromPubmed(cited_id)
                elif (cited_by['dbto'] == 'pmc'):
                    pub = self._getPublicationFromPMC(cited_id)

                # Ignore if the publication doesn't have a doi
                if 'doi' in pub:
                    record[pub['doi']] = pub

        return record
    
    #----------------------------------------------------
    # getProjectFundingDetails:
    # This function retrieves data from NIH reporter for a given project identified by
    # the 'project_no'.
    # project_no = [List of project numbers]
    #----------------------------------------------------
    def getProjectFundingDetails (self, project_no):
        self.__NIH_timestamp = self.__maintainRequestFrequency(self.__NIH_timestamp, 1)
        url = "https://api.reporter.nih.gov/v1/projects/Search/"
        headers = CaseInsensitiveDict()
        headers["Content-Type"] = "application/json"

        payload = self._generateFundingDetailsPayload(project_no)
        resp = requests.post(url, headers=headers, data=payload)
        
        if (resp.status_code == 200):
            return json.loads(resp.content)
        
        return {}

    #----------------------------------------------------
    # generateRecord:
    # Given the json object containing the data recevied from NIH reporter,
    # this function generates a dict containing only the important fields, that has to be
    # stored in the central database.
    #----------------------------------------------------
    def generateRecord(self, jsonData):
        record = {}

        for sub_project in jsonData['results']:
            data = {
                'appl_id': sub_project['appl_id'],
                'institute': sub_project['org_name'],
                'country': sub_project['org_country'],
                'amount': sub_project['award_amount'],
                'year': sub_project['fiscal_year'],
                'keywords': sub_project['terms'],
            }

            record[sub_project['project_num']] = data
        return record
    
    #----------------------------------------------------
    # getPublications:
    # Retrieve publications associated with a given grant application identified by the "appl_id"
    #----------------------------------------------------
    def getPublications(self, appl_id):
        self.__NIH_timestamp = self.__maintainRequestFrequency(self.__NIH_timestamp, 1)
        resp = requests.get(
            f'https://reporter.nih.gov/services/Projects/Publications?projectId={str(appl_id)}'
        )


        record = {}
        if (resp.status_code == 200):
            jsonPub = json.loads(resp.content)

            for pub in jsonPub['results']:
                pubmed_data  = self._getPublicationFromPubmed(pub['pm_id'])

                data = {
                    'title': pub['pub_title'],
                    'journal': pub['journal_title'],
                    'year': pub['pub_year'],
                    'author_list': pub['author_list'],
                    'url': pub['journal_title_link']['value'],
                    'pm_id': pub['pm_id'],
                }

                # Ignore if the paper doesn't have a doi
                if ('doi' in pubmed_data):
                    data['doi']                = pubmed_data['doi']
                    record[pubmed_data['doi']] = data

        return record

    #----------------------------------------------------
    # getPublicationWithSearchTerm:
    # Get all publications that mention the given search term.
    #----------------------------------------------------
    def getPublicationWithSearchTerm(self, search_term):
        self.__NCBI_timestamp = self.__maintainRequestFrequency(self.__NCBI_timestamp, 1)
        term = urlparser.quote(str(search_term), safe='')
        resp = requests.get(
            f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pmc&retmode=json&term={term}'
        )


        record = {}
        if (resp.status_code == 200):
            jsonData = json.loads(resp.content)
            pmc_ids = jsonData['esearchresult']['idlist']

            for pmc_id in pmc_ids:
               pub = self._getPublicationFromPMC(pmc_id)

               # Ignore if the publication doesn't have a doi
               if 'doi' in pub:
                   record[pub['doi']] = pub

        return record
    