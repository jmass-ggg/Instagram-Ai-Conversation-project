from django.urls import path

from .views import instagram_comment

urlpatterns = [
    path("instagram/comments", instagram_comment, name="instagram-comment"),
]
