from rest_framework import serializers
from .models import BlogPost

class BlogPostSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField()  # returns username

    class Meta:
        model = BlogPost
        fields = [
            'id', 'title', 'slug', 'author', 'content', 'featured_image',
            'seo_title', 'seo_description', 'seo_keywords',
            'status', 'created_at', 'updated_at'
        ]
