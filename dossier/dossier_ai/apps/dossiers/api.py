from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import Dossier
from .services import DossierAnalysisFacade


class DossierSerializer(serializers.ModelSerializer):
    verdict = serializers.SerializerMethodField()

    class Meta:
        model = Dossier
        fields = ["id", "code", "status", "progress", "current_stage", "recommendation", "confidence", "created_at", "verdict"]

    def get_verdict(self, obj):
        v = obj.verdicts.first()
        return v.payload if v else None


class DossierViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dossier.objects.all()
    serializer_class = DossierSerializer

    @action(detail=True, methods=["post"])
    def rerun(self, request, pk=None):
        if not request.user.can_correct:
            raise PermissionDenied()
        DossierAnalysisFacade.start(self.get_object(), "rules")
        return Response({"status": "queued"}, status=202)
