from django.urls import path
from api.views import health, optimize_route

urlpatterns = [
    path("health/", health, name="health"),
    path("api/v1/route/optimize/", optimize_route, name="optimize-route"),
]
