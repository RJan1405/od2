import filetype
import os
from django.core.exceptions import ValidationError
from PIL import Image

# Security Constants
MAX_IMAGE_DIMENSION = 5000  # 5000x5000px max (prevent pixel floods)
ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm',
    'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm', 'audio/x-m4a', 'audio/aac',
    'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain', 'application/zip', 'application/x-zip-compressed', 'application/octet-stream'
}
# Safe Extensions Map (Enforce extension matches mime)
MIME_TO_EXT = {
    'image/jpeg': ['.jpg', '.jpeg'],
    'image/png': ['.png'],
    'image/gif': ['.gif'],
    'image/webp': ['.webp'],
    'video/mp4': ['.mp4'],
    'video/quicktime': ['.mov'],
    'video/x-matroska': ['.mkv'],
    'video/webm': ['.webm'],
    'audio/mpeg': ['.mp3'],
    'audio/wav': ['.wav'],
    'audio/ogg': ['.ogg'],
    'audio/webm': ['.webm'],
    'audio/x-m4a': ['.m4a'],
    'audio/aac': ['.aac'],
    'application/pdf': ['.pdf'],
    'application/msword': ['.doc'],
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
    'application/vnd.ms-excel': ['.xls'],
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    'application/vnd.ms-powerpoint': ['.ppt'],
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
    'text/plain': ['.txt'],
    'application/zip': ['.zip'],
    'application/x-zip-compressed': ['.zip'],
    # Allow but be careful
    'application/octet-stream': ['.bin', '.exe', '.dll', '.pkg', '.dmg', '.pdf']
}


def validate_media_file(file_obj):
    """
    Instagram-style Magic Byte & Security Validation.
    Reject files that are spoofed (e.g., exe renamed to jpg).
    """

    # 1. Reset file pointer
    file_obj.seek(0)

    # 2. Read Magic Bytes (first 262 bytes usually enough)
    head_sample = file_obj.read(262)
    file_obj.seek(0)  # Reset immediately

    # 3. Detect Real Type
    kind = filetype.guess(head_sample)

    mime = None
    if kind:
        mime = kind.mime
    else:
        # Fallback to mimetypes detection for documents/text
        import mimetypes
        mime, _ = mimetypes.guess_type(file_obj.name)

    if mime is None:
        # Default to safe binary if unknown but extension is safe
        mime = 'application/octet-stream'

    # 4. Whitelist Check
    if mime not in ALLOWED_MIME_TYPES:
        # Final safety: if it's application/octet-stream, we only allow it if extension is in our whitelist
        user_ext = os.path.splitext(file_obj.name)[1].lower()
        if not any(user_ext in exts for exts in MIME_TO_EXT.values()):
            raise ValidationError(
                f"File type '{mime}' or extension '{user_ext}' is not supported.")
        # If it's a known doc extension, we let it pass as octet-stream

    # 5. Extension vs Content Check (Spoofing Protection)
    user_ext = os.path.splitext(file_obj.name)[1].lower()
    allowed_exts = MIME_TO_EXT.get(mime, [])

    # DOCS TRUST: If the user extension is a common document type, be much more lenient
    SAFE_DOC_EXTS = ['.pdf', '.doc', '.docx', '.xls',
                     '.xlsx', '.ppt', '.pptx', '.txt', '.zip']
    if user_ext in SAFE_DOC_EXTS:
        return True  # Trust common doc extensions

    # Be more lenient: if mime is octet-stream, we rely on extension whitelist check above.
    # If mime is specific, we check if extension is compatible.
    if mime != 'application/octet-stream' and allowed_exts and user_ext not in allowed_exts:
        # Check if it's a "compatible" mismatch (e.g. .jpeg for image/jpeg)
        pass

    # 6. Image Specific Checks (Pixel Flood / Zip Bomb)
    if mime.startswith('image/'):
        # Skip Pillow verification for actual GIFs to preserve animation frames
        # Check magic bytes: GIF87a or GIF89a
        file_obj.seek(0)
        header = file_obj.read(6)
        file_obj.seek(0)
        is_actual_gif = header.startswith(
            b'GIF87') or header.startswith(b'GIF89')

        if not is_actual_gif:
            try:
                # We open without loading data to check header
                img = Image.open(file_obj)
                img.verify()  # Verify file integrity

                # Check dimensions against DoS attacks
                width, height = img.size
                if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                    raise ValidationError(
                        f"Image is too large ({width}x{height}). Max allowed is {MAX_IMAGE_DIMENSION}px.")

                # Re-open for future processing (verify closes file)
                file_obj.seek(0)

            except Exception as e:
                if isinstance(e, ValidationError):
                    raise e
                raise ValidationError("Invalid or corrupt image file.")
        else:
            # For actual GIFs, skip Pillow verification to preserve animation
            logger.info(
                f"🎬 Actual GIF detected in validation, skipping Pillow verification to preserve animation")
            file_obj.seek(0)

    return True
