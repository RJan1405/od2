from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView

urlpatterns = [
    # Explicit redirect to enforce trailing slash before React catch-all can swallow it
    path('admin', RedirectView.as_view(url='/admin/', permanent=True)),
    path('admin/', admin.site.urls),
    path('', include('chat.urls')),
    path('chat/', include('chat.urls')),
    path('api/analytics/', include('analytics.urls')),

]
