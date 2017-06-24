'''
Call this module to query the TargetDB database. Returns a pandas dataframe.

    My main program query_TargetDb calls the function queryTFDB to generate df
    for each TF
'''

##############
# Modules
from __future__ import absolute_import
import pandas as pd
from ....models import TargetDBTF, Edges, Metadata, Analysis, Annotation, ReferenceId, \
    Interactions, Regulation, MetaIddata
#from create_mysqlDB_v2 import TargetDBTF, Edges, Annotation, Interactions, ReferenceId, Metadata, Analysis
from sqlalchemy import and_

################################################
# Query the database
#@profile
def queryTFDB(q_TFname):
    rs = list(Interactions.objects.select_related().filter(db_tf_id__db_tf_agi__exact=q_TFname). \
              values_list('db_tf_id__db_tf_agi', 'edge_id__edge_name', 'target_id__agi_id', 'ref_id__ref_id'))

    rs_pd = pd.DataFrame(rs, columns=['TF', 'EDGE', 'TARGET', 'REFID'])
    list_ref_id = rs_pd.REFID.unique()
    meta_ref = ReferenceId.objects.select_related().filter(ref_id__in=list_ref_id). \
        values_list('ref_id', 'meta_id__meta_fullid', 'analysis_id__analysis_fullid')
    print('meta_ref= ', meta_ref)

    meta_ref_dict = dict()
    for val_m in meta_ref:
        meta_ref_dict[val_m[0]] = '_'.join([val_m[1], val_m[2], str(val_m[0])])

    # Pandas query func throws an error if columns names are numbers so I had to include meta_id in RefID
    # column name '1', '1_2', '1_a' etc. will not work
    if not rs_pd.empty:
        rs_pd.REFID.replace(to_replace=meta_ref_dict, inplace=True)
        # pvalues '.' are replaces because pandas does not allow to use these chars with pandas.query
        rs_pd['REFID'] = rs_pd['REFID'].str.replace('.', '_')

    return rs_pd