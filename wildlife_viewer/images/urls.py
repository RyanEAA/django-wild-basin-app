from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", views.gallery, name="gallery"),
    path("image/<str:file_id>/", views.image_detail, name="image_detail"),  
    
    path("ajax/species-search/", views.species_search, name="species_search"),

    path("researcher/", views.researcher_dashboard, name="researcher_dashboard"),
    path("researcher/upload/", views.upload_metadata, name="upload_metadata"),

    path("ajax/cache-image/<str:file_id>/", views.cache_image_ajax, name="cache_image_ajax")
    
    ]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)