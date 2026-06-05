from django.urls import path
from . import views
from . import api_views

urlpatterns = [
    # HTML pages
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("flashcards/", views.flashcards, name="flashcards"),
    path("search/", views.search, name="search"),
    path("song/<int:song_id>/", views.song_detail, name="song_detail"),

    # JSON API
    path("api/lyrics/search/", api_views.lyrics_search, name="api_lyrics_search"),
    path("api/lyrics/get/", api_views.lyrics_get, name="api_lyrics_get"),
    path("api/lyrics/resolve/", api_views.lyrics_resolve, name="api_lyrics_resolve"),
    path("api/cards/", api_views.cards_create, name="api_cards_create"),
]
