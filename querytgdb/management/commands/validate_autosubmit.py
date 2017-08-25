#!/usr/bin/env python

from ...models import Metadata, Analysis, ReferenceId
from django.core.management.base import BaseCommand
import sys

'''
This script validates the data based on the crietria below:
    1) If metadata file entires are correct
    2) All the uploaded files are in tab-delimited format
    3) Have correct number of columns and data entered in files is in specified format
    4) No duplicated genes in read count and gene list file
    5) All the samples provided in read count should be included in experimental design file
If the data pass all the above validation steps, run the insert script.
'''


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-i', '--genelist', help= 'User submitted genelist file', required= True)
        parser.add_argument('-m', '--metadatafile', help= 'User submitted metadata file', required= True)
        parser.add_argument('-r', '--readcount', help= 'User submitted readcount file', required= True)
        parser.add_argument('-e', '--expdesign', help= 'User submitted experimental design file', required= True)


    def handle(self, *args, **options):
        metadict= self.validate_metadata(options['metadatafile'])
        self.validate_genelist(options['genelist'], metadict)
        self.validate_readcount_expdesign(options['readcount'], options['expdesign'])


    def validate_metadata(self, metadatafile):

        print('metadatafile= ',metadatafile)
        # 1. throw an error if the experiment id and analysis id already exists
        # Should submit RNASEQ1, RNASEQ2 or submit as a newid
        # read meta data input file- store data in a dictionary
        metadict = dict()
        metadata = open(metadatafile, 'r', encoding='utf-8')
        for valm in metadata:
            if not valm.split(':')[1].strip().upper() == 'NA':
                metadict[valm.split(':')[0].strip().upper()] = valm.split(':')[1].upper().strip()

        # Raise error if both metaid and analysisid already exists in the database
        try:
            rs_meta= Metadata.objects.values_list('meta_fullid', flat=True) # get the existing meta_fullid from the database
            allmetaid= list(set(rs_meta))
        except Exception as e:
            allmetaid=[]

        meta_exist_flag = 0
        existed_exp_id = None

        # if experiment ID already exists: check if for the same exp, analysis_id provided in the current file also exists
        if metadict['Experiment_ID'.upper()].upper().strip() in allmetaid:
            print('\nMetaid already Exist!')
            meta_exist_flag = meta_exist_flag + 1
            ref_data = ReferenceId.objects.filter(meta_id__meta_fullid__exact=metadict['Experiment_ID'.upper()].upper(),
                       analysis_id__analysis_fullid__exact=metadict['Analysis_ID'.upper()].upper()).values('analysis_id')

            if not ref_data:
                exist_mdata_tmp = ReferenceId.objects.filter(meta_id__meta_fullid__exact=metadict['Experiment_ID'.upper()].
                                                      upper()).distinct().values_list('meta_id', flat=True)
                existed_exp_id = list(exist_mdata_tmp)[0]
            else:  # Cannot submit an experiment as both exp and analysis id already exist
                print('\nError: Experiment ID and analysis ID provided in the Metadata file ',metadict['Experiment_ID'.upper()].
                          upper(), ' and ', metadict['Analysis_ID'.upper()].upper(), ' already exists in the database')
                print('Provide a different Experiment ID, Experiment version or a different analysis ID to submit your data\n')
                # Raise Error 1
                raise ValueError('Experiment ID and analysis ID provided in the Metadata file already exists in the database!\n')

        # 2. No spaces entered in any of the entered values except type column.
        #print('metadict= ', metadict)
        for val_checkspace in metadict:
		# check '\t','\r' other chars
            if ' ' in val_checkspace.strip():
                #print('No spaces allowed in metadata types and values')
                # Raise Error 2
                raise ValueError('No spaces allowed in metadata types and values')
            if ' ' in metadict[val_checkspace] and (not val_checkspace.strip().upper() in ['ANALYSIS_COMMAND','ANALYSIS_NOTES',
                                                                           'METADATA_NOTES','TF_HISTORY']):
                # spaces can be allowed in Analysis_command, Analysis_notes, Metadata_notes and 'TF_History' values
                #print('No spaces allowed in metadata types and values')
                # Raise Error 3
                raise ValueError('No spaces allowed in metadata types and values')
            # For value fields make sure there are no colon ":" characters as colons are used to separate type field from
            # value fields. Check if there are colons in values.
            if ':' in metadict[val_checkspace]:
                print('No colon character ":" allowed in metadata values')
                # Raise Error 4
                raise ValueError('No colon character ":" allowed in metadata values')

        # 3. Not sure if there is any way to check treatments and replicates?

        # 4. check if the analysis method selected is valid. If you select expression, you cannot select macs2.
        # Waiting for new file format generated by Zach.

        print('Metadata file successfully validated!\n')

        return metadict

    def validate_genelist(self, genelist, metadict):

        print('genelist= ',genelist)
        g_list= open(genelist, 'r', encoding='utf-8')

        genelist_col1= list() # contains genelist to test for duplicate genes in the file
        # Allow 5 columns for RNAseq, separated by '/t' and the data entered for all the columns is in order.

        if metadict['EXPERIMENT'] == 'TARGET':
            if metadict['EXPRESSION_TYPE'] == 'RNASEQ':
                for i, val_glist in enumerate(g_list):
                    genelist_col1.append(val_glist.split('\t')[0].strip().upper())
                    if not val_glist.count('\t') == 4:
                        # Raise Error 5
                        print('File format is not correct')
                        raise ValueError('RNAseq input file should contain 5 columns')

                    # checking here Col1 is a geneids, Col2 is pval (values between 0 and 1), Col3 is induced or repressed,
                    # Col4 is a string and Col5 is fold change. Display message on GUI to provide only the log2 fold changes.
                    if not (val_glist.split('\t')[0].strip().isalnum() and\
                    (float(val_glist.split('\t')[1].strip())>=0 and float(val_glist.split('\t')[1])<=1) and\
                    (val_glist.split('\t')[2].upper().strip()=='INDUCED' or
                        val_glist.split('\t')[2].upper().strip()=='REPRESSED') and\
                    (val_glist.split('\t')[3].isalpha()) and isinstance(float(val_glist.split('\t')[4]), (int, float))):

                        # Raise Error 6
                        raise ValueError('RNAseq input file did not pass the validation step. Check line number:',i)

            elif metadict['EXPRESSION_TYPE'] == 'CHIPSEQ':
                for j, val_glist1 in enumerate(g_list):
                    genelist_col1.append(val_glist1.split('\t')[0].strip().upper())
                    if not val_glist1.count('\t') == 4:
                        # Raise Error 5
                        print('File format is not correct')
                        raise ValueError('ChIPseq input file should contain 5 columns')

                    # checking here Col1 is a geneids, Col2 is pval (values between 0 and 1), Col3 is timepoint,
                    # Col4 is a string and Col5 is fold change. Display message on GUI to provide only the log2 fold changes.
                    if not (val_glist1.split('\t')[0].strip().isalnum() and \
                        (float(val_glist1.split('\t')[1].strip()) >= 0 and float(val_glist1.split('\t')[1]) <= 1) and \
                        (val_glist1.split('\t')[2].isdigit()) and \
                        (val_glist1.split('\t')[3].isalpha()) and isinstance(float(val_glist1.split('\t')[4]), (int, float))):

                        # Raise Error 6
                        raise ValueError('ChIPseq input file did not pass the validation step. Check line number:',j)

        if metadict['EXPERIMENT'] == 'INPLANTA':
            print('Inplanta data columns can vary. The code does not test the inplanta data at the moment but soon to be '
                  'implemented')

        # Checking for duplicated genes in gene list file
        duplicategenes= set(x for x in genelist_col1 if genelist_col1.count(x) > 1)
        if duplicategenes:
            # Raise Error 7
            raise ValueError('Gene list file contains duplicate genes: check and resubmit ',duplicategenes)

        print('Genelist file successfully validated!\n')


    def validate_readcount_expdesign(self, readcount, expdesign):

        # No duplicate genes in read count file. Read count file should have all the Ath genes.
        # Experimental design file should have all the samples from read count.

        print('readcount= ',readcount)
        print('expdesign= ',expdesign)

        rcount_glist= list()
        with open(readcount, 'r', encoding='utf-8') as readcountdata:
            rcount_header= [x.strip().upper() for x in next(readcountdata).split('\t')]
            for val_rcount in readcountdata:
                rcount_glist.append(val_rcount)

        duplicategenes_rcount= set([x for x in rcount_glist if rcount_glist.count(x) > 1])
        if duplicategenes_rcount:
            # Raise Error 8
            raise ValueError('Read count file contains duplicate genes: check and resubmit ',duplicategenes_rcount)

        expdesign_samples= list()
        # check if the expdesign file has all the samples from readcount file. Nothing should be duplicated.
        with open(expdesign, 'r', encoding='utf-8') as expdesigndata:
            for val_edesign in expdesigndata:
                expdesign_samples.append(val_edesign.split('\t')[0].strip().upper())
        print('test_rcount_header= ',rcount_header)
        if not (set(filter(None, rcount_header)) == set(filter(None, expdesign_samples))):
            print('rcount_header= ',set(rcount_header))
            print('expdesign_samples= ',set(expdesign_samples))
            # Raise Error 9
            raise ValueError('Read count and experimental design file do not share the same samples')

        duplicatesamples_rcount= set(x for x in rcount_header if rcount_header.count(x) > 1)
        if duplicatesamples_rcount:
            # Raise Error 10
            raise ValueError('Duplicate sample names in read count file')

        duplicatesamples_design= set(x for x in expdesign_samples if expdesign_samples.count(x) > 1)
        if duplicatesamples_design:
            # Raise Error 11
            raise ValueError('Duplicate sample names in experimental design file')

        print('Read count and experimental design files successfully validated!\n')