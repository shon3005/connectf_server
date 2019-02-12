import logging
import re
import sys
from operator import attrgetter, itemgetter
from typing import Tuple

import numpy as np
import pandas as pd
from django.db.transaction import atomic

from querytgdb.models import Analysis, AnalysisData, Annotation, EdgeData, EdgeType, Interaction, MetaKey, Regulation
from querytgdb.utils.sif import get_network

nan_regex = re.compile(r'^n/?an?$', flags=re.I)
searchable = ['TRANSCRIPTION_FACTOR_ID', 'EXPERIMENT_TYPE', 'EXPERIMENTER', 'DATE', 'TECHNOLOGY', 'ANALYSIS_METHOD',
              'ANALYSIS_CUTOFF', 'EDGE_TYPE', 'GENOTYPE', 'DATA_SOURCE', 'TREATMENTS', 'CONTROL', 'TISSUE/SAMPLE']


def process_meta_file(f) -> pd.Series:
    metadata = pd.Series(f.readlines())

    metadata = (metadata
                .str.split(':', 1, True)
                .apply(lambda x: x.str.strip())
                .replace([r'', nan_regex], np.nan, regex=True)
                .dropna(subset=[0])
                .fillna('')
                .set_index(0, verify_integrity=True)
                .squeeze())

    metadata.index = metadata.index.str.upper().str.replace(' ', '_')

    date_rows = metadata.index.str.contains(r'_?DATE$')

    if date_rows.any():
        metadata[date_rows] = pd.to_datetime(
            metadata[date_rows], infer_datetime_format=True).dt.strftime('%Y-%m-%d')

    return metadata


def process_data(f, sep=',') -> Tuple[pd.DataFrame, bool]:
    data = pd.read_csv(f, header=0, sep=sep,
                       na_values=['#DIV/0!', '#N/A!', '#NAME?', '#NULL!', '#NUM!', '#REF!', '#VALUE!'])
    data = data.dropna(axis=0, how='all').dropna(axis=1, how='all')

    cols = data.shape[1]

    if cols == 3:
        data.columns = ['gene_id', 'log2fc', 'pvalue']

        data['log2fc'] = data['log2fc'].mask(np.isneginf(data['log2fc']), -sys.float_info.max)
        data['log2fc'] = data['log2fc'].mask(np.isposinf(data['log2fc']), sys.float_info.max)

        return data, True
    elif cols == 1:
        data.columns = ['gene_id']
        return data, False
    else:
        raise ValueError(
            "Malformed Data. Must have 1 gene id column, optionally accompanied by 2 columns, log2 fold change and "
            "adjusted p-value.")


def insert_data(data_file, metadata_file, sep=','):
    data, has_pvals = process_data(data_file, sep=sep)

    try:
        with open(metadata_file) as m:
            metadata = process_meta_file(m)
    except TypeError:
        metadata = process_meta_file(metadata_file)

    try:
        tf = Annotation.objects.get(gene_id=metadata['TRANSCRIPTION_FACTOR_ID'])
    except Annotation.DoesNotExist:
        raise ValueError('Transcription Factor ID {} does not exist.'.format(metadata['TRANSCRIPTION_FACTOR_ID']))

    if not metadata.index.contains('EDGE_TYPE'):
        raise ValueError('Please assign an EDGE_TYPE to the metadata.')

    if not metadata.index.contains('EXPERIMENT_TYPE'):
        raise ValueError('Please assign an EXPERIMENT_TYPE to the metadata. Typically Expression or Binding.')

    # Insert Analysis
    analysis = Analysis(tf=tf)
    analysis.save()

    meta_keys = [MetaKey.objects.get_or_create(name=n, defaults={'searchable': n in searchable})
                 for n in metadata.index]

    meta_key_frame = pd.DataFrame(((m.id, m.name, m.searchable, c) for m, c in meta_keys),
                                  columns=['id', 'name', 'searchable', 'created'])
    meta_key_frame = meta_key_frame.set_index('name')

    AnalysisData.objects.bulk_create(
        [AnalysisData(analysis=analysis, key_id=meta_key_frame.at[key, 'id'], value=val)
         for key, val in metadata.iteritems()])

    anno = pd.DataFrame(Annotation.objects.filter(
        gene_id__in=data.iloc[:, 0]
    ).values_list('gene_id', 'id', named=True).iterator())

    data = data.merge(anno, on='gene_id')

    Interaction.objects.bulk_create(
        Interaction(
            analysis=analysis,
            target_id=row.id
        ) for row in data.itertuples()
    )

    if has_pvals:
        Regulation.objects.bulk_create(
            Regulation(
                analysis=analysis,
                foldchange=row.log2fc,
                p_value=row.pvalue,
                target_id=row.id
            ) for row in data.itertuples(index=False)
        )


logger = logging.getLogger(__name__)


def read_annotation_file(annotation_file: str) -> pd.DataFrame:
    in_anno = pd.read_csv(annotation_file, comment='#').fillna('')
    in_anno.columns = ["gene_id", "name", "fullname", "gene_type", "gene_family"]

    return in_anno


def import_annotations(annotation_file: str, dry_run: bool = False, delete_existing: bool = True):
    anno = pd.DataFrame(Annotation.objects.values_list(named=True).iterator())
    if anno.empty:
        anno = pd.DataFrame(columns=["id", "gene_id", "name", "fullname", "gene_type", "gene_family"])

    anno = anno.set_index('gene_id').fillna('')

    in_anno = read_annotation_file(annotation_file)
    in_anno = in_anno.set_index('gene_id')

    changed = (in_anno.loc[anno.index, ["name", "fullname", "gene_type", "gene_family"]] != anno[
        ["name", "fullname", "gene_type", "gene_family"]]).any(axis=1)

    to_update = pd.concat([
        anno['id'],
        in_anno.loc[in_anno.index.isin(changed[changed].index), :]
    ], axis=1, join='inner').reset_index()

    new_anno = in_anno.loc[~in_anno.index.isin(anno.index), :].reset_index()

    to_delete = anno.loc[anno.index.difference(in_anno.index), :]

    if dry_run:
        logger.info("Update:")
        logger.info(to_update)
        logger.info("Create:")
        logger.info(new_anno)

        if delete_existing:
            logger.info("Delete:")
            logger.info(to_delete)
    else:
        with atomic():
            for a in (Annotation(**row._asdict()) for row in to_update.itertuples(index=False)):
                a.save()

            Annotation.objects.bulk_create(
                (Annotation(**row._asdict()) for row in new_anno.itertuples(index=False)))

            if delete_existing:
                Annotation.objects.filter(pk__in=to_delete['id']).delete()


def import_additional_edges(edge_file: str, sif: bool = False, directional: bool = True):
    if sif:
        try:
            with open(edge_file) as f:
                g = get_network(f)
        except TypeError:
            g = get_network(edge_file)

        df = pd.DataFrame(iter(g.edges(keys=True)))
    else:
        df = pd.read_csv(edge_file)
        df = df.dropna(axis=0, how='all').dropna(axis=1, how='all')

    df.columns = ['source', 'target', 'edge']
    df = df.drop_duplicates()

    edges = pd.DataFrame.from_records(map(attrgetter('id', 'name'),
                                          map(itemgetter(0),
                                              (EdgeType.objects.get_or_create(
                                                  name=e,
                                                  directional=directional
                                              ) for e in
                                                  df['edge'].unique()))),
                                      columns=['edge_id', 'edge'])

    anno = pd.DataFrame(Annotation.objects.values_list('id', 'gene_id', named=True).iterator())

    df = (df
          .merge(edges, on='edge')
          .merge(anno, left_on='source', right_on='gene_id')
          .merge(anno, left_on='target', right_on='gene_id'))

    df = df[['edge_id', 'id_x', 'id_y']]

    if not directional:
        und_df = df.copy()
        und_df[['id_x', 'id_y']] = und_df[['id_y', 'id_x']]
        df = pd.concat([df, und_df])
        df = df.drop_duplicates()

    EdgeData.objects.bulk_create(
        (EdgeData(
            type_id=e,
            tf_id=s,
            target_id=t
        ) for e, s, t in df[['edge_id', 'id_x', 'id_y']].itertuples(index=False, name=None)),
        batch_size=1000
    )
