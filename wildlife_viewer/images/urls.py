from django.urls import path
from . import views

urlpatterns = [
    path("", views.gallery, name="gallery"),
    path("researcher/", views.researcher_dashboard, name="researcher_dashboard"),
    path("researcher/upload/", views.upload_metadata, name="upload_metadata"),
]