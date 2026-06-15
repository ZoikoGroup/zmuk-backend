from rest_framework import generics
from .models import BlogPost
from .serializers import BlogPostSerializer

class BlogPostListAPI(generics.ListAPIView):
    queryset = BlogPost.objects.filter(status='published')
    serializer_class = BlogPostSerializer

class BlogPostDetailAPI(generics.RetrieveAPIView):
    queryset = BlogPost.objects.filter(status='published')
    serializer_class = BlogPostSerializer
    lookup_field = 'slug'
