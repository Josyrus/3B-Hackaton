from rest_framework.routers import DefaultRouter
from .api import DossierViewSet

router = DefaultRouter()
router.register("dossiers", DossierViewSet, basename="api-dossier")
urlpatterns = router.urls
