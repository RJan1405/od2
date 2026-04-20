"""Custom Django fields for handling GIF animation preservation"""
from django.db.models import ImageField
from django.core.files.base import ContentFile
import uuid


class GIFPreservingImageField(ImageField):
    """Custom ImageField that preserves GIF animation by skipping Pillow processing"""

    def get_prep_value(self, value):
        """Override to prevent Pillow from processing GIFs"""
        if value and hasattr(value, 'name'):
            # Check if it's a GIF
            if value.name.lower().endswith('.gif'):
                # Return as-is without processing
                return value
        return super().get_prep_value(value)
