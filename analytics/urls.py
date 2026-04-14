from django.urls import path
from .views import ProxyAnalyticsEventView

urlpatterns = [
    path('proxy-event/', ProxyAnalyticsEventView.as_view(), name='proxy_event'),
]
