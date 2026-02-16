"""
S3 File Storage Integration for Frappe
Handles file uploads to Amazon S3 or S3-compatible storage
"""

import os
import re
import mimetypes
import boto3
from botocore.exceptions import ClientError

import frappe
from frappe import _

# -----------------------------
# Main Upload Function
# -----------------------------
def write_file(file_doc):
    """
    Upload file to S3 bucket when use_s3 is enabled.
    Called via write_file hook.
    """

    s3_settings = get_s3_settings()
    if not s3_settings or file_doc.attached_to_doctype == "Data Import":
        return file_doc.save_file_on_filesystem()
    try:
        s3_client = create_s3_client(s3_settings)

        # Prepare content
        content = file_doc._content
        if isinstance(content, str):
            content = content.encode('utf-8')

        # S3 Key
        file_key = get_s3_key(file_doc.file_name, file_doc.is_private)

        # Content type
        content_type = mimetypes.guess_type(file_doc.file_name)[0] or 'application/octet-stream'

        # Upload
        s3_client.put_object(
            Bucket=s3_settings['bucket'],
            Key=file_key,
            Body=content,
            ContentType=content_type
        )

        # Generate file URL
        file_url = get_s3_file_url(file_key, s3_settings)
        file_doc.file_url = file_url
        file_doc.is_stored_in_s3 = True

        frappe.log_error(title="S3 File Upload Successful", message=f"Uploaded file: {file_doc.file_name} with key: {file_key}")
        frappe.logger().info(f"S3 File Upload Successful - Key: {file_key}")
        return {
            "file_name": file_doc.file_name,
            "file_url": file_url
        }

    except ClientError as e:
        frappe.log_error(title="S3 Upload Failed", message=f"{str(e)}")
        frappe.msgprint(_("Failed to upload to S3, saving locally"))
        return file_doc.save_file_on_filesystem()
    except Exception as e:
        frappe.log_error(title="S3 Upload Error", message=f"{str(e)}")
        return file_doc.save_file_on_filesystem()

@frappe.whitelist()
def update_file_url(file_doc,method = None):
    file_key = extract_s3_key_from_url(file_doc.file_url)
    frappe.log_error(title="S3 File Key Extraction2", message=f"Extracted file key: {file_key} from URL: {file_doc.file_url}")
    if not file_key or not file_doc.is_private:
        return

    frappe.db.sql("""UPDATE `tabFile` SET file_url=%s WHERE name=%s""", (f'/api/method/ecs_s3_storage.utils.s3_file_storage.get_file_presigned_url?file_key={file_key}', file_doc.name))
    frappe.db.commit()

from urllib.parse import urlparse

def extract_s3_key_from_url(url: str) -> str | None:
    """
    Extract S3 object key from an S3 URL.

    Args:
        url (str): S3 file URL

    Returns:
        str | None: S3 key (e.g. private/files/xxx.jpg)
    """
    parsed = urlparse(url)

    if not parsed.path:
        return None

    # path starts with /
    return parsed.path.lstrip("/")


# -----------------------------
# Delete file from S3
# -----------------------------
def delete_file_data_content(file_doc, only_thumbnail=False):
    """
    Delete file from S3 storage.
    Called via delete_file_data_content hook.
    """
    s3_settings = get_s3_settings()
    if not s3_settings or file_doc.attached_to_doctype == "Data Import":
        return file_doc.delete_file_from_filesystem(only_thumbnail=only_thumbnail)

    try:
        s3_client = create_s3_client(s3_settings)
        files_to_delete = []

        if only_thumbnail and file_doc.thumbnail_url:
            files_to_delete.append(file_doc.thumbnail_url)
        elif not only_thumbnail:
            if file_doc.file_url:
                files_to_delete.append(file_doc.file_url)
            if file_doc.thumbnail_url:
                files_to_delete.append(file_doc.thumbnail_url)

        for file_url in files_to_delete:
            if file_url and (file_url.startswith('http://') or file_url.startswith('https://')):
                file_key = extract_key_from_url(file_url, s3_settings)
                if file_key:
                    s3_client.delete_object(Bucket=s3_settings['bucket'], Key=file_key)
                    frappe.logger().info(f"Deleted S3 file: {file_key}")

    except Exception as e:
        frappe.log_error(title="S3 Delete Failed", message=f"{str(e)}")


# -----------------------------
# S3 Client Helper
# -----------------------------
def create_s3_client(s3_settings):
    """
    Create boto3 client for S3 or S3-compatible storage
    """
    client_config = {
        'aws_access_key_id': s3_settings['access_key_id'],
        'aws_secret_access_key': s3_settings['secret_access_key'],
        'region_name': s3_settings.get('region', 'us-east-1')
    }

    endpoint = s3_settings.get('endpoint_url')
    if endpoint and not endpoint.endswith('amazonaws.com'):
        client_config['endpoint_url'] = endpoint  # custom S3 storage

    return boto3.client('s3', **client_config)


# -----------------------------
# Get S3 Config
# -----------------------------
def get_s3_settings():
    settings = {}
    # get S3 settings from S3 Setting doctype
    s3_settings = frappe.get_cached_doc("S3 Setting", "S3 Setting")
    if s3_settings.enable_s3:
        settings = {
            'bucket': s3_settings.bucket_name,
            'region': s3_settings.region or 'us-east-1',
            'access_key_id': s3_settings.access_key_id,
            'secret_access_key': s3_settings.get_password("access_key_secret"),
            'endpoint_url': s3_settings.endpoint_url,
        }

        if not all([settings['bucket'], settings['access_key_id'], settings['secret_access_key']]):
            frappe.log_error(title="S3 Configuration Incomplete", message="Missing bucket, access_key_id, or secret_access_key")
            return None

    return settings


# -----------------------------
# Generate S3 Key
# -----------------------------
def get_s3_key(file_name, is_private=False):
    safe_name = re.sub(r'[/\\%?#]', '_', file_name)
    folder = "private/files" if is_private else "public/files"
    return f"{folder}/{safe_name}"


# -----------------------------
# Regenerate Pre-signed URL for File
# -----------------------------
@frappe.whitelist(allow_guest=True)
def get_file_presigned_url(file_key, expires_in=604800):
    """
    Generate a fresh pre-signed URL for a file stored in S3 using the file key.
    Useful for private files when the URL has expired.
    
    Args:
        file_key: The S3 file key (e.g., 'private/files/document.pdf' or 'public/files/image.jpg')
        expires_in: URL expiration time in seconds (default: 7 days - maximum allowed by AWS S3)
    
    Returns:
        Pre-signed URL as plain text (redirects directly to the URL)
    """
    s3_settings = get_s3_settings()
    if not s3_settings:
        frappe.throw(_("S3 is not configured"))
    
    try:
        if not file_key:
            frappe.throw(_("File key is required"))
        
        # Generate pre-signed URL
        s3_client = create_s3_client(s3_settings)
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': s3_settings['bucket'], 'Key': file_key},
            ExpiresIn=int(expires_in)
        )
        
        # Redirect to the pre-signed URL
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = presigned_url
        
    except Exception as e:
        frappe.log_error(title="Pre-signed URL Generation Failed", message=f"{str(e)}")
        frappe.throw(_("Failed to generate pre-signed URL: {0}").format(str(e)))


# -----------------------------
# Extract key from URL
# -----------------------------
def extract_key_from_url(file_url, s3_settings):
    """
    Extract S3 key from full URL
    """
    if '?' in file_url:
        file_url = file_url.split('?', 1)[0]

    bucket = s3_settings['bucket']

    # bucket.s3.region.amazonaws.com/key
    if f"{bucket}.s3" in file_url:
        parts = file_url.split(f"{bucket}.s3", 1)
        key = parts[1].lstrip('/').split('/', 1)[-1] if len(parts) > 1 else None
        return key

    # endpoint/bucket/key
    if f"/{bucket}/" in file_url:
        return file_url.split(f"/{bucket}/", 1)[1]

    # CDN
    if s3_settings.get('cdn_url') and file_url.startswith(s3_settings['cdn_url']):
        return file_url.replace(f"{s3_settings['cdn_url'].rstrip('/')}/", "")

    return None


# -----------------------------
# Generate S3 File URL
# -----------------------------
def get_s3_file_url(file_key, s3_settings, is_private=False):
    """
    Generate the file URL for S3 storage.
    For private files, generate a pre-signed URL.
    For public files, use CDN URL if available, otherwise S3 URL.
    """
    # Use CDN URL if configured
    if s3_settings.get('cdn_url'):
        cdn_url = s3_settings['cdn_url'].rstrip('/')
        return f"{cdn_url}/{file_key}"
    
    # For private files, generate pre-signed URL
    if is_private:
        try:
            s3_client = create_s3_client(s3_settings)
            # Generate pre-signed URL valid for 7 days (maximum allowed)
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod='get_object',
                Params={'Bucket': s3_settings['bucket'], 'Key': file_key},
                ExpiresIn=604800  # 7 days
            )
            return presigned_url
        except Exception as e:
            frappe.log_error(title="Pre-signed URL Generation Failed", message=f"{str(e)}")
    
    # Default S3 URL for public files
    bucket = s3_settings['bucket']
    region = s3_settings.get('region', 'us-east-1')
    
    # Check if custom endpoint is used
    endpoint = s3_settings.get('endpoint_url')
    if endpoint and not endpoint.endswith('amazonaws.com'):
        # Custom S3-compatible storage
        endpoint = endpoint.rstrip('/')
        return f"{endpoint}/{bucket}/{file_key}"
    
    # Standard AWS S3 URL
    return f"https://{bucket}.s3.{region}.amazonaws.com/{file_key}"


