import os
from collections import OrderedDict
from typing import Generator, Iterable

from django.core.files.storage import FileSystemStorage
from django.db import connection
from rest_framework import views
from rest_framework.response import Response

from querytgdb.models import Analysis, AnalysisData, Edge, EdgeData, EdgeType, Experiment, ExperimentData
from .serializers import TFValueSerializer

storage = FileSystemStorage('commongenelists/')


def get_lists(files: Iterable) -> Generator[str, None, None]:
    for f in files:
        name, ext = os.path.splitext(f)
        if ext == '.txt':
            yield name


def check_regulation(instance: Analysis):
    return instance.regulation_set.exists()


class TFView(views.APIView):
    def get(self, request, *args, **kwargs):
        queryset = [OrderedDict([('gene_id', 'oralltfs')]),
                    OrderedDict([('gene_id', 'andalltfs')])]

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT a.gene_id as gene_id, a.name as gene_name FROM querytgdb_experiment as e "
                "LEFT JOIN querytgdb_annotation as a ON e.tf_id = a.id "
                "ORDER BY gene_id, gene_name")

            for gene_id, gene_name in cursor:
                queryset.append(OrderedDict([
                    ("gene_id", gene_id),
                    ("gene_name", gene_name)
                ]))

        serializer = TFValueSerializer(queryset, many=True)

        return Response(serializer.data)


class EdgeListView(views.APIView):
    def get(self, request, *args, **kwargs):
        return Response(EdgeType.objects.values_list("name", flat=True))


class InterestingListsView(views.APIView):
    def get(self, request, *args, **kwargs):
        directories, files = storage.listdir('./')

        return Response(get_lists(files))


class KeyView(views.APIView):
    def get(self, request):
        tfs = set(request.GET.getlist('tf'))

        if tfs & {'oralltfs', 'andalltfs'}:
            tfs = set()

        queryset = ['pvalue', 'edge', 'fc', 'has_column']

        if tfs:
            experiments = Experiment.objects.filter(tf__gene_id__in=tfs)

            if EdgeData.objects.filter(tf__gene_id__in=tfs).exists():
                queryset.append('edge_properties')

            queryset.extend(AnalysisData.objects.filter(
                analysis__experiment__in=experiments
            ).distinct().values_list('key', flat=True))

            queryset.extend(ExperimentData.objects.filter(
                experiment__in=experiments
            ).distinct().values_list('key', flat=True))
        else:
            queryset.append('edge_properties')
            queryset.extend(AnalysisData.objects.distinct().values_list('key', flat=True))
            queryset.extend(ExperimentData.objects.distinct().values_list('key', flat=True))

        return Response(queryset)


class ValueView(views.APIView):
    def get(self, request, key: str) -> Response:
        tfs = set(request.GET.getlist('tf'))

        if tfs & {'oralltfs', 'andalltfs'}:
            tfs = set()

        key = key.upper()

        if key in ('PVALUE', 'FC'):
            return Response([])
        elif key == 'EDGE':
            if tfs:

                return Response(Experiment.objects.filter(tf__gene_id__in=tfs).distinct().values_list(
                    'analysis__interaction__edge__name', flat=True))
            return Response(Edge.objects.distinct().values_list('name', flat=True))
        elif key == 'EDGE_PROPERTIES':
            if tfs:
                return Response(
                    EdgeData.objects.filter(tf__gene_id__in=tfs).distinct().values_list('type__name', flat=True))
            return Response(EdgeType.objects.distinct().values_list('name', flat=True))
        elif key == 'HAS_COLUMN':
            queryset = ['EDGE']

            if tfs:
                if any(map(check_regulation, Analysis.objects.filter(experiment__tf__gene_id__in=tfs))):
                    queryset.extend(('Pvalue', 'FC'))
                if EdgeData.objects.filter(tf__gene_id__in=tfs).exists():
                    queryset.append('edge_properties')
            else:
                queryset.extend(('Pvalue', 'FC', 'edge_properties'))

            return Response(queryset)
        else:
            queryset = []

            if tfs:
                experiments = Experiment.objects.filter(tf__gene_id__in=tfs)

                queryset.extend(AnalysisData.objects.filter(
                    analysis__experiment__in=experiments,
                    key__iexact=key
                ).distinct().values_list('value', flat=True))

                queryset.extend(
                    ExperimentData.objects.filter(experiment__in=experiments,
                                                  key__iexact=key).distinct().values_list('value', flat=True))
            else:
                queryset.extend(
                    AnalysisData.objects.filter(key__iexact=key).distinct().values_list('value', flat=True))
                queryset.extend(
                    ExperimentData.objects.filter(key__iexact=key).distinct().values_list('value', flat=True))

            return Response(queryset)
